"""Guaranteed discovery: user config, project roots, automatic refresh, `list`, Spanish queries, weak-match signal.

Everything here is hermetic: temporary folders, `--config`/`--registry` flags, and `home=` arguments.
The Spanish words below are test data for the query translation table and the recall fixture.
"""
import contextlib
import io
import json
import os
import re
import tempfile
import time
import unittest
from unittest import mock

from orchestrator import __version__
from orchestrator import config as cfg
from orchestrator.cli import main
from orchestrator.scan import build_registry, catalog_entries, find_skill_files
from orchestrator.search import (STOPWORDS, WEAK_BEST_SCORE, WEAK_MIN_RESULTS, fold, is_weak, name_matches,
                                 query_terms, rank, tokenize)
from tests.helpers import skill, write

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEAK_LINE = ("WEAK MATCH: do not conclude that no skill exists. Rephrase in English with two more wordings (--also), "
             "check your platform's own skill list, and run: list --names")


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run(*argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if cwd:
            with chdir(cwd):
                code = main(list(argv))
        else:
            code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def read_registry(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Workspace(unittest.TestCase):
    """A temporary 'machine': a work folder with projects, a cold library, and two git projects."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.work = os.path.join(self.tmp, "work")
        self.cold = os.path.join(self.tmp, "cold")
        self.proj = os.path.join(self.tmp, "proj")
        self.other = os.path.join(self.tmp, "other")
        self.registry = os.path.join(self.tmp, "state", "registry.json")
        for project in (self.proj, self.other):
            os.makedirs(os.path.join(project, ".git"))
        skill(self.work, "projA/.claude/skills/browser-devtools", "browser-devtools",
              "Open a page in the browser and inspect console messages, network requests and the DOM. Use when debugging a web page.")
        skill(self.work, "projB/skills/invoice-helper", "invoice-helper", "Prepare customer invoices and payment reminders.")
        skill(self.cold, "repoX/skills/pricing-deep", "pricing-deep", "Decide pricing tiers and packaging for software.")
        skill(self.proj, ".claude/skills/local-helper", "local-helper", "Release notes helper that belongs to one project.")
        skill(self.other, ".agents/skills/other-helper", "other-helper", "Helper that exists only in the other project.")

    def config(self, **keys):
        data = {"registry": self.registry, "use_platform_roots": False,
                "extra_roots": [self.work], "vendor": [self.cold]}
        data.update(keys)
        return write(self.tmp, "config.json", json.dumps(data))

    def ids(self, path=None):
        return {e["id"] for e in read_registry(path or self.registry)["entries"]}


class ConfigFileTests(Workspace):
    def test_default_path_is_env_then_home(self):
        with mock.patch.dict(os.environ, {cfg.CONFIG_ENV: "somewhere.json"}):
            self.assertEqual(cfg.default_config_path(), "somewhere.json")
        with mock.patch.dict(os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp}):
            os.environ.pop(cfg.CONFIG_ENV, None)
            self.assertEqual(cfg.default_config_path(), os.path.join(self.tmp, ".skills-orchestrator", "config.json"))

    def test_missing_file_gives_documented_defaults(self):
        config = cfg.load_config(os.path.join(self.tmp, "nope.json"))
        self.assertTrue(config["use_platform_roots"])
        self.assertTrue(config["use_cwd_project_roots"])
        self.assertEqual(config["max_age_hours"], 12)
        for key in ("extra_roots", "vendor", "catalogs", "exclude_paths"):
            self.assertEqual(config[key], [])
        for key in ("registry", "overrides", "profiles_dir"):
            self.assertIsNone(config[key])

    def test_malformed_config_warns_once_and_is_empty(self):
        for text in ("{not json", "[1, 2]"):
            path = write(self.tmp, "bad.json", text)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                config = cfg.load_config(path)
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1, err.getvalue())
            self.assertIn("warning", err.getvalue())
            self.assertEqual(config["extra_roots"], [])
            self.assertTrue(config["use_platform_roots"])

    def test_tilde_and_environment_variables_are_expanded(self):
        path = write(self.tmp, "c.json", json.dumps({"registry": "~/reg.json", "vendor": ["${SO_TEST_BASE}/cold"]}))
        with mock.patch.dict(os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp, "SO_TEST_BASE": self.tmp}):
            config = cfg.load_config(path)
        self.assertEqual(config["registry"], os.path.normpath(os.path.join(self.tmp, "reg.json")))
        self.assertEqual(config["vendor"], [os.path.normpath(os.path.join(self.tmp, "cold"))])

    def test_relative_paths_are_resolved_against_the_config_folder(self):
        path = write(self.tmp, "sub/c.json", json.dumps({"vendor": ["lib"]}))
        self.assertEqual(cfg.load_config(path)["vendor"], [os.path.join(self.tmp, "sub", "lib")])

    def test_extra_root_forms_and_defaults(self):
        path = write(self.tmp, "c.json", json.dumps({"extra_roots": [
            self.work, {"path": self.cold, "source_from": "fixed", "contain": True}]}))
        plain, detailed = cfg.load_config(path)["extra_roots"]
        self.assertEqual((plain["path"], plain["source_from"], plain["contain"]), (self.work, "first-child", False))
        self.assertEqual((detailed["source_from"], detailed["contain"]), ("fixed", True))
        self.assertFalse(plain["hot"])

    def test_invalid_values_are_ignored_with_one_warning(self):
        path = write(self.tmp, "c.json", json.dumps({"extra_roots": [5, {"nopath": 1}, self.work], "max_age_hours": "soon",
                                                      "use_platform_roots": "yes"}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            config = cfg.load_config(path)
        self.assertEqual([r["path"] for r in config["extra_roots"]], [self.work])
        self.assertEqual(config["max_age_hours"], 12)
        self.assertTrue(config["use_platform_roots"])
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1, err.getvalue())

    def test_registry_path_precedence_config_then_env_then_home(self):
        with mock.patch.dict(os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp, cfg.REGISTRY_ENV: "from-env.json"}):
            self.assertEqual(cfg.registry_path({"registry": "from-config.json"}), "from-config.json")
            self.assertEqual(cfg.registry_path({"registry": None}), "from-env.json")
            os.environ.pop(cfg.REGISTRY_ENV)
            self.assertEqual(cfg.registry_path({"registry": None}),
                             os.path.join(self.tmp, ".skills-orchestrator", "registry.json"))


class AssembleRootsTests(Workspace):
    def load(self, **keys):
        return cfg.load_config(self.config(**keys))

    def test_project_folders_are_found_from_cwd_up_to_the_git_root(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        os.makedirs(os.path.join(repo, ".claude", "skills"))
        os.makedirs(os.path.join(repo, "packages", "app", ".agents", "skills"))
        os.makedirs(os.path.join(self.tmp, ".claude", "skills"))  # above the git root: must not be included
        specs = cfg.assemble_roots(self.load(extra_roots=[], vendor=[]), os.path.join(repo, "packages", "app"),
                                   use_platforms=False, home=os.path.join(self.tmp, "elsewhere"))
        found = {(s["source"], s["path"]) for s in specs}
        self.assertEqual(found, {("project:repo", os.path.join(repo, ".claude", "skills")),
                                 ("project:app", os.path.join(repo, "packages", "app", ".agents", "skills"))})
        self.assertTrue(all(s["hot"] is False for s in specs))

    def test_all_seven_tool_folders_count_as_project_roots(self):
        project = os.path.join(self.tmp, "seven")
        os.makedirs(os.path.join(project, ".git"))
        for rel in cfg.PROJECT_SKILL_DIRS:
            os.makedirs(os.path.join(project, *rel.split("/")))
        self.assertEqual(sorted(cfg.PROJECT_SKILL_DIRS), sorted([
            ".claude/skills", ".agents/skills", ".github/skills", ".cursor/skills", ".gemini/skills",
            ".opencode/skills", ".codex/skills"]))
        specs = cfg.assemble_roots(self.load(extra_roots=[], vendor=[]), project, use_platforms=False, home=self.tmp + "x")
        self.assertEqual(len(specs), 7)

    def test_without_a_git_root_the_walk_stops_before_the_home_folder(self):
        home = os.path.join(self.tmp, "home")
        deep = os.path.join(home, "work", "p")
        for folder in (os.path.join(home, ".claude", "skills"), os.path.join(home, "work", ".claude", "skills"),
                       os.path.join(deep, ".claude", "skills")):
            os.makedirs(folder)
        specs = cfg.assemble_roots(self.load(extra_roots=[], vendor=[]), deep, use_platforms=False, home=home)
        self.assertEqual({s["source"] for s in specs}, {"project:p", "project:work"})
        self.assertEqual(cfg.assemble_roots(self.load(extra_roots=[], vendor=[]), home, use_platforms=False, home=home), [])

    def test_cwd_project_roots_can_be_switched_off(self):
        config = self.load(extra_roots=[], vendor=[], use_cwd_project_roots=False)
        self.assertEqual(cfg.assemble_roots(config, self.proj, use_platforms=False), [])

    def test_platform_roots_follow_both_switches(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".claude", "skills"))
        on = cfg.assemble_roots(self.load(use_platform_roots=True, extra_roots=[], vendor=[]), home, home=home)
        self.assertEqual([(s["platform"], s["hot"]) for s in on if s.get("platform") == "claude"], [("claude", True)])
        self.assertEqual(cfg.assemble_roots(self.load(use_platform_roots=True, extra_roots=[], vendor=[]), home,
                                            use_platforms=False, home=home), [])
        self.assertEqual(cfg.assemble_roots(self.load(use_platform_roots=False, extra_roots=[], vendor=[]), home,
                                            home=home), [])

    def test_vendor_roots_are_contained_and_extra_roots_are_not(self):
        specs = cfg.assemble_roots(self.load(), self.proj, use_platforms=False)
        by_path = {s["path"]: s for s in specs}
        self.assertTrue(by_path[self.cold]["contain"])
        self.assertEqual(by_path[self.cold]["source_from"], "first-child")
        self.assertFalse(by_path[self.work]["contain"])
        self.assertEqual(by_path[self.work]["source_from"], "first-child")

    def test_exclude_paths_prune_extra_roots_by_directory_prefix(self):
        skill(self.work, "skip/hidden-one", "hidden-one", "should not be indexed")
        skill(self.work, "skipper/kept-one", "kept-one", "similar folder name must survive")
        config = self.load(exclude_paths=[os.path.join(self.work, "skip")])
        specs = cfg.assemble_roots(config, self.proj, use_platforms=False)
        ids = {e["id"] for e in build_registry(specs)["entries"]}
        self.assertNotIn("skip/hidden-one", ids)
        self.assertIn("skipper/kept-one", ids)
        self.assertIn("projA/browser-devtools", ids)

    def test_find_skill_files_exclude_argument(self):
        found = find_skill_files(self.work, exclude=[os.path.join(self.work, "projA")])
        self.assertTrue(found and all("projA" not in path for path in found))


class ScanFromConfigTests(Workspace):
    def test_scan_without_arguments_covers_config_cold_library_and_current_project(self):
        code, out, _err = run("scan", "--config", self.config(), cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertIn(self.registry, out)
        self.assertEqual(self.ids(), {"projA/browser-devtools", "projB/invoice-helper", "repoX/pricing-deep",
                                      "project:proj/local-helper"})
        registry = read_registry(self.registry)
        self.assertEqual(registry["built_with"], "config")
        self.assertIsInstance(registry["roots_signature"], list)
        self.assertIn(os.path.normcase(os.path.join(self.proj, ".claude", "skills")),
                      [os.path.normcase(p) for p in registry["roots_signature"]])

    def test_hidden_project_folders_under_extra_roots_are_not_flagged_internal(self):
        run("scan", "--config", self.config(), cwd=self.proj)
        entry = {e["id"]: e for e in read_registry(self.registry)["entries"]}["projA/browser-devtools"]
        self.assertFalse(entry["internal"])
        code, out, _err = run("find", "browser console", "--registry", self.registry, "--json")
        self.assertEqual(json.loads(out)["results"][0]["id"], "projA/browser-devtools")

    def test_explicit_roots_alone_ignore_the_config(self):
        explicit = os.path.join(self.tmp, "explicit.json")
        code, _out, err = run("scan", "--root", os.path.join(self.cold, "repoX") + "::x", "--out", explicit, cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertEqual(self.ids(explicit), {"x/pricing-deep"})
        self.assertEqual(read_registry(explicit)["built_with"], "explicit")
        self.assertIsInstance(read_registry(explicit)["roots_signature"], list)

    def test_explicit_roots_plus_config_flag_use_both(self):
        extra = os.path.join(self.tmp, "extra")
        skill(extra, "z", "z-skill", "extra explicit root")
        code, _out, _err = run("scan", "--config", self.config(), "--root", extra + "::manual", cwd=self.proj)
        self.assertEqual(code, 0)
        ids = self.ids()
        self.assertIn("manual/z-skill", ids)
        self.assertIn("repoX/pricing-deep", ids)
        self.assertEqual(read_registry(self.registry)["built_with"], "config")

    def test_check_mode_with_config_writes_nothing(self):
        code, out, _err = run("scan", "--config", self.config(), "--check", cwd=self.proj)
        self.assertEqual(code, 0, out)
        self.assertIn("files=4", out)
        self.assertFalse(os.path.exists(self.registry))

    def test_config_catalogs_become_tool_entries_and_a_missing_catalog_only_warns(self):
        catalog = write(self.tmp, "cat.json", json.dumps({"items": [
            {"name": "Some Tool", "kind": "cli", "what": "Does useful things.", "impact": "none", "activation": "run it",
             "upstream": "https://example.org/some-tool"}]}))
        config = self.config(catalogs=[catalog, os.path.join(self.tmp, "missing-catalog.json")])
        code, _out, err = run("scan", "--config", config, cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertIn("catalog/some-tool", self.ids())
        self.assertIn("warning", err)

    def test_scan_prints_note_when_explicit_roots_replace_the_default_registry(self):
        with mock.patch.dict(os.environ, {cfg.CONFIG_ENV: self.config()}):
            code, _out, err = run("scan", "--root", os.path.join(self.cold, "repoX") + "::x", cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertIn("note", err)


class EnsureRegistryTests(Workspace):
    def test_first_find_builds_the_registry_automatically(self):
        code, out, err = run("find", "pricing tiers", "--config", self.config(), cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(self.registry))
        self.assertRegex(err, r"registry rebuilt: 4 entries")
        self.assertIn("repoX/pricing-deep", out)

    def test_fresh_registry_is_not_rebuilt(self):
        config = self.config()
        run("find", "pricing", "--config", config, cwd=self.proj)
        before = os.path.getmtime(self.registry)
        _code, _out, err = run("find", "pricing", "--config", config, cwd=self.proj)
        self.assertNotIn("registry rebuilt", err)
        self.assertEqual(os.path.getmtime(self.registry), before)

    def test_stale_registry_is_rebuilt_unless_max_age_is_large(self):
        config = self.config()
        run("find", "pricing", "--config", config, cwd=self.proj)
        old = time.time() - 48 * 3600
        os.utime(self.registry, (old, old))
        _code, _out, err = run("find", "pricing", "--config", config, cwd=self.proj)
        self.assertIn("registry rebuilt", err)
        os.utime(self.registry, (old, old))
        _code, _out, err = run("find", "pricing", "--config", self.config(max_age_hours=1000), cwd=self.proj)
        self.assertNotIn("registry rebuilt", err)

    def test_changing_project_changes_the_signature_and_rebuilds(self):
        config = self.config()
        run("find", "pricing", "--config", config, cwd=self.proj)
        self.assertIn("project:proj/local-helper", self.ids())
        _code, out, err = run("find", "helper other project", "--config", config, "--json", cwd=self.other)
        self.assertIn("registry rebuilt", err)
        self.assertIn("project:other/other-helper", {r["id"] for r in json.loads(out)["results"]})
        self.assertNotIn("project:proj/local-helper", self.ids())
        _code, _out, err = run("find", "pricing", "--config", config, cwd=self.proj)
        self.assertIn("registry rebuilt", err)

    def test_registry_without_signature_is_rebuilt(self):
        config = self.config()
        run("scan", "--root", os.path.join(self.cold, "repoX") + "::x", "--out", self.registry, cwd=self.proj)
        data = read_registry(self.registry)
        data.pop("roots_signature")
        data.pop("built_with")
        write(os.path.dirname(self.registry), "registry.json", json.dumps(data))
        _code, _out, err = run("find", "pricing", "--config", config, cwd=self.proj)
        self.assertIn("registry rebuilt", err)
        self.assertEqual(read_registry(self.registry)["built_with"], "config")

    def test_refresh_flag_forces_a_rebuild(self):
        config = self.config()
        run("find", "pricing", "--config", config, cwd=self.proj)
        _code, _out, err = run("find", "pricing", "--config", config, "--refresh", cwd=self.proj)
        self.assertIn("registry rebuilt", err)

    def test_no_auto_scan_keeps_the_old_error_and_the_old_file(self):
        config = self.config()
        code, _out, err = run("find", "pricing", "--config", config, "--no-auto-scan", cwd=self.proj)
        self.assertEqual(code, 2)
        self.assertIn("cannot read registry", err)
        self.assertFalse(os.path.exists(self.registry))
        run("find", "pricing", "--config", config, cwd=self.proj)
        old = time.time() - 48 * 3600
        os.utime(self.registry, (old, old))
        _code, _out, err = run("find", "pricing", "--config", config, "--no-auto-scan", cwd=self.proj)
        self.assertNotIn("registry rebuilt", err)

    def test_explicit_registry_is_used_as_is(self):
        explicit = os.path.join(self.tmp, "explicit.json")
        run("scan", "--root", os.path.join(self.cold, "repoX") + "::x", "--out", explicit, cwd=self.proj)
        old = time.time() - 48 * 3600
        os.utime(explicit, (old, old))
        code, out, err = run("find", "pricing", "--registry", explicit, "--config", self.config(), "--json", cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertNotIn("registry rebuilt", err)
        self.assertEqual([r["id"] for r in json.loads(out)["results"]], ["x/pricing-deep"])
        _code, _out, err = run("find", "pricing", "--registry", explicit, "--config", self.config(), "--refresh", cwd=self.proj)
        self.assertIn("registry rebuilt", err)
        self.assertEqual(read_registry(explicit)["built_with"], "config")

    def test_missing_explicit_registry_is_still_an_error(self):
        missing = os.path.join(self.tmp, "none.json")
        code, _out, err = run("find", "pricing", "--registry", missing, "--config", self.config(), cwd=self.proj)
        self.assertEqual(code, 2)
        self.assertIn("cannot read registry", err)
        self.assertFalse(os.path.exists(missing))

    def test_every_registry_command_rebuilds_when_the_registry_is_missing(self):
        config = self.config()
        for command in (["list"], ["overlaps"], ["conflicts"], ["doctor"], ["find", "pricing"]):
            with self.subTest(command=command[0]):
                if os.path.exists(self.registry):
                    os.remove(self.registry)
                code, _out, err = run(*(command + ["--config", config]), cwd=self.proj)
                self.assertEqual(code, 0, err)
                self.assertIn("registry rebuilt", err)

    def test_conflicts_with_a_missing_explicit_registry_keeps_working(self):
        missing = os.path.join(self.tmp, "none.json")
        code, _out, err = run("conflicts", "--registry", missing, "--config", self.config(), cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertNotIn("registry rebuilt", err)
        self.assertFalse(os.path.exists(missing))

    def test_unwritable_registry_location_still_searches(self):
        blocker = write(self.tmp, "blocker", "a file, not a folder")
        config = self.config(registry=os.path.join(blocker, "sub", "registry.json"))
        code, out, err = run("find", "pricing tiers", "--config", config, cwd=self.proj)
        self.assertEqual(code, 0)
        self.assertIn("repoX/pricing-deep", out)
        self.assertIn("cannot write registry", err)

    def test_config_overrides_file_applies_to_the_default_registry(self):
        overrides = write(self.tmp, "my-overrides.json", json.dumps({"repoX/pricing-deep": {"tags": ["zebrafish"]}}))
        config = self.config(overrides=overrides)
        _code, out, _err = run("find", "zebrafish", "--config", config, "--json", cwd=self.proj)
        self.assertEqual(json.loads(out)["results"][0]["id"], "repoX/pricing-deep")

    def test_spanish_request_end_to_end_from_an_unrelated_project(self):
        request = "abro la pagina en el navegador y miro los errores de la consola"
        code, out, err = run("find", request, "--config", self.config(), "--json", cwd=self.other)
        self.assertEqual(code, 0)
        self.assertIn("registry rebuilt", err)
        self.assertEqual(json.loads(out)["results"][0]["id"], "projA/browser-devtools")


class ListCommandTests(Workspace):
    def setUp(self):
        super().setUp()
        hot = os.path.join(self.tmp, "hot")
        cold = os.path.join(self.tmp, "cold2")
        vend = os.path.join(self.tmp, "vend")
        skill(hot, "alpha", "alpha", "Alpha skill " + "x" * 300)
        skill(cold, "beta", "beta", "Beta​ skill with a zero width space")
        skill(vend, "repo/.claude/skills/internal-one", "internal-one", "contributor copy")
        catalog = write(self.tmp, "tools.json", json.dumps({"items": [
            {"name": "Some Tool", "kind": "cli", "what": "A tool.", "impact": "", "activation": "run", "upstream": "https://example.org/t"}]}))
        registry = build_registry([{"path": hot, "source": "h", "hot": True}, {"path": cold, "source": "c"},
                                   {"path": vend, "source_from": "first-child", "platform": "vendor"}])
        registry["entries"] = sorted(registry["entries"] + catalog_entries(catalog), key=lambda e: e["id"])
        self.reg = write(self.tmp, "list-registry.json", json.dumps(registry))

    def rows(self, out):
        return [line for line in out.splitlines() if line and not line.startswith("#")]

    def test_rows_are_sorted_and_show_state_and_short_description(self):
        code, out, _err = run("list", "--registry", self.reg)
        self.assertEqual(code, 0)
        rows = self.rows(out)
        self.assertEqual([r.split("  ")[0] for r in rows], ["c/beta", "catalog/some-tool", "h/alpha"])
        self.assertEqual([re.search(r"\[(\w+)\]", r).group(1) for r in rows], ["cold", "tool", "hot"])
        for row in rows:
            self.assertLessEqual(len(row.split("  ", 2)[2]), 100)
        self.assertNotIn("​", out)
        self.assertRegex(out, r"# 3 skills")

    def test_all_includes_internal_entries(self):
        _code, out, _err = run("list", "--registry", self.reg, "--all")
        self.assertIn("repo/internal-one", out)
        self.assertNotIn("repo/internal-one", run("list", "--registry", self.reg)[1])

    def test_names_prints_a_count_line_then_one_id_per_line(self):
        _code, out, _err = run("list", "--registry", self.reg, "--names")
        lines = out.splitlines()
        self.assertIn("3", lines[0])
        self.assertEqual(lines[1:], ["c/beta", "catalog/some-tool", "h/alpha"])

    def test_source_and_profile_filters(self):
        self.assertEqual(self.rows(run("list", "--registry", self.reg, "--source", "c")[1])[0].split("  ")[0], "c/beta")
        profiles = os.path.join(self.tmp, "profiles")
        write(profiles, "only-h.json", json.dumps({"include": ["h/*"]}))
        _code, out, _err = run("list", "--registry", self.reg, "--profile", "only-h", "--profiles-dir", profiles, "--names")
        self.assertEqual(out.splitlines()[1:], ["h/alpha"])
        code, _out, err = run("list", "--registry", self.reg, "--profile", "nope")
        self.assertEqual(code, 2)

    def test_json_output(self):
        _code, out, _err = run("list", "--registry", self.reg, "--json")
        data = json.loads(out)
        self.assertEqual(data["count"], 3)
        self.assertEqual([s["id"] for s in data["skills"]], ["c/beta", "catalog/some-tool", "h/alpha"])
        self.assertEqual([s["state"] for s in data["skills"]], ["cold", "tool", "hot"])
        self.assertIn("untrusted", data["notice"].lower())
        self.assertLessEqual(max(len(s["description_untrusted"]) for s in data["skills"]), 100)


class FoldAndStopwordTests(unittest.TestCase):
    def test_fold_removes_accents_and_case(self):
        self.assertEqual(fold("CÓDIGO Niño áéíóú ü"), "codigo nino aeiou u")
        self.assertEqual(fold("plain ASCII"), "plain ascii")

    def test_accented_and_plain_forms_match_each_other(self):
        corpus = [{"id": "x/a", "name": "a", "description": "revisa el codigo", "when_to_use": ""},
                  {"id": "x/b", "name": "b", "description": "something else entirely", "when_to_use": ""}]
        self.assertEqual(rank(corpus, "código", k=1)[0][1]["id"], "x/a")
        self.assertEqual(tokenize("código"), tokenize("codigo"))

    def test_spanish_stopwords_are_dropped(self):
        for word in ("el", "la", "los", "las", "de", "del", "para", "que", "con", "por", "mas", "sobre", "hacia"):
            self.assertIn(word, STOPWORDS)
        self.assertEqual(tokenize("el la los de del para"), [])

    def test_english_stopwords_still_work(self):
        self.assertEqual(tokenize("the quick fix"), ["quick", "fix"])


class TranslationTests(unittest.TestCase):
    def exact(self, text):
        return query_terms(text)[0]

    def test_translated_words_join_the_users_own_words(self):
        tokens = self.exact("panel consola navegador")
        for expected in ("dashboard", "console", "browser"):
            self.assertIn(tokenize(expected)[0], tokens)

    def test_translated_words_have_full_weight_not_expansion_weight(self):
        exact, groups = query_terms("consola")
        console = tokenize("console")[0]
        self.assertIn(console, exact)
        self.assertTrue(all(console not in group for group in groups))

    def test_plural_forms_fall_back_to_singular(self):
        self.assertIn(tokenize("console")[0], self.exact("consolas"))
        self.assertIn(tokenize("browser")[0], self.exact("navegadores"))

    def test_accents_do_not_matter(self):
        self.assertEqual(self.exact("depuración"), self.exact("depuracion"))
        self.assertIn(tokenize("debug")[0], self.exact("depurar"))

    def test_multi_word_entries(self):
        self.assertIn(tokenize("database")[0], self.exact("la base de datos"))

    def test_untranslated_spanish_words_are_harmless(self):
        corpus = [{"id": "x/a", "name": "alpha", "description": "parse widgets", "when_to_use": ""}]
        self.assertEqual(rank(corpus, "zzzxyz widgets", k=1)[0][1]["id"], "x/a")

    def test_english_queries_are_not_changed_by_the_table(self):
        self.assertEqual(self.exact("write tests first"), tokenize("write tests first"))

    def test_translation_table_is_large_and_lowercase_ascii(self):
        from orchestrator.search import load_translations
        single, multi = load_translations()
        self.assertGreaterEqual(len(single) + len(multi), 250)
        for key in single:
            self.assertEqual(key, fold(key))


CORPUS = {
    "test-driven-development": "Write a failing test first, then the code that makes it pass. Use when building a new function or feature test first.",
    "systematic-debugging": "Find the root cause of a failing build, crash or unexpected behavior before changing code. Use when something is broken and the cause is unknown.",
    "pull-request-review": "Review a pull request or a diff for correctness and missing tests before it is merged. Use when asked to check changes.",
    "branch-management": "Create, rename and merge git branches and keep history tidy.",
    "pricing-strategy": "Decide pricing tiers, packaging and what to charge for a subscription product. Use when choosing a price.",
    "outbound-email": "Write cold outreach emails and follow-ups to prospects and leads that get replies.",
    "diagram-maker": "Draw architecture, flow and sequence diagrams of a system as one SVG file.",
    "web-page-reader": "Fetch a web page and return its content as markdown. Use when the text of a page is needed.",
    "web-research": "Search the internet by keyword and collect sources. Use when looking up facts or news online.",
    "security-audit": "Audit source code for vulnerabilities such as injection and leaked secrets and propose fixes. Use for security reviews.",
    "requirements-interview": "Ask the user clarifying questions one at a time until the requirements are clear. Use when a request is ambiguous.",
    "session-handoff": "Summarize the current state of the work so the next session can continue without the history.",
    "browser-devtools": "Open a page in the browser and inspect the console, network requests and DOM. Use when debugging a web page front end.",
    "documentation-writer": "Write documentation and architecture decision records explaining how a module works and why a design was chosen.",
    "performance-profiler": "Profile slow code, find the bottleneck and speed it up.",
    "code-simplifier": "Simplify code and remove dead code without changing behavior.",
    "database-migration": "Plan and run safe database schema changes.",
    "invoice-generator": "Create customer invoices and track payments.",
    "spreadsheet-analysis": "Analyze data in spreadsheets, build tables and charts.",
    "calendar-scheduler": "Schedule meetings and manage a calendar.",
    "ci-pipeline": "Set up continuous integration and deployment pipelines.",
    "accessibility-check": "Check a user interface for accessibility problems.",
    "landing-page-copy": "Write marketing copy for landing pages and headlines.",
    "git-commit-messages": "Write clear commit messages.",
    "api-design": "Design REST API endpoints and schemas.",
    "code-explainer": "Explain how existing code works to a newcomer.",
}

# Twelve Spanish requests written for this fixture. A hit means an acceptable skill is in the top three.
SPANISH_PROMPTS = [
    ("la compilacion falla y no entiendo por que, necesito encontrar la causa", {"systematic-debugging"}),
    ("quiero escribir las pruebas primero y despues el codigo de la funcion nueva", {"test-driven-development"}),
    ("revisa mis cambios antes de fusionar la rama", {"pull-request-review"}),
    ("cuanto debo cobrar por mi suscripcion y como armo los planes de precios", {"pricing-strategy"}),
    ("redacta un correo frio para un cliente potencial", {"outbound-email"}),
    ("dibuja un diagrama de la arquitectura del sistema", {"diagram-maker"}),
    ("lee esta pagina y dame el contenido", {"web-page-reader"}),
    ("audita el codigo en busca de vulnerabilidades de seguridad", {"security-audit"}),
    ("hazme preguntas hasta que los requisitos esten claros", {"requirements-interview"}),
    ("voy a cerrar la sesion, resume el estado para la proxima sesion", {"session-handoff"}),
    ("abro la pagina en el navegador y miro los errores de la consola", {"browser-devtools"}),
    ("documenta como funciona el modulo y por que elegimos este diseno", {"documentation-writer"}),
]


class SpanishRecallFixture(unittest.TestCase):
    """Synthetic: a 26-skill English corpus and 12 requests written together. It shows the mapping works; it is not a recall estimate."""

    def entries(self):
        return [{"id": "x/" + name, "name": name, "description": text, "when_to_use": ""} for name, text in CORPUS.items()]

    def test_fixture_shape(self):
        self.assertEqual(len(SPANISH_PROMPTS), 12)
        self.assertEqual(len(CORPUS), 26)
        for _prompt, acceptable in SPANISH_PROMPTS:
            self.assertTrue(acceptable <= set(CORPUS))

    def test_top3_recall_is_at_least_10_of_12(self):
        corpus, misses = self.entries(), []
        for prompt, acceptable in SPANISH_PROMPTS:
            top = [e["name"] for _score, e in rank(corpus, prompt, k=3)]
            if not acceptable & set(top):
                misses.append((prompt, sorted(acceptable), top))
        hits = len(SPANISH_PROMPTS) - len(misses)
        self.assertGreaterEqual(hits, 10, "hits %d/12; misses: %r" % (hits, misses))

    def test_the_same_requests_translated_by_hand_still_work(self):
        # Sanity check of the fixture itself: English phrasing of three of the requests.
        corpus = self.entries()
        self.assertEqual(rank(corpus, "write the tests first and then the code", k=1)[0][1]["name"], "test-driven-development")
        self.assertEqual(rank(corpus, "what should I charge for my subscription", k=1)[0][1]["name"], "pricing-strategy")


class FindCoverageTests(Workspace):
    def make_registry(self, count_fillers=0, extra=()):
        skills = os.path.join(self.tmp, "cov")
        for name, text in extra:
            skill(skills, name, name, text)
        for index in range(count_fillers):
            skill(skills, "filler-%d" % index, "filler-%d" % index, "unrelated topic number %d with words w%d x%d" % (index, index, index * 3))
        path = os.path.join(self.tmp, "cov-registry.json")
        code = run("scan", "--root", skills + "::s", "--out", path)[0]
        self.assertEqual(code, 0)
        return path

    def test_weak_result_prints_the_exact_line_and_json_coverage(self):
        reg = self.make_registry(extra=[("alpha-tool", "parse widgets"), ("beta-tool", "grind gears")])
        _code, out, _err = run("find", "widgets", "--registry", reg)
        self.assertIn(WEAK_LINE, out.splitlines())
        _code, out, _err = run("find", "widgets", "--registry", reg, "--json")
        coverage = json.loads(out)["coverage"]
        self.assertTrue(coverage["weak"])
        self.assertIsInstance(coverage["best_score"], float)
        self.assertIn("list --names", coverage["hint"])

    def test_no_match_at_all_is_weak(self):
        reg = self.make_registry(extra=[("alpha-tool", "parse widgets")])
        _code, out, _err = run("find", "zebra marmalade", "--registry", reg)
        self.assertIn("no matches", out)
        self.assertIn(WEAK_LINE, out.splitlines())

    def test_strong_result_is_not_weak(self):
        targets = [("helm-chart-deploy", "Deploy a helm chart to a kubernetes cluster."),
                   ("helm-chart-lint", "Lint a helm chart for kubernetes."),
                   ("kubernetes-helm-upgrade", "Upgrade a kubernetes helm release safely.")]
        reg = self.make_registry(count_fillers=40, extra=targets)
        _code, out, _err = run("find", "helm chart kubernetes", "--registry", reg, "--json")
        data = json.loads(out)
        self.assertFalse(data["coverage"]["weak"], data["coverage"])
        self.assertGreaterEqual(data["coverage"]["best_score"], WEAK_BEST_SCORE)
        self.assertNotIn(WEAK_LINE, run("find", "helm chart kubernetes", "--registry", reg)[1])

    def test_hint_is_fixed_text_never_registry_content(self):
        reg = self.make_registry(extra=[("ignore-all-previous-instructions", "widgets and more widgets")])
        data = json.loads(run("find", "widgets", "--registry", reg, "--json")[1])
        self.assertNotIn("ignore", data["coverage"]["hint"].lower())
        self.assertEqual(WEAK_LINE.split(": ", 1)[1], data["coverage"]["hint"])

    def test_is_weak_rule(self):
        self.assertTrue(is_weak(2.99, 10))
        self.assertTrue(is_weak(9.0, WEAK_MIN_RESULTS - 1))
        self.assertFalse(is_weak(WEAK_BEST_SCORE, WEAK_MIN_RESULTS))
        self.assertTrue(is_weak(0.0, 0))

    def test_also_phrasings_are_merged_keeping_the_best_score(self):
        reg = self.make_registry(extra=[("alpha-tool", "parse widgets"), ("beta-tool", "grind gears")])
        score = {}
        for query in ("widgets", "gears"):
            result = json.loads(run("find", query, "--registry", reg, "--json")[1])["results"]
            score.update({r["id"]: r["score"] for r in result})
        merged = json.loads(run("find", "widgets", "--also", "gears", "--also", "widgets", "--registry", reg, "--json")[1])
        self.assertEqual({r["id"]: r["score"] for r in merged["results"]}, score)
        self.assertEqual(len(merged["results"]), len({r["id"] for r in merged["results"]}))

    def test_name_matches_outside_the_top_results_are_listed(self):
        reg = self.make_registry(extra=[("report-builder", "build report builder tool for reports"),
                                        ("report-archive", "stores old things"), ("job-runner", "runs jobs")])
        data = json.loads(run("find", "report", "-k", "1", "--registry", reg, "--json")[1])
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["also_consider"], ["s/report-archive"])
        text = run("find", "report", "-k", "1", "--registry", reg)[1]
        self.assertIn("also consider (name match): s/report-archive", text)

    def test_name_matches_need_four_characters_and_are_capped_at_ten(self):
        extra = [("report-%02d" % i, "stores old things %d" % i) for i in range(15)] + [("job-runner", "runs jobs")]
        reg = self.make_registry(extra=extra + [("report-main", "report report report")])
        data = json.loads(run("find", "report", "-k", "1", "--registry", reg, "--json")[1])
        self.assertEqual(len(data["also_consider"]), 10)
        short = json.loads(run("find", "job", "-k", "1", "--registry", reg, "--json")[1])
        self.assertEqual(short["also_consider"], [])

    def test_name_matches_use_translated_tokens(self):
        entries = [{"id": "s/console-tools", "name": "console-tools", "description": "x", "when_to_use": ""},
                   {"id": "s/other", "name": "other", "description": "y", "when_to_use": ""}]
        self.assertEqual(name_matches(entries, ["la consola"], set()), ["s/console-tools"])
        self.assertEqual(name_matches(entries, ["la consola"], {"s/console-tools"}), [])


class SkillAndReleaseTests(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
            return handle.read()

    def test_skill_md_is_short_and_carries_the_coverage_rules(self):
        text = self.read("skills", "skills-orchestrator", "SKILL.md")
        self.assertLessEqual(len(text.splitlines()), 110)
        description = re.search(r"^description:(.*)$", text, re.M).group(1)
        self.assertIn("any language", description)
        self.assertIn("any project", description)
        for phrase in ("Two sources, every time", "Search in English", "Coverage rule (mandatory)", "list --names", "--also",
                       "WEAK MATCH", "injects", "skills belong to the user, not to a project", "--refresh"):
            self.assertTrue(phrase in text, "SKILL.md lacks: " + phrase)
        for gone in ("continue without a skill", "If the best score is weak", "run.py scan` rebuilds"):
            self.assertTrue(gone not in text, "SKILL.md still has: " + gone)

    def test_skill_md_commands_table_lists_the_new_command(self):
        text = self.read("skills", "skills-orchestrator", "SKILL.md")
        self.assertRegex(text, r"\|\s*`list ")

    def test_versions_agree(self):
        self.assertEqual(__version__, "0.1.1")
        self.assertRegex(self.read("pyproject.toml"), r'(?m)^version = "0\.1\.1"$')
        self.assertEqual(json.loads(self.read(".claude-plugin", "plugin.json"))["version"], "0.1.1")
        self.assertTrue("## [0.1.1] - 2026-10-11" in self.read("CHANGELOG.md"), "CHANGELOG lacks the 0.1.1 section")

    def test_docs_describe_every_config_key(self):
        for doc in (("README.md",), ("docs", "ARCHITECTURE.md")):
            text = self.read(*doc)
            for key in ("registry", "extra_roots", "vendor", "catalogs", "exclude_paths", "use_platform_roots",
                        "use_cwd_project_roots", "max_age_hours", "overrides", "profiles_dir"):
                self.assertTrue('"%s"' % key in text, "%s lacks %s" % (doc[-1], key))


if __name__ == "__main__":
    unittest.main()
