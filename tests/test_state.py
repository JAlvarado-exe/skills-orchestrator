"""Session memory of the hook and usage feedback (`used`, `stats`). Everything lives in a temporary state folder."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest

from orchestrator import feedback, session
from orchestrator.cli import main
from orchestrator.hook import run_hook
from tests.helpers import skill, write


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Machine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        lib = os.path.join(self.tmp, "lib")
        skill(lib, "browser-console", "browser-console", "Read console errors and failed network requests of a web page.")
        skill(lib, "network-debugging", "network-debugging", "Debug failed network requests and console errors.")
        for index in range(15):
            skill(lib, "filler-%d" % index, "filler-%d" % index, "Gardens, recipes and travel plans %d." % index)
        self.registry = os.path.join(self.tmp, "reg", "registry.json")
        self.state = os.path.join(self.tmp, "state")
        self.config = write(self.tmp, "config.json", json.dumps({
            "registry": self.registry, "extra_roots": [{"path": lib, "source_from": "fixed"}], "use_platform_roots": False,
            "use_cwd_project_roots": False, "state_dir": self.state}))
        self.assertEqual(run("scan", "--config", self.config)[0], 0)

    def hook(self, prompt, session_id="sess-1"):
        payload = json.dumps({"session_id": session_id, "prompt": prompt})
        with contextlib.redirect_stderr(io.StringIO()):
            out = run_hook(payload, config_path=self.config)
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def ids(self, block):
        return [line.split(" ")[1] for line in block.splitlines() if line[:1].isdigit()]


class SessionMemoryTests(Machine):
    PROMPT = "the page shows console errors and failed network requests"

    def test_an_id_shown_twice_and_not_used_is_suppressed_for_the_session(self):
        first, second, third = (self.ids(self.hook(self.PROMPT)) for _ in range(3))
        self.assertIn("lib/browser-console", first)
        self.assertEqual(first, second)
        self.assertNotIn("lib/browser-console", third)
        self.assertIn("lib/browser-console", self.ids(self.hook(self.PROMPT, session_id="sess-2")))

    def test_an_id_used_in_the_session_keeps_being_shown(self):
        self.hook(self.PROMPT)
        self.hook(self.PROMPT)
        self.assertEqual(run("used", "lib/browser-console", "--config", self.config)[0], 0)
        self.assertIn("lib/browser-console", self.ids(self.hook(self.PROMPT)))

    def test_a_session_id_that_is_not_a_plain_token_gets_no_memory(self):
        for _ in range(3):
            block = self.hook(self.PROMPT, session_id="../../evil")
        self.assertIn("lib/browser-console", self.ids(block))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.json")))

    def test_an_unwritable_state_folder_never_breaks_the_hook(self):
        write(self.tmp, "state", "a file where the folder should be")
        self.assertIn("lib/browser-console", self.ids(self.hook(self.PROMPT)))

    def test_old_session_files_are_pruned(self):
        old = write(self.state, "sessions/old.json", json.dumps({"started": 0, "shown": {}}))
        past = time.time() - (session.KEEP_DAYS + 1) * 86400
        os.utime(old, (past, past))
        self.hook(self.PROMPT)
        self.assertFalse(os.path.exists(old))

    def test_eval_never_reads_or_writes_session_state(self):
        cases = write(self.tmp, "cases.json", json.dumps([{"id": "a", "payload": {"session_id": "sess-9", "prompt": self.PROMPT},
                                                           "expected": ["lib/browser-console"]}] * 4))
        _c, out, _e = run("eval", cases, "--config", self.config, "--json")
        self.assertEqual(json.loads(out)["summary"]["hit_at_3"], 1.0)
        self.assertFalse(os.path.exists(os.path.join(self.state, "sessions", "sess-9.json")))


class FeedbackTests(Machine):
    def test_used_appends_to_the_usage_log(self):
        code, out, _e = run("used", "lib/browser-console", "--helped", "yes", "--config", self.config)
        self.assertEqual(code, 0)
        self.assertIn("recorded", out)
        rows = feedback.load_usage(self.state)
        self.assertEqual([(r["id"], r["helped"]) for r in rows], [("lib/browser-console", "yes")])

    def test_used_with_an_unknown_id_warns_and_records(self):
        code, _o, err = run("used", "platform:some-skill", "--config", self.config)
        self.assertEqual(code, 0)
        self.assertIn("not in the registry", err)
        self.assertEqual(feedback.load_usage(self.state)[0]["id"], "platform:some-skill")

    def test_factor_is_bounded_both_ways(self):
        self.assertAlmostEqual(feedback.factor({"helpful": 50, "used": 50, "shown": 0}), 1.0 + feedback.MAX_BOOST)
        self.assertAlmostEqual(feedback.factor({"helpful": 0, "used": 0, "shown": 10000}), 1.0 - feedback.MAX_PENALTY)
        self.assertEqual(feedback.factor({"helpful": 0, "used": 0, "shown": feedback.FREE_SHOWS}), 1.0)
        self.assertEqual(feedback.factor({"helpful": 0, "used": 1, "shown": 10000}), 1.0)

    def test_helpful_uses_reorder_results(self):
        query = "console errors and failed network requests"
        _c, out, _e = run("find", query, "--config", self.config, "--json")
        before = [r["id"] for r in json.loads(out)["results"]]
        loser = before[1]
        for _ in range(3):
            run("used", loser, "--helped", "yes", "--config", self.config)
        _c, out, _e = run("find", query, "--config", self.config, "--json")
        self.assertEqual(json.loads(out)["results"][0]["id"], loser)

    def test_feedback_never_makes_a_result_appear(self):
        for _ in range(5):
            run("used", "lib/filler-1", "--helped", "yes", "--config", self.config)
        _c, out, _e = run("find", "debug failed network requests and console errors", "--config", self.config, "--json")
        self.assertNotIn("lib/filler-1", [r["id"] for r in json.loads(out)["results"]])

    def test_stats_lists_most_used_and_most_ignored(self):
        prompt = "the page shows console errors and failed network requests"
        for number in range(3):
            self.hook(prompt, session_id="s%d" % number)
        run("used", "lib/browser-console", "--helped", "yes", "--config", self.config)
        code, out, _e = run("stats", "--config", self.config)
        self.assertEqual(code, 0)
        used_part, ignored_part = out.split("most ignored")
        self.assertIn("lib/browser-console", used_part)
        self.assertIn("lib/network-debugging", ignored_part)
        data = json.loads(run("stats", "--config", self.config, "--json")[1])
        self.assertEqual(data["used"][0]["id"], "lib/browser-console")
        self.assertEqual(data["ignored"][0]["shown"], 3)


if __name__ == "__main__":
    unittest.main()
