"""Make third-party text safe to show to a model or a human.

Skill descriptions come from strangers. Before they are echoed anywhere they lose
invisible and control characters (a common way to hide instructions), have their
whitespace flattened, and are cut to a fixed length.
"""
from __future__ import annotations

import re

# zero-width, bidi controls, word joiners, BOM, and the Unicode "tag" block (ASCII smuggling)
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SPACE = re.compile(r"\s+")


def sanitize(text, limit: int = 300) -> str:
    if not isinstance(text, str):
        return ""
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text
