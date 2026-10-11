"""Make third-party text safe to show to a model or a human.

Skill descriptions, names and folder names come from strangers. Before they are echoed anywhere
they lose invisible and control characters (a common way to hide instructions), have their
whitespace flattened, and are cut to a fixed length.
"""
from __future__ import annotations

import re
import unicodedata

# Not in category Cf, but they render as nothing (fillers, joiners, Braille blank, Hangul fillers).
_BLANK = frozenset(ord(c) for c in "\u034f\u115f\u1160\u17b4\u17b5\u2800\u3164\uffa0")
_TO_SPACE = re.compile("[\x0b\x0c\x1c-\x1f]")
_CONTROL = re.compile("[\x00-\x08\x0e-\x1b\x7f-\x9f]")
_SPACE = re.compile(r"\s+")


def is_invisible(char: str) -> bool:
    """True for every format character (category Cf), the blank-rendering list, variation selectors and tags."""
    code = ord(char)
    if code < 0xAD:  # ASCII and C1 controls: handled as control characters
        return False
    return (code in _BLANK or 0xFE00 <= code <= 0xFE0F or 0xE0000 <= code <= 0xE007F or 0xE0100 <= code <= 0xE01EF
            or unicodedata.category(char) == "Cf")


def sanitize(text, limit: int = 300) -> str:
    if not isinstance(text, str):
        return ""
    if not text.isascii():
        text = "".join(char for char in text if not is_invisible(char))
    text = _TO_SPACE.sub(" ", text)
    text = _CONTROL.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return text
