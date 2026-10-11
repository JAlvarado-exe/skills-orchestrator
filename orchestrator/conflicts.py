"""Curated conflict clusters: groups of skills that overlap, contradict or must be composed.

The file is hand-written because only a human (or a model reading both skills) knows whether two
similar skills are rivals or phases of one flow. Code only matches patterns and reports which
members are installed. Patterns are fnmatch globs against registry ids ("source/name").
"""
from __future__ import annotations

import json
from fnmatch import fnmatchcase

RELATIONS = ("alternatives", "complementary", "contradictory")
POLICIES = ("compose", "prefer-by-context", "owner-pin")


def load_conflicts(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_conflicts(data: dict):
    problems = []
    seen = set()
    for index, cluster in enumerate(data.get("clusters", [])):
        label = cluster.get("id") or "#%d" % index
        if not cluster.get("id"):
            problems.append("cluster %s: missing id" % label)
        elif cluster["id"] in seen:
            problems.append("cluster %s: duplicate id" % label)
        seen.add(cluster.get("id"))
        for key in ("topic", "guidance"):
            if not cluster.get(key):
                problems.append("cluster %s: missing %s" % (label, key))
        if cluster.get("relation") not in RELATIONS:
            problems.append("cluster %s: relation must be one of %s" % (label, ", ".join(RELATIONS)))
        if cluster.get("policy") not in POLICIES:
            problems.append("cluster %s: policy must be one of %s" % (label, ", ".join(POLICIES)))
        members, tools = cluster.get("members", []), cluster.get("tools", [])
        if not members or len(members) + len(tools) < 2:
            problems.append("cluster %s: needs at least two members or tools" % label)
    return problems


def match_clusters(data: dict, entries, skill_id: str = None):
    """Return clusters (optionally only those containing skill_id) with the installed member ids."""
    result = []
    for cluster in data.get("clusters", []):
        patterns = cluster.get("members", [])
        if skill_id is not None and not any(fnmatchcase(skill_id, p) for p in patterns):
            continue
        present = sorted(e["id"] for e in entries if any(fnmatchcase(e["id"], p) for p in patterns))
        copy = dict(cluster)
        copy["present"] = present
        result.append(copy)
    return result
