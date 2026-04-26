"""Background playback worker.

Single FIFO queue + dedicated thread. synthesize -> save wav -> play via
sounddevice on the backend machine. All operations are non-blocking from the
Tool caller's perspective.
"""
from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from .engine import TTSEngine, create_engine
from .profiles import get_profile
from . import audio_stream

LOGGER = logging.getLogger(__name__)

_PACK_ROOT = Path(__file__).resolve().parent.parent.parent
# ユーザーローカル設定ファイル(.gitignore 対象、各環境固有の値を持つ)。
# 存在しない場合は .template から自動コピーされる(_load_config 内)。
_CONFIG_PATH = _PACK_ROOT / "config" / "default.json"
_CONFIG_TEMPLATE_PATH = _PACK_ROOT / "config" / "default.json.template"
_ADDON_NAME = "saiverse-voice-tts"


def _get_active_message_id() -> Optional[str]:
    try:
        from tools.context import get_active_message_id  # type: ignore
        mid = get_active_message_id()
        return str(mid) if mid is not None else None
    except Exception:
        return None


def _parse_output_device(value: Any) -> Optional[int]:
    """Resolve an output_device value (from addon UI or JSON config) to a
    ``sounddevice`` device index or None (= OS default).

    Accepted input shapes:
      - None / "" / "<default>"         → None
      - int                             → returned as-is
      - "3"                             → 3
      - "3: Speakers (Realtek)"         → 3   (UI dropdown format)

    Any unparsable value falls back to None so playback still reaches the
    OS default device instead of crashing.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # Guard against bool being treated as int (True→1 is almost never intended here).
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s or s == "<default>":
        return None
    # Leading integer, optionally followed by ":" and label.
    head = s.split(":", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def _get_effective_params(persona_id: Optional[str]) -> Dict[str, Any]:
    """Return UI-driven addon params merged with pack-local defaults.

    Preference order:
      1. ``saiverse.addon_config.get_params`` (host UI-managed values, with
         persona-level overrides applied by the host)
      2. ``config/default.json`` of this pack (legacy / backward compat for
         SAIVerse builds without the addon framework)
      3. Hard-coded "enabled, everything on" fallback
    """
    cfg = _worker._load_config() if "_worker" in globals() else {}
    params: Dict[str, Any] = {
        "_enabled": True,
        "auto_speak": True,
        "server_side_playback": bool(cfg.get("server_side_playback", True)),
        "streaming": bool(cfg.get("streaming", True)),
    }
    try:
        from saiverse.addon_config import get_params  # type: ignore
        remote = get_params(_ADDON_NAME, persona_id=persona_id)
        if isinstance(remote, dict):
            params.update(remote)
    except Exception as exc:
        LOGGER.debug("addon_config.get_params unavailable: %s", exc)
    return params


def get_effective_params(persona_id: Optional[str]) -> Dict[str, Any]:
    """Public helper for the Tool to inspect effective addon settings."""
    return _get_effective_params(persona_id)


def _audio_path(message_id: str) -> str:
    return f"/api/addon/{_ADDON_NAME}/audio/{message_id}"


def _audio_stream_url(message_id: str) -> str:
    return f"/api/addon/{_ADDON_NAME}/audio/{message_id}/stream"


def _notify_stream_ready(message_id: Optional[str]) -> None:
    """Broadcast audio_ready at stream open time.

    ストリーミング推論で使用。合成完了を待たずに発火することで、クライアント側
    再生がレイテンシ少なく話し始められる。event.data には stream URL と
    最終 URL の両方を含める (executor は stream URL を優先、無ければ audio_path)。
    """
    if not message_id:
        LOGGER.warning(
            "notify_stream_ready skipped: message_id is None. "
            "Streaming client-side playback will not be triggered."
        )
        return
    stream_url = _audio_stream_url(message_id)
    audio_path = _audio_path(message_id)
    try:
        from saiverse.addon_metadata import set_metadata  # type: ignore
        set_metadata(
            message_id=message_id,
            addon_name=_ADDON_NAME,
            key="audio_stream_url",
            value=stream_url,
        )
        # audio_path は合成完了後にファイルへ解決される URL。この時点で metadata
        # に入れておくと、後続で合成が完了すれば自動でバブル再生でも使える。
        set_metadata(
            message_id=message_id,
            addon_name=_ADDON_NAME,
            key="audio_path",
            value=audio_path,
        )
    except Exception as exc:
        LOGGER.warning("notify_stream_ready set_metadata failed for msg=%s: %s", message_id, exc)
    try:
        from saiverse.addon_events import emit_addon_event  # type: ignore
        emit_addon_event(
            addon=_ADDON_NAME,
            event="audio_ready",
            message_id=message_id,
            data={"audio_stream_url": stream_url, "audio_path": audio_path},
        )
    except Exception as exc:
        LOGGER.warning("emit_addon_event(stream_ready) failed for msg=%s: %s", message_id, exc)


def _notify_audio_ready(
    message_id: Optional[str],
    wav_path: Path,
    emit_event: bool = True,
) -> None:
    """Register wav metadata and (optionally) broadcast an audio_ready event.

    ``emit_event=False`` はストリーミング合成後のフォローアップ用途。既に
    ``_notify_stream_ready`` で event を発火済みのため、完成 wav の metadata
    だけを更新する (audio_file を設定してバブル再生ボタンが正式なファイルを
    返せるようにする)。

    ``emit_event=True`` (デフォルト) は非ストリーミング経路用。完成時に
    初めて URL が確定するので、metadata と SSE の両方を発火する。
    """
    if not message_id:
        LOGGER.warning(
            "notify_audio_ready skipped: message_id is None. "
            "Bubble playback button will not be registered for this utterance."
        )
        return
    audio_path = _audio_path(message_id)
    meta_ok = False
    event_ok = False
    try:
        from saiverse.addon_metadata import set_metadata  # type: ignore
        # audio_path: フロントが <audio src=...> に使う URL
        set_metadata(
            message_id=message_id,
            addon_name=_ADDON_NAME,
            key="audio_path",
            value=audio_path,
        )
        # audio_file: バックエンド配信エンドポイントが実ファイルを開くためのローカルパス
        set_metadata(
            message_id=message_id,
            addon_name=_ADDON_NAME,
            key="audio_file",
            value=str(wav_path),
        )
        meta_ok = True
    except Exception as exc:
        LOGGER.warning("set_metadata failed for msg=%s: %s", message_id, exc)
    if emit_event:
        try:
            from saiverse.addon_events import emit_addon_event  # type: ignore
            emit_addon_event(
                addon=_ADDON_NAME,
                event="audio_ready",
                message_id=message_id,
                data={"audio_path": audio_path},
            )
            event_ok = True
        except Exception as exc:
            LOGGER.warning("emit_addon_event failed for msg=%s: %s", message_id, exc)
    LOGGER.debug(
        "notify_audio_ready: msg=%s metadata=%s event=%s (emit=%s)",
        message_id, meta_ok, event_ok, emit_event,
    )


def _saiverse_home() -> Path:
    import os
    env = os.getenv("SAIVERSE_HOME")
    if env:
        return Path(env)
    return Path.home() / ".saiverse"


_OUT_DIR = _saiverse_home() / "user_data" / "voice" / "out"


@dataclass
class _Job:
    job_id: str
    persona_id: Optional[str]
    text: str
    message_id: Optional[str] = None


class _TTSWorker:
    def __init__(self) -> None:
        self._queue: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._engines: Dict[str, TTSEngine] = {}
        self._config: Dict[str, Any] = {}
        self._config_loaded = False
        self._lock = threading.Lock()

    def _load_config(self) -> Dict[str, Any]:
        if self._config_loaded:
            return self._config
        # ローカル版が無ければ .template から初回コピー (first-run materialization)。
        # ユーザーが local 版を編集して上流 pull で衝突しないようにするための仕組み。
        if not _CONFIG_PATH.exists() and _CONFIG_TEMPLATE_PATH.exists():
            try:
                _CONFIG_PATH.write_text(
                    _CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                LOGGER.info(
                    "Materialized %s from %s (first run).",
                    _CONFIG_PATH.name, _CONFIG_TEMPLATE_PATH.name,
                )
            except Exception as exc:
                LOGGER.warning(
                    "Failed to materialize %s from template: %s",
                    _CONFIG_PATH, exc,
                )
        # 読み込み元: ローカル版 → なければ template の内容を直接使う
        source = _CONFIG_PATH if _CONFIG_PATH.exists() else _CONFIG_TEMPLATE_PATH
        if source.exists():
            try:
                self._config = json.loads(source.read_text(encoding="utf-8"))
            except Exception as exc:
                LOGGER.error("Failed to load voice-tts config from %s: %s", source, exc)
                self._config = {}
        self._config_loaded = True
        return self._config

    def _get_engine(self, name: str) -> TTSEngine:
        if name in self._engines:
            return self._engines[name]
        cfg = self._load_config()
        engine_cfg = (cfg.get("engines") or {}).get(name, {})
        engine = create_engine(name, engine_cfg)
        self._engines[name] = engine
        return engine

    def _save_wav(self, audio: np.ndarray, sample_rate: int, job_id: str) -> Path:
        import wave
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUT_DIR / f"{job_id}.wav"
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return path

    def _play(
        self,
        audio: np.ndarray,
        sample_rate: int,
        output_device: Optional[int] = None,
    ) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            LOGGER.warning("sounddevice not installed; skipping playback.")
            return
        try:
            sd.play(audio, sample_rate, device=output_device, blocking=True)
        except Exception as exc:
            LOGGER.error("sounddevice playback failed: %s", exc)

    @staticmethod
    def _to_int16_bytes(audio_np: np.ndarray) -> bytes:
        clipped = np.clip(audio_np, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()

    def _play_streaming(
        self,
        engine: TTSEngine,
        text: str,
        ref_audio: Optional[str],
        ref_text: Optional[str],
        params: Optional[Dict[str, Any]],
        job_id: str,
        message_id: Optional[str] = None,
        server_side_playback: bool = True,
        output_device: Optional[int] = None,
    ) -> bool:
        """Synthesize and play chunk-by-chunk while saving the full wav.

        If ``message_id`` is provided, each chunk is also forwarded to the
        in-process ``audio_stream`` registry so that the HTTP endpoint
        ``/api/addon/saiverse-voice-tts/audio/<message_id>/stream`` can serve
        the same audio to remote clients via HTTP Chunked Transfer.

        Returns True on success, False if streaming fell through and caller
        should use the non-streaming fallback.
        """
        sd = None
        if server_side_playback:
            try:
                import sounddevice as sd  # type: ignore
            except ImportError:
                LOGGER.warning(
                    "sounddevice not installed; streaming to HTTP only "
                    "(server-side playback disabled)."
                )
                sd = None

        device = output_device

        collected: list[np.ndarray] = []
        stream = None
        http_opened = False
        sample_rate: Optional[int] = None
        first_chunk_at: Optional[float] = None
        t_start = time.time()
        try:
            for chunk in engine.synthesize_stream(
                text=text, ref_audio=ref_audio, ref_text=ref_text, params=params,
            ):
                audio_np = chunk.audio
                if audio_np.ndim > 1:
                    audio_np = audio_np.reshape(-1)
                if audio_np.size == 0:
                    continue
                if sample_rate is None:
                    sample_rate = chunk.sample_rate
                    if sd is not None:
                        stream = sd.OutputStream(
                            samplerate=sample_rate,
                            channels=1,
                            device=device,
                            dtype="float32",
                        )
                        stream.start()
                    if message_id:
                        audio_stream.open_stream(message_id, sample_rate)
                        http_opened = True
                        # ストリーム開始直後に audio_ready を発火する。Route Handler
                        # 側で /stream エンドポイントは arrayBuffer バッファ展開を
                        # スキップして素通しするようになったため、クライアントは
                        # ここからチャンクを progressive に受け取って早期再生できる。
                        _notify_stream_ready(message_id)
                    first_chunk_at = time.time()
                    LOGGER.debug(
                        "TTS first chunk ready after %.2fs (job=%s, msg=%s)",
                        first_chunk_at - t_start, job_id, message_id,
                    )
                if stream is not None:
                    stream.write(audio_np.astype(np.float32, copy=False))
                if http_opened:
                    audio_stream.push_chunk(
                        message_id, self._to_int16_bytes(audio_np),
                    )
                collected.append(audio_np)
        except Exception as exc:
            LOGGER.error("Streaming synthesis/playback failed: %s", exc)
            if http_opened:
                audio_stream.close_stream(message_id)
            return False
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

        if http_opened:
            audio_stream.close_stream(message_id)

        if not collected or sample_rate is None:
            LOGGER.warning("Streaming produced no audio for job %s", job_id)
            return False

        try:
            full = np.concatenate(collected)
            wav_path = self._save_wav(full, sample_rate, job_id)
            LOGGER.debug(
                "TTS streamed wav saved: %s (%d ms, total %.2fs)",
                wav_path, int(len(full) / sample_rate * 1000), time.time() - t_start,
            )
            # ストリーミング経路は _notify_stream_ready で先に audio_ready を
            # 発火済み。ここでは完成 wav の metadata (audio_file) だけ更新し、
            # event の重複発火を避ける。
            _notify_audio_ready(message_id, wav_path, emit_event=False)
        except Exception as exc:
            LOGGER.warning("Failed to save streamed wav: %s", exc)

        return True

    def _gc_old_files(self) -> None:
        cfg = self._load_config()
        hours = float(cfg.get("gc_hours", 24))
        if hours <= 0 or not _OUT_DIR.exists():
            return
        cutoff = time.time() - hours * 3600
        for path in _OUT_DIR.glob("*.wav"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def _process(self, job: _Job) -> None:
        profile = get_profile(job.persona_id)
        if profile is None:
            LOGGER.info(
                "No voice profile for persona_id=%s (and no _default); skipping TTS.",
                job.persona_id,
            )
            return

        cfg = self._load_config()
        engine_name = profile.get("engine") or cfg.get("default_engine", "gpt_sovits")
        try:
            engine = self._get_engine(engine_name)
        except Exception as exc:
            LOGGER.error("Failed to initialize engine '%s': %s", engine_name, exc)
            return

        effective = _get_effective_params(job.persona_id)
        LOGGER.debug(
            "effective addon params for persona=%s: streaming=%s server_side=%s enabled=%s",
            job.persona_id,
            effective.get("streaming"),
            effective.get("server_side_playback"),
            effective.get("_enabled"),
        )
        use_streaming = bool(effective.get("streaming", True)) and getattr(
            engine, "supports_streaming", False
        )
        server_side_playback = bool(effective.get("server_side_playback", True))

        # UI で指定されたデバイス（"<default>" / "3: Realtek..." 等）を優先し、
        # 未指定なら config/default.json の output_device にフォールバックする。
        ui_device = effective.get("output_device")
        resolved_device = _parse_output_device(ui_device)
        if resolved_device is None:
            resolved_device = _parse_output_device(cfg.get("output_device"))

        if use_streaming:
            ok = self._play_streaming(
                engine=engine,
                text=job.text,
                ref_audio=profile.get("ref_audio"),
                ref_text=profile.get("ref_text"),
                params=profile.get("params"),
                job_id=job.job_id,
                message_id=job.message_id,
                server_side_playback=server_side_playback,
                output_device=resolved_device,
            )
            if ok:
                return
            LOGGER.info("Streaming failed; falling back to non-streaming synthesis.")

        try:
            result = engine.synthesize(
                text=job.text,
                ref_audio=profile.get("ref_audio"),
                ref_text=profile.get("ref_text"),
                params=profile.get("params"),
            )
        except Exception as exc:
            LOGGER.error("TTS synthesis failed (engine=%s): %s", engine_name, exc)
            return

        wav_path: Optional[Path] = None
        try:
            wav_path = self._save_wav(result.audio, result.sample_rate, job.job_id)
            LOGGER.debug("TTS wav saved: %s (%d ms)", wav_path, result.duration_ms)
        except Exception as exc:
            LOGGER.warning("Failed to save wav: %s", exc)

        if wav_path is not None:
            _notify_audio_ready(job.message_id, wav_path)

        if server_side_playback:
            self._play(result.audio, result.sample_rate, output_device=resolved_device)

    def _run(self) -> None:
        last_gc = 0.0
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                now = time.time()
                if now - last_gc > 3600:
                    self._gc_old_files()
                    last_gc = now
                continue
            if job is None:
                break
            try:
                self._process(job)
            except Exception:
                LOGGER.exception("Unhandled error in TTS worker")
            finally:
                self._queue.task_done()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="voice-tts-worker", daemon=True
            )
            self._thread.start()
            atexit.register(self.shutdown)

    def enqueue(self, text: str, persona_id: Optional[str]) -> str:
        self.start()
        job_id = uuid.uuid4().hex
        # Capture message_id here: the persona_context is valid at enqueue
        # time (tool invocation) but may be gone by the time the worker
        # thread actually picks up the job.
        captured_msg_id = _get_active_message_id()
        LOGGER.debug(
            "enqueue: job=%s persona=%s message_id=%s",
            job_id, persona_id, captured_msg_id,
        )
        self._queue.put(
            _Job(
                job_id=job_id,
                persona_id=persona_id,
                text=text,
                message_id=captured_msg_id,
            )
        )
        return job_id

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


_worker = _TTSWorker()


def enqueue_tts(text: str, persona_id: Optional[str]) -> str:
    return _worker.enqueue(text, persona_id)
