"""Find skills that probably do the same job, so a human (or a curated conflicts file) can arbitrate.

Similarity uses the overlap coefficient (shared keywords / size of the smaller keyword set) with a
minimum number of shared keywords. Jaccard punishes long descriptions too much: a 15-word skill and
a 60-word skill about the same thing barely register.
"""
from __future__ import annotations

from .search import tokenize


def _sources(entry: dict):
    return set(entry.get("sources") or [entry.get("source")])


def _keywords(entry: dict):
    return set(tokenize(entry.get("name", ""))) | set(tokenize(entry.get("description", "") + " " + entry.get("when_to_use", "")))


def find_overlaps(entries, threshold: float = 0.4, limit: int = 50, min_shared: int = 4):
    by_name = {}
    for entry in entries:
        by_name.setdefault(entry["name"], []).append(entry["id"])
    collisions = [{"name": name, "ids": sorted(ids)} for name, ids in sorted(by_name.items()) if len(ids) > 1]

    keyed = [(e, _keywords(e), _sources(e)) for e in entries if not e.get("internal")]
    similar = []
    for i in range(len(keyed)):
        a, ka, sa = keyed[i]
        if not ka:
            continue
        for j in range(i + 1, len(keyed)):
            b, kb, sb = keyed[j]
            if not kb or (sa & sb):
                continue
            shared = len(ka & kb)
            if shared < min_shared:
                continue
            score = shared / float(min(len(ka), len(kb)))
            if score >= threshold:
                similar.append({"a": a["id"], "b": b["id"], "score": round(score, 3), "shared": shared,
                                "jaccard": round(shared / float(len(ka | kb)), 3)})
    similar.sort(key=lambda p: (-p["score"], -p["shared"], p["a"], p["b"]))
    return {"name_collisions": collisions, "similar": similar[:limit]}
