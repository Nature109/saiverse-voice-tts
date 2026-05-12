"""In-process audio stream registry for HTTP Chunked Transfer.

The playback worker (sync thread) pushes PCM chunks for a given ``message_id``
while synthesis progresses. The FastAPI ``/audio/{message_id}/stream`` endpoint
(async coroutine) consumes the same registry and writes MP3 bytes to the HTTP
response as a single ``audio/mpeg`` chunked body. The client ``<audio>`` element
begins playback as soon as the first MP3 frame arrives, which mirrors the
server-side ``sounddevice`` real-time experience for remote listeners
(e.g. Tailscale-connected phones).

Design notes:
  - Multiple consumers can subscribe to the same ``message_id``. Each consumer
    receives a private queue seeded with all MP3 frames accumulated so far,
    then receives new frames as they're produced. This broadcast model
    handles three common realities cleanly:
      1. The browser may fire multiple parallel stream requests for the same
         src (HTML ``<audio>`` occasionally does this for progressive audio).
      2. Connection drops cause the browser to re-fetch; the new request
         replays from the start.
      3. Debug clients (curl, second tab) can peek at the live stream without
         stealing frames from the primary playback consumer.
  - Container is MP3 (audio/mpeg). Progressive WAV with 0xFFFFFFFF header
    was previously used but rejected by some browsers with "The operation
    is not supported". MP3 is a pure concatenation of frames with no
    container-level size requirement, so chunked transfer works natively.
  - Encoding is done via ``lameenc`` (libmp3lame wheel bundled in PyPI).
  - Streams are buffered only in memory; the registry entry is GC'd when
    ``close_stream`` runs after synthesis completes.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

_STREAMS_LOCK = threading.Lock()


@dataclass
class _StreamContext:
    """Per-stream state: encoder + accumulated frames + live consumer queues."""
    encoder: Optional[Any]  # lameenc.Encoder instance (or None if unavailable)
    sample_rate: int
    # すべての MP3 frame を溜めておき、late-joining consumer に先頭から配れる
    # ようにする。メモリ使用量は 1 発話あたり数百KB 程度なので許容。
    frames: List[bytes] = field(default_factory=list)
    # 各 consumer 専用の queue。push_chunk は全 consumer の queue に frame を
    # 流す (= broadcast)。
    consumers: List["Queue[Optional[bytes]]"] = field(default_factory=list)
    closed: bool = False


_STREAMS: Dict[str, _StreamContext] = {}

# Sentinel pushed on close_stream to tell consumers that no more data will
# arrive.
_SENTINEL: Optional[bytes] = None


@dataclass
class _PcmStreamContext:
    """PCM 経路用の per-stream state. MP3 経路 (_StreamContext) と独立。

    encoder は持たず、PCM bytes を生のまま frames に蓄積 + consumers に broadcast。
    物理 vessel (Stack-chan 等) が MP3 decode を省略して playRaw に直結できるよう、
    voice-tts が PCM を圧縮なしで配信する用途。
    """
    sample_rate: int
    channels: int = 1
    frames: List[bytes] = field(default_factory=list)
    consumers: List["Queue[Optional[bytes]]"] = field(default_factory=list)
    closed: bool = False


_PCM_STREAMS: Dict[str, _PcmStreamContext] = {}

# MP3 encoding parameters. 128 kbps mono is a good quality/bandwidth trade-off
# for speech synthesis output.
_MP3_BITRATE = 128
_MP3_QUALITY = 2  # 2-7 in lameenc; lower = higher quality / slower


def _make_encoder(sample_rate: int) -> Optional[Any]:
    """Create a new lameenc Encoder configured for mono 16-bit PCM input."""
    try:
        import lameenc  # type: ignore
    except ImportError:
        LOGGER.warning(
            "lameenc not installed; /audio/*/stream will not work. "
            "Run `pip install lameenc` or rerun setup.bat."
        )
        return None
    enc = lameenc.Encoder()
    enc.set_bit_rate(_MP3_BITRATE)
    enc.set_in_sample_rate(sample_rate)
    enc.set_channels(1)
    enc.set_quality(_MP3_QUALITY)
    return enc


def open_stream(message_id: str, sample_rate: int) -> None:
    """Allocate a new broadcast stream for ``message_id``.

    If a placeholder context already exists (created by an early
    ``subscribe()`` call before this ``open_stream()`` arrived), reuse it:
    fill in the encoder/sample_rate and preserve any consumers that
    subscribed before this point. Otherwise allocate a fresh context as
    before.

    Reuse only applies to not-yet-closed contexts. A closed stream context
    is replaced (the message_id can be re-opened from scratch).

    This subscribe-before-open support lets late publishers (e.g. TTS
    synthesis that hasn't started yet) be matched deterministically with
    early subscribers, removing the need for callers to poll.
    """
    if not message_id:
        return
    encoder = _make_encoder(sample_rate)
    with _STREAMS_LOCK:
        existing = _STREAMS.get(str(message_id))
        if existing is not None and not existing.closed:
            # Reuse placeholder created by subscribe-before-open: fill in
            # encoder/sample_rate while preserving pre-registered consumers
            # and frames (frames should be empty at this point).
            existing.encoder = encoder
            existing.sample_rate = sample_rate
            LOGGER.debug(
                "audio_stream open (reuse placeholder): message_id=%s sr=%d "
                "consumers=%d",
                message_id, sample_rate, len(existing.consumers),
            )
            return
        ctx = _StreamContext(encoder=encoder, sample_rate=sample_rate)
        _STREAMS[str(message_id)] = ctx
    LOGGER.debug(
        "audio_stream open: message_id=%s sr=%d encoder=%s",
        message_id, sample_rate, "lameenc" if encoder is not None else "none",
    )


def push_chunk(message_id: str, pcm_bytes: bytes) -> None:
    """Encode PCM to MP3 and broadcast to all subscribed consumers.

    Also accumulates emitted MP3 frames in ``ctx.frames`` so that consumers
    who subscribe later can replay from the start.
    """
    if not message_id or not pcm_bytes:
        return
    with _STREAMS_LOCK:
        ctx = _STREAMS.get(str(message_id))
    if ctx is None:
        return
    if ctx.encoder is None:
        # No encoder — treat input as already-encoded bytes (pass-through).
        frame = pcm_bytes
    else:
        try:
            mp3_frames = ctx.encoder.encode(pcm_bytes)
        except Exception as exc:
            LOGGER.warning("MP3 encode error for msg=%s: %s", message_id, exc)
            return
        if not mp3_frames:
            return
        frame = bytes(mp3_frames)
    # 蓄積 + 全 consumer に broadcast
    with _STREAMS_LOCK:
        ctx.frames.append(frame)
        consumers = list(ctx.consumers)
    for q in consumers:
        q.put(frame)


def close_stream(message_id: str) -> None:
    """Flush encoder, mark stream closed, and signal all consumers."""
    if not message_id:
        return
    with _STREAMS_LOCK:
        ctx = _STREAMS.get(str(message_id))
        if ctx is None:
            return
        ctx.closed = True
        consumers = list(ctx.consumers)
    # flush encoder (synchronous, outside lock)
    final_frame: bytes = b""
    if ctx.encoder is not None:
        try:
            tail = ctx.encoder.flush()
        except Exception as exc:
            LOGGER.warning("MP3 flush error for msg=%s: %s", message_id, exc)
            tail = b""
        if tail:
            final_frame = bytes(tail)
    with _STREAMS_LOCK:
        if final_frame:
            ctx.frames.append(final_frame)
    if final_frame:
        for q in consumers:
            q.put(final_frame)
    for q in consumers:
        q.put(_SENTINEL)
    LOGGER.debug("audio_stream close: message_id=%s consumers=%d", message_id, len(consumers))


def subscribe(message_id: str) -> "Optional[Queue[Optional[bytes]]]":
    """Subscribe a new consumer. Returns a queue seeded with all frames so far.

    If ``message_id`` is empty (validation failure) returns None.

    If the stream is not yet opened (subscribe-before-open case), creates
    an empty placeholder context so that a later ``open_stream()`` call
    can pick it up while preserving this consumer's queue. This allows
    late publishers (e.g. TTS synthesis that hasn't started yet) to be
    matched deterministically with early subscribers, removing the need
    for callers to poll for stream readiness.

    If the stream is already closed, returns a queue pre-populated with
    all frames + a sentinel, so the consumer can drain completed audio
    cleanly.
    """
    if not message_id:
        return None
    q: "Queue[Optional[bytes]]" = Queue()
    with _STREAMS_LOCK:
        ctx = _STREAMS.get(str(message_id))
        if ctx is None:
            # subscribe-before-open: create empty placeholder context so the
            # consumer queue is registered and ready when open_stream()
            # arrives. encoder/sample_rate will be filled by open_stream().
            ctx = _StreamContext(encoder=None, sample_rate=0)
            _STREAMS[str(message_id)] = ctx
            LOGGER.debug(
                "audio_stream subscribe (before-open): message_id=%s "
                "(placeholder ctx created)",
                message_id,
            )
        # Replay already-emitted frames
        for frame in ctx.frames:
            q.put(frame)
        if ctx.closed:
            q.put(_SENTINEL)
        else:
            ctx.consumers.append(q)
    return q


def has_stream(message_id: str) -> bool:
    """Return True if a stream context exists (open or closed) for ``message_id``.

    Used by the /stream endpoint to decide between 404 vs streaming response
    before starting the HTTP body (to avoid mid-response aborts).
    """
    if not message_id:
        return False
    with _STREAMS_LOCK:
        return str(message_id) in _STREAMS


def discard_stream(message_id: str) -> None:
    """Remove a stream context from the registry (after all consumers drained).

    Called by the final consumer or by a cleanup task when the stream is no
    longer needed. Kept separate from ``close_stream`` so that late joiners
    can still replay a recently-finished stream.
    """
    if not message_id:
        return
    with _STREAMS_LOCK:
        _STREAMS.pop(str(message_id), None)


def get_queue(message_id: str) -> "Optional[Queue[Optional[bytes]]]":
    """Backwards-compat alias for ``subscribe``.

    Kept so existing callers (e.g. older api_routes.py check) keep working.
    New code should prefer ``subscribe`` for clarity.
    """
    return subscribe(message_id)


def active_stream_count() -> int:
    with _STREAMS_LOCK:
        return len(_STREAMS)


__all__ = [
    "open_stream",
    "push_chunk",
    "close_stream",
    "subscribe",
    "get_queue",
    "has_stream",
    "discard_stream",
    "active_stream_count",
    # PCM 経路 (物理 vessel 等、decoder を持たない consumer 向け)
    "open_pcm_stream",
    "push_pcm_chunk",
    "close_pcm_stream",
    "subscribe_pcm",
    "get_pcm_stream_info",
    "discard_pcm_stream",
]


# ============================================================================
# PCM 経路 (decoder を持たない consumer 向け、Stack-chan 等の物理 vessel 用)
# ============================================================================
# MP3 経路 (上の open_stream / push_chunk / ...) と完全に独立。
# voice-tts は両方に並列で push する (playback_worker)。MP3 経路は HTTP/WS で
# decoder ありの consumer 向け、PCM 経路は ESP32 等のシンプルな再生器向け。


def open_pcm_stream(
    message_id: str, sample_rate: int, channels: int = 1
) -> None:
    """Allocate a new broadcast stream for ``message_id`` (PCM)."""
    if not message_id:
        return
    with _STREAMS_LOCK:
        existing = _PCM_STREAMS.get(str(message_id))
        if existing is not None and not existing.closed:
            existing.sample_rate = sample_rate
            existing.channels = channels
            LOGGER.debug(
                "audio_stream open_pcm (reuse placeholder): message_id=%s "
                "sr=%d ch=%d consumers=%d",
                message_id, sample_rate, channels, len(existing.consumers),
            )
            return
        ctx = _PcmStreamContext(sample_rate=sample_rate, channels=channels)
        _PCM_STREAMS[str(message_id)] = ctx
    LOGGER.debug(
        "audio_stream open_pcm: message_id=%s sr=%d ch=%d",
        message_id, sample_rate, channels,
    )


def push_pcm_chunk(message_id: str, pcm_bytes: bytes) -> None:
    """Broadcast PCM bytes to all subscribed consumers (PCM path).

    ``pcm_bytes`` is raw signed 16-bit little-endian PCM. No header,
    no metadata. The sample_rate / channels are conveyed via
    ``open_pcm_stream`` / ``get_pcm_stream_info``.
    """
    if not message_id or not pcm_bytes:
        return
    with _STREAMS_LOCK:
        ctx = _PCM_STREAMS.get(str(message_id))
        if ctx is None:
            return
        ctx.frames.append(pcm_bytes)
        consumers = list(ctx.consumers)
    for q in consumers:
        q.put(pcm_bytes)


def close_pcm_stream(message_id: str) -> None:
    """Mark PCM stream closed and signal all consumers."""
    if not message_id:
        return
    with _STREAMS_LOCK:
        ctx = _PCM_STREAMS.get(str(message_id))
        if ctx is None:
            return
        ctx.closed = True
        consumers = list(ctx.consumers)
    for q in consumers:
        q.put(_SENTINEL)
    LOGGER.debug(
        "audio_stream close_pcm: message_id=%s consumers=%d",
        message_id, len(consumers),
    )


def subscribe_pcm(message_id: str) -> "Optional[Queue[Optional[bytes]]]":
    """Subscribe a new consumer to the PCM broadcast.

    Supports subscribe-before-open: if no open_pcm_stream has happened yet,
    creates a placeholder context so this consumer's queue is registered.
    A later open_pcm_stream will fill in sample_rate / channels while
    preserving the queue.
    """
    if not message_id:
        return None
    q: "Queue[Optional[bytes]]" = Queue()
    with _STREAMS_LOCK:
        ctx = _PCM_STREAMS.get(str(message_id))
        if ctx is None:
            ctx = _PcmStreamContext(sample_rate=0, channels=0)
            _PCM_STREAMS[str(message_id)] = ctx
            LOGGER.debug(
                "audio_stream subscribe_pcm (before-open): message_id=%s "
                "(placeholder ctx created)",
                message_id,
            )
        for frame in ctx.frames:
            q.put(frame)
        if ctx.closed:
            q.put(_SENTINEL)
        else:
            ctx.consumers.append(q)
    return q


def get_pcm_stream_info(message_id: str):
    """Return ``(sample_rate, channels)`` if the PCM stream is open with
    valid metadata, else ``None``. Used by consumers that subscribed
    before open and need to wait for the open_pcm_stream to fill metadata.
    """
    if not message_id:
        return None
    with _STREAMS_LOCK:
        ctx = _PCM_STREAMS.get(str(message_id))
        if ctx is None or ctx.sample_rate == 0:
            return None
        return (ctx.sample_rate, ctx.channels)


def discard_pcm_stream(message_id: str) -> None:
    """Remove the PCM stream context."""
    if not message_id:
        return
    with _STREAMS_LOCK:
        _PCM_STREAMS.pop(str(message_id), None)
