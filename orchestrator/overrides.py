"""Per-user classification of skills, kept next to the registry and never overwritten by a scan.

Format: {"source/name": {"tags": ["extra", "search", "words"], "internal": false, "note": "free text"}}
"""
from __future__ import annotations

import json
import os


def load_overrides(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_overrides(entries, overrides: dict):
    result = []
    for entry in entries:
        override = overrides.get(entry["id"])
        if not isinstance(override, dict):
            result.append(entry)
            continue
        copy = dict(entry)
        tags = [t for t in override.get("tags", []) if isinstance(t, str)]
        if tags:
            copy["tags"] = tags
            copy["when_to_use"] = (entry.get("when_to_use", "") + " " + " ".join(tags)).strip()
        if isinstance(override.get("note"), str):
            copy["note"] = override["note"]
        if "internal" in override:
            copy["internal"] = bool(override["internal"])
        result.append(copy)
    return result
