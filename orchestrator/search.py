"""BM25 search over registry entries (stdlib only)."""
from __future__ import annotations

import math
import re

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
STOPWORDS = frozenset(
    "a an and any are as at be by do does for from how i if in is it its my not of on or so that the this to we "
    "when will with you your use used using can all".split()
)


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str):
    tokens = []
    for raw in _WORD.findall((text or "").lower()):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        tokens.append(_stem(raw))
    return tokens


def _doc_tokens(entry: dict):
    return tokenize(entry.get("name", "")) * 3 + tokenize(entry.get("description", "")) + tokenize(entry.get("when_to_use", ""))


def rank(entries, query: str, k: int = 5, k1: float = 1.5, b: float = 0.75):
    """Return up to k (score, entry) pairs, best first. Only entries with score > 0."""
    q_tokens = sorted(set(tokenize(query)))
    if not q_tokens or not entries:
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
        for token in q_tokens:
            if token not in tf:
                continue
            idf = math.log(1.0 + (n - df[token] + 0.5) / (df[token] + 0.5))
            freq = tf[token]
            score += idf * (freq * (k1 + 1.0)) / (freq + k1 * (1.0 - b + b * len(doc) / avg))
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("id", "")))
    return scored[: max(0, k)]
