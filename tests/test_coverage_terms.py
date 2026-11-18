import contextlib
import io
import json
import os
import tempfile
import unittest

from orchestrator import search
from orchestrator.cli import main
from orchestrator.search import match_count, matched_terms, query_terms
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

    def test_match_count_counts_distinct_terms_and_synonym_groups(self):
        e = entry("pricing", "Decide pricing tiers and packaging.")
        self.assertEqual(match_count(e, *query_terms("pricing tiers")), 2)
        self.assertEqual(match_count(e, *query_terms("calibrate the clock of the pricing server with ntp")), 1)


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

    def test_one_shared_word_is_not_shown_even_when_scores_look_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            # relax the score gate so only the term gate can decide
            _, out = self.run_cli("find", "calibrate the clock of the server with ntp", "--registry", reg, "--json",
                                  "-k", "3", "--min-score", "0")
            data = json.loads(out)
            self.assertEqual(data["results"], [])
            self.assertFalse(data["confident"])

    def test_a_request_that_shares_two_terms_is_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            _, out = self.run_cli("find", "back up a server", "--registry", reg, "--json", "-k", "3", "--min-score", "0")
            data = json.loads(out)
            self.assertTrue(data["confident"])
            self.assertEqual(data["results"][0]["id"], "s/server-backup")

    def test_text_output_shows_matched_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            _, out = self.run_cli("find", "back up a server", "--registry", reg, "-k", "1", "--min-score", "0")
            self.assertIn("matched:", out)


if __name__ == "__main__":
    unittest.main()
