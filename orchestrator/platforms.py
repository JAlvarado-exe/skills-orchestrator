"""Platform adapters are data: a JSON file that lists where each agent platform keeps skills."""
from __future__ import annotations

import json
import os


def load_platforms(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _expand(path: str, home: str) -> str:
    if path.startswith("~"):
        path = home + path[1:]
    return os.path.normpath(os.path.expandvars(path))


def resolve_roots(data: dict, home: str = None):
    """Return (roots, missing). roots exist on disk and can be passed to build_registry."""
    home = home or os.path.expanduser("~")
    roots, missing = [], []
    for platform in data.get("platforms", []):
        for root in platform.get("roots", []):
            path = _expand(root["path"], home)
            record = {
                "path": path,
                "platform": platform["id"],
                "status": platform.get("status", "documented-only"),
                "hot": bool(root.get("hot", False)),
                "source": root.get("source") or platform["id"],
                "source_from": root.get("source_from", "fixed"),
            }
            (roots if os.path.isdir(path) else missing).append(record)
    return roots, missing
