"""Local usage feedback: which suggested skills were used, whether they helped, and how often each was shown.

``used`` appends one JSON line per use to ``<state_dir>/usage.jsonl``; the hook counts how often it showed each id in
``<state_dir>/stats.json``. Ranking turns both into a bounded order factor: helpful uses lift a skill by up to
MAX_BOOST, and a skill shown many times but never used drops by up to MAX_PENALTY. The factor only reorders results
that already passed the confidence gates; it never makes a result appear. Nothing here leaves the machine.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager

from .jsonio import read_json, write_json_atomic

USAGE_FILE = "usage.jsonl"
STATS_FILE = "stats.json"
MAX_BOOST = 0.3
BOOST_PER_HELP = 0.1
MAX_PENALTY = 0.3
PENALTY_PER_SHOW = 0.02
FREE_SHOWS = 5
HELPED_VALUES = ("yes", "no")
INDEX_FILE = "usage-index.json"


@contextmanager
def state_lock(state_dir: str):
    """Serialize local writers across processes; the OS releases the lock if a writer exits."""
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, ".state.lock"), "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            deadline = time.monotonic() + 5
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def default_state_dir(registry_file: str) -> str:
    """The ``state`` folder next to the registry, like the hook's log: per machine, never inside a repository."""
    return os.path.join(os.path.dirname(os.path.abspath(registry_file)), "state")


def record_use(state_dir: str, ident: str, helped=None, now: float = None, session_id=None) -> dict:
    """Append one use. Raises OSError when the folder cannot be written."""
    row = {"ts": round(now if now is not None else time.time(), 3), "id": ident,
           "helped": helped if helped in HELPED_VALUES else None}
    from . import session
    with state_lock(state_dir):
        if session_id is None:
            session_id = session.sole_session(state_dir, ident, row["ts"])
        if session.session_path(state_dir, session_id):
            row["session_id"] = session_id
        with open(os.path.join(state_dir, USAGE_FILE), "a+b") as handle:
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    handle.write(b"\n")
            handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    return row


def load_usage(state_dir: str):
    """Every well-formed use row; broken lines are skipped."""
    rows = []
    try:
        with open(os.path.join(state_dir, USAGE_FILE), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("ts"), (int, float)):
                    rows.append(row)
    except OSError:
        return []
    return rows


def load_stats(state_dir: str) -> dict:
    try:
        data = read_json(os.path.join(state_dir, STATS_FILE))
    except (OSError, ValueError, RecursionError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("shown"), int)
            and v["shown"] >= 0} if isinstance(data, dict) else {}


def bump_shown(state_dir: str, ids) -> None:
    """Add one to the shown count of each id. Silently does nothing when the folder cannot be written."""
    if not ids:
        return
    try:
        with state_lock(state_dir):
            stats = load_stats(state_dir)
            for ident in ids:
                record = stats.setdefault(ident, {})
                record["shown"] = int(record.get("shown", 0)) + 1
            write_json_atomic(os.path.join(state_dir, STATS_FILE), stats)
    except OSError:
        pass


def tally(usage_rows, stats: dict) -> dict:
    """{id: {"shown", "used", "helpful", "unhelpful"}} over everything recorded."""
    table = {}
    for ident, record in stats.items():
        table.setdefault(ident, {"shown": 0, "used": 0, "helpful": 0, "unhelpful": 0})["shown"] = int(record.get("shown", 0))
    for row in usage_rows:
        record = table.setdefault(row["id"], {"shown": 0, "used": 0, "helpful": 0, "unhelpful": 0})
        record["used"] += 1
        if row.get("helped") == "yes":
            record["helpful"] += 1
        elif row.get("helped") == "no":
            record["unhelpful"] += 1
    return table


def factor(record: dict) -> float:
    """Bound the net helpfulness signal; unhelpful-only uses retain the exposure penalty."""
    negative = record.get("unhelpful", 0)
    signal = BOOST_PER_HELP * (record.get("helpful", 0) - negative)
    if record.get("used", 0) <= negative:
        signal -= PENALTY_PER_SHOW * max(0, record.get("shown", 0) - FREE_SHOWS)
    return 1.0 + max(-MAX_PENALTY, min(MAX_BOOST, signal))


def usage_index(state_dir: str):
    """Summarize new log bytes once. Rebuild from JSON lines if the cache or log was replaced."""
    path = os.path.join(state_dir, USAGE_FILE)
    index_path = os.path.join(state_dir, INDEX_FILE)
    if not os.path.isfile(path):
        return {}, {}
    try:
        with state_lock(state_dir), open(path, "rb") as log:
            stat = os.fstat(log.fileno())
            try:
                index = read_json(index_path)
            except (OSError, ValueError, RecursionError):
                index = {}
            if not isinstance(index, dict):
                index = {}
            totals, sessions = index.get("totals"), index.get("sessions")
            size = index.get("size")
            reusable = (isinstance(totals, dict) and isinstance(sessions, dict) and isinstance(size, int)
                        and 0 <= size <= stat.st_size and index.get("inode") == stat.st_ino)
            if reusable:
                reusable = (all(isinstance(counts, dict) and all(isinstance(counts.get(key), int)
                                for key in ("used", "helpful", "unhelpful")) for counts in totals.values())
                            and all(isinstance(uses, dict) and all(isinstance(ts, (int, float))
                                    for ts in uses.values()) for uses in sessions.values()))
            if reusable and size == stat.st_size and index.get("mtime") == stat.st_mtime_ns:
                return totals, sessions
            if reusable and size < stat.st_size and index.get("complete_line"):
                log.seek(size)
            else:
                totals, sessions = {}, {}
            complete_line = True
            for line in log:
                complete_line = line.endswith(b"\n")
                try:
                    row = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("ts"), (int, float)):
                    continue
                ident = row["id"]
                counts = totals.setdefault(ident, {"used": 0, "helpful": 0, "unhelpful": 0})
                counts["used"] += 1
                if row.get("helped") in HELPED_VALUES:
                    counts["helpful" if row["helped"] == "yes" else "unhelpful"] += 1
                sid = row.get("session_id")
                if isinstance(sid, str) and row.get("helped") != "no":
                    by_id = sessions.setdefault(sid, {})
                    by_id[ident] = max(by_id.get(ident, 0), row["ts"])
            # Active long-running sessions keep their first use. Expired sessions no longer need timestamps.
            from .session import session_path
            sessions = {sid: uses for sid, uses in sessions.items()
                        if (file := session_path(state_dir, sid)) is not None and os.path.isfile(file)}
            write_json_atomic(index_path, {"size": stat.st_size, "inode": stat.st_ino, "mtime": stat.st_mtime_ns,
                                          "complete_line": complete_line, "totals": totals, "sessions": sessions})
            return totals, sessions
    except OSError:
        return {}, {}


def factors(state_dir: str, totals=None) -> dict:
    if totals is None:
        totals, _sessions = usage_index(state_dir)
    stats = load_stats(state_dir)
    return {ident: factor(dict(totals.get(ident, {}), shown=stats.get(ident, {}).get("shown", 0)))
            for ident in totals.keys() | stats.keys()}
