"""BM25 search over registry entries (stdlib only).

Two small additions keep a lexical ranker useful for natural requests: a stemmer that collapses
common inflections, and a data-driven table of synonym groups and phrases (data/synonyms.json)
that expands the *query* only, at half weight, so exact words always outrank guesses.
"""
from __future__ import annotations

import json
import math
import os
import re

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
STOPWORDS = frozenset(
    "a an and any are as at be by do does for from how i if in is it its my not of on or so that the this to we "
    "when will with you your use used using can all".split()
)
SYNONYMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "synonyms.json")
EXPANSION_WEIGHT = 0.5
_VOWELS = "aeiou"


def _stem(token: str) -> str:
    if len(token) <= 3:
        return token
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    for suffix in ("ing", "ed"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            base = token[: -len(suffix)]
            if base[-1] == base[-2] and base[-1] not in _VOWELS and base[-1] not in "lsz":
                base = base[:-1]
            return base
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str):
    tokens = []
    for raw in _WORD.findall((text or "").lower()):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        tokens.append(_stem(raw))
    return tokens


_SYNONYMS = None


def load_synonyms():
    """Return (token -> set of related tokens, ordered list of (phrase, replacement words))."""
    global _SYNONYMS
    if _SYNONYMS is None:
        related, phrases = {}, []
        try:
            with open(SYNONYMS_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
        for group in data.get("groups", []):
            stems = {t for word in group for t in tokenize(word)}
            for stem in stems:
                related.setdefault(stem, set()).update(stems - {stem})
        for phrase, words in data.get("phrases", {}).items():
            phrases.append((phrase.lower(), words))
        _SYNONYMS = (related, phrases)
    return _SYNONYMS


def query_weights(query: str):
    """Map each query token to a weight: 1.0 for the user's words, 0.5 for expansions."""
    related, phrases = load_synonyms()
    lowered = (query or "").lower()
    extra = " ".join(words for phrase, words in phrases if phrase in lowered)
    weights = {t: 1.0 for t in tokenize(lowered)}
    for token in tokenize(extra):
        weights.setdefault(token, EXPANSION_WEIGHT)
    for token in list(weights):
        if weights[token] == 1.0:
            for other in related.get(token, ()):
                weights.setdefault(other, EXPANSION_WEIGHT)
    return weights


def _doc_tokens(entry: dict):
    return tokenize(entry.get("name", "")) * 3 + tokenize(entry.get("description", "")) + tokenize(entry.get("when_to_use", ""))


def rank(entries, query: str, k: int = 5, k1: float = 1.5, b: float = 0.75):
    """Return up to k (score, entry) pairs, best first. Only entries with score > 0."""
    weights = query_weights(query)
    if not weights or not entries:
        return []
    docs = [_doc_tokens(e) for e in entries]
    n = len(docs)
    avg = (sum(len(d) for d in docs) / float(n)) or 1.0
    df = {}
    for doc in docs:
        for token in set(doc):
            df[token] = df.get(token, 0) + 1
    scored = []
    for entry, doc in zip(entries, docs):
        if not doc:
            continue
        tf = {}
        for token in doc:
            tf[token] = tf.get(token, 0) + 1
        score = 0.0
        for token, weight in weights.items():
            if token not in tf:
                continue
            idf = math.log(1.0 + (n - df[token] + 0.5) / (df[token] + 0.5))
            freq = tf[token]
            score += weight * idf * (freq * (k1 + 1.0)) / (freq + k1 * (1.0 - b + b * len(doc) / avg))
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("id", "")))
    return scored[: max(0, k)]
