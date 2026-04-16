"""In-process audio stream registry for HTTP Chunked Transfer.

The playback worker (sync thread) pushes PCM chunks for a given ``message_id``
while synthesis progresses. The FastAPI ``/audio/{message_id}/stream`` endpoint
(async coroutine) consumes the same queue and writes bytes to the HTTP
response as a single ``audio/wav`` chunked body. The client ``<audio>`` element
begins playback as soon as the first chunk arrives, which mirrors the
server-side ``sounddevice`` real-time experience for remote listeners
(e.g. Tailscale-connected phones).

Design notes:
  - Uses ``threading.Queue`` because producers are sync worker threads and
    consumers are async endpoints; ``run_in_executor(None, q.get)`` bridges
    the two cleanly without needing a running event-loop reference at push
    time.
  - WAV header is emitted with ``0xFFFFFFFF`` sizes so the whole stream is
    a legal WAV file of "unknown length"; browsers accept this for
    progressive playback.
  - Streams are buffered only in memory; once the endpoint finishes writing
    the last chunk the registry entry is GC'd.
"""
from __future__ import annotations

import logging
import struct
import threading
from queue import Queue
from typing import Dict, Optional

LOGGER = logging.getLogger(__name__)

_STREAMS_LOCK = threading.Lock()
_STREAMS: Dict[str, "Queue[Optional[bytes]]"] = {}

# Sentinel pushed on close_stream to tell consumers that no more data will
# arrive. We reuse ``None`` rather than defining a class because the queue
# type is restricted to ``Optional[bytes]`` anyway.
_SENTINEL: Optional[bytes] = None


def _pcm16_wav_header(sample_rate: int, channels: int = 1) -> bytes:
    """Build a 44-byte PCM16 WAV header with 0xFFFFFFFF sizes.

    Produces a legal WAV prefix whose total/data size is "unknown", which
    most browsers and media players accept for progressive streaming.
    """
    bits = 16
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 0xFFFFFFFF),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),               # fmt chunk size
            struct.pack("<H", 1),                # PCM
            struct.pack("<H", channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits),
            b"data",
            struct.pack("<I", 0xFFFFFFFF),
        ]
    )


def open_stream(message_id: str, sample_rate: int) -> None:
    """Allocate a new stream for ``message_id`` and seed it with WAV header."""
    if not message_id:
        return
    header = _pcm16_wav_header(sample_rate=sample_rate, channels=1)
    q: "Queue[Optional[bytes]]" = Queue()
    q.put(header)
    with _STREAMS_LOCK:
        _STREAMS[str(message_id)] = q
    LOGGER.debug("audio_stream open: message_id=%s sr=%d", message_id, sample_rate)


def push_chunk(message_id: str, pcm_bytes: bytes) -> None:
    """Append a PCM-int16 byte chunk to the live stream."""
    if not message_id or not pcm_bytes:
        return
    with _STREAMS_LOCK:
        q = _STREAMS.get(str(message_id))
    if q is not None:
        q.put(pcm_bytes)


def close_stream(message_id: str) -> None:
    """Mark the stream as complete. Waiting consumers will see end-of-stream."""
    if not message_id:
        return
    with _STREAMS_LOCK:
        q = _STREAMS.pop(str(message_id), None)
    if q is not None:
        q.put(_SENTINEL)
        LOGGER.debug("audio_stream close: message_id=%s", message_id)


def get_queue(message_id: str) -> "Optional[Queue[Optional[bytes]]]":
    """Return the queue for ``message_id`` or ``None`` if no active stream."""
    with _STREAMS_LOCK:
        return _STREAMS.get(str(message_id))


def active_stream_count() -> int:
    with _STREAMS_LOCK:
        return len(_STREAMS)


__all__ = [
    "open_stream",
    "push_chunk",
    "close_stream",
    "get_queue",
    "active_stream_count",
]
