"""Recall fixture for `find`: 20 plain-language requests against a synthetic corpus of 30 skills.

The corpus imitates how real skill descriptions are written (a capability sentence plus a "use when"
clause) without copying any real skill. Written before the ranking algorithm was tuned against it.
A hit means at least one acceptable skill is in the top three results.
"""
import unittest

from orchestrator.search import rank

CORPUS = {
    "test-driven-development": "Write a failing test first, then the code that makes it pass, then refactor. Use when implementing a feature or fixing a bug with tests.",
    "systematic-debugging": "Find the root cause of a failing build, crash or unexpected behavior before changing code. Use when something is broken and the cause is unknown.",
    "code-review": "Review a pull request or diff for correctness, security, style and missing tests. Use when asked to look over a change before merge.",
    "spec-driven-development": "Write a specification with goals, constraints and acceptance criteria before building. Use for new features, flows or projects.",
    "planning-and-task-breakdown": "Break an approved spec into small ordered tasks with dependencies. Use when a plan or ticket list is needed.",
    "git-workflow": "Branching, commits, rebasing and release tags. Use when organizing version control history.",
    "security-hardening": "Audit code for vulnerabilities such as injection, broken auth and secrets in source, and fix them. Use for security reviews.",
    "performance-optimization": "Profile slow code, find the bottleneck and speed it up. Use when something is slow or uses too much memory.",
    "documentation-and-adrs": "Write documentation and architecture decision records. Use when recording why a design was chosen.",
    "diagram-design": "Draw architecture, sequence and flow diagrams as a single HTML and SVG file. Use when a diagram is requested.",
    "humanizer": "Rewrite text that sounds machine-written so it reads naturally. Use when prose feels robotic or full of stock phrases.",
    "copywriting": "Write or improve marketing copy for landing pages, headlines and calls to action. Use for homepage and product page text.",
    "pricing": "Decide pricing tiers, packaging and monetization for a software product. Use when choosing what to charge.",
    "cold-email": "Write outbound prospecting emails and follow-up sequences that get replies. Use for cold outreach to leads.",
    "sales-enablement": "Create pitch decks, one-pagers and objection handling documents for sales teams.",
    "founder-board": "Stress-test a business idea with a simulated board of advisors before launch.",
    "founder-competitors": "Map competitors, their pricing and positioning, and what the idea is up against. Use when researching the market.",
    "web-fetch": "Fetch a web page and return its content as markdown, json or a screenshot. Use when current page content is needed.",
    "web-search": "Search the web by keyword and return sources. Use when looking up recent news or facts online.",
    "api-learning": "Learn how a website calls its own backend and save the calls as reusable operations.",
    "reverse-engineering": "Analyze compiled binaries and apps you are authorized to inspect to understand how they work.",
    "knowledge-graph": "Turn code, documents, PDFs and schemas into a queryable knowledge graph. Use to map a large body of material.",
    "code-intelligence": "Index a repository and answer structural questions: who calls this function, what depends on this module.",
    "handoff": "Summarize the current state of work so another session can resume without the history. Use when stopping or switching sessions.",
    "grilling": "Ask the user probing questions one at a time until the requirements are clear. Use when a request is ambiguous.",
    "brainstorming": "Explore intent and design options with the user before building anything creative.",
    "code-simplification": "Simplify code, remove dead code and unnecessary abstractions without changing behavior.",
    "ci-cd-and-automation": "Set up continuous integration, automated test runs and deployment pipelines.",
    "database-migration": "Plan and run safe schema changes and data migrations.",
    "accessibility-review": "Check a user interface against accessibility standards such as contrast, focus and screen reader support.",
}

PROMPTS = [
    ("I want to add a feature but write the tests first", {"test-driven-development"}),
    ("the build keeps failing and I have no idea why", {"systematic-debugging"}),
    ("can you look over my pull request before I merge", {"code-review"}),
    ("we need a spec before building the new checkout flow", {"spec-driven-development"}),
    ("how should I price my software tiers", {"pricing"}),
    ("draft a cold outreach email to a prospect", {"cold-email"}),
    ("draw an architecture diagram of the backend", {"diagram-design"}),
    ("read this web page and give me its content", {"web-fetch"}),
    ("look up recent news about this company online", {"web-search"}),
    ("this paragraph sounds like a robot wrote it", {"humanizer"}),
    ("write homepage copy that converts visitors", {"copywriting"}),
    ("stress test my business idea before launch", {"founder-board"}),
    ("who are my competitors and what do they charge", {"founder-competitors", "pricing"}),
    ("make this function simpler and remove the dead code", {"code-simplification"}),
    ("find everything that calls this function in the repo", {"code-intelligence"}),
    ("turn my documents and PDFs into a knowledge graph", {"knowledge-graph"}),
    ("I am stopping now so summarize the state for the next session", {"handoff"}),
    ("ask me questions until the requirements are clear", {"grilling"}),
    ("set up continuous integration to run tests and deploy", {"ci-cd-and-automation"}),
    ("audit this code for security vulnerabilities", {"security-hardening"}),
]


def entries():
    return [{"id": "x/" + name, "name": name, "description": text, "when_to_use": ""} for name, text in CORPUS.items()]


class RecallTests(unittest.TestCase):
    def test_top3_recall_is_at_least_80_percent(self):
        corpus = entries()
        misses = []
        for prompt, acceptable in PROMPTS:
            top = [e["name"] for _score, e in rank(corpus, prompt, k=3)]
            if not acceptable & set(top):
                misses.append((prompt, sorted(acceptable), top))
        hits = len(PROMPTS) - len(misses)
        recall = hits / float(len(PROMPTS))
        self.assertGreaterEqual(recall, 0.8, "recall %.0f%%; misses: %r" % (recall * 100, misses))

    def test_fixture_shape(self):
        self.assertEqual(len(PROMPTS), 20)
        self.assertEqual(len(CORPUS), 30)
        for _prompt, acceptable in PROMPTS:
            self.assertTrue(acceptable <= set(CORPUS))


if __name__ == "__main__":
    unittest.main()
