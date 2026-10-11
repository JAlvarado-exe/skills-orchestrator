import os
import subprocess
import tempfile
import unittest

from orchestrator.scan import build_registry, count_skill_files, find_skill_files
from tests.helpers import skill, write


def independent_count(root, skip=("node_modules", ".git")):
    total = 0
    for _dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        total += sum(1 for f in files if f == "SKILL.md")
    return total


class FindSkillFilesTests(unittest.TestCase):
    def test_finds_nested_and_skips_vendor_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "a", "a", "alpha")
            skill(tmp, "group/b", "b", "beta")
            skill(tmp, "node_modules/x", "x", "ignored")
            skill(tmp, ".git/y", "y", "ignored")
            found = sorted(os.path.relpath(p, tmp).replace("\\", "/") for p in find_skill_files(tmp))
            self.assertEqual(found, ["a/SKILL.md", "group/b/SKILL.md"])

    def test_count_matches_independent_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(7):
                skill(tmp, "s%d" % i, "s%d" % i, "d%d" % i)
            skill(tmp, "deep/er/est", "deep", "d")
            self.assertEqual(count_skill_files(tmp), independent_count(tmp))

    def test_link_loop_does_not_hang(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "a", "a", "alpha")
            link = os.path.join(tmp, "a", "loop")
            try:
                os.symlink(tmp, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                if os.name != "nt":
                    self.skipTest("symlinks not permitted here")
                # Windows without Developer Mode: a junction needs no privilege
                made = subprocess.run(["cmd", "/c", "mklink", "/J", link, tmp], capture_output=True)
                if made.returncode != 0:
                    self.skipTest("neither symlink nor junction could be created")
            try:
                self.assertEqual(len(find_skill_files(tmp)), 1)
            finally:
                # remove the link itself, never the directory it points to
                if os.path.islink(link):
                    os.unlink(link)
                elif os.path.exists(link):
                    os.rmdir(link)


class BuildRegistryTests(unittest.TestCase):
    def test_entry_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "tdd", "tdd", "Write tests first.")
            reg = build_registry([{"path": tmp, "source": "mine", "platform": "claude", "hot": True}])
            self.assertEqual(len(reg["entries"]), 1)
            entry = reg["entries"][0]
            self.assertEqual(entry["id"], "mine/tdd")
            self.assertEqual(entry["name"], "tdd")
            self.assertTrue(entry["hot"])
            self.assertGreater(entry["est_tokens"], 0)
            self.assertTrue(os.path.isabs(entry["path"]))

    def test_identical_content_is_one_entry_with_two_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "one", "same", "identical text")
            skill(tmp, "configs/copy", "same", "identical text")
            reg = build_registry([{"path": tmp, "source": "repo"}])
            self.assertEqual(len(reg["entries"]), 1)
            self.assertEqual(len(reg["entries"][0]["paths"]), 2)

    def test_same_name_different_content_gets_distinct_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "one", "tdd", "version one")
            skill(tmp, "two", "tdd", "version two")
            reg = build_registry([{"path": tmp, "source": "repo"}])
            ids = sorted(e["id"] for e in reg["entries"])
            self.assertEqual(len(ids), 2)
            self.assertEqual(len(set(ids)), 2)

    def test_first_child_source_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "repo-a/skills/x", "x", "d")
            skill(tmp, "repo-b/skills/y", "y", "d")
            reg = build_registry([{"path": tmp, "source_from": "first-child"}])
            self.assertEqual(sorted(e["source"] for e in reg["entries"]), ["repo-a", "repo-b"])

    def test_plugin_cache_source_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "market/plugin-x/1.0.0/skills/s", "s", "d")
            reg = build_registry([{"path": tmp, "source_from": "plugin-cache"}])
            self.assertEqual(reg["entries"][0]["source"], "plugin:plugin-x")

    def test_bad_frontmatter_still_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "broken/SKILL.md", "no frontmatter at all\n")
            skill(tmp, "good", "good", "fine")
            reg = build_registry([{"path": tmp, "source": "s"}])
            self.assertEqual(len(reg["entries"]), 2)
            flags = {e["name"]: e["frontmatter_ok"] for e in reg["entries"]}
            self.assertFalse(flags["broken"])
            self.assertTrue(flags["good"])

    def test_missing_root_is_reported_not_fatal(self):
        reg = build_registry([{"path": os.path.join(tempfile.gettempdir(), "does-not-exist-xyz"), "source": "s"}])
        self.assertEqual(reg["entries"], [])
        self.assertEqual(len(reg["missing_roots"]), 1)

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("b", "a", "c"):
                skill(tmp, n, n, "d " + n)
            first = build_registry([{"path": tmp, "source": "s"}])["entries"]
            second = build_registry([{"path": tmp, "source": "s"}])["entries"]
            self.assertEqual(first, second)
            self.assertEqual([e["name"] for e in first], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
