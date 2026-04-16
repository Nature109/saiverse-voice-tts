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

LOGGER = logging.getLogger(__name__)

_PACK_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PACK_ROOT / "config" / "default.json"


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
        if _CONFIG_PATH.exists():
            try:
                self._config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                LOGGER.error("Failed to load voice-tts config: %s", exc)
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

    def _play(self, audio: np.ndarray, sample_rate: int) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            LOGGER.warning("sounddevice not installed; skipping playback.")
            return
        try:
            cfg = self._load_config()
            device = cfg.get("output_device")
            sd.play(audio, sample_rate, device=device, blocking=True)
        except Exception as exc:
            LOGGER.error("sounddevice playback failed: %s", exc)

    def _play_streaming(
        self,
        engine: TTSEngine,
        text: str,
        ref_audio: Optional[str],
        ref_text: Optional[str],
        params: Optional[Dict[str, Any]],
        job_id: str,
    ) -> bool:
        """Synthesize and play chunk-by-chunk while saving the full wav.

        Returns True on success, False if streaming fell through and caller
        should use the non-streaming fallback.
        """
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            LOGGER.warning("sounddevice not installed; skipping streaming playback.")
            return True  # nothing to fall back to

        cfg = self._load_config()
        device = cfg.get("output_device")

        collected: list[np.ndarray] = []
        stream = None
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
                if stream is None:
                    sample_rate = chunk.sample_rate
                    stream = sd.OutputStream(
                        samplerate=sample_rate,
                        channels=1,
                        device=device,
                        dtype="float32",
                    )
                    stream.start()
                    first_chunk_at = time.time()
                    LOGGER.debug(
                        "TTS first chunk ready after %.2fs (job=%s)",
                        first_chunk_at - t_start, job_id,
                    )
                stream.write(audio_np.astype(np.float32, copy=False))
                collected.append(audio_np)
        except Exception as exc:
            LOGGER.error("Streaming synthesis/playback failed: %s", exc)
            return False
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

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
        engine_name = profile.get("engine") or cfg.get("default_engine", "qwen3_tts")
        try:
            engine = self._get_engine(engine_name)
        except Exception as exc:
            LOGGER.error("Failed to initialize engine '%s': %s", engine_name, exc)
            return

        use_streaming = cfg.get("streaming", True) and getattr(
            engine, "supports_streaming", False
        )

        if use_streaming:
            ok = self._play_streaming(
                engine=engine,
                text=job.text,
                ref_audio=profile.get("ref_audio"),
                ref_text=profile.get("ref_text"),
                params=profile.get("params"),
                job_id=job.job_id,
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

        try:
            wav_path = self._save_wav(result.audio, result.sample_rate, job.job_id)
            LOGGER.debug("TTS wav saved: %s (%d ms)", wav_path, result.duration_ms)
        except Exception as exc:
            LOGGER.warning("Failed to save wav: %s", exc)

        self._play(result.audio, result.sample_rate)

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
        self._queue.put(_Job(job_id=job_id, persona_id=persona_id, text=text))
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
