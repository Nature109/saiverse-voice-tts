"""GPT-SoVITS engine adapter (local Python inference — no external API server).

Imports the upstream `TTS_infer_pack.TTS` module from the cloned repository at
`external/GPT-SoVITS/`. Pretrained weights are downloaded from HuggingFace
`lj1995/GPT-SoVITS` and placed under `external/GPT-SoVITS/GPT_SoVITS/pretrained_models/`.

Upstream code/weights license: MIT (redistribution permitted).
Upstream: https://github.com/RVC-Boss/GPT-SoVITS
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from .base import SynthesisResult, TTSEngine

LOGGER = logging.getLogger(__name__)

_PACK_ROOT = Path(__file__).resolve().parents[3]
_EXTERNAL_REPO = _PACK_ROOT / "external" / "GPT-SoVITS"


def _prepare_sys_path() -> None:
    if not _EXTERNAL_REPO.exists():
        raise RuntimeError(
            f"GPT-SoVITS repository not found at {_EXTERNAL_REPO}. "
            "Run: python scripts/install_backends.py gpt_sovits"
        )
    for p in (_EXTERNAL_REPO, _EXTERNAL_REPO / "GPT_SoVITS"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


class GPTSoVITSEngine(TTSEngine):
    name = "gpt_sovits"

    def __init__(self, engine_config: Dict[str, Any]):
        super().__init__(engine_config)
        self._tts = None
        self._last_ref: Optional[str] = None
        self._ref_language = self.config.get("ref_language", "ja")
        self._target_language = self.config.get("target_language", "ja")

    def _lazy_load(self) -> None:
        if self._tts is not None:
            return
        _prepare_sys_path()
        try:
            from TTS_infer_pack.TTS import TTS, TTS_Config  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Failed to import GPT-SoVITS TTS_infer_pack. "
                "Ensure external/GPT-SoVITS is properly installed and its "
                "dependencies are available."
            ) from exc

        config_yaml = self.config.get("config_yaml")
        if config_yaml:
            cfg = TTS_Config(str(config_yaml))
        else:
            default_cfg = _EXTERNAL_REPO / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
            cfg = TTS_Config(str(default_cfg)) if default_cfg.exists() else TTS_Config()

        LOGGER.info("Loading GPT-SoVITS TTS pipeline (config=%s)", cfg)
        self._tts = TTS(cfg)

    def synthesize(
        self,
        text: str,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> SynthesisResult:
        self._lazy_load()
        params = params or {}

        if not ref_audio:
            raise ValueError("GPT-SoVITS requires ref_audio.")

        if ref_audio != self._last_ref:
            self._tts.set_ref_audio(ref_audio)
            self._last_ref = ref_audio

        inputs: Dict[str, Any] = {
            "text": text,
            "text_lang": self._target_language,
            "ref_audio_path": ref_audio,
            "prompt_text": ref_text or "",
            "prompt_lang": self._ref_language,
            "text_split_method": params.get("text_split_method", "cut5"),
            "batch_size": 1,
            "speed_factor": float(params.get("speed", 1.0)),
            "top_k": int(params.get("top_k", 15)),
            "top_p": float(params.get("top_p", 1.0)),
            "temperature": float(params.get("temperature", 1.0)),
            "return_fragment": False,
        }

        result_iter = self._tts.run(inputs)

        chunks: list[np.ndarray] = []
        sr = 32000
        for sr_chunk, audio_chunk in result_iter:
            sr = int(sr_chunk)
            if not isinstance(audio_chunk, np.ndarray):
                audio_chunk = np.asarray(audio_chunk)
            if audio_chunk.dtype == np.int16:
                audio_chunk = audio_chunk.astype(np.float32) / 32768.0
            else:
                audio_chunk = audio_chunk.astype(np.float32)
            chunks.append(audio_chunk)

        if not chunks:
            raise RuntimeError("GPT-SoVITS produced no audio.")

        audio = np.concatenate(chunks)
        duration_ms = int(len(audio) / sr * 1000)
        return SynthesisResult(audio=audio, sample_rate=sr, duration_ms=duration_ms)
