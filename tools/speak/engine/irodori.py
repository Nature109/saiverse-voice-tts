"""Irodori-TTS engine adapter (local Python inference).

Imports the upstream inference runtime from the cloned repository at
`external/Irodori-TTS/`. Model weights (Aratako/Irodori-TTS-500M-v2) are
downloaded automatically from HuggingFace by `InferenceRuntime.from_key`.

Upstream code/weights license: MIT (redistribution permitted; base dependency
licenses should be individually verified before bundling).
Upstream: https://github.com/Aratako/Irodori-TTS
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
_EXTERNAL_REPO = _PACK_ROOT / "external" / "Irodori-TTS"


def _prepare_sys_path() -> None:
    if not _EXTERNAL_REPO.exists():
        raise RuntimeError(
            f"Irodori-TTS repository not found at {_EXTERNAL_REPO}. "
            "Run: python scripts/install_backends.py irodori"
        )
    sp = str(_EXTERNAL_REPO)
    if sp not in sys.path:
        sys.path.insert(0, sp)


class IrodoriEngine(TTSEngine):
    name = "irodori"

    def __init__(self, engine_config: Dict[str, Any]):
        super().__init__(engine_config)
        self._runtime = None

    def _lazy_load(self) -> None:
        if self._runtime is not None:
            return
        _prepare_sys_path()
        try:
            from irodori_tts.inference import InferenceRuntime, RuntimeKey  # type: ignore
        except ImportError:
            try:
                from irodori_tts import InferenceRuntime, RuntimeKey  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Failed to import irodori_tts. Ensure external/Irodori-TTS "
                    "is installed (pip install -e external/Irodori-TTS)."
                ) from exc

        checkpoint = self.config.get("checkpoint", "Aratako/Irodori-TTS-500M-v2")
        codec_repo = self.config.get("codec_repo", "Aratako/Semantic-DACVAE-Japanese-32dim")
        device = self.config.get("device", "cuda")

        LOGGER.info("Loading Irodori-TTS runtime: %s (device=%s)", checkpoint, device)
        self._runtime = InferenceRuntime.from_key(
            RuntimeKey(
                checkpoint=checkpoint,
                model_device=device,
                codec_repo=codec_repo,
            )
        )

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
            raise ValueError("Irodori-TTS zero-shot cloning requires ref_audio.")

        from irodori_tts.inference import SamplingRequest  # type: ignore

        result = self._runtime.synthesize(
            SamplingRequest(
                text=text,
                ref_wav=ref_audio,
                num_steps=int(params.get("num_steps", 24)),
            )
        )
        audio = np.asarray(result.audio, dtype=np.float32)
        sr = int(getattr(result, "sample_rate", 48000))
        duration_ms = int(len(audio) / sr * 1000)
        return SynthesisResult(audio=audio, sample_rate=sr, duration_ms=duration_ms)
