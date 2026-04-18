"""FastAPI router for the saiverse-voice-tts addon.

The SAIVerse host auto-discovers ``expansion_data/<addon>/api_routes.py`` at
startup, imports the ``router`` attribute, and mounts it under
``/api/addon/<addon>``.

Endpoints exposed:

    GET  /api/addon/saiverse-voice-tts/audio/{message_id}
         → serves the fully synthesised WAV from disk.

    GET  /api/addon/saiverse-voice-tts/audio/{message_id}/stream
         → HTTP Chunked Transfer of the WAV as it is being synthesised.
           Browsers start playback as soon as the first chunk arrives,
           mirroring the server-side sounddevice streaming experience for
           remote (Tailscale) listeners.

Authentication: relies on the host's ``saiverse.addon_deps.get_manager``
dependency. Being able to resolve ``get_manager`` is, today, the effective
auth gate.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

LOGGER = logging.getLogger(__name__)
_ADDON_NAME = "saiverse-voice-tts"

# ---------------------------------------------------------------------------
# Host-provided helpers (loaded lazily; absence is a fatal misconfiguration
# at request time but not at import time so the pack can still register the
# router when the addon framework is partially available).
# ---------------------------------------------------------------------------


def _get_metadata(message_id: str) -> Any:
    from saiverse.addon_metadata import get_metadata  # type: ignore
    return get_metadata(message_id=message_id, addon_name=_ADDON_NAME)


def _get_manager_dep() -> Any:
    """Return the host's ``get_manager`` dependency or a noop placeholder.

    The placeholder keeps routes importable on old host builds; real auth
    requires the host to provide ``saiverse.addon_deps.get_manager``.
    """
    try:
        from saiverse.addon_deps import get_manager  # type: ignore
        return get_manager
    except Exception:  # pragma: no cover
        async def _noop() -> None:
            return None
        return _noop


# Import the stream registry from the tools tree. We guard the import so
# that ``router`` is still usable even if the tool subpackage is not on the
# path (e.g. for type checks or route documentation).
try:
    from tools.speak.audio_stream import get_queue  # type: ignore
except Exception:  # pragma: no cover
    def get_queue(message_id: str) -> Any:  # type: ignore[misc]
        return None


router = APIRouter()


# ---------------------------------------------------------------------------
# GET /audio/{message_id}
# ---------------------------------------------------------------------------
@router.get("/audio/{message_id}")
async def get_audio(
    message_id: str,
    manager: Any = Depends(_get_manager_dep()),
) -> FileResponse:
    """Serve the fully synthesised WAV for ``message_id``.

    Looks up ``audio_path`` from the host's ``addon_metadata`` store, keyed by
    ``(message_id, addon_name=saiverse-voice-tts, key=audio_path)``.
    """
    try:
        meta = _get_metadata(message_id)
    except Exception as exc:
        LOGGER.exception("addon_metadata lookup failed for %s", message_id)
        raise HTTPException(status_code=500, detail="metadata lookup failed") from exc

    if not meta or not isinstance(meta, dict):
        raise HTTPException(status_code=404, detail="audio not yet available")

    # audio_file はバックエンドローカルの WAV ファイルパス。
    # audio_path はフロント向け URL なのでファイルオープンに使ってはならない。
    fs_path = meta.get("audio_file")
    if not fs_path:
        # 旧バージョン互換: audio_file 未設定だが audio_path が実パスになっている
        # ケース (生成後にキーを分離する前のデータ) はフォールバックとして許容する。
        legacy = meta.get("audio_path")
        if legacy and not str(legacy).startswith("/api/"):
            fs_path = legacy
    if not fs_path:
        raise HTTPException(status_code=404, detail="audio not yet available")

    path = Path(str(fs_path))
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio file missing on disk")

    # filename を渡すと FastAPI が Content-Disposition: attachment をデフォルトで
    # 付与し、ブラウザが <audio> で再生せずダウンロード扱いしてしまう。
    # content_disposition_type="inline" を明示してインライン再生可能にする。
    return FileResponse(
        path=str(path),
        media_type="audio/wav",
        filename=path.name,
        content_disposition_type="inline",
    )


# ---------------------------------------------------------------------------
# GET /audio/{message_id}/stream
# ---------------------------------------------------------------------------
async def _stream_body(message_id: str) -> AsyncIterator[bytes]:
    """Yield WAV bytes from the in-process stream registry as they arrive."""
    q = get_queue(message_id)
    if q is None:
        # Maybe the wav is already fully saved; fall back to completed wav.
        try:
            meta = _get_metadata(message_id)
        except Exception:
            meta = None
        fs_path = None
        if meta and isinstance(meta, dict):
            fs_path = meta.get("audio_file")
            if not fs_path:
                legacy = meta.get("audio_path")
                if legacy and not str(legacy).startswith("/api/"):
                    fs_path = legacy
        if fs_path:
            path = Path(str(fs_path))
            if path.exists():
                with path.open("rb") as f:
                    while True:
                        buf = f.read(64 * 1024)
                        if not buf:
                            break
                        yield buf
                return
        raise HTTPException(status_code=404, detail="no active stream")

    loop = asyncio.get_event_loop()
    while True:
        chunk = await loop.run_in_executor(None, q.get)
        if chunk is None:
            break
        yield chunk


@router.get("/audio/{message_id}/stream")
async def stream_audio(
    message_id: str,
    manager: Any = Depends(_get_manager_dep()),
) -> StreamingResponse:
    """Chunked WAV stream consumed live while synthesis is in progress."""
    return StreamingResponse(
        _stream_body(message_id),
        media_type="audio/wav",
    )


# ---------------------------------------------------------------------------
# GET /audio-devices
# ---------------------------------------------------------------------------
@router.get("/audio-devices")
async def list_audio_devices() -> dict:
    """List host machine audio output devices for the addon UI dropdown.

    Returned format matches the AddonParamSchema `options_endpoint` contract:
    ``{"options": ["<default>", "0: Speakers (Realtek)", ...]}``.
    The first entry is always ``"<default>"`` which maps to ``None`` on the
    backend (= sounddevice's default device).
    """
    options: list[str] = ["<default>"]
    try:
        import sounddevice as sd  # type: ignore
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            # 出力チャンネルを持つデバイスのみ（入力専用マイクを除外）
            if int(dev.get("max_output_channels", 0)) <= 0:
                continue
            name = str(dev.get("name", f"device{i}")).strip()
            options.append(f"{i}: {name}")
    except Exception:
        LOGGER.exception("failed to enumerate audio devices")
    return {"options": options}
