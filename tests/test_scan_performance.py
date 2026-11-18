"""Exercise copy comparison, registry provenance and concurrent snapshot writes."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import tempfile
import threading
import tracemalloc
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from orchestrator import cli, scan
from orchestrator.hook import build_context
from orchestrator.overlaps import find_overlaps
from tests.helpers import skill, write


class CopyScanTests(unittest.TestCase):
    def test_longest_block_keeps_leftmost_ties_and_internal_edits(self):
        rng = random.Random(17)
        text = "".join(rng.choice("abcdefgh ") for _ in range(1450))
        changed = text[:450] + "revised" + text[485:940] + "different" + text[944:]
        for left, right in ((text, changed), ("z" + text[:1080] + "w" + text[:1080], "v" + text[:1080]),
                            (text, text[::-1]), ("ab" * 560, "ba" * 560)):
            expected = difflib.SequenceMatcher(None, left, right, autojunk=False)
            matcher = scan._CopyMatcher(None, left, right, autojunk=False)
            self.assertEqual(matcher.find_longest_match(), expected.find_longest_match())
            self.assertEqual(matcher.get_matching_blocks(), expected.get_matching_blocks())

    def test_overlap_limits_bound_memory_and_preserve_ordered_scores(self):
        entries = [{"id": "repo%03d/s" % i, "name": "guide", "source": "repo%03d" % i,
                    "description": "inspect sediment glacier records evidence"} for i in range(150)]
        tracemalloc.start()
        try:
            pairs = find_overlaps(entries, limit=3)["similar"]
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual([(p["a"], p["b"], p["score"]) for p in pairs],
                         [("repo000/s", "repo%03d/s" % i, 1.0) for i in (1, 2, 3)])
        self.assertLess(peak, 2_000_000)

    def test_long_unchanged_end_proves_a_match_without_quadratic_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "Inspect the report and record the evidence.\n" * 120
            for edition in ("a", "b", "c"):
                skill(tmp, edition, "report", "Edition " + edition, body)
            with mock.patch.object(scan, "_CopyMatcher", side_effect=AssertionError("unnecessary comparison")):
                entries = scan.build_registry([{"path": tmp, "source_from": "first-child"}])["entries"]
            self.assertEqual([e["dup_group"] for e in entries], ["a/report"] * 3)

    def test_edits_around_boilerplate_match_the_original_character_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            common = "Record the measured evidence. " * 8
            bodies = [common + "x" * 16 + common, common + "y" * 16 + common,
                      common + "z" * 230 + common]
            for number, body in enumerate(bodies):
                skill(tmp, str(number), "task", "Inspect report", body)
            spec = [{"path": tmp, "source_from": "first-child"}]
            previous = scan.make_registry(spec)
            self.assertEqual([e["dup_group"] for e in previous["entries"]], ["0/task", "0/task", "2/task"])
            with mock.patch.object(scan, "_CopyMatcher", side_effect=AssertionError("unchanged pair")):
                refreshed = scan.make_registry(spec, previous=previous)
            self.assertEqual(previous["entries"], refreshed["entries"])
            skill(tmp, "2", "task", "Inspect report", common + "q" * 16 + common)
            changed = scan.make_registry(spec, previous=previous)
            self.assertEqual({e["dup_group"] for e in changed["entries"]}, {"0/task"})

    def test_origins_associate_paths_with_each_root_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.realpath(skill(tmp, "repo/s", "task", "Main"))
            b = os.path.realpath(skill(tmp, "installed/s", "task", "Main"))
            c = os.path.realpath(skill(tmp, "repo/fixtures/s", "task", "Old"))
            entries = scan.build_registry([
                {"path": tmp, "source_from": "first-child"},
                {"path": os.path.join(tmp, "installed"), "source": "host", "platform": "host", "hot": True}
            ])["entries"]
            origins = [origin for entry in entries for origin in entry["origins"]]
            self.assertEqual({(o["path"], o["source"], o["platform"], o["hot"], o["internal"]) for o in origins},
                             {(a, "repo", None, False, False), (b, "installed", None, False, False),
                              (b, "host", "host", True, False), (c, "repo", None, False, True)})
            hashes = {o["path"]: o["sha256"] for o in origins}
            self.assertEqual(hashes[a], hashes[b])
            self.assertNotEqual(hashes[a], hashes[c])
            self.assertTrue(all(e["auto_eligible"] for e in entries))
            skill(tmp, "manual", "manual", "Manual only", extra="disable-model-invocation: true\n")
            manual = next(e for e in scan.build_registry([{"path": tmp}])["entries"] if e["name"] == "manual")
            self.assertFalse(manual["auto_eligible"])

    def test_semantic_inputs_and_root_order_change_the_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, value) for value in ("a", "b", "excluded")]
            base = [{"path": paths[0]}, {"path": paths[1]}]
            signature = scan.roots_signature(base)
            for field, value in [("source", "alias"), ("source_from", "first-child"), ("detect_internal", False),
                                 ("hot", True), ("contain", True), ("platform", "host")]:
                with self.subTest(field=field):
                    self.assertNotEqual(signature, scan.roots_signature([dict(base[0], **{field: value}), base[1]]))
            self.assertNotEqual(signature, scan.roots_signature(base[::-1]))
            self.assertNotEqual(scan.roots_signature([dict(base[0], exclude=paths[2:]), base[1]]),
                                scan.roots_signature([base[0], dict(base[1], exclude=paths[2:])]))
            catalog = write(tmp, "catalog.json", '{"items": []}')
            first = scan.roots_signature(base, [catalog])
            write(tmp, "catalog.json", '{"items": [{"kind": "cli"}]}')
            self.assertNotEqual(first, scan.roots_signature(base, [catalog]))

    def test_registry_writers_never_share_a_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            meet = threading.Barrier(2)
            replace = os.replace
            writer_sources = {}

            def replace_together(source, target):
                writer = threading.get_ident()
                if writer not in writer_sources:
                    writer_sources[writer] = source
                    meet.wait(timeout=10)
                replace(source, target)

            with mock.patch.object(cli.os, "replace", side_effect=replace_together), ThreadPoolExecutor(2) as pool:
                list(pool.map(lambda value: cli._write_registry({"value": value}, path), [1, 2]))
            with open(path, encoding="utf-8") as handle:
                self.assertIn(json.load(handle)["value"], (1, 2))
            self.assertEqual(os.listdir(tmp), ["registry.json"])
            self.assertEqual(len(set(writer_sources.values())), 2)

    def test_prompt_reuses_a_compatible_snapshot_after_project_switch_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = os.path.join(tmp, "registry.json")
            config = write(tmp, "config.json", json.dumps({"registry": reg, "use_platform_roots": False,
                                                          "max_age_hours": 0}))
            args = argparse.Namespace(config=config)
            projects = []
            for name in ("first", "second"):
                project = os.path.join(tmp, name)
                os.makedirs(os.path.join(project, ".git"))
                skill(project, ".agents/skills/report", name, "Inspect report")
                projects.append(project)
                cli.ensure_registry(args, cwd=project, prompt=True)
            with mock.patch.object(cli, "make_registry", side_effect=AssertionError("unnecessary rebuild")):
                for project in projects:
                    _, registry, _ = cli.ensure_registry(args, cwd=project, prompt=True)
                    self.assertEqual([e["name"] for e in registry["entries"]], [os.path.basename(project)])
            # A newly configured root must not reuse either older snapshot.
            extra = os.path.join(tmp, "extra")
            skill(extra, "s", "extra", "Other")
            write(tmp, "config.json", json.dumps({"registry": reg, "extra_roots": [extra], "use_platform_roots": False}))
            _, registry, _ = cli.ensure_registry(args, cwd=projects[0], prompt=True)
            self.assertEqual({e["name"] for e in registry["entries"]}, {"first", "extra"})

    def test_stale_prompt_never_hands_out_changed_or_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write(tmp, "config.json", json.dumps({"registry": os.path.join(tmp, "registry.json"),
                    "extra_roots": ["lib"], "use_platform_roots": False, "use_cwd_project_roots": False,
                    "max_age_hours": 0, "min_score": 0, "feedback": False}))
            path = skill(tmp, "lib/glacier", "glacier", "Inspect glacier sediment stratigraphy")
            prompt = "inspect glacier sediment stratigraphy"
            self.assertIn("glacier", build_context(prompt, tmp, config_path=config))
            skill(tmp, "lib/glacier", "glacier", "Inspect glacier sediment stratigraphy",
                  extra="disable-model-invocation: true\n")
            self.assertEqual(build_context(prompt, tmp, config_path=config), "")

            os.unlink(path)
            self.assertEqual(build_context(prompt, tmp, config_path=config), "")

    def test_cold_scan_can_be_disabled_only_for_the_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = os.path.join(tmp, "registry.json")
            config = write(tmp, "config.json", json.dumps({"registry": reg, "extra_roots": ["lib"],
                    "use_platform_roots": False, "use_cwd_project_roots": False, "min_score": 0,
                    "hook_cold_scan": False, "feedback": False}))
            skill(tmp, "lib/glacier", "glacier", "Inspect glacier sediment stratigraphy")
            prompt = "inspect glacier sediment stratigraphy"
            with mock.patch.object(cli, "make_registry", side_effect=AssertionError("hook tried to scan")):
                self.assertEqual(build_context(prompt, tmp, config_path=config), "")
                self.assertFalse(os.path.exists(reg))
            cli.ensure_registry(argparse.Namespace(config=config), cwd=tmp)
            self.assertIn("glacier/glacier", build_context(prompt, tmp, config_path=config))
