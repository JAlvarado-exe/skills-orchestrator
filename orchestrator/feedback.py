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

from .jsonio import read_json

USAGE_FILE = "usage.jsonl"
STATS_FILE = "stats.json"
MAX_BOOST = 0.3
BOOST_PER_HELP = 0.1
MAX_PENALTY = 0.3
PENALTY_PER_SHOW = 0.02
FREE_SHOWS = 5
HELPED_VALUES = ("yes", "no")


def default_state_dir(registry_file: str) -> str:
    """The ``state`` folder next to the registry, like the hook's log: per machine, never inside a repository."""
    return os.path.join(os.path.dirname(os.path.abspath(registry_file)), "state")


def record_use(state_dir: str, ident: str, helped=None, now: float = None) -> dict:
    """Append one use. Raises OSError when the folder cannot be written."""
    row = {"ts": round(now if now is not None else time.time(), 3), "id": ident,
           "helped": helped if helped in HELPED_VALUES else None}
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, USAGE_FILE), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_usage(state_dir: str):
    """Every well-formed use row; broken lines are skipped."""
    rows = []
    try:
        with open(os.path.join(state_dir, USAGE_FILE), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
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
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def bump_shown(state_dir: str, ids) -> None:
    """Add one to the shown count of each id. Silently does nothing when the folder cannot be written."""
    if not ids:
        return
    stats = load_stats(state_dir)
    for ident in ids:
        record = stats.setdefault(ident, {})
        record["shown"] = int(record.get("shown", 0)) + 1
    try:
        os.makedirs(state_dir, exist_ok=True)
        temp = os.path.join(state_dir, STATS_FILE + ".tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(stats, handle, ensure_ascii=False)
        os.replace(temp, os.path.join(state_dir, STATS_FILE))
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
    """1 + bounded boost for helpful uses - bounded penalty for being shown often and never used."""
    boost = min(MAX_BOOST, BOOST_PER_HELP * record.get("helpful", 0))
    penalty = 0.0
    if not record.get("used"):
        penalty = min(MAX_PENALTY, PENALTY_PER_SHOW * max(0, record.get("shown", 0) - FREE_SHOWS))
    return 1.0 + boost - penalty


def factors(state_dir: str) -> dict:
    return {ident: factor(record) for ident, record in tally(load_usage(state_dir), load_stats(state_dir)).items()}
