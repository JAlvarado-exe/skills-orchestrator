"""Profiles are named lists of skill-id patterns that narrow a search to what a kind of task needs."""
from __future__ import annotations

import os
import re
from fnmatch import fnmatchcase

from .jsonio import read_json

PROFILE_NAME = re.compile(r"[A-Za-z0-9_-]+")


def load_profile(name: str, dirs):
    """Load NAME.json from the first directory that has it. Raises KeyError (missing) or ValueError (bad name or file)."""
    if not PROFILE_NAME.fullmatch(name or ""):
        raise ValueError("a profile name may only contain letters, digits, '-' and '_'")
    for directory in dirs:
        path = os.path.join(directory, name + ".json")
        if os.path.isfile(path):
            data = read_json(path)
            if not isinstance(data, dict):
                raise ValueError("a profile file must hold a JSON object")
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
