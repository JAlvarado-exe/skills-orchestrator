"""BM25 search over registry entries (stdlib only).

Two small additions keep a lexical ranker useful for natural requests: a stemmer that collapses
common inflections, and a data-driven table of synonym groups and phrases (data/synonyms.json)
that expands the *query* only. Expansions are scored as evidence, not as extra words: each
group (the synonyms of one query word, or the words of one matched phrase) contributes only its
single best match, at half weight, and never for a word the user already typed. So an exact word
outranks a document that merely lists many synonyms.

Requests in Spanish work through two more steps. ``fold`` strips accents and case on both the query
and the documents, and a table of folded Spanish words (``translations`` in data/synonyms.json)
adds their English equivalents to the query as the user's own words (full weight): skills are
written in English, so the table is a bridge, not a second index. Spanish words without an entry
simply do not match.
"""
from __future__ import annotations

import math
import os
import re
import unicodedata

from .jsonio import read_json

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
SYNONYMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "synonyms.json")
EXPANSION_WEIGHT = 0.5
# `find` calls a result set weak when it cannot be taken as proof that no skill exists: the best
# BM25 score is below WEAK_BEST_SCORE, or fewer than WEAK_MIN_RESULTS skills matched at all.
# BM25 scores grow with corpus size, so these are rough guards chosen on small registries.
WEAK_BEST_SCORE = 3.0
WEAK_MIN_RESULTS = 3
# A result also counts as weak when no shown skill contains at least this many of the request's terms
# (or all of them, for a one-word request): one shared word such as "server" is not a match.
WEAK_MIN_TERMS = 2
_VOWELS = "aeiou"
_ENGLISH_STOPWORDS = (
    "a an and any are as at be by do does for from how i if in is it its my not of on or so that the this to we "
    "when will with you your use used using can all"
).split()


def fold(text: str) -> str:
    """Lowercase and strip accents (NFKD, combining marks dropped): "Código" and "codigo" become the same word."""
    text = text or ""
    if text.isascii():
        return text.lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.category(char).startswith("M")).lower()


def _read_data() -> dict:
    try:
        data = read_json(SYNONYMS_FILE)
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _stopwords() -> frozenset:
    """English function words plus the Spanish ones listed under "stopwords" in data/synonyms.json."""
    listed = _read_data().get("stopwords", [])
    spanish = [fold(word) for word in listed if isinstance(word, str)] if isinstance(listed, list) else []
    return frozenset(_ENGLISH_STOPWORDS + spanish)


STOPWORDS = _stopwords()


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
    for raw in _WORD.findall(fold(text)):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        stem = _stem(raw)
        if stem in STOPWORDS:
            continue
        tokens.append(stem)
    return tokens


_SYNONYMS = None
_TRANSLATIONS = None


def load_synonyms():
    """Return (token -> set of related tokens, list of (compiled phrase pattern, replacement words))."""
    global _SYNONYMS
    if _SYNONYMS is None:
        related, phrases = {}, []
        data = _read_data()
        for group in data.get("groups", []):
            stems = {t for word in group for t in tokenize(word)}
            for stem in stems:
                related.setdefault(stem, set()).update(stems - {stem})
        for phrase, words in data.get("phrases", {}).items():
            phrases.append((re.compile(r"\b" + re.escape(phrase.lower()) + r"\b"), words))
        _SYNONYMS = (related, phrases)
    return _SYNONYMS


def load_translations():
    """Return (folded single word -> English words, list of (compiled multi-word pattern, English words))."""
    global _TRANSLATIONS
    if _TRANSLATIONS is None:
        single, multi = {}, []
        table = _read_data().get("translations", {})
        for key, words in (table.items() if isinstance(table, dict) else ()):
            if not isinstance(key, str) or not isinstance(words, str):
                continue
            key = " ".join(_WORD.findall(fold(key)))
            if " " in key:
                multi.append((re.compile(r"\b" + re.escape(key) + r"\b"), words))
            elif key:
                single[key] = words
        _TRANSLATIONS = (single, multi)
    return _TRANSLATIONS


def _translate(word: str, single: dict):
    """Look the word up as typed, then without a plural "s" or "es"."""
    for candidate in (word, word[:-1] if word.endswith("s") else "", word[:-2] if word.endswith("es") else ""):
        if candidate in single:
            return single[candidate]
    return None


def _query_tokens(folded: str):
    """Stemmed tokens of the typed words plus the English equivalents of any Spanish word in the table.

    The typed word is always kept, so a word that is also English ("error") still matches itself.
    """
    single, multi = load_translations()
    words = _WORD.findall(folded)
    joined = " ".join(words)
    tokens = []
    for pattern, english in multi:
        if pattern.search(joined):
            tokens.extend(tokenize(english))
    for word in words:
        tokens.extend(tokenize(word))
        english = None if word in STOPWORDS else _translate(word, single)
        if english:
            tokens.extend(tokenize(english))
    return tokens


def query_terms(query: str):
    """Return (the user's own tokens, a list of expansion groups). A group is a set of related tokens."""
    related, phrases = load_synonyms()
    lowered = fold(query)
    exact = []
    for token in _query_tokens(lowered):
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


def matched_terms(entry: dict, query: str):
    """The request's own terms (after translation) that appear in the skill's name, description or when_to_use."""
    exact, _groups = query_terms(query)
    present = set(_doc_tokens(entry))
    return [token for token in exact if token in present]


def is_covered(entry: dict, queries) -> bool:
    """True when, for at least one phrasing, the skill contains WEAK_MIN_TERMS of its terms (all of them if fewer)."""
    for query in queries:
        exact, _groups = query_terms(query)
        need = min(WEAK_MIN_TERMS, len(exact))
        if need and len(matched_terms(entry, query)) >= need:
            return True
    return False


def is_weak(best_score: float, result_count: int) -> bool:
    """True when a result set cannot be taken as proof that no skill fits (see WEAK_BEST_SCORE)."""
    return best_score < WEAK_BEST_SCORE or result_count < WEAK_MIN_RESULTS


def name_matches(entries, queries, skip_ids, limit: int = 10, min_length: int = 4):
    """Ids that contain a query token (after translation) of at least min_length characters.

    A cheap second net under BM25: a skill whose name says what the user asked for is worth a look even
    when its description ranked it low. Entries already shown (skip_ids) are left out; more distinct
    token hits come first.
    """
    tokens = {token for query in queries for token in query_terms(query)[0] if len(token) >= min_length}
    scored = []
    for entry in entries:
        ident = entry.get("id", "")
        if not tokens or ident in skip_ids:
            continue
        folded = fold(ident)
        hits = sum(1 for token in tokens if token in folded)
        if hits:
            scored.append((-hits, ident))
    scored.sort()
    return [ident for _hits, ident in scored[: max(0, limit)]]
