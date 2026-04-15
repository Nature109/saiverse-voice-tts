"""Voice profile registry loader.

Maps persona_id to voice profile entry. Falls back to "_default" when a
persona has no registered profile.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)

_PACK_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _PACK_ROOT / "voice_profiles" / "registry.json"

_cached_registry: Optional[Dict[str, Any]] = None


def _load_registry() -> Dict[str, Any]:
    global _cached_registry
    if _cached_registry is not None:
        return _cached_registry
    if not _REGISTRY_PATH.exists():
        LOGGER.warning("Voice profile registry not found: %s", _REGISTRY_PATH)
        _cached_registry = {}
        return _cached_registry
    try:
        _cached_registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        LOGGER.error("Failed to parse voice profile registry: %s", exc)
        _cached_registry = {}
    return _cached_registry


def get_profile(persona_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the voice profile for persona_id, or _default if not registered.

    Returns None only if neither the persona nor _default is registered.
    Resolves ref_audio to an absolute path relative to the pack root.
    """
    registry = _load_registry()
    entry = None
    if persona_id and persona_id in registry:
        entry = dict(registry[persona_id])
    elif "_default" in registry:
        entry = dict(registry["_default"])
    if entry is None:
        return None
    ref = entry.get("ref_audio")
    if ref and not Path(ref).is_absolute():
        entry["ref_audio"] = str((_PACK_ROOT / "voice_profiles" / ref).resolve())
    return entry


def reload_registry() -> None:
    global _cached_registry
    _cached_registry = None
