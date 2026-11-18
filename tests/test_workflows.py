from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

from orchestrator.cli import main
from tests.helpers import skill, write


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.config = write(self.root, "config.json", json.dumps({
            "catalogs": ["catalog.json"], "vendor": ["library"], "registry": "registry.json",
            "use_platform_roots": False, "use_cwd_project_roots": False}))
        self.item = {"kind": "workflow", "id": "field-study", "name": "Field study",
                     "description": "Field interview research synthesis", "entry": "guide/start.md"}
        self.catalog(self.item)
        for name in ["start", "observe", "review"]:
            write(self.root, "guide/" + name + ".md", "Local working instructions.")
        self.phases = [{"id": "observe", "instructions": "observe.md"},
                       {"id": "review", "requires": ["observe"], "instructions": "review.md",
                        "requires_approval": True}]
        self.manifest(self.phases)
        skill(self.root, "library/other/invoices", "invoices", "Calculate monthly income.")

    def manifest(self, phases):
        write(self.root, "guide/workflow.json", json.dumps({"phases": phases}))

    def catalog(self, item):
        write(self.root, "catalog.json", json.dumps({"items": [item]}))

    def run_command(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main([*args, "--config", self.config, "--json"])
        return status, json.loads(output.getvalue()) if output.getvalue() else {}, error.getvalue()

    def test_discover_local_guide_without_skill_frontmatter(self):
        status, result, _ = self.run_command("find", "field interview research synthesis", "--min-score", "0")
        self.assertEqual(status, 0)
        self.assertEqual(result["results"][0]["id"], "workflow/field-study")
        self.assertEqual(result["results"][0]["label"], "WORKFLOW")

    def test_resume_checks_prerequisites_and_keeps_approval_explicit(self):
        args = ("workflow", "workflow/field-study")
        status, data, _ = self.run_command(*args)
        self.assertEqual(status, 0)
        self.assertEqual([p["id"] for p in data["ready"]], ["observe"])
        self.assertTrue(os.path.isfile(data["ready"][0]["instructions"]))
        _, data, _ = self.run_command(*args, "--done", "observe")
        self.assertEqual(data["ready"][0]["status"], "requires-approval")
        self.assertNotIn("instructions", data["ready"][0])
        _, data, _ = self.run_command(*args, "--done", "observe", "--approved", "review")
        self.assertTrue(data["ready"][0]["instructions"].endswith("review.md"))
        self.assertNotEqual(self.run_command(*args, "--done", "review")[0], 0)
        self.assertNotEqual(self.run_command(*args, "--done", "unknown")[0], 0)
        _, data, _ = self.run_command(*args, "--done", "observe", "--done", "review", "--approved", "review")
        self.assertTrue(data["complete"])

    def test_blocked_workflow_has_no_phase_paths(self):
        write(self.root, "config.json", json.dumps({"registry": "registry.json", "catalogs": ["catalog.json"],
              "use_platform_roots": False, "use_cwd_project_roots": False, "blocked": ["workflow/*"]}))
        status, result, _ = self.run_command("workflow", "workflow/field-study")
        self.assertNotEqual(status, 0)
        self.assertFalse(result)

    def test_rejects_invalid_or_external_phases(self):
        for phases in [[{"id": "one", "instructions": "../outside.md"}],
                       [{"id": "one", "instructions": "start.md", "requires": ["one"]}],
                       [{"id": "one", "instructions": "absent.md"}]]:
            with self.subTest(phases=phases):
                self.manifest(phases)
                self.assertNotEqual(self.run_command("workflow", "workflow/field-study")[0], 0)

    def test_catalog_rejects_an_overview_outside_its_directory(self):
        self.catalog(dict(self.item, entry="../external.md"))
        _, result, _ = self.run_command("list")
        self.assertNotIn("workflow/field-study", [row["id"] for row in result["skills"]])
