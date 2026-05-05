"""OpenAI TTS engine (cloud, no GPU required).

OpenAI の Text-to-Speech API を呼び出して合成する軽量エンジン。GPU を
持たないユーザー向けの選択肢。

特徴:
- ゼロショットボイスクローンは無し。プリセット 9 voice (alloy / echo /
  fable / onyx / nova / shimmer / ash / sage / coral) からペルソナごとに
  選択する設計。``ref_audio`` / ``ref_text`` は無視される。
- ``response_format=pcm`` (16-bit signed at 24kHz, raw PCM) を使うことで
  デコード不要・即時 numpy 化。
- ストリーミング対応 (HTTP chunked) で TTFC が短い。
- API key は addon param ``openai_api_key`` 優先、未設定時は環境変数
  ``OPENAI_API_KEY`` を使う (本体既設定の流用)。
- 依存: ``httpx`` のみ (本体 requirements に既存)。

API リファレンス:
- POST https://api.openai.com/v1/audio/speech
- https://platform.openai.com/docs/api-reference/audio/createSpeech
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional

import httpx
import numpy as np

from .base import SynthesisChunk, SynthesisResult, TTSEngine

LOGGER = logging.getLogger(__name__)

_API_URL = "https://api.openai.com/v1/audio/speech"
_PCM_SAMPLE_RATE = 24_000  # OpenAI TTS PCM 出力はサンプリングレート固定
_DEFAULT_VOICE = "alloy"
_DEFAULT_MODEL = "tts-1"
_VALID_VOICES = {
    "alloy", "echo", "fable", "onyx", "nova", "shimmer",
    "ash", "sage", "coral",
}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 1
_RETRY_BASE_SLEEP = 1.5  # 秒、429 / 5xx は短いリトライ


class OpenAITTSEngine(TTSEngine):
    name = "openai_tts"
    supports_streaming = True

    def __init__(self, engine_config: Dict[str, Any]):
        super().__init__(engine_config)
        # config/default.json からの API key (legacy フォールバック)。
        # addon UI 経由の値はリクエストごとに fresh に解決される。
        self._api_key_legacy: Optional[str] = (
            (engine_config or {}).get("api_key") or None
        )
        # タイムアウトは長めに (gpt-4o-mini-tts は 1〜2 分かかるケースもある)
        self._timeout = float((engine_config or {}).get("timeout", 120.0))

    # -------------------------------------------------------------- helpers

    def _resolve_api_key(self) -> Optional[str]:
        """API key の優先順位: addon UI param → config/default.json → env。"""
        try:
            from saiverse.addon_config import get_params  # type: ignore
            params = get_params("saiverse-voice-tts")
            ui_key = (params.get("openai_api_key") or "").strip()
            if ui_key:
                return ui_key
        except Exception as exc:
            LOGGER.debug("openai_tts: addon_config unavailable: %s", exc)
        if self._api_key_legacy:
            return self._api_key_legacy
        env = os.getenv("OPENAI_API_KEY")
        return env or None

    def _resolve_voice(self, params: Optional[Dict[str, Any]]) -> str:
        params = params or {}
        voice = (
            params.get("voice")
            or params.get("openai_voice")
            or _DEFAULT_VOICE
        )
        voice = str(voice).strip().lower()
        if voice not in _VALID_VOICES:
            LOGGER.warning(
                "openai_tts: unknown voice %r, falling back to %s",
                voice, _DEFAULT_VOICE,
            )
            return _DEFAULT_VOICE
        return voice

    def _build_request_body(
        self,
        text: str,
        params: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        params = params or {}
        body: Dict[str, Any] = {
            "model": str(params.get("model") or _DEFAULT_MODEL),
            "voice": self._resolve_voice(params),
            "input": text,
            "response_format": "pcm",  # raw 16-bit signed PCM @ 24kHz
        }
        # speed は tts-1 / tts-1-hd のみ。gpt-4o-mini-tts では無視される (API 側で)
        if "speed" in params and params["speed"] is not None:
            try:
                speed = float(params["speed"])
                if 0.25 <= speed <= 4.0:
                    body["speed"] = speed
            except (TypeError, ValueError):
                pass
        # instructions は gpt-4o-mini-tts のみ意味がある (スタイル指示)。
        # 他モデルでも害はないので素通しでよい (API 側で無視されるか弾かれる)。
        if params.get("instructions"):
            body["instructions"] = str(params["instructions"])
        return body

    def _post_streaming_pcm(
        self, body: Dict[str, Any], api_key: str,
    ) -> Iterator[bytes]:
        """OpenAI に POST してチャンクごとに raw PCM bytes を yield。

        429 / 5xx は ``_MAX_RETRIES`` 回まで短いリトライ。それ以外の 4xx は
        即座に例外を上げる。
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        attempt = 0
        while True:
            try:
                with httpx.stream(
                    "POST",
                    _API_URL,
                    json=body,
                    headers=headers,
                    timeout=self._timeout,
                ) as resp:
                    if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                        LOGGER.warning(
                            "openai_tts: HTTP %d (attempt %d), retrying",
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
                # 4xx (auth / bad request 等) は再試行しない。詳細は body から
                status = exc.response.status_code
                detail = ""
                try:
                    detail = exc.response.text[:300]
                except Exception:  # pragma: no cover
                    pass
                LOGGER.error(
                    "openai_tts: API error HTTP %d: %s",
                    status, detail,
                )
                raise
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    LOGGER.warning(
                        "openai_tts: network error %s (attempt %d), retrying",
                        exc, attempt + 1,
                    )
                    attempt += 1
                    time.sleep(_RETRY_BASE_SLEEP * attempt)
                    continue
                LOGGER.error("openai_tts: network error after retry: %s", exc)
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
        # ストリーミング経路を集約して 1 本にする (シンプル化)。
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
                "openai_tts: ref_audio is ignored (preset voices only)",
            )
        api_key = self._resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "openai_tts: API key not configured. Set addon param "
                "'openai_api_key' or environment variable 'OPENAI_API_KEY'."
            )
        body = self._build_request_body(text, params)
        LOGGER.debug(
            "openai_tts: synthesize model=%s voice=%s len=%d",
            body["model"], body["voice"], len(text),
        )
        # 細かすぎる chunk (例: 100 byte 単位) は React 側 useEffect の負荷に
        # もなるので、ある程度集約してから yield する。50 ms ぶん (=2400 frame
        # × 2 byte = 4800 byte) を目安にバッファリング。
        # 重要: int16 PCM なので numpy 変換は 2 byte 境界に揃ってる必要がある。
        # HTTP chunked transfer は任意のバイト境界で fragment し得るので、
        # flush 時に奇数 byte が末尾に来たら次回まで持ち越す。
        buf = bytearray()
        flush_threshold = 4800
        for raw in self._post_streaming_pcm(body, api_key):
            buf.extend(raw)
            if len(buf) >= flush_threshold:
                emit_len = len(buf) - (len(buf) % 2)
                if emit_len > 0:
                    audio = self._pcm_bytes_to_audio_np(bytes(buf[:emit_len]))
                    del buf[:emit_len]
                    yield SynthesisChunk(audio=audio, sample_rate=_PCM_SAMPLE_RATE)
        if buf:
            # 最後の残りも 2 byte 境界に揃える (理論上完全な PCM は偶数 byte で
            # 終わるが、接続中断等で奇数バイト残った場合に備えた防御)。
            emit_len = len(buf) - (len(buf) % 2)
            if emit_len > 0:
                audio = self._pcm_bytes_to_audio_np(bytes(buf[:emit_len]))
                yield SynthesisChunk(audio=audio, sample_rate=_PCM_SAMPLE_RATE)
