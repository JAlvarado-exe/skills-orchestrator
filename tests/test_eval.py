import contextlib
import io
import json
import os
import tempfile
import unittest

from orchestrator.cli import main
from orchestrator.evaluate import load_cases, run_case, summarize
from tests.helpers import skill, write

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "eval")


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, out.getvalue()


class ScoringTests(unittest.TestCase):
    def test_precision_counts_expected_ids_among_the_shown_results(self):
        row = run_case({"id": "a", "prompt": "x", "expected": ["s/one"]}, None, lambda payload, loaded: (["s/one", "s/two"], "block"))
        self.assertAlmostEqual(row["precision_at_3"], 0.5)
        self.assertTrue(row["hit_at_3"])

    def test_only_the_first_three_results_count(self):
        row = run_case({"id": "a", "prompt": "x", "expected": ["s/four"]}, None,
                       lambda payload, loaded: (["s/one", "s/two", "s/three", "s/four"], "block"))
        self.assertEqual(row["precision_at_3"], 0.0)

    def test_a_case_with_no_results_scores_zero(self):
        row = run_case({"id": "a", "prompt": "x", "expected": ["s/one"]}, None, lambda payload, loaded: ([], ""))
        self.assertEqual(row["precision_at_3"], 0.0)
        self.assertTrue(row["silent"])

    def test_a_silent_case_passes_only_when_nothing_is_printed(self):
        quiet = run_case({"id": "q", "prompt": "hola", "silent": True}, None, lambda payload, loaded: ([], ""))
        loud = run_case({"id": "q", "prompt": "hola", "silent": True}, None, lambda payload, loaded: ([], "block"))
        summary = summarize([quiet, loud])
        self.assertEqual((summary["silent_ok"], summary["silent_cases"]), (1, 2))

    def test_forbidden_ids_are_counted(self):
        row = run_case({"id": "a", "prompt": "x", "expected": ["s/one"], "forbidden": ["s/bad"]}, None,
                       lambda payload, loaded: (["s/one", "s/bad"], "block"))
        self.assertEqual(row["forbidden_shown"], ["s/bad"])

    def test_payload_cases_pass_the_payload_through(self):
        seen = []
        run_case({"id": "p", "payload": {"prompt": "<x>y</x>"}, "silent": True}, None,
                 lambda payload, loaded: (seen.append(payload) or ([], "")))
        self.assertEqual(seen[0]["prompt"], "<x>y</x>")

    def test_a_file_that_is_not_a_case_list_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "cases.json", json.dumps({"cases": "nope"}))
            with self.assertRaises(ValueError):
                load_cases(path)


class CommandTests(unittest.TestCase):
    def test_eval_builds_the_registry_from_the_config_in_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "skills/repo/pricing", "pricing", "Decide pricing tiers, packaging and free trials.")
            write(tmp, "config.json", json.dumps({"vendor": ["skills"], "use_platform_roots": False, "use_cwd_project_roots": False}))
            write(tmp, "cases.json", json.dumps([{"id": "p", "prompt": "pricing tiers and free trials", "expected": ["repo/pricing"]}]))
            code, out = run_cli("eval", os.path.join(tmp, "cases.json"), "--config", os.path.join(tmp, "config.json"), "--json")
            self.assertEqual(code, 0)
            report = json.loads(out)
            self.assertEqual(report["rows"][0]["shown"][0], "repo/pricing")
            self.assertFalse(os.path.exists(os.path.join(tmp, "registry.json")))

    def test_the_shipped_cases_have_the_promised_shape(self):
        cases = load_cases(os.path.join(FIXTURE, "cases.json"))
        silent = [case for case in cases if case.get("silent")]
        spanish = [case for case in cases if case["id"].startswith(("es-", "silent-smalltalk-es", "silent-quota-es", "silent-thanks"))]
        self.assertEqual(len(cases), 40)
        self.assertEqual(len(silent), 10)
        self.assertGreaterEqual(len(spanish), 15)
        self.assertEqual(len({case["id"] for case in cases}), 40)


if __name__ == "__main__":
    unittest.main()
