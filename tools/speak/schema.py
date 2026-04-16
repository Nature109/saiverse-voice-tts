"""speak_as_persona tool — fire-and-forget TTS for persona utterances.

Auto-discovered by SAIVerse from:
    expansion_data/saiverse-voice-tts/tools/speak/schema.py

The tool enqueues a synthesis job and returns immediately so that SEA
playbook execution is not blocked by TTS latency. Actual audio playback
happens on the backend PC's speaker via sounddevice.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from tools.core import ToolSchema
from tools.context import get_active_persona_id

from .playback_worker import enqueue_tts, get_effective_params
from .text_cleaner import clean_text_for_tts

LOGGER = logging.getLogger(__name__)


def schema() -> ToolSchema:
    return ToolSchema(
        name="speak_as_persona",
        description=(
            "Synthesize the given text in the active persona's cloned voice and "
            "play it on the backend machine's speaker. Fire-and-forget: returns "
            "immediately with a job id; actual audio playback happens asynchronously."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to speak (the persona's utterance).",
                },
            },
            "required": ["text"],
        },
        result_type="object",
    )


def speak_as_persona(text: str) -> Dict[str, Any]:
    cleaned = clean_text_for_tts(text or "")
    if not cleaned:
        return {"content": "", "status": "skipped_empty"}

    persona_id = get_active_persona_id()

    # Honour addon UI toggles: the addon can be globally disabled, or the
    # "auto_speak" flag can be off (per-persona overrides applied by the host).
    params = get_effective_params(persona_id)
    if not params.get("_enabled", True):
        LOGGER.debug(
            "speak_as_persona skipped: addon disabled (persona=%s)", persona_id,
        )
        return {"content": "", "status": "skipped_addon_disabled"}
    if not params.get("auto_speak", True):
        LOGGER.debug(
            "speak_as_persona skipped: auto_speak=false (persona=%s)", persona_id,
        )
        return {"content": "", "status": "skipped_auto_speak_off"}

    job_id = enqueue_tts(cleaned, persona_id)
    LOGGER.debug(
        "speak_as_persona enqueued: persona=%s job=%s len=%d (orig_len=%d)",
        persona_id, job_id, len(cleaned), len(text or ""),
    )
    return {
        "content": "",
        "metadata": {
            "voice_tts": {
                "status": "queued",
                "job_id": job_id,
                "persona_id": persona_id,
            }
        },
    }
