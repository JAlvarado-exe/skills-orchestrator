"""Profiles are named lists of skill-id patterns that narrow a search to what a kind of task needs."""
from __future__ import annotations

import json
import os
from fnmatch import fnmatchcase


def load_profile(name: str, dirs):
    for directory in dirs:
        path = os.path.join(directory, name + ".json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data.setdefault("name", name)
            return data
    raise KeyError(name)


def filter_entries(entries, profile: dict):
    include = profile.get("include") or ["*"]
    exclude = profile.get("exclude") or []
    kept = []
    for entry in entries:
        if any(fnmatchcase(entry["id"], p) for p in include) and not any(fnmatchcase(entry["id"], p) for p in exclude):
            kept.append(entry)
    return kept
