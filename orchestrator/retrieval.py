"""One retrieval pipeline for ``find``, the prompt hook and ``eval``.

1. ``search.confident_matches``: BM25F plus the confidence gates, on the raw score.
2. Order factors that never let a result through by themselves: preferred (policy), the detected intent's
   profile, and usage feedback.
3. Copies of one skill (same ``dup_group``) collapse into one result, shown as the best-placed copy.
4. Ids suppressed for this session (hook only) are dropped.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

from .policy import PREFERRED_BOOST, matches
from .search import DEFAULT_MIN_SCORE, DEFAULT_MIN_TERMS, confident_matches

INTENT_BOOST = 1.2


def kind(entry: dict) -> str:
    """SKILL (a SKILL.md to read by path) or TOOL (a program to run)."""
    return "TOOL" if entry.get("kind") == "tool" else "SKILL"


def state(entry: dict) -> str:
    return "hot" if entry.get("hot") else "tool" if entry.get("kind") == "tool" else "cold"


def copy_priority(entry: dict):
    """Which copy of a skill to show: hot, then a platform's user folder, a project, a configured folder, a cloned
    library (cold) and last a catalog tool; then the id, for a stable choice."""
    platforms = entry.get("platforms") or []
    if entry.get("hot"):
        rank = 0
    elif entry.get("kind") == "tool":
        rank = 5
    elif "vendor" in platforms:
        rank = 4
    elif platforms:
        rank = 1
    elif str(entry.get("source", "")).startswith("project:"):
        rank = 2
    else:
        rank = 3
    return (rank, entry.get("id", ""))


def in_profile(entry: dict, profile) -> bool:
    if not profile:
        return False
    include = profile.get("include") or []
    exclude = profile.get("exclude") or []
    ident = entry.get("id", "")
    return any(fnmatchcase(ident, p) for p in include) and not any(fnmatchcase(ident, p) for p in exclude)


def retrieve(pool, queries, min_score=None, min_terms=None, preferred=(), profile=None, factors=None, suppressed=()):
    """[{"entry", "score", "order", "matched", "copies"}] best first; [] means nothing is confident enough."""
    min_score = DEFAULT_MIN_SCORE if min_score is None else min_score
    min_terms = DEFAULT_MIN_TERMS if min_terms is None else min_terms
    factors = factors or {}
    groups = {}
    for entry in pool:
        groups.setdefault(entry.get("dup_group") or entry.get("id"), []).append(entry)
    best = {}
    for score, entry, matched in confident_matches(pool, queries, min_score, min_terms):
        order = score
        if matches(entry, preferred):
            order *= PREFERRED_BOOST
        if in_profile(entry, profile):
            order *= INTENT_BOOST
        order *= factors.get(entry.get("id"), 1.0)
        key = entry.get("dup_group") or entry.get("id")
        if key not in best or order > best[key]["order"]:
            best[key] = {"score": score, "order": order, "matched": matched, "hit": entry}
    results = []
    for key, item in best.items():
        members = groups.get(key) or [item["hit"]]
        shown = min(members, key=copy_priority)
        if shown.get("id") in suppressed:
            continue
        results.append({"entry": shown, "score": item["score"], "order": item["order"], "matched": item["matched"],
                        "copies": len(members) - 1})
    results.sort(key=lambda r: (-r["order"], r["entry"].get("id", "")))
    return results
