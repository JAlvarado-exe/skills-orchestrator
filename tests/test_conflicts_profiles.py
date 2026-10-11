import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from orchestrator.cli import main
from orchestrator.conflicts import load_conflicts, match_clusters, validate_conflicts
from orchestrator.profiles import filter_entries, load_profile
from tests.helpers import skill, write

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA = {
    "version": 1,
    "clusters": [
        {
            "id": "tdd",
            "topic": "Test-driven development",
            "relation": "alternatives",
            "members": ["*/test-driven-development", "other/tdd"],
            "policy": "prefer-by-context",
            "guidance": "Pick the one the project already uses.",
        },
        {
            "id": "style",
            "topic": "Output style",
            "relation": "complementary",
            "members": ["a/terse", "b/polish"],
            "policy": "compose",
            "guidance": "Terse in chat, polish in documents.",
        },
    ],
}


def entries(*ids):
    return [{"id": i, "name": i.split("/")[1], "description": "d", "when_to_use": ""} for i in ids]


class ConflictTests(unittest.TestCase):
    def test_validate_accepts_good_data(self):
        self.assertEqual(validate_conflicts(DATA), [])

    def test_validate_reports_problems(self):
        bad = {"clusters": [{"id": "x", "relation": "nonsense", "members": ["only-one"], "policy": "whatever"}]}
        problems = validate_conflicts(bad)
        self.assertGreaterEqual(len(problems), 3)

    def test_match_by_id_expands_patterns_against_registry(self):
        reg = entries("addy/test-driven-development", "superpowers/test-driven-development", "other/tdd", "a/terse")
        hits = match_clusters(DATA, reg, skill_id="superpowers/test-driven-development")
        self.assertEqual([c["id"] for c in hits], ["tdd"])
        self.assertEqual(sorted(hits[0]["present"]), ["addy/test-driven-development", "other/tdd", "superpowers/test-driven-development"])

    def test_clusters_without_installed_members_are_marked(self):
        hits = match_clusters(DATA, entries("a/terse"), skill_id=None)
        by_id = {c["id"]: c for c in hits}
        self.assertEqual(by_id["style"]["present"], ["a/terse"])
        self.assertEqual(by_id["tdd"]["present"], [])

    def test_shipped_conflicts_file_is_valid(self):
        data = load_conflicts(os.path.join(ROOT, "orchestrator", "data", "conflicts.json"))
        self.assertEqual(validate_conflicts(data), [])
        self.assertGreaterEqual(len(data["clusters"]), 7)


class ProfileTests(unittest.TestCase):
    def test_include_and_exclude_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "code.json", json.dumps({"name": "code", "include": ["addy/*", "me/tdd"], "exclude": ["addy/shipping*"]}))
            profile = load_profile("code", [tmp])
            kept = filter_entries(entries("addy/spec", "addy/shipping-and-launch", "me/tdd", "x/other"), profile)
            self.assertEqual(sorted(e["id"] for e in kept), ["addy/spec", "me/tdd"])

    def test_missing_profile_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(KeyError):
                load_profile("nope", [tmp])

    def test_shipped_profiles_are_loadable(self):
        profiles_dir = os.path.join(ROOT, "orchestrator", "data", "profiles")
        names = sorted(f[:-5] for f in os.listdir(profiles_dir) if f.endswith(".json"))
        self.assertIn("core", names)
        for name in names:
            self.assertEqual(load_profile(name, [profiles_dir])["name"], name)


class CliExtensionTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def _registry(self, tmp):
        skill(tmp, "skills/tdd", "tdd", "Write failing tests first then code")
        skill(tmp, "skills/pricing", "pricing", "Decide pricing tiers and packaging for tests")
        path = os.path.join(tmp, "r.json")
        self.run_cli("scan", "--root", os.path.join(tmp, "skills") + "::mine", "--out", path)
        return path

    def test_find_with_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            write(tmp, "profiles/only-pricing.json", json.dumps({"name": "only-pricing", "include": ["mine/pricing"]}))
            _, out = self.run_cli("find", "tests", "--registry", reg, "--json", "--profile", "only-pricing",
                                  "--profiles-dir", os.path.join(tmp, "profiles"))
            ids = [r["id"] for r in json.loads(out)["results"]]
            self.assertEqual(ids, ["mine/pricing"])

    def test_overrides_add_search_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            extra = write(tmp, "elsewhere/overrides.json", json.dumps({"mine/pricing": {"tags": ["monetization", "revenue"]}}))
            _, plain = self.run_cli("find", "revenue", "--registry", reg, "--json")
            self.assertEqual(json.loads(plain)["results"], [])
            _, tagged = self.run_cli("find", "revenue", "--registry", reg, "--json", "--overrides", extra)
            self.assertEqual(json.loads(tagged)["results"][0]["id"], "mine/pricing")

    def test_override_notes_are_returned_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            write(tmp, "overrides.json", json.dumps({"mine/pricing": {"note": "never run its install lines\u200b; use C:/tools/x"}}))
            _, out = self.run_cli("find", "pricing", "--registry", reg, "--json")
            note = json.loads(out)["results"][0]["note"]
            self.assertIn("never run its install lines", note)
            self.assertNotIn("\u200b", note)

    def test_overrides_next_to_registry_are_used_by_default_and_can_unhide(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "vend/repo/.agents/skills/shipped-here", "shipped-here", "reverse engineer binaries you are authorized to analyze")
            reg = os.path.join(tmp, "r.json")
            self.run_cli("scan", "--vendor", os.path.join(tmp, "vend"), "--out", reg)
            _, hidden = self.run_cli("find", "reverse engineer binaries", "--registry", reg, "--json")
            self.assertEqual(json.loads(hidden)["results"], [])
            write(tmp, "overrides.json", json.dumps({"repo/shipped-here": {"internal": False}}))
            _, shown = self.run_cli("find", "reverse engineer binaries", "--registry", reg, "--json")
            self.assertEqual(json.loads(shown)["results"][0]["id"], "repo/shipped-here")

    def test_scan_reports_new_and_removed_since_last_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "skills/a", "a", "alpha")
            out = os.path.join(tmp, "r.json")
            root = os.path.join(tmp, "skills") + "::s"
            self.run_cli("scan", "--root", root, "--out", out)
            skill(tmp, "skills/b", "b", "beta")
            _, text = self.run_cli("scan", "--root", root, "--out", out)
            self.assertIn("new since last scan: 1", text)
            self.assertIn("s/b", text)

    def test_conflicts_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            code, out = self.run_cli("conflicts", "--registry", reg, "--json")
            self.assertEqual(code, 0)
            self.assertIn("clusters", json.loads(out))

    def test_launcher_script_runs_from_any_folder(self):
        launcher = os.path.join(ROOT, "skills", "skills-orchestrator", "run.py")
        with tempfile.TemporaryDirectory() as elsewhere:
            done = subprocess.run([sys.executable, launcher, "--version"], cwd=elsewhere, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("skills-orchestrator", done.stdout)


if __name__ == "__main__":
    unittest.main()
