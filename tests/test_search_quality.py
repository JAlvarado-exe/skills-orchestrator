import contextlib
import io
import json
import os
import tempfile
import unittest

from orchestrator.cli import main
from orchestrator.search import rank, tokenize
from tests.helpers import write


def entry(name, description, when=""):
    return {"id": "x/" + name, "name": name, "description": description, "when_to_use": when}


class StemTests(unittest.TestCase):
    def test_inflections_collapse(self):
        for a, b in (("failing", "fails"), ("failing", "failed"), ("stopping", "stopped"), ("sounds", "sounding"), ("tests", "testing")):
            with self.subTest(a=a, b=b):
                self.assertEqual(tokenize(a), tokenize(b))

    def test_short_words_are_left_alone(self):
        self.assertEqual(tokenize("bus"), ["bus"])
        self.assertEqual(tokenize("sing"), ["sing"])


class SynonymTests(unittest.TestCase):
    def setUp(self):
        self.corpus = [
            entry("humanizer", "Rewrite AI-sounding text so it reads naturally. Use when prose has stock AI phrases."),
            entry("systematic-debugging", "Use when encountering any bug, test failure or unexpected behavior, before proposing fixes."),
            entry("web-search", "Search the web by keyword and return sources."),
            entry("caveman", "Ultra-compressed communication mode that cuts output tokens. Use for be brief or less tokens."),
            entry("ci-cd-and-automation", "Set up pipelines and automated checks for releases."),
            entry("handoff", "Compact the conversation into a handoff document so another session can resume."),
            entry("pricing", "Decide pricing tiers and packaging."),
            entry("code-review", "Review a pull request diff for correctness."),
        ]

    def top(self, query, k=3):
        return [e["name"] for _s, e in rank(self.corpus, query, k=k)]

    def test_robot_means_ai(self):
        self.assertIn("humanizer", self.top("this paragraph sounds like a robot wrote it"))

    def test_failing_build_means_bug(self):
        self.assertIn("systematic-debugging", self.top("the build keeps failing and I have no idea why"))

    def test_look_up_means_search(self):
        self.assertIn("web-search", self.top("look up recent news about this company online"))

    def test_verbose_means_brief(self):
        self.assertIn("caveman", self.top("make the agent stop being so verbose in chat"))

    def test_continuous_integration_means_ci(self):
        self.assertIn("ci-cd-and-automation", self.top("set up continuous integration to run tests"))

    def test_next_session_means_handoff(self):
        self.assertIn("handoff", self.top("I am stopping now so summarize the state for the next session"))

    def test_exact_words_outrank_synonyms(self):
        corpus = [entry("exact", "Handles the robot control loop."), entry("synonym", "Rewrite AI-sounding text.")]
        self.assertEqual(rank(corpus, "robot", k=2)[0][1]["name"], "exact")

    def test_unrelated_query_still_returns_nothing(self):
        self.assertEqual(rank(self.corpus, "zebra marmalade quantum", k=3), [])


class CatalogTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def test_catalog_tools_are_searchable_and_marked_as_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = write(tmp, "catalog.json", json.dumps({"items": [
                {"id": "o/graphify", "name": "Graphify", "kind": "cli", "upstream": "https://example.org/graphify",
                 "what": "Builds a knowledge graph of code, documents and PDFs.", "activation": "Research profile.", "rating": 6, "risk": "medium"},
                {"id": "o/lib", "name": "NotATool", "kind": "skill-library", "upstream": "https://example.org/lib",
                 "what": "A library of skills.", "activation": "Cold.", "rating": 7, "risk": "low"},
            ]}))
            reg = os.path.join(tmp, "r.json")
            write(tmp, "skills/a/SKILL.md", "---\nname: a\ndescription: unrelated\n---\n")
            code, _ = self.run_cli("scan", "--root", os.path.join(tmp, "skills") + "::s", "--catalog", catalog, "--out", reg)
            self.assertEqual(code, 0)
            _, out = self.run_cli("find", "turn documents and pdfs into a knowledge graph", "--registry", reg, "--json")
            first = json.loads(out)["results"][0]
            self.assertEqual(first["id"], "catalog/graphify")
            self.assertEqual(first["kind"], "tool")
            self.assertEqual(first["upstream"], "https://example.org/graphify")
            ids = [e["id"] for e in json.load(open(reg, encoding="utf-8"))["entries"]]
            self.assertNotIn("catalog/notatool", ids)

    def test_check_mode_ignores_catalog_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = write(tmp, "catalog.json", json.dumps({"items": [
                {"id": "o/t", "name": "T", "kind": "mcp", "upstream": "u", "what": "w", "activation": "a", "rating": 5, "risk": "low"}]}))
            write(tmp, "skills/a/SKILL.md", "---\nname: a\ndescription: d\n---\n")
            code, out = self.run_cli("scan", "--root", os.path.join(tmp, "skills") + "::s", "--catalog", catalog, "--check")
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
