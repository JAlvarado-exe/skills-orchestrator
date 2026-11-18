"""Policy and usage are checked against the recommendations actually rendered."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from orchestrator import feedback, hook, session
from orchestrator.cli import _hook_run, main
from orchestrator.evaluate import load_target
from orchestrator.policy import matches
from orchestrator.retrieval import display_origin, retrieve
from tests.helpers import skill, write


class RoutingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.state = os.path.join(self.tmp, "state")
        self.lib = os.path.join(self.tmp, "skills")
        self.config = write(self.tmp, "config.json", json.dumps({
            "state_dir": self.state, "use_platform_roots": False, "use_cwd_project_roots": False,
            "registry": os.path.join(self.tmp, "registry.json"), "extra_roots": [{"path": self.lib}],
            "catalogs": [os.path.join(self.tmp, "catalog.json")], "hook_top": 10, "min_score": 0}))
        for n in range(18):
            skill(self.lib, "filler-%d" % n, "filler-%d" % n, "Gardening and irrigation tips.")
        write(self.tmp, "catalog.json", json.dumps({"items": [
            {"name": "atlas", "kind": "cli", "what": "Triangulate maritime coordinates",
             "upstream": "https://example.org/atlas"}]}))

    def command(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--config", self.config]), 0)
        return out.getvalue()

    def block(self, query, session_id="first"):
        return hook.build_context(query, self.tmp, config_path=self.config, session_id=session_id)

    def test_hook_skips_manual_only_frontmatter_but_manual_inventory_and_tools_survive(self):
        skill(self.lib, "compass", "compass", "Triangulate maritime coordinates",
              extra="disable-model-invocation: true\n")
        self.command("scan")
        query = "Triangulate maritime coordinates"
        block = self.block(query)
        self.assertIn("catalog/atlas", block)
        self.assertNotIn("/compass", block)
        self.assertIn("/compass", self.command("list", "--names"))
        self.assertIn("/compass", self.command("find", query))

    def test_owner_policy_precedes_action_even_for_a_lone_match(self):
        skill(self.lib, "social", "social", "Coordinate publication campaigns")
        self.command("scan")
        for text in [self.command("find", "Coordinate publication campaigns"),
                     self.block("Coordinate publication campaigns")]:
            self.assertIn("/social", text)
            self.assertIn("owner-pin", text)
            self.assertIn("social-publishing", text)
            self.assertNotIn("read:", text)
            self.assertNotIn("run (see its docs)", text)
        result = json.loads(self.command("find", "Coordinate publication campaigns", "--json"))["results"][0]
        self.assertFalse(result.get("path"))
        self.assertIn("social-publishing", result["owner_pin"])

    def test_catalog_tool_named_in_owner_policy_never_exposes_an_action(self):
        write(self.tmp, "catalog.json", json.dumps({"items": [
            {"name": "Postiz App", "kind": "cli", "what": "Calendar publication timetable",
             "upstream": "https://example.org/scheduler"}]}))
        self.command("scan")
        result = json.loads(self.command("find", "calendar publication timetable", "--json"))["results"][0]
        self.assertIn("social-publishing", result.get("owner_pin", []))
        self.assertNotIn("upstream", result)
        self.assertNotIn("example.org", self.block("calendar publication timetable"))

    def test_policy_matches_every_origin_of_a_physical_copy(self):
        row = {"id": "shared/map", "name": "map", "sources": ["shared"],
               "origins": [{"source": "archived"}, {"source": "shared"}]}
        self.assertTrue(matches(row, ["archived/*"]))

    def test_display_origin_uses_hot_and_visibility_of_the_selected_text(self):
        common = {"source": "shared", "platform": None, "hot": False, "internal": False}
        row = {"id": "shared/map", "sha256": "one", "origins": [
            dict(common, path="first", sha256="one"), dict(common, path="second", sha256="one", hot=True, internal=True),
            dict(common, path="third", sha256="two", hot=True)], "hot": True}
        result = display_origin(row)
        self.assertEqual((result["path"], result["hot"]), ("first", False))

    def test_copy_explains_its_own_matches(self):
        base = {"source": "s", "dup_group": "a", "name": "guide"}
        actual = dict(base, id="s/guide", description="Fold origami cranes")
        other = dict(base, id="t/guide", hot=True, description="Bind manuscripts")
        result = retrieve([other, actual], ["Fold origami cranes"], 0, 2)[0]
        self.assertEqual(result["entry"]["id"], actual["id"])

    def test_equivalent_evidence_prefers_the_better_placed_copy(self):
        base = {"dup_group": "a", "name": "guide"}
        short = dict(base, id="vendor/guide", description="Fold origami cranes")
        local = dict(base, id="local/guide", hot=True, description="Fold origami cranes using several sheets of paper")
        result = retrieve([short, local], ["Fold origami cranes"], 0, 2)[0]
        self.assertEqual(result["entry"]["id"], local["id"])

    def test_status_closings_do_not_hide_a_follow_on_request(self):
        self.command("scan")
        for report in ("The maritime coordinates were triangulated. No further action, thanks.",
                       "Ya terminé de triangular las coordenadas. Era solo para avisarte."):
            self.assertEqual(self.block(report), "")
        for query in ("The diagram is finished. Now triangulate maritime coordinates.",
                      "No further action on the diagram. Please triangulate maritime coordinates.",
                      "Can you triangulate maritime coordinates? Just letting you know."):
            self.assertIn("atlas", self.block(query, session_id=None))
        payload = {"prompt": "Triangulate maritime coordinates", "message_type": "status"}
        self.assertEqual(hook.run_hook(json.dumps(payload), config_path=self.config), "")

    def test_stats_and_eval_only_count_ids_that_fit_in_the_block(self):
        for n in range(8):
            name = "cartographer-%d" % n
            skill(self.lib, name, name, "Triangulate maritime coordinates " + str(n))
        self.command("scan")
        query = "Triangulate maritime coordinates"
        loaded = load_target(self.config)
        with mock.patch.object(hook, "HARD_CAP", 450):
            result = self.block(query)
            shown = [l.split()[1] for l in result.splitlines() if l[:1].isdigit()]
            self.assertTrue(shown)
            self.assertLess(len(shown), 8)
            self.assertEqual(sorted(feedback.load_stats(self.state)), sorted(shown))
            measured, printed = _hook_run({"prompt": query}, loaded)
            self.assertEqual(measured, [l.split()[1] for l in printed.splitlines() if l[:1].isdigit()])

    def test_explicit_use_in_one_session_never_unlocks_another(self):
        skill(self.lib, "compass", "compass", "Triangulate maritime coordinates")
        self.command("scan")
        query = "Triangulate maritime coordinates"
        for sid in ("first", "second"):
            for _ in range(2):
                self.assertIn("/compass", self.block(query, sid))
        ident = next(i for i in feedback.load_stats(self.state) if i.endswith("/compass"))
        self.command("used", ident)
        self.assertNotIn("session_id", feedback.load_usage(self.state)[0])
        self.assertNotIn("/compass", self.block(query, "first"))
        self.command("used", ident, "--session-id", "second")
        self.assertNotIn("/compass", self.block(query, "first"))
        self.assertIn("/compass", self.block(query, "second"))

    def test_repeated_negative_feedback_is_a_bounded_penalty(self):
        self.assertLess(feedback.factor({"used": 1, "unhelpful": 1}), 1)
        self.assertGreaterEqual(feedback.factor({"used": 999, "unhelpful": 999}), 1 - feedback.MAX_PENALTY)

    def test_concurrent_increments_survive_stale_reader_snapshots(self):
        worker = """
import sys
from orchestrator import feedback, session
state = sys.argv[1]
for _ in range(20):
    memory = session.load(state, "parallel")
    session.record(state, "parallel", memory, ["s/map"])
    feedback.bump_shown(state, ["s/map"])
    feedback.record_use(state, "s/map", "yes", session_id="parallel")
"""
        workers = [subprocess.Popen([sys.executable, "-B", "-c", worker, self.state]) for _ in range(5)]
        self.assertEqual([worker.wait(timeout=30) for worker in workers], [0] * 5)
        self.assertEqual(feedback.load_stats(self.state)["s/map"]["shown"], 100)
        self.assertEqual(session.load(self.state, "parallel")["shown"]["s/map"], 100)
        self.assertEqual(len(feedback.load_usage(self.state)), 100)

    def test_interrupted_replacement_preserves_previous_stats(self):
        feedback.bump_shown(self.state, ["s/map"])
        with mock.patch("orchestrator.jsonio.os.replace", side_effect=OSError("disk full")):
            feedback.bump_shown(self.state, ["s/map"])
        self.assertEqual(feedback.load_stats(self.state)["s/map"]["shown"], 1)
        feedback.bump_shown(self.state, ["s/map"])
        self.assertEqual(feedback.load_stats(self.state)["s/map"]["shown"], 2)

    def test_large_legacy_history_is_not_replayed_on_every_query(self):
        write(self.state, "usage.jsonl", (json.dumps({"ts": 1, "id": "s/map", "helped": "yes"}) + "\n") * 2000)
        self.assertGreater(feedback.factors(self.state)["s/map"], 1)
        with mock.patch.object(feedback.json, "loads", wraps=json.loads) as decode:
            self.assertGreater(feedback.factors(self.state)["s/map"], 1)
            self.assertLess(decode.call_count, 10)
        feedback.record_use(self.state, "s/new", "no")
        with mock.patch.object(feedback.json, "loads", wraps=json.loads) as decode:
            self.assertLess(feedback.factors(self.state)["s/new"], 1)
            self.assertLess(decode.call_count, 10)
