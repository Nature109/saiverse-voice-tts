"""TTS engine registry."""
from __future__ import annotations

from typing import Any, Dict

from .base import SynthesisResult, TTSEngine


def create_engine(name: str, engine_config: Dict[str, Any]) -> TTSEngine:
    name = (name or "").lower()
    if name == "gpt_sovits":
        from .gpt_sovits import GPTSoVITSEngine
        return GPTSoVITSEngine(engine_config)
    if name == "irodori":
        from .irodori import IrodoriEngine
        return IrodoriEngine(engine_config)
    raise ValueError(f"Unknown TTS engine: {name}")


__all__ = ["TTSEngine", "SynthesisResult", "create_engine"]
