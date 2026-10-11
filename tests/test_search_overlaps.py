import unittest

from orchestrator.overlaps import find_overlaps
from orchestrator.search import rank, tokenize


def entry(eid, name, description, source="s", sha=None, when_to_use=""):
    return {
        "id": eid,
        "name": name,
        "description": description,
        "when_to_use": when_to_use,
        "source": source,
        "sha256": sha or eid,
        "path": "/x/%s/SKILL.md" % name,
        "paths": ["/x/%s/SKILL.md" % name],
    }


CORPUS = [
    entry("a/tdd", "test-driven-development", "Write failing tests first, then code until they pass. Red green refactor."),
    entry("a/debug", "systematic-debugging", "Find the root cause of a bug or failing build before changing code."),
    entry("a/review", "code-review", "Review a pull request diff for correctness, security and style problems."),
    entry("a/pricing", "pricing", "Decide pricing tiers, packaging and monetization for a software product."),
    entry("a/diagram", "diagram-design", "Draw architecture diagrams as a single HTML and SVG file."),
]


class TokenizeTests(unittest.TestCase):
    def test_lowercases_splits_and_drops_stopwords(self):
        toks = tokenize("The Test-Driven approach, for a Bug!")
        self.assertIn("test", toks)
        self.assertIn("driven", toks)
        self.assertNotIn("the", toks)
        self.assertNotIn("for", toks)

    def test_light_plural_stemming(self):
        self.assertEqual(tokenize("tests"), tokenize("test"))


class RankTests(unittest.TestCase):
    def test_finds_obvious_match_first(self):
        top = rank(CORPUS, "I need to write tests before the code", k=3)
        self.assertEqual(top[0][1]["id"], "a/tdd")

    def test_name_match_is_boosted(self):
        top = rank(CORPUS, "pricing", k=2)
        self.assertEqual(top[0][1]["id"], "a/pricing")

    def test_k_limits_results(self):
        self.assertLessEqual(len(rank(CORPUS, "code review tests debugging", k=2)), 2)

    def test_empty_query_returns_nothing(self):
        self.assertEqual(rank(CORPUS, "   ", k=3), [])

    def test_no_match_returns_nothing(self):
        self.assertEqual(rank(CORPUS, "zebra quantum marmalade", k=3), [])

    def test_empty_corpus(self):
        self.assertEqual(rank([], "anything", k=3), [])


class OverlapTests(unittest.TestCase):
    def test_flags_near_duplicate_descriptions_across_sources(self):
        entries = [
            entry("x/tdd", "tdd", "Write failing tests first then implement code until tests pass red green refactor", source="x"),
            entry("y/test-first", "test-first", "Write failing tests first then implement code until tests pass red green refactor loop", source="y"),
            entry("z/pricing", "pricing", "Decide pricing tiers and packaging for a software product", source="z"),
        ]
        result = find_overlaps(entries, threshold=0.5)
        pairs = {frozenset((p["a"], p["b"])) for p in result["similar"]}
        self.assertIn(frozenset(("x/tdd", "y/test-first")), pairs)
        self.assertEqual(len(pairs), 1)

    def test_same_name_different_source_is_a_collision(self):
        entries = [
            entry("x/tdd", "tdd", "first", source="x", sha="1"),
            entry("y/tdd", "tdd", "something else entirely", source="y", sha="2"),
        ]
        result = find_overlaps(entries)
        self.assertEqual(len(result["name_collisions"]), 1)
        self.assertEqual(result["name_collisions"][0]["name"], "tdd")

    def test_same_source_pairs_are_not_flagged_as_similar(self):
        entries = [
            entry("x/a", "a", "alpha beta gamma delta epsilon zeta", source="x"),
            entry("x/b", "b", "alpha beta gamma delta epsilon zeta eta", source="x"),
        ]
        self.assertEqual(find_overlaps(entries, threshold=0.5)["similar"], [])


if __name__ == "__main__":
    unittest.main()
