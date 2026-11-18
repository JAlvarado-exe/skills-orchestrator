"""Request intent from a keyword table (data/intents.json): build, review, debug, research, write, decide, operate.

No model call: words are folded and stemmed like the search, counted against each intent's keywords, and the
intent with the most hits wins (ties go to the earlier intent in the table). The result only changes ranking order.
"""
from __future__ import annotations

import os

from .jsonio import read_json
from .search import _WORD, _stem, fold

INTENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "intents.json")
NONE = "none"
_TABLE = None


def load_table(path: str = None):
    """[(intent id, profile name or None, set of stemmed keywords)] in table order."""
    global _TABLE
    if path is None and _TABLE is not None:
        return _TABLE
    try:
        data = read_json(path or INTENTS_FILE)
    except (OSError, ValueError, RecursionError):
        data = {}
    table = []
    for item in data.get("intents", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        words = {_stem(fold(word)) for word in item.get("keywords", []) if isinstance(word, str)}
        profile = item.get("profile") if isinstance(item.get("profile"), str) else None
        table.append((item["id"], profile, words))
    if path is None:
        _TABLE = table
    return table


def classify(text: str, table=None):
    """(intent id, profile name or None); ("none", None) when no keyword matches."""
    words = [_stem(word) for word in _WORD.findall(fold(text or ""))]
    best, best_hits = (NONE, None), 0
    for ident, profile, keywords in table if table is not None else load_table():
        hits = sum(1 for word in words if word in keywords)
        if hits > best_hits:
            best, best_hits = (ident, profile), hits
    return best
