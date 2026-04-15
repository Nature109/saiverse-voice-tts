"""Qwen3-TTS (OSS, Apache 2.0) engine adapter.

Uses the official `qwen-tts` package (PyPI) OR the cloned repository at
`external/Qwen3-TTS/` if present. Both expose `Qwen3TTSModel`.

Default model: Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice (zero-shot voice cloning
from 3-second reference audio).

Upstream code/weights license: Apache 2.0 (redistribution permitted).
Upstream: https://github.com/QwenLM/Qwen3-TTS
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
_EXTERNAL_REPO = _PACK_ROOT / "external" / "Qwen3-TTS"


def _prepare_sys_path() -> None:
    if _EXTERNAL_REPO.exists():
        sp = str(_EXTERNAL_REPO)
        if sp not in sys.path:
            sys.path.insert(0, sp)


class Qwen3TTSEngine(TTSEngine):
    name = "qwen3_tts"

    def __init__(self, engine_config: Dict[str, Any]):
        super().__init__(engine_config)
        self._model = None

    def _lazy_load(self) -> None:
        if self._model is not None:
            return

        _prepare_sys_path()
        try:
            from qwen_tts import Qwen3TTSModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Qwen3-TTS not available. Install via `pip install qwen-tts`, or "
                "clone https://github.com/QwenLM/Qwen3-TTS to expansion_data/"
                "saiverse-voice-tts/external/Qwen3-TTS and `pip install -e .` it."
            ) from exc

        model_id = self.config.get("model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        device_map = self.config.get("device", "auto")
        dtype_name = str(self.config.get("dtype", "bfloat16")).lower()

        import torch  # type: ignore
        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        dtype = dtype_map.get(dtype_name, torch.bfloat16)

        LOGGER.info(
            "Loading Qwen3-TTS: %s (device_map=%s dtype=%s)",
            model_id, device_map, dtype_name,
        )
        kwargs: Dict[str, Any] = {
            "device_map": device_map,
            "dtype": dtype,
        }
        if self.config.get("flash_attention"):
            kwargs["attn_implementation"] = "flash_attention_2"

        self._model = Qwen3TTSModel.from_pretrained(model_id, **kwargs)

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
            raise ValueError("Qwen3-TTS voice cloning requires ref_audio.")

        wavs, sr = self._model.generate_voice_clone(
            text=text,
            language=params.get("language", "Japanese"),
            ref_audio=ref_audio,
            ref_text=ref_text or "",
        )
        audio = np.asarray(wavs[0], dtype=np.float32)
        sr = int(sr)
        duration_ms = int(len(audio) / sr * 1000)
        return SynthesisResult(audio=audio, sample_rate=sr, duration_ms=duration_ms)
