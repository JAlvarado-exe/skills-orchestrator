"""BM25 search over registry entries (stdlib only).

Two small additions keep a lexical ranker useful for natural requests: a stemmer that collapses
common inflections, and a data-driven table of synonym groups and phrases (data/synonyms.json)
that expands the *query* only. Expansions are scored as evidence, not as extra words: each
group (the synonyms of one query word, or the words of one matched phrase) contributes only its
single best match, at half weight, and never for a word the user already typed. So an exact word
outranks a document that merely lists many synonyms.

Local vocabulary tables connect task terms across languages. Each recognized alias contributes
one lexical unit. Metadata uses its canonical token, so knowing multiple names for a concept
does not add extra votes to a document. Unknown terms can still match their original spelling.
"""
from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from .jsonio import read_json

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SYNONYMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "synonyms.json")
LANGUAGES_FILE = os.path.join(os.path.dirname(SYNONYMS_FILE), "language_bridges.json")
EXPANSION_WEIGHT = 0.5
# Confidence gates (see docs/EVAL.md for how they were chosen). A result is shown only when its normalized score is
# at least MIN_SCORE, it shares enough distinct terms with the request (required_terms) and it scores at least
# RELATIVE_FLOOR times the best result. Below that, silence is better than a guess. The normalized score divides the
# BM25F score by the weight of one rare word (unit_weight), so the same threshold works for 5 skills and for 5,000.
DEFAULT_MIN_SCORE = 1.7
DEFAULT_MIN_TERMS = 2
MAX_REQUIRED_TERMS = 5
TERMS_PER_REQUIRED = 12
RELATIVE_FLOOR = 0.35
_VOWELS = "aeiou"


def fold(text: str) -> str:
    """Fold Latin accents while preserving vowel signs, kana voicing and Hangul syllables."""
    text = text or ""
    if text.isascii():
        return text.lower()
    result = []
    latin = False
    for char in unicodedata.normalize("NFKD", text.casefold()):
        if unicodedata.category(char).startswith("M"):
            if latin:
                continue
        else:
            latin = unicodedata.name(char, "").startswith("LATIN ")
        result.append(char)
    return unicodedata.normalize("NFC", "".join(result))


def _read_data() -> dict:
    try:
        data = read_json(SYNONYMS_FILE)
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _stopwords() -> frozenset:
    """The English ("stopwords_en") and Spanish ("stopwords") lists of data/synonyms.json, folded.

    Both hold function words and generic task words ("code", "file", "run") that appear in almost every request
    and every skill: counting them let the same few skills win whatever the task was.
    """
    data = _read_data()
    words = []
    for key in ("stopwords_en", "stopwords"):
        listed = data.get(key, [])
        if isinstance(listed, list):
            words.extend(fold(word) for word in listed if isinstance(word, str))
    return frozenset(words)


STOPWORDS = _stopwords()
STEMMER_VERSION = "script-bridge-1"


def tokenizer_id() -> str:
    """Fingerprint of everything that changes tokens: a registry whose stored tokens carry another id is re-tokenized."""
    import hashlib
    data = STEMMER_VERSION + "\n" + " ".join(sorted(STOPWORDS)) + "\n" + _bridges().fingerprint
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


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


def _script(char):
    """Keep adjacent identifiers separate from CJK text, including compatibility Han blocks."""
    name = unicodedata.name(char, "")
    if name.startswith(("CJK ", "HIRAGANA ", "KATAKANA ")) or char == "ー":
        return "cjk"
    return name.partition(" ")[0] if char.isalpha() else ""


def _spans(text):
    if text.isascii():
        yield from _WORD.findall(text)
        return
    start, script = 0, ""
    for i, char in enumerate(text):
        if not (char.isalnum() or unicodedata.category(char).startswith("M")):
            if i > start:
                yield text[start:i]
            start, script = i + 1, ""
            continue
        current = _script(char)
        if current and script and current != script:
            yield text[start:i]
            start = i
        if current:
            script = current
    if start < len(text):
        yield text[start:]


def _insert(trie, parts, value):
    for part in parts:
        trie = trie.setdefault(part, {})
    trie[None] = value


def _longest(trie, parts, start):
    """Return the longest vocabulary match starting here, or the unchanged cursor."""
    end, value = start, None
    for pos in range(start, len(parts)):
        trie = trie.get(parts[pos])
        if trie is None:
            break
        if None in trie:
            end, value = pos + 1, trie[None]
    return end, value


@dataclass
class _Vocabulary:
    terms: dict
    unspaced: dict
    korean_words: set
    particles: tuple
    fingerprint: str


@lru_cache(maxsize=1)
def _bridges():
    try:
        tables = read_json(LANGUAGES_FILE)
    except (OSError, ValueError, RecursionError):
        tables = {}
    if not isinstance(tables, dict):
        tables = {}
    endings = tables.get("korean_particles", [])
    particles = tuple(sorted((p for p in endings if isinstance(p, str) and p), key=lambda p: (-len(p), p)))
    aliases = {}
    for table in tables.values():
        for pivot, words in table.items() if isinstance(table, dict) else ():
            if isinstance(words, list):
                for word in words:
                    if isinstance(word, str):
                        aliases[fold(word)] = pivot
    # Reuse the existing Spanish vocabulary for these concepts. Homographs
    # used as English translation targets keep their English document meaning.
    pivots = set(aliases.values())
    spanish = _read_data().get("translations", {})
    spanish = {key: value for key, value in spanish.items() if isinstance(value, str) and value.strip()
               } if isinstance(spanish, dict) else {}
    english = {word for value in spanish.values() for word in value.split()}
    for word, value in spanish.items():
        pivot = value.split()[0]
        if pivot in pivots and word not in english:
            aliases.setdefault(word, pivot)
    terms, cjk, korean_words = {}, {}, set()
    for alias, pivot in aliases.items():
        parts = list(_spans(alias))
        if not parts:
            continue
        _insert(terms, parts, pivot)
        for part in parts:
            if _script(part[0]) == "cjk":
                _insert(cjk, part, part)
            elif _script(part[0]) == "HANGUL":
                korean_words.add(part)
    fingerprint = "\n".join(k + "=" + aliases[k] for k in sorted(aliases))
    return _Vocabulary(terms, cjk, korean_words, particles, fingerprint + "\n" + " ".join(particles))


def _words(text, vocab):
    for word in _spans(text):
        if word.isascii():
            yield word
        elif _script(word[0]) == "cjk":
            pos = start = 0
            while pos < len(word):
                end, known = _longest(vocab.unspaced, word, pos)
                if known:
                    if pos > start:
                        yield word[start:pos]
                    yield known
                    pos = start = end
                else:
                    pos += 1
            if pos > start:
                yield word[start:pos]
        elif _script(word[0]) == "HANGUL":
            for suffix in vocab.particles:
                if word.endswith(suffix) and word[:-len(suffix)] in vocab.korean_words:
                    word = word[:-len(suffix)]
                    break
            yield word
        else:
            yield word


def _lexemes(text):
    vocab = _bridges()
    words = list(_words(text, vocab))
    pos = 0
    while pos < len(words):
        end, pivot = _longest(vocab.terms, words, pos)
        if pivot:
            yield words[pos:end], pivot
            pos = end
        else:
            yield [words[pos]], None
            pos += 1


def _surface(word):
    if word in STOPWORDS or len(word) < 2:
        return None
    token = _stem(word) if word.isascii() else word
    return token if token not in STOPWORDS else None


def _identifier_forms(text):
    """Internal capitals distinguish product spellings such as SQLite from prose inflections."""
    forms = {}
    for match in _IDENTIFIER.finditer(text):
        word = match.group()
        if word.islower() or word.isupper() or word.istitle():
            continue
        raw = word.lower()
        stem = _surface(raw)
        if stem and raw != stem:
            forms[stem] = raw
    return forms


def tokenize(text: str):
    tokens = []
    for words, pivot in _lexemes(fold(text)):
        token = _surface(pivot or words[0])
        if token:
            tokens.append(token)
    return tokens + list(_identifier_forms(text).values())


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


def _query_units(folded: str):
    """One list of stemmed tokens per word the user typed (the word plus its English equivalents), and one per
    multi-word phrase found in the translation table.

    The typed word is always kept, so a word that is also English ("error") still matches itself.
    """
    single, multi = load_translations()
    lexemes = list(_lexemes(folded))
    joined = " ".join(word for words, _pivot in lexemes for word in words)
    units = []
    for pattern, english in multi:
        if pattern.search(joined):
            units.append(tokenize(english))
    for words, pivot in lexemes:
        word = " ".join(words)
        unit = [token for token in (_surface(pivot or word),) if token]
        english = None if word in STOPWORDS else _translate(word, single)
        if english:
            unit = unit + tokenize(english)
        if unit:
            units.append(unit)
    return units


def _query_tokens(folded: str):
    return [token for unit in _query_units(folded) for token in unit]


def query_units(query: str):
    """Distinct sets of tokens, one per typed word or translated phrase, widened with the word's synonym group: the
    units of evidence for the term gate.

    One Spanish word that translates to two English words ("actualizacion" -> update, upgrade) is one unit, so it
    cannot pass a two-term gate on its own; "fail" still counts against "failure" through its group.
    """
    related, _phrases = load_synonyms()
    seen, units = [], []
    literals = _identifier_forms(query)
    for unit in _query_units(fold(query)):
        typed = frozenset(unit)
        if typed in seen:
            continue
        seen.append(typed)
        wide = set(typed)
        for token in typed:
            wide |= related.get(token, set())
            if token in literals:
                wide.add(literals[token])
        units.append(frozenset(wide))
    return units


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


# BM25F field weights: a word in the skill's name says more than one in its tags, and tags more than prose.
FIELD_WEIGHTS = (("name", 3.0), ("tags", 2.0), ("body", 1.0))
K1 = 1.2
B = 0.75


def doc_fields(entry: dict) -> dict:
    """Tokens per field: name, tags (from overrides) and body (description plus when_to_use).

    A registry built by this version stores name and body tokens under ``tok``; they are reused when present.
    """
    stored = entry.get("tok")
    if isinstance(stored, dict) and isinstance(stored.get("name"), list) and isinstance(stored.get("body"), list):
        name, body = stored["name"], stored["body"]
    else:
        name = tokenize(entry.get("name", ""))
        body = tokenize(entry.get("description", "") + " " + entry.get("when_to_use", ""))
    tags = entry.get("tags")
    tag_tokens = tokenize(" ".join(t for t in tags if isinstance(t, str))) if isinstance(tags, list) else []
    return {"name": name, "tags": tag_tokens, "body": body}


def _doc_tokens(entry: dict):
    fields = doc_fields(entry)
    return fields["name"] + fields["tags"] + fields["body"]


def unit_weight(entry_count: int) -> float:
    """The BM25 inverse document frequency of a word found in exactly one of entry_count skills."""
    return math.log(1.0 + (max(entry_count, 1) - 0.5) / 1.5) or 1.0


def rank(entries, query: str, k: int = 5, k1: float = K1, b: float = B):
    """Return up to k (score, entry) pairs, best first. Only entries with score > 0.

    BM25F: each field's term frequency is length-normalized against that field's average and weighted
    (FIELD_WEIGHTS) before the usual saturation, so a long description cannot outweigh a name.
    """
    exact, groups = query_terms(query)
    if (not exact and not groups) or not entries:
        return []
    docs = [doc_fields(e) for e in entries]
    n = len(docs)
    avg = {}
    for field, _weight in FIELD_WEIGHTS:
        # averaged over the entries that have the field: tags are sparse, and counting empty ones would make the
        # few tagged entries look long and push their tags down
        filled = [len(d[field]) for d in docs if d[field]]
        avg[field] = (sum(filled) / float(len(filled))) if filled else 1.0
    df = {}
    for doc in docs:
        for token in set(doc["name"]) | set(doc["tags"]) | set(doc["body"]):
            df[token] = df.get(token, 0) + 1
    literals = _identifier_forms(query)
    wanted = set(exact) | set(literals.values()) | {t for group in groups for t in group}
    scored = []
    for entry, doc in zip(entries, docs):
        weighted = {}
        for field, weight in FIELD_WEIGHTS:
            tokens = doc[field]
            if not tokens:
                continue
            norm = 1.0 - b + b * len(tokens) / avg[field]
            for token in tokens:
                if token in wanted:
                    weighted[token] = weighted.get(token, 0.0) + weight / norm
        if not weighted:
            continue

        def bm25(token):
            freq = weighted.get(token, 0.0)
            if not freq:
                return 0.0
            idf = math.log(1.0 + (n - df[token] + 0.5) / (df[token] + 0.5))
            return idf * (freq * (k1 + 1.0)) / (freq + k1)

        score = sum(max(bm25(t), bm25(literals[t])) if t in literals else bm25(t) for t in exact)
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


def required_terms(query_term_count: int, min_terms: int = DEFAULT_MIN_TERMS) -> int:
    """Distinct terms a skill must share with a request of this many terms: all of them for a short request, then
    min_terms, growing by one per TERMS_PER_REQUIRED terms up to MAX_REQUIRED_TERMS, so a long pasted text cannot be
    matched on two generic words."""
    if query_term_count <= min_terms:
        return query_term_count
    return max(min_terms, min(MAX_REQUIRED_TERMS, int(math.ceil(query_term_count / float(TERMS_PER_REQUIRED)))))


def match_count(entry: dict, exact, groups, units=None) -> int:
    """Distinct pieces of evidence: each request term found in the skill, plus each synonym group with a hit.

    With units (from query_units), a typed word counts once however many of its translations the skill contains.
    """
    present = set(_doc_tokens(entry))
    if units is None:
        return sum(1 for token in exact if token in present) + sum(1 for group in groups if group & present)
    # each unit needs its own word of the skill: two typed words that are synonyms of one skill word count once
    used, hits = set(), 0
    for found in sorted((unit & present for unit in units), key=len):
        free = found - used
        if free:
            used.add(min(free))
            hits += 1
    return hits


def confident_matches(entries, queries, min_score: float = DEFAULT_MIN_SCORE, min_terms: int = DEFAULT_MIN_TERMS,
                      floor: float = RELATIVE_FLOOR):
    """[(normalized score, entry, matched terms)] that pass the gates for at least one phrasing, best first."""
    best = {}
    unit = unit_weight(len(entries))
    for query in queries:
        exact, groups = query_terms(query)
        units = query_units(query)
        need = required_terms(len(units), min_terms)
        if not need:
            continue
        # the normalized score is roughly a count of rare-word matches: a one-word request cannot reach two
        floor_score = min_score * min(1.0, len(exact) / 2.0)
        for raw, entry in rank(entries, query, k=len(entries)):
            score = raw / unit
            if score < floor_score:
                break
            if match_count(entry, exact, groups, units) < need:
                continue
            ident = entry.get("id", "")
            if ident not in best or score > best[ident][0]:
                best[ident] = (score, entry, matched_terms(entry, query))
    ranked = sorted(best.values(), key=lambda item: (-item[0], item[1].get("id", "")))
    if not ranked:
        return []
    cutoff = ranked[0][0] * floor
    return [item for item in ranked if item[0] >= cutoff]


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
