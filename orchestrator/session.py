"""Per-session memory for the prompt hook: what was already shown in this conversation.

An id shown SUPPRESS_AFTER times without being used (no ``used`` entry since the session started) is not shown
again in that session: repeating an ignored suggestion only costs context. The session id comes from the hook
payload; one that is not a plain token gets no memory at all. Every failure means "no memory", never an error.
"""
from __future__ import annotations

import json
import os
import re
import time

from .feedback import load_usage
from .jsonio import read_json

SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
SUPPRESS_AFTER = 2
KEEP_DAYS = 7


def _folder(state_dir: str) -> str:
    return os.path.join(state_dir, "sessions")


def session_path(state_dir: str, session_id):
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        return None
    return os.path.join(_folder(state_dir), session_id + ".json")


def load(state_dir: str, session_id, now: float = None):
    """{"started", "shown": {id: n}} for the session, a fresh one if none is stored, or None without a usable id."""
    path = session_path(state_dir, session_id)
    if path is None:
        return None
    try:
        data = read_json(path)
        if isinstance(data, dict) and isinstance(data.get("shown"), dict) and isinstance(data.get("started"), (int, float)):
            return data
    except (OSError, ValueError, RecursionError):
        pass
    return {"started": now if now is not None else time.time(), "shown": {}}


def suppressed(state_dir: str, memory) -> set:
    """Ids shown SUPPRESS_AFTER times or more and not used since the session started."""
    if not memory:
        return set()
    used = {row["id"] for row in load_usage(state_dir) if row["ts"] >= memory["started"]}
    return {ident for ident, count in memory["shown"].items() if isinstance(count, int) and count >= SUPPRESS_AFTER and ident not in used}


def record(state_dir: str, session_id, memory, ids, now: float = None) -> None:
    """Add the shown ids and save; old session files are removed on the way. Never raises."""
    path = session_path(state_dir, session_id)
    if path is None or memory is None:
        return
    for ident in ids:
        memory["shown"][ident] = int(memory["shown"].get(ident, 0)) + 1
    try:
        os.makedirs(_folder(state_dir), exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(memory, handle, ensure_ascii=False)
        os.replace(temp, path)
        _prune(state_dir, now if now is not None else time.time())
    except OSError:
        pass


def _prune(state_dir: str, now: float) -> None:
    folder = _folder(state_dir)
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        try:
            if name.endswith(".json") and now - os.path.getmtime(full) > KEEP_DAYS * 86400:
                os.unlink(full)
        except OSError:
            continue
