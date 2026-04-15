"""TTS engine abstraction.

All concrete engines must inherit from TTSEngine and implement synthesize().
Engines return 16-bit or float32 PCM waveform as numpy array + sample rate.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np


@dataclass
class SynthesisResult:
    audio: np.ndarray
    sample_rate: int
    duration_ms: int


class TTSEngine(ABC):
    name: str = "base"

    def __init__(self, engine_config: Dict[str, Any]):
        self.config = engine_config or {}

    @abstractmethod
    def synthesize(
        self,
        text: str,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> SynthesisResult:
        raise NotImplementedError

    def close(self) -> None:
        pass
