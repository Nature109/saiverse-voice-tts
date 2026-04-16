"""Strip markup/URIs from text before passing it to TTS.

Personas commonly produce Markdown-flavored text containing links to SAIVerse
resources. Reading the URL aloud (especially UUID-heavy paths) sounds unnatural,
so we flatten the markup and drop bare URIs before synthesis.
"""
from __future__ import annotations

import re

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_BACKTICK = re.compile(r"`+([^`]+?)`+")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_STRIKE = re.compile(r"~~([^~]+)~~")
_BARE_URL = re.compile(r"(?:https?|saiverse|ftp|file|mailto)://\S+", re.IGNORECASE)
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_LIST_MARK = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_MULTI_BLANK = re.compile(r"\n{3,}")


def clean_text_for_tts(text: str) -> str:
    if not text:
        return ""
    t = _MD_IMAGE.sub("", text)
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_REF_LINK.sub(r"\1", t)
    t = _BARE_URL.sub("", t)
    t = _BACKTICK.sub(r"\1", t)
    t = _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", t)
    t = _ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", t)
    t = _STRIKE.sub(r"\1", t)
    t = _HEADER.sub("", t)
    t = _LIST_MARK.sub("", t)
    t = _BLOCKQUOTE.sub("", t)
    t = _MULTI_BLANK.sub("\n\n", t)
    return t.strip()
