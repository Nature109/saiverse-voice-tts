"""Azure AI Speech engine (cloud, no GPU required, Personal Voice 対応).

Microsoft Azure の Text-to-Speech API を呼び出すエンジン。Neural TTS の
preset 日本語 voice (ja-JP-NanamiNeural 等) は漢字読みが極めて強く、
固有名詞や読み分けの精度で OpenAI / ElevenLabs より優位。

加えて **Personal Voice** に対応し、Azure Speech リソースで作成した
Speaker Profile ID を指定すれば任意話者のクローン合成も可能。

特徴:
- ストリーミング対応 (HTTP chunked + ``X-Microsoft-OutputFormat:
  raw-24khz-16bit-mono-pcm``)。
- API key + region (例: ``japaneast``) で認証。
- 既存パックの PCM ストリーミング基盤と互換。
- 漢字読み: Open JTalk + 自社韻律モデルで信頼度高い (preset / Personal
  Voice 共通の利点)。
- ペルソナ別パラメータで `azure_voice` (preset 名) と
  `azure_personal_voice_id` (Personal Voice 利用時) の両方をサポート。
- SSML の ``<mstts:express-as style="...">`` でスタイル指定可能。

API リファレンス:
- POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1
- https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech
- https://learn.microsoft.com/azure/ai-services/speech-service/personal-voice-overview
"""
from __future__ import annotations

import logging
import os
import time
import xml.sax.saxutils as saxutils
from typing import Any, Dict, Iterator, List, Optional

import httpx
import numpy as np

from .base import SynthesisChunk, SynthesisResult, TTSEngine

LOGGER = logging.getLogger(__name__)

_PCM_SAMPLE_RATE = 24_000
_DEFAULT_VOICE = "ja-JP-NanamiNeural"
_DEFAULT_REGION = "japaneast"
# Personal Voice 利用時のベース voice。Microsoft 公式ドキュメントに準じる。
# DragonLatestNeural が Personal Voice 用の標準ベースとして推奨されている。
_PERSONAL_VOICE_BASE = "DragonLatestNeural"
_OUTPUT_FORMAT = "raw-24khz-16bit-mono-pcm"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 1
_RETRY_BASE_SLEEP = 1.5


class AzureTTSEngine(TTSEngine):
    name = "azure_tts"
    supports_streaming = True

    def __init__(self, engine_config: Dict[str, Any]):
        super().__init__(engine_config)
        # config/default.json からの legacy フォールバック値。
        # addon UI 経由の値は synthesize ごとに fresh 解決される。
        self._api_key_legacy: Optional[str] = (
            (engine_config or {}).get("api_key") or None
        )
        self._region_legacy: Optional[str] = (
            (engine_config or {}).get("region") or None
        )
        self._timeout = float((engine_config or {}).get("timeout", 120.0))

    # -------------------------------------------------------------- helpers

    def _resolve_addon_params(self) -> Dict[str, Any]:
        try:
            from saiverse.addon_config import get_params  # type: ignore
            return get_params("saiverse-voice-tts") or {}
        except Exception as exc:
            LOGGER.debug("azure_tts: addon_config unavailable: %s", exc)
            return {}

    def _resolve_api_key(self) -> Optional[str]:
        addon = self._resolve_addon_params()
        ui_key = (addon.get("azure_subscription_key") or "").strip()
        if ui_key:
            return ui_key
        if self._api_key_legacy:
            return self._api_key_legacy
        return os.getenv("AZURE_SPEECH_KEY") or None

    def _resolve_region(self) -> str:
        addon = self._resolve_addon_params()
        ui_region = (addon.get("azure_region") or "").strip()
        if ui_region:
            return ui_region
        if self._region_legacy:
            return self._region_legacy
        env = os.getenv("AZURE_SPEECH_REGION")
        return env or _DEFAULT_REGION

    @staticmethod
    def _resolve_voice(params: Optional[Dict[str, Any]]) -> str:
        params = params or {}
        for key in ("voice", "azure_voice"):
            v = params.get(key)
            if v:
                return str(v).strip()
        return _DEFAULT_VOICE

    @staticmethod
    def _resolve_personal_voice_id(
        params: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        params = params or {}
        for key in ("personal_voice_id", "azure_personal_voice_id"):
            v = params.get(key)
            if v:
                return str(v).strip() or None
        return None

    @staticmethod
    def _resolve_style(params: Optional[Dict[str, Any]]) -> Optional[str]:
        params = params or {}
        for key in ("style", "azure_voice_style"):
            v = params.get(key)
            if v:
                return str(v).strip() or None
        return None

    @staticmethod
    def _resolve_lang(params: Optional[Dict[str, Any]]) -> str:
        params = params or {}
        v = params.get("lang") or params.get("azure_lang")
        return str(v).strip() if v else "ja-JP"

    @staticmethod
    def _build_ssml(
        text: str,
        voice: str,
        lang: str,
        personal_voice_id: Optional[str],
        style: Optional[str],
    ) -> str:
        """Azure SSML を組み立てる。

        - Personal Voice 利用時: ``<mstts:ttsembedding speakerProfileId=...>``
          で text を包む。voice タグ自体はベース voice (DragonLatestNeural 等)
          になる。
        - スタイル指定時: ``<mstts:express-as style=...>`` で内側を包む。
        - 通常時: ``<voice name=...>`` の中にエスケープ済み text。

        XML エスケープは saxutils.escape を使用。
        """
        escaped = saxutils.escape(text or "")
        # Personal Voice ありなら base voice を強制
        actual_voice = _PERSONAL_VOICE_BASE if personal_voice_id else voice
        # 内側 (text 部分) の構築
        inner = escaped
        if personal_voice_id:
            inner = (
                f'<mstts:ttsembedding speakerProfileId="{saxutils.quoteattr(personal_voice_id)[1:-1]}">'
                f'{inner}</mstts:ttsembedding>'
            )
        if style:
            inner = (
                f'<mstts:express-as style="{saxutils.quoteattr(style)[1:-1]}">'
                f'{inner}</mstts:express-as>'
            )
        ssml = (
            f'<speak version="1.0" '
            f'xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xmlns:mstts="https://www.w3.org/2001/mstts" '
            f'xml:lang="{saxutils.quoteattr(lang)[1:-1]}">'
            f'<voice name="{saxutils.quoteattr(actual_voice)[1:-1]}">'
            f'{inner}'
            f'</voice></speak>'
        )
        return ssml

    def _post_streaming_pcm(
        self, ssml: str, api_key: str, region: str,
    ) -> Iterator[bytes]:
        """Azure に POST してチャンクごとに raw PCM bytes を yield。

        429 / 5xx は ``_MAX_RETRIES`` 回まで短いリトライ。それ以外の 4xx は
        即座に例外を上げる。
        """
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": _OUTPUT_FORMAT,
            "User-Agent": "saiverse-voice-tts",
        }
        attempt = 0
        while True:
            try:
                with httpx.stream(
                    "POST",
                    url,
                    content=ssml.encode("utf-8"),
                    headers=headers,
                    timeout=self._timeout,
                ) as resp:
                    if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                        LOGGER.warning(
                            "azure_tts: HTTP %d (attempt %d), retrying",
                            resp.status_code, attempt + 1,
                        )
                        attempt += 1
                        time.sleep(_RETRY_BASE_SLEEP * attempt)
                        continue
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes():
                        if chunk:
                            yield chunk
                return
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                detail = ""
                try:
                    detail = exc.response.text[:300]
                except Exception:  # pragma: no cover
                    pass
                LOGGER.error(
                    "azure_tts: API error HTTP %d: %s",
                    status, detail,
                )
                raise
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    LOGGER.warning(
                        "azure_tts: network error %s (attempt %d), retrying",
                        exc, attempt + 1,
                    )
                    attempt += 1
                    time.sleep(_RETRY_BASE_SLEEP * attempt)
                    continue
                LOGGER.error("azure_tts: network error after retry: %s", exc)
                raise

    @staticmethod
    def _pcm_bytes_to_audio_np(pcm: bytes) -> np.ndarray:
        if not pcm:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    # -------------------------------------------------------------- public

    def synthesize(
        self,
        text: str,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> SynthesisResult:
        chunks: List[np.ndarray] = []
        for chunk in self.synthesize_stream(text, ref_audio, ref_text, params):
            chunks.append(chunk.audio)
        if not chunks:
            audio = np.zeros(0, dtype=np.float32)
        else:
            audio = np.concatenate(chunks)
        duration_ms = int(len(audio) / _PCM_SAMPLE_RATE * 1000) if audio.size else 0
        return SynthesisResult(
            audio=audio,
            sample_rate=_PCM_SAMPLE_RATE,
            duration_ms=duration_ms,
        )

    def synthesize_stream(
        self,
        text: str,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Iterator[SynthesisChunk]:
        if ref_audio:
            LOGGER.debug(
                "azure_tts: ref_audio is ignored (use Personal Voice "
                "speakerProfileId instead)",
            )
        api_key = self._resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "azure_tts: subscription key not configured. Set addon param "
                "'azure_subscription_key' or environment variable "
                "'AZURE_SPEECH_KEY'."
            )
        region = self._resolve_region()
        voice = self._resolve_voice(params)
        personal_voice_id = self._resolve_personal_voice_id(params)
        style = self._resolve_style(params)
        lang = self._resolve_lang(params)
        ssml = self._build_ssml(text, voice, lang, personal_voice_id, style)
        LOGGER.debug(
            "azure_tts: synthesize region=%s voice=%s pvid=%s style=%s len=%d",
            region, voice, personal_voice_id or "-", style or "-", len(text),
        )
        # 既存エンジンと同じく、50 ms ぶん (4800 byte) でバッファリング。
        # int16 PCM の 2 byte 境界に揃って flush する (HTTP chunked transfer は
        # 任意のバイト境界で fragment し得るので、奇数バイトは次回まで持ち越す)。
        buf = bytearray()
        flush_threshold = 4800
        for raw in self._post_streaming_pcm(ssml, api_key, region):
            buf.extend(raw)
            if len(buf) >= flush_threshold:
                emit_len = len(buf) - (len(buf) % 2)
                if emit_len > 0:
                    audio = self._pcm_bytes_to_audio_np(bytes(buf[:emit_len]))
                    del buf[:emit_len]
                    yield SynthesisChunk(audio=audio, sample_rate=_PCM_SAMPLE_RATE)
        if buf:
            emit_len = len(buf) - (len(buf) % 2)
            if emit_len > 0:
                audio = self._pcm_bytes_to_audio_np(bytes(buf[:emit_len]))
                yield SynthesisChunk(audio=audio, sample_rate=_PCM_SAMPLE_RATE)
