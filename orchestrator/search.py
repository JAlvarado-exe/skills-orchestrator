"""BM25 search over registry entries (stdlib only).

Two small additions keep a lexical ranker useful for natural requests: a stemmer that collapses
common inflections, and a data-driven table of synonym groups and phrases (data/synonyms.json)
that expands the *query* only. Expansions are scored as evidence, not as extra words: each
group (the synonyms of one query word, or the words of one matched phrase) contributes only its
single best match, at half weight, and never for a word the user already typed. So an exact word
outranks a document that merely lists many synonyms.
"""
from __future__ import annotations

import math
import os
import re

from .jsonio import read_json

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
    stem = token
    if len(token) > 4 and token.endswith("ies"):
        stem = token[:-3] + "y"
    else:
        for suffix in ("ing", "ed"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                stem = token[: -len(suffix)]
                if stem[-1] == stem[-2] and stem[-1] not in _VOWELS and stem[-1] not in "lsz":
                    stem = stem[:-1]
                break
        else:
            if token.endswith("s") and not token.endswith("ss"):
                stem = token[:-1]
    if len(stem) > 4 and stem.endswith("e"):  # create / creating / created -> creat
        stem = stem[:-1]
    return stem


def tokenize(text: str):
    tokens = []
    for raw in _WORD.findall((text or "").lower()):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        stem = _stem(raw)
        if stem in STOPWORDS:
            continue
        tokens.append(stem)
    return tokens


_SYNONYMS = None


def load_synonyms():
    """Return (token -> set of related tokens, list of (compiled phrase pattern, replacement words))."""
    global _SYNONYMS
    if _SYNONYMS is None:
        related, phrases = {}, []
        try:
            data = read_json(SYNONYMS_FILE)
        except (OSError, ValueError):
            data = {}
        for group in data.get("groups", []):
            stems = {t for word in group for t in tokenize(word)}
            for stem in stems:
                related.setdefault(stem, set()).update(stems - {stem})
        for phrase, words in data.get("phrases", {}).items():
            phrases.append((re.compile(r"\b" + re.escape(phrase.lower()) + r"\b"), words))
        _SYNONYMS = (related, phrases)
    return _SYNONYMS


def query_terms(query: str):
    """Return (the user's own tokens, a list of expansion groups). A group is a set of related tokens."""
    related, phrases = load_synonyms()
    lowered = (query or "").lower()
    exact = []
    for token in tokenize(lowered):
        if token not in exact:
            exact.append(token)
    typed = set(exact)
    groups = [related[t] - typed for t in exact if related.get(t, set()) - typed]
    for pattern, words in phrases:
        if pattern.search(lowered):
            group = set(tokenize(words)) - typed
            if group:
                groups.append(group)
    return exact, groups


def _doc_tokens(entry: dict):
    return tokenize(entry.get("name", "")) * 3 + tokenize(entry.get("description", "")) + tokenize(entry.get("when_to_use", ""))


def rank(entries, query: str, k: int = 5, k1: float = 1.5, b: float = 0.75):
    """Return up to k (score, entry) pairs, best first. Only entries with score > 0."""
    exact, groups = query_terms(query)
    if (not exact and not groups) or not entries:
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
        norm = k1 * (1.0 - b + b * len(doc) / avg)

        def bm25(token):
            freq = tf.get(token, 0)
            if not freq:
                return 0.0
            idf = math.log(1.0 + (n - df[token] + 0.5) / (df[token] + 0.5))
            return idf * (freq * (k1 + 1.0)) / (freq + norm)

        score = sum(bm25(t) for t in exact)
        score += EXPANSION_WEIGHT * sum(max(bm25(t) for t in group) for group in groups)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("id", "")))
    return scored[: max(0, k)]
