"""One retrieval pipeline for ``find``, the prompt hook and ``eval``.

1. ``search.confident_matches``: BM25F plus the confidence gates, on the raw score.
2. Order factors that never let a result through by themselves: preferred (policy), the detected intent's
   profile, and usage feedback.
3. Copies of one skill (same ``dup_group``) collapse into one result, shown as the best-placed copy.
4. Ids suppressed for this session (hook only) are dropped.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from functools import lru_cache
import os

from .conflicts import load_conflicts
from .policy import PREFERRED_BOOST, matches
from .search import DEFAULT_MIN_SCORE, DEFAULT_MIN_TERMS, confident_matches

INTENT_BOOST = 1.2


def kind(entry: dict) -> str:
    """The type of artifact found in the registry."""
    return {"tool": "TOOL", "workflow": "WORKFLOW"}.get(entry.get("kind"), "SKILL")


def auto_eligible(entry: dict) -> bool:
    """Old skills store their manual-only setting in listed. Catalog listing cost is unrelated."""
    return bool(entry.get("auto_eligible", kind(entry) != "SKILL" or entry.get("listed", True)))


@lru_cache(maxsize=1)
def _pin_clusters():
    path = os.path.join(os.path.dirname(__file__), "data", "conflicts.json")
    return [c for c in load_conflicts(path)["clusters"] if c["policy"] == "owner-pin"]


def owner_pins(entry: dict):
    """Resolve owner conditions even when no other member of the cluster is installed."""
    ident = entry["id"].casefold()
    tool_names = {str(entry.get("name", "")).casefold(), ident.rsplit("/", 1)[-1]}
    return [c["id"] for c in _pin_clusters()
            if any(fnmatchcase(ident, p.casefold()) for p in c["members"])
            or (kind(entry) == "TOOL" and any(label.partition(" (")[0].casefold() in tool_names for label in c.get("tools", [])))]


def display_origin(entry: dict, show_internal: bool = False):
    """Select a physical copy of the indexed text; aggregated flags may describe a different version."""
    origins = entry.get("origins")
    if not origins:
        return entry
    primary = [o for o in origins if o["sha256"] == entry.get("sha256")]
    # An override may explicitly expose an otherwise entirely internal entry.
    if not show_internal and any(not o["internal"] for o in origins):
        primary = [o for o in primary if not o["internal"]]
    if not primary:
        return None
    def origin_key(origin):
        platform = origin.get("platform")
        proxy = dict(origin, platforms=[platform] if platform else [])
        return (origin["internal"], copy_priority(proxy)[0], origin["path"], origin["source"])
    origin = min(primary, key=origin_key)
    platform = origin.get("platform")
    return dict(entry, path=origin["path"], origin_source=origin["source"], hot=origin["hot"],
                platforms=[platform] if platform else [])


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
    elif str(entry.get("origin_source", entry.get("source", ""))).startswith("project:"):
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
    hits = {}
    for score, entry, matched in confident_matches(pool, queries, min_score, min_terms):
        weight = factors.get(entry.get("id"), 1.0)
        if matches(entry, preferred):
            weight *= PREFERRED_BOOST
        if in_profile(entry, profile):
            weight *= INTENT_BOOST
        key = entry.get("dup_group") or entry.get("id")
        hits.setdefault(key, []).append({"entry": entry, "score": score, "order": score * weight,
                                         "weight": weight, "matched": matched})
    results = []
    for key, candidates in hits.items():
        best = max(candidates, key=lambda c: c["order"])
        # Slight document-length differences need not move a workflow to a vendor copy.
        # Retain policy and feedback preferences among copies with the same evidence.
        equivalent = (c for c in candidates if c["matched"] == best["matched"])
        item = min(equivalent, key=lambda c: (-c["weight"], copy_priority(c["entry"])))
        shown = item["entry"]
        if shown.get("id") in suppressed:
            continue
        results.append({"entry": shown, "score": item["score"], "order": item["order"], "matched": item["matched"],
                        "copies": len(groups[key]) - 1})
    results.sort(key=lambda r: (-r["order"], r["entry"].get("id", "")))
    return results
