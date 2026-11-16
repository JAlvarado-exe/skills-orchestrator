"""Retrieval v2: weighted fields, generic words, policy (blocked/preferred), copies, labels and intent."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from orchestrator.cli import main
from orchestrator.hook import run_hook
from orchestrator.intent import classify
from orchestrator.policy import matches
from orchestrator.retrieval import copy_priority, retrieve
from orchestrator.search import rank
from tests.helpers import skill, write

FILLERS = [("filler-%d" % i, "Unrelated topic %d about gardens, recipes and travel plans." % i) for i in range(20)]


def entry(name, description, source="s", **extra):
    data = {"id": "%s/%s" % (source, name), "name": name, "description": description, "when_to_use": "", "source": source}
    data.update(extra)
    return data


def corpus(*items):
    return [entry(n, d) for n, d in FILLERS] + list(items)


def run(*argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    previous = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
    finally:
        os.chdir(previous)
    return code, out.getvalue(), err.getvalue()


class RankingTests(unittest.TestCase):
    def test_generic_words_do_not_decide_the_result(self):
        pool = corpus(entry("token-saver", "Wraps every build, run, file and code command and its output for the user."),
                      entry("browser-console", "Read console errors of a web page in the browser."))
        top = retrieve(pool, ["run the build and check the code output file, then read the browser console errors"])
        self.assertEqual(top[0]["entry"]["name"], "browser-console")
        self.assertNotIn("token-saver", [r["entry"]["name"] for r in top])

    def test_a_word_in_the_name_outweighs_the_same_word_in_a_long_description(self):
        pool = corpus(entry("invoice-chaser", "Send reminders."),
                      entry("mailer", "Sends many kinds of messages, newsletters, receipts, invoice copies and alerts."))
        self.assertEqual(rank(pool, "invoice reminders", k=1)[0][1]["name"], "invoice-chaser")

    def test_tags_are_searched_as_their_own_field(self):
        pool = corpus(entry("pricing", "Decide tiers.", tags=["monetization", "revenue"]))
        self.assertEqual(retrieve(pool, ["monetization and revenue"])[0]["entry"]["name"], "pricing")
        self.assertEqual(retrieve(corpus(entry("pricing", "Decide tiers.")), ["monetization and revenue"]), [])

    def test_a_long_pasted_text_needs_more_shared_terms(self):
        pasted = " ".join("word%d" % i for i in range(60)) + " console errors"
        pool = corpus(entry("browser-console", "Read console errors of a web page in the browser."))
        self.assertEqual(retrieve(pool, [pasted]), [])
        self.assertTrue(retrieve(pool, ["console errors in the browser page"]))

    def test_results_below_the_relative_floor_are_dropped(self):
        pool = corpus(entry("helm-deploy", "Deploy a helm chart to a kubernetes cluster with values and rollbacks."),
                      entry("cluster-notes", "Notes about a kubernetes meetup."))
        names = [r["entry"]["name"] for r in retrieve(pool, ["deploy a helm chart with rollbacks to kubernetes"])]
        self.assertEqual(names, ["helm-deploy"])


class PolicyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        lib = os.path.join(self.tmp, "lib")
        skill(lib, "router-hub/model-router", "model-router", "Route prompts to other model providers when the quota runs out.")
        skill(lib, "router-hub/quota-tracker", "quota-tracker", "Track usage quota and weekly limits of model providers.")
        skill(lib, "good/usage-report", "usage-report", "Report weekly usage limits of the plan and the quota left.")
        for name, text in FILLERS:
            skill(lib, "fill/" + name, name, text)
        self.registry = os.path.join(self.tmp, "state", "registry.json")
        self.config = write(self.tmp, "config.json", json.dumps({
            "registry": self.registry, "vendor": [lib], "use_platform_roots": False, "use_cwd_project_roots": False,
            "blocked": ["router-hub"], "session_memory": False, "feedback": False}))
        self.assertEqual(run("scan", "--config", self.config)[0], 0)

    def ids(self, out):
        return [r["id"] for r in json.loads(out)["results"]]

    def test_blocked_entries_never_appear_in_find_list_or_the_hook(self):
        query = "track the weekly usage quota of the model providers"
        _c, out, _e = run("find", query, "--config", self.config, "--json")
        self.assertTrue(all(not i.startswith("router-hub/") for i in self.ids(out)), out)
        _c, out, _e = run("list", "--names", "--config", self.config)
        self.assertNotIn("router-hub/", out)
        with contextlib.redirect_stderr(io.StringIO()):
            hook = run_hook(json.dumps({"prompt": query}), config_path=self.config)
        self.assertNotIn("router-hub/", hook)
        self.assertIn("good/usage-report", hook)

    def test_all_shows_blocked_entries_in_find_and_list(self):
        _c, out, _e = run("find", "track the weekly usage quota of the model providers", "--config", self.config, "--json", "--all")
        self.assertIn("router-hub/quota-tracker", self.ids(out))
        _c, out, _e = run("list", "--names", "--all", "--config", self.config)
        self.assertIn("router-hub/quota-tracker", out)

    def test_blocked_entries_never_appear_in_eval(self):
        cases = write(self.tmp, "cases.json", json.dumps([{"id": "q", "prompt": "track the weekly usage quota of the model providers",
                                                           "expected": ["good/usage-report"], "forbidden": ["router-hub/quota-tracker"]}]))
        _c, out, _e = run("eval", cases, "--config", self.config, "--json")
        self.assertEqual(json.loads(out)["summary"]["forbidden_shown"], 0)

    def test_a_project_file_adds_blocked_patterns(self):
        project = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(project, ".git"))
        write(project, ".skills-orchestrator.json", json.dumps({"blocked": ["good/*"], "unknown": 1}))
        _c, out, _e = run("find", "weekly usage limits of the plan and quota", "--config", self.config, "--json", cwd=project)
        self.assertNotIn("good/usage-report", self.ids(out))
        _c, out, _e = run("find", "weekly usage limits of the plan and quota", "--config", self.config, "--json", cwd=self.tmp)
        self.assertIn("good/usage-report", self.ids(out))

    def test_patterns_match_ids_sources_and_globs_without_case(self):
        e = {"id": "OmniRoute/cli-tools", "source": "OmniRoute", "sources": ["OmniRoute"]}
        self.assertTrue(matches(e, ["omniroute"]))
        self.assertTrue(matches(e, ["omniroute/*"]))
        self.assertTrue(matches(e, ["OmniRoute/cli-tools"]))
        self.assertFalse(matches(e, ["omni"]))

    def test_preferred_entries_move_up_but_never_past_the_gates(self):
        pool = corpus(entry("debug-a", "Debug a failing test and read the stack trace."),
                      entry("debug-b", "Debug a failing test and read the stack trace carefully."))
        plain = [r["entry"]["name"] for r in retrieve(pool, ["debug a failing test stack trace"])]
        boosted = [r["entry"]["name"] for r in retrieve(pool, ["debug a failing test stack trace"], preferred=["s/" + plain[1]])]
        self.assertEqual(boosted[0], plain[1])
        self.assertEqual(retrieve(pool, ["gardening schedule"], preferred=["s/debug-a"]), [])


class CopyTests(unittest.TestCase):
    def test_near_copies_collapse_into_the_best_placed_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "## Steps\n\n" + "".join("%d. Step number %d of the tiered workflow.\n" % (i, i) for i in range(30))
            skill(tmp, "user/flow-steps", "flow-steps", "Tiered workflow with success criteria and cost routing.", body=body)
            skill(tmp, "vendor/old/flow-steps", "flow-steps", "Tiered workflow with success criteria and cost routing.",
                  body=body.replace("Step number 3 ", "Step 3 "))
            skill(tmp, "vendor/other/flow-steps", "flow-steps", "Unrelated steps for a dance routine.", body="Different.\n")
            for name, text in FILLERS:
                skill(tmp, "user/" + name, name, text)
            reg = os.path.join(tmp, "r.json")
            config = write(tmp, "c.json", json.dumps({"registry": reg, "extra_roots": [{"path": os.path.join(tmp, "user"),
                                                                                       "source_from": "fixed"}],
                                                      "vendor": [os.path.join(tmp, "vendor")], "use_platform_roots": False,
                                                      "use_cwd_project_roots": False, "feedback": False}))
            run("scan", "--config", config)
            _c, out, _e = run("find", "tiered workflow success criteria cost routing", "--config", config, "--json")
            results = json.loads(out)["results"]
            self.assertEqual([r["id"] for r in results], ["user/flow-steps"])
            self.assertEqual(results[0]["copies"], 1)
            _c, text, _e = run("find", "tiered workflow success criteria cost routing", "--config", config)
            self.assertIn("(+1 copies)", text)

    def test_copy_priority_prefers_hot_then_user_then_project_then_folders_then_vendor_then_tools(self):
        order = [{"id": "z/hot", "hot": True}, {"id": "z/user", "platforms": ["claude"]}, {"id": "z/proj", "source": "project:x"},
                 {"id": "z/extra"}, {"id": "z/vendor", "platforms": ["vendor"]}, {"id": "z/tool", "kind": "tool"}]
        self.assertEqual(sorted(reversed(order), key=copy_priority), order)


class OutputAndIntentTests(unittest.TestCase):
    def test_find_marks_skills_and_tools_and_prints_the_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = write(tmp, "catalog.json", json.dumps({"items": [
                {"name": "graph-index", "kind": "mcp", "upstream": "https://example.org/g",
                 "what": "Index a repository into a knowledge graph of callers and modules.", "activation": "Exploring code."}]}))
            skill(tmp, "skills/codebase-map", "codebase-map", "Map modules, callers and the dependency graph of a repository.")
            for name, text in FILLERS:
                skill(tmp, "skills/" + name, name, text)
            reg = os.path.join(tmp, "r.json")
            run("scan", "--root", os.path.join(tmp, "skills") + "::s", "--catalog", catalog, "--out", reg)
            _c, out, _e = run("find", "explore the callers and modules graph of this repository", "--registry", reg)
            self.assertIn("# intent: research", out)
            self.assertIn("catalog/graph-index  TOOL tool", out)
            self.assertIn("s/codebase-map  SKILL cold", out)
            data = json.loads(run("find", "explore the callers and modules graph of this repository", "--registry", reg, "--json")[1])
            self.assertEqual(data["intent"], "research")
            self.assertEqual({r["label"] for r in data["results"]}, {"TOOL", "SKILL"})

    def test_intents_from_english_and_spanish_keywords(self):
        cases = {"the checkout crashes with a stack trace": "debug", "revisa este diff antes de fusionar": "review",
                 "implement the export endpoint": "build", "investiga a los competidores del mercado": "research",
                 "redacta un correo para el cliente": "write", "help me decide between these options": "decide",
                 "the production server is down, restore the backup": "operate", "hola, como estas": "none"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify(text)[0], expected)

    def test_the_detected_profile_reorders_and_never_hides(self):
        profile = {"include": ["s/systematic-debugging"]}
        pool = corpus(entry("systematic-debugging", "Find the root cause of a failing test."),
                      entry("root-cause-notes", "Find the root cause of a failing test quickly."))
        names = [r["entry"]["name"] for r in retrieve(pool, ["find the root cause of the failing test"], profile=profile)]
        self.assertEqual(names[0], "systematic-debugging")
        self.assertIn("root-cause-notes", names)


if __name__ == "__main__":
    unittest.main()
