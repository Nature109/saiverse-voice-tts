"""Irodori-TTS engine adapter (local Python inference).

Imports the upstream inference runtime from the cloned repository at
`external/Irodori-TTS/`. Model weights (Aratako/Irodori-TTS-500M-v2 +
Aratako/Semantic-DACVAE-Japanese-32dim) are downloaded automatically from
HuggingFace on first run via ``InferenceRuntime.from_key``.

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


_SAMPLING_REQUEST_FIELDS = {
    "caption",
    "ref_latent",
    "no_ref",
    "ref_normalize_db",
    "ref_ensure_max",
    "num_candidates",
    "decode_mode",
    "seconds",
    "max_ref_seconds",
    "max_text_len",
    "max_caption_len",
    "num_steps",
    "cfg_scale_text",
    "cfg_scale_caption",
    "cfg_scale_speaker",
    "cfg_guidance_mode",
    "cfg_scale",
    "cfg_min_t",
    "cfg_max_t",
    "truncation_factor",
    "rescale_k",
    "rescale_sigma",
    "context_kv_cache",
    "speaker_kv_scale",
    "speaker_kv_min_t",
    "speaker_kv_max_layers",
    "seed",
    "trim_tail",
    "tail_window_size",
    "tail_std_threshold",
    "tail_mean_threshold",
}


class IrodoriEngine(TTSEngine):
    name = "irodori"
    supports_streaming = False  # 上流の InferenceRuntime は一括合成のみ

    def __init__(self, engine_config: Dict[str, Any]):
        super().__init__(engine_config)
        self._runtime = None

    def _lazy_load(self) -> None:
        if self._runtime is not None:
            return
        _prepare_sys_path()
        try:
            from irodori_tts.inference_runtime import (  # type: ignore
                InferenceRuntime,
                RuntimeKey,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Failed to import irodori_tts.inference_runtime. Ensure external/Irodori-TTS "
                "is cloned and its requirements are installed."
            ) from exc

        checkpoint = self.config.get("checkpoint", "Aratako/Irodori-TTS-500M-v2")
        codec_repo = self.config.get("codec_repo", "Aratako/Semantic-DACVAE-Japanese-32dim")
        device = self.config.get("device", "cuda")
        model_precision = self.config.get("model_precision", "bf16" if device == "cuda" else "fp32")
        codec_device = self.config.get("codec_device", "cpu")
        codec_precision = self.config.get("codec_precision", "fp32")

        # 上流 InferenceRuntime は checkpoint をローカルファイルパスとして解釈する
        # ため、HF repo ID が指定された場合はここで model.safetensors を解決する。
        checkpoint_path = self._resolve_checkpoint(checkpoint)

        LOGGER.info(
            "Loading Irodori-TTS runtime: %s (device=%s precision=%s)",
            checkpoint, device, model_precision,
        )
        self._runtime = InferenceRuntime.from_key(
            RuntimeKey(
                checkpoint=checkpoint_path,
                model_device=device,
                model_precision=model_precision,
                codec_device=codec_device,
                codec_precision=codec_precision,
                codec_repo=codec_repo,
            )
        )

    @staticmethod
    def _resolve_checkpoint(checkpoint: str) -> str:
        suffix = Path(checkpoint).suffix.lower()
        if suffix in {".pt", ".safetensors"}:
            return checkpoint
        # HuggingFace repo ID と見なしてダウンロード
        from huggingface_hub import hf_hub_download  # type: ignore
        filename = "model.safetensors"
        resolved = hf_hub_download(repo_id=checkpoint, filename=filename)
        LOGGER.info("Irodori-TTS checkpoint resolved: hf://%s -> %s", checkpoint, resolved)
        return resolved

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

        from irodori_tts.inference_runtime import SamplingRequest  # type: ignore

        # registry.json の params から SamplingRequest のフィールドだけ抜き出す。
        # ref_text は上流がサポートしていないため黙って無視(ref_wav のみで音声特徴を推定)。
        kwargs = {k: v for k, v in params.items() if k in _SAMPLING_REQUEST_FIELDS}

        result = self._runtime.synthesize(
            SamplingRequest(
                text=text,
                ref_wav=ref_audio,
                **kwargs,
            )
        )

        # SamplingResult.audio は torch.Tensor (shape: [samples] or [channels, samples])
        audio_tensor = result.audio
        if hasattr(audio_tensor, "detach"):
            audio_tensor = audio_tensor.detach().cpu()
        audio = np.asarray(audio_tensor, dtype=np.float32)
        if audio.ndim > 1:
            # ステレオは平均して mono 化 (playback_worker は mono 前提)
            audio = audio.mean(axis=0) if audio.shape[0] < audio.shape[-1] else audio[:, 0]
        sr = int(result.sample_rate)
        duration_ms = int(len(audio) / sr * 1000)
        return SynthesisResult(audio=audio, sample_rate=sr, duration_ms=duration_ms)
