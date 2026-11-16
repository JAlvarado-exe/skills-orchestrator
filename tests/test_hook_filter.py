"""The prompt hook ignores messages the harness wrapped or wrote, and still searches what the user typed."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from orchestrator.cli import main
from orchestrator.hook import run_hook, user_text
from tests.helpers import skill, write

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hook")
SILENT = ("task_notification", "subagent_report", "system_reminder", "local_command", "interrupted", "continued_session",
          "cross_session", "short", "unclosed_wrapper")


def fixture(name):
    with open(os.path.join(FIXTURES, name + ".json"), encoding="utf-8") as handle:
        return handle.read()


class FilterFixtureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        lib = os.path.join(self.tmp, "lib")
        skill(lib, "payment-test-debugging", "payment-test-debugging",
              "Debug a failing payment test and the console errors of the payment page.")
        for index in range(12):
            skill(lib, "filler-%d" % index, "filler-%d" % index, "Unrelated topic %d about gardens and recipes." % index)
        self.registry = os.path.join(self.tmp, "registry.json")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["scan", "--root", lib + "::lib", "--out", self.registry])
        self.config = write(self.tmp, "config.json", json.dumps({
            "registry": self.registry, "use_platform_roots": False, "use_cwd_project_roots": False,
            "hook_skip_tags": ["cross-session-message"], "session_memory": False, "feedback": False}))

    def hook(self, name):
        with contextlib.redirect_stderr(io.StringIO()):
            return run_hook(fixture(name), config_path=self.config, registry_path=self.registry)

    def test_each_harness_message_prints_nothing(self):
        for name in SILENT:
            with self.subTest(fixture=name):
                self.assertEqual(self.hook(name), "")

    def test_the_same_words_typed_by_the_user_are_searched(self):
        # counter-check: the silent fixtures are silent because of their wrappers, not because nothing matches
        payload = json.loads(fixture("subagent_report"))
        payload["prompt"] = "Found a failing test and a console error in the payment page; the pull request needs a fix."
        with contextlib.redirect_stderr(io.StringIO()):
            out = run_hook(json.dumps(payload), config_path=self.config, registry_path=self.registry)
        self.assertIn("lib/payment-test-debugging", out)

    def test_a_real_request_with_a_reminder_attached_is_still_searched(self):
        out = self.hook("real_request_with_reminder")
        self.assertIn("lib/payment-test-debugging", out)

    def test_the_cross_session_tag_is_only_skipped_when_configured(self):
        config = write(self.tmp, "plain.json", json.dumps({
            "registry": self.registry, "use_platform_roots": False, "use_cwd_project_roots": False,
            "session_memory": False, "feedback": False}))
        with contextlib.redirect_stderr(io.StringIO()):
            out = run_hook(fixture("cross_session"), config_path=config, registry_path=self.registry)
        self.assertIn("lib/payment-test-debugging", out)


class UserTextTests(unittest.TestCase):
    def test_wrapper_blocks_are_removed_and_user_text_kept(self):
        text = "<system-reminder>ignore me</system-reminder> fix the login form <command-name>/x</command-name>"
        self.assertEqual(user_text(text), "fix the login form")

    def test_pasted_content_is_the_users_text(self):
        text = '<pasted_content id="1">debug the payment test</pasted_content>'
        self.assertIn("debug the payment test", user_text(text))

    def test_tag_names_are_matched_whole(self):
        self.assertEqual(user_text("<task-notifications>keep this text</task-notifications>"),
                         "<task-notifications>keep this text</task-notifications>")

    def test_a_listed_prefix_makes_the_message_empty(self):
        self.assertEqual(user_text("[Request interrupted by user]"), "")

    def test_the_minimum_length_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "lib")
            skill(lib, "ntp-sync", "ntp-sync", "Sync clocks with ntp servers.")
            for index in range(6):
                skill(lib, "filler-%d" % index, "filler-%d" % index, "Gardens and recipes %d." % index)
            registry = os.path.join(tmp, "r.json")
            with contextlib.redirect_stdout(io.StringIO()):
                main(["scan", "--root", lib + "::lib", "--out", registry])
            payload = json.dumps({"prompt": "ntp clocks"})
            config = write(tmp, "c.json", json.dumps({"use_platform_roots": False, "hook_min_chars": 20,
                                                      "session_memory": False, "feedback": False}))
            self.assertEqual(run_hook(payload, config_path=config, registry_path=registry), "")
            config = write(tmp, "c2.json", json.dumps({"use_platform_roots": False, "hook_min_chars": 4,
                                                       "session_memory": False, "feedback": False}))
            self.assertIn("lib/ntp-sync", run_hook(payload, config_path=config, registry_path=registry))


if __name__ == "__main__":
    unittest.main()
