"""Registry format v2 (stored tokens, copy groups), upgrade of older registries on load, and the hook's time budget."""
import contextlib
import io
import json
import os
import statistics
import tempfile
import time
import unittest

from orchestrator.cli import main
from orchestrator.hook import select
from orchestrator.scan import REGISTRY_VERSION, build_registry, upgrade_registry
from orchestrator.search import tokenize, tokenizer_id
from tests.helpers import skill, write

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec "
         "romeo sierra tango uniform victor whiskey xray yankee zulu amber basalt cedar dune ember fjord garnet harbor "
         "iris jade kelp lagoon meadow nectar onyx prairie quartz reef saffron tundra umber valley willow").split()


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, out.getvalue()


class FormatTests(unittest.TestCase):
    def test_a_new_registry_is_version_2_with_tokens_and_copy_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "a/pricing", "pricing", "Decide pricing tiers.")
            skill(tmp, "b/pricing", "pricing", "Decide pricing tiers.", body="Body.\r\n")
            registry = build_registry([{"path": tmp, "source_from": "first-child"}])
            self.assertEqual(registry["version"], REGISTRY_VERSION)
            self.assertEqual(registry["tokenizer"], tokenizer_id())
            entries = registry["entries"]
            self.assertEqual({e["dup_group"] for e in entries}, {"a/pricing"})
            self.assertEqual(entries[0]["tok"]["name"], tokenize("pricing"))
            self.assertIn(tokenize("tiers")[0], entries[0]["tok"]["body"])

    def test_same_name_with_different_content_stays_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "a/tdd", "tdd", "Test-driven development: red, green, refactor.")
            skill(tmp, "b/tdd", "tdd", "Tabletop dungeon design for game masters.", body="Rooms, traps and treasure.\n")
            groups = {e["dup_group"] for e in build_registry([{"path": tmp, "source_from": "first-child"}])["entries"]}
            self.assertEqual(len(groups), 2)

    def test_a_version_1_registry_is_upgraded_in_memory_and_searched(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"version": 1, "entries": [
                {"id": "s/pricing", "name": "pricing", "description": "Decide pricing tiers and packaging.", "when_to_use": "",
                 "path": "/x/SKILL.md", "paths": [], "variants": [], "sha256": "ab"}] +
                [{"id": "s/f%d" % i, "name": "f%d" % i, "description": "gardens %d" % i, "when_to_use": "", "path": "/y",
                  "paths": [], "variants": [], "sha256": str(i)} for i in range(10)]}
            reg = write(tmp, "old.json", json.dumps(old))
            code, out = run("find", "pricing tiers and packaging", "--registry", reg, "--json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["results"][0]["id"], "s/pricing")
            upgraded = upgrade_registry(json.loads(json.dumps(old)))
            self.assertEqual(upgraded["entries"][0]["dup_group"], "s/pricing")
            self.assertEqual(upgraded["entries"][0]["norm_sha"], "ab")

    def test_stored_tokens_from_another_tokenizer_are_recomputed(self):
        registry = {"version": 2, "tokenizer": "other", "entries": [
            {"id": "s/x", "name": "pricing", "description": "Decide tiers.", "when_to_use": "", "tok": {"name": ["stale"], "body": []}}]}
        upgraded = upgrade_registry(registry)
        self.assertEqual(upgraded["entries"][0]["tok"]["name"], tokenize("pricing"))
        self.assertEqual(upgraded["tokenizer"], tokenizer_id())

    def test_an_automatic_rebuild_replaces_a_version_1_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "lib")
            skill(lib, "pricing", "pricing", "Decide pricing tiers.")
            reg = os.path.join(tmp, "registry.json")
            config = write(tmp, "c.json", json.dumps({"registry": reg, "extra_roots": [{"path": lib, "source_from": "fixed"}],
                                                      "use_platform_roots": False, "use_cwd_project_roots": False}))
            run("scan", "--config", config)
            with open(reg, encoding="utf-8") as handle:
                data = json.load(handle)
            data["version"] = 1
            write(tmp, "registry.json", json.dumps(data))
            run("list", "--config", config)
            with open(reg, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["version"], REGISTRY_VERSION)


class TimingTests(unittest.TestCase):
    def test_the_hook_selection_takes_under_150_ms_on_1000_entries(self):
        entries = []
        for number in range(1000):
            words = [WORDS[(number * 7 + k * 13) % len(WORDS)] for k in range(40)]
            name = "%s-%s-%d" % (WORDS[number % len(WORDS)], WORDS[(number // len(WORDS)) % len(WORDS)], number)
            entries.append({"id": "lib/" + name, "name": name, "source": "lib", "description": " ".join(words) + ".",
                            "when_to_use": "", "path": "/lib/%s/SKILL.md" % name, "paths": [], "variants": [],
                            "sha256": "%064x" % number})
        registry = upgrade_registry({"version": 2, "entries": entries})
        with tempfile.TemporaryDirectory() as tmp:
            reg = write(tmp, "registry.json", json.dumps(registry))
            config = write(tmp, "c.json", json.dumps({"registry": reg, "use_platform_roots": False, "use_cwd_project_roots": False,
                                                      "state_dir": os.path.join(tmp, "state")}))
            prompt = "the alpha bravo charlie pipeline fails with a delta echo error in foxtrot"
            select(prompt, tmp, config_path=config, registry_path=reg, session_id="warm")
            times = []
            for run_number in range(5):
                start = time.perf_counter()
                select(prompt, tmp, config_path=config, registry_path=reg, session_id="t%d" % run_number)
                times.append(time.perf_counter() - start)
        median = statistics.median(times)
        self.assertLess(median, 0.150, "median %.0f ms" % (median * 1000))


if __name__ == "__main__":
    unittest.main()
