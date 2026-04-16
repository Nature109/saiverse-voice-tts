"""TTS engine abstraction.

All concrete engines must inherit from TTSEngine and implement synthesize().
Engines return 16-bit or float32 PCM waveform as numpy array + sample rate.

Engines that can produce audio incrementally (chunk-by-chunk) may also set
``supports_streaming = True`` and implement ``synthesize_stream()`` to yield
``SynthesisChunk`` objects as they become available. Callers can then play
audio in real time while synthesis is still in progress, dramatically
reducing time-to-first-sound.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

import numpy as np


@dataclass
class SynthesisResult:
    audio: np.ndarray
    sample_rate: int
    duration_ms: int


@dataclass
class SynthesisChunk:
    """A partial audio chunk yielded during streaming synthesis."""
    audio: np.ndarray
    sample_rate: int


class TTSEngine(ABC):
    name: str = "base"
    supports_streaming: bool = False

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

    def synthesize_stream(
        self,
        text: str,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Iterator[SynthesisChunk]:
        """Yield audio chunks as synthesis progresses.

        Default implementation wraps ``synthesize()`` and yields the whole
        result as a single chunk. Override in subclasses that natively
        support streaming inference.
        """
        result = self.synthesize(text, ref_audio, ref_text, params)
        yield SynthesisChunk(audio=result.audio, sample_rate=result.sample_rate)

    def close(self) -> None:
        pass
