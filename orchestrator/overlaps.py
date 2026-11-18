"""Find skills that probably do the same job, so a human (or a curated conflicts file) can arbitrate.

Similarity uses the overlap coefficient (shared keywords / size of the smaller keyword set) with a
minimum number of shared keywords. Jaccard punishes long descriptions too much: a 15-word skill and
a 60-word skill about the same thing barely register.
"""
from __future__ import annotations

import heapq

from .search import tokenize


def _sources(entry: dict):
    return set(entry.get("sources") or [entry.get("source")])


def _keywords(entry: dict):
    tags = " ".join(t for t in entry.get("tags", []) if isinstance(t, str))
    return set(tokenize(entry.get("name", ""))) | set(tokenize(entry.get("description", "") + " " + entry.get("when_to_use", "") + " " + tags))


def _candidate_scores(keyed, min_shared, threshold):
    postings = {}
    required = max(min_shared, int(threshold > 0))
    for i in reversed(range(len(keyed))):
        a, ka, sa = keyed[i]
        if not ka or len(ka) < required:
            continue
        if required:
            # A qualifying pair must share a word outside any required-1 excluded words.
            # Omit the most frequent words, which would generate the largest posting lists.
            words = sorted(ka, key=lambda word: len(postings.get(word, ())))
            candidates = set()
            for word in words[:len(words) - required + 1]:
                candidates.update(postings.get(word, ()))
        else:
            candidates = range(i + 1, len(keyed))
        for j in candidates:
            b, kb, sb = keyed[j]
            if not kb or not sa.isdisjoint(sb):
                continue
            shared = len(ka & kb)
            if shared >= min_shared:
                score = shared / min(len(ka), len(kb))
                if score >= threshold:
                    yield (-round(score, 3), -shared, a["id"], b["id"], i, j)
        for word in ka:
            postings.setdefault(word, []).append(i)


def find_overlaps(entries, threshold: float = 0.4, limit: int = 50, min_shared: int = 4):
    entries = list(entries)
    by_name = {}
    for entry in entries:
        by_name.setdefault(entry["name"], []).append(entry["id"])
    collisions = [{"name": name, "ids": sorted(ids)} for name, ids in sorted(by_name.items()) if len(ids) > 1]

    keyed = [(e, _keywords(e), _sources(e)) for e in entries if not e.get("internal")]
    scores = _candidate_scores(keyed, min_shared, threshold)
    best = heapq.nsmallest(limit, scores) if limit >= 0 else sorted(scores)[:limit]
    similar = []
    for score, count, a, b, i, j in best:
        shared = -count
        union = len(keyed[i][1]) + len(keyed[j][1]) - shared
        similar.append({"a": a, "b": b, "score": -score, "shared": shared, "jaccard": round(shared / union, 3)})
    return {"name_collisions": collisions, "similar": similar}
