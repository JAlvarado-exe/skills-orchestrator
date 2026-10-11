import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import search
from orchestrator.cli import main
from orchestrator.search import is_covered, matched_terms
from tests.helpers import skill


def entry(name, description):
    return {"id": "x/" + name, "name": name, "description": description, "when_to_use": ""}


class MatchedTermsTests(unittest.TestCase):
    def test_lists_only_query_terms_present_in_the_skill(self):
        e = entry("web-server-setup", "Configure a web server and its TLS certificates.")
        self.assertEqual(matched_terms(e, "calibrate the clock of the server with ntp"), ["server"])

    def test_spanish_words_match_through_their_english_equivalents(self):
        e = entry("browser-devtools", "Debug a web page in the browser and read the console.")
        found = matched_terms(e, "reviso la consola del navegador")
        # terms are reported in their normalized (stemmed) form
        self.assertIn(search.tokenize("console")[0], found)
        self.assertIn(search.tokenize("browser")[0], found)

    def test_covered_needs_two_terms_unless_the_query_has_one(self):
        e = entry("pricing", "Decide pricing tiers and packaging.")
        self.assertTrue(is_covered(e, ["pricing"]))
        self.assertFalse(is_covered(e, ["calibrate the clock of the pricing server with ntp"]))
        self.assertTrue(is_covered(e, ["pricing tiers"]))

    def test_any_phrasing_can_cover(self):
        e = entry("pricing", "Decide pricing tiers and packaging.")
        self.assertTrue(is_covered(e, ["calibrate the clock of the pricing server", "pricing tiers"]))


class CliCoverageTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def _registry(self, tmp):
        for name, text in (
            ("web-server-setup", "Configure a web server and its TLS certificates."),
            ("server-logs", "Rotate and read server logs."),
            ("server-backup", "Back up a server to object storage."),
            ("pricing", "Decide pricing tiers and packaging."),
        ):
            skill(tmp, "skills/" + name, name, text)
        reg = os.path.join(tmp, "r.json")
        self.run_cli("scan", "--root", os.path.join(tmp, "skills") + "::s", "--out", reg)
        return reg

    def test_one_shared_word_is_flagged_even_when_scores_look_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            # relax the score-based rules so only the new term-coverage rule can decide
            with mock.patch.object(search, "WEAK_BEST_SCORE", 0.0), mock.patch.object(search, "WEAK_MIN_RESULTS", 1):
                _, out = self.run_cli("find", "calibrate the clock of the server with ntp", "--registry", reg, "--json", "-k", "3")
            data = json.loads(out)
            self.assertTrue(data["results"])
            self.assertTrue(data["coverage"]["weak"])
            self.assertIn("server", data["results"][0]["matched"])

    def test_a_request_that_shares_two_terms_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            with mock.patch.object(search, "WEAK_BEST_SCORE", 0.0), mock.patch.object(search, "WEAK_MIN_RESULTS", 1):
                _, out = self.run_cli("find", "back up a server", "--registry", reg, "--json", "-k", "3")
            data = json.loads(out)
            self.assertFalse(data["coverage"]["weak"])

    def test_text_output_shows_matched_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            _, out = self.run_cli("find", "back up a server", "--registry", reg, "-k", "1")
            self.assertIn("matched:", out)


if __name__ == "__main__":
    unittest.main()
