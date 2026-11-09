"""Recall for cold skills: `find` must surface the right skill for plain requests in new domains.

The corpus is synthetic: each description imitates how a real skill is written (a capability sentence plus a
"use when" clause) without copying one. Requests in Spanish are included where the vocabulary table covers them.
"""
import os
import unittest

from orchestrator.conflicts import load_conflicts, match_clusters, validate_conflicts
from orchestrator.profiles import filter_entries, load_profile
from orchestrator.search import rank

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "orchestrator", "data")

CORPUS = {
    "scrapling-official": "Scrape web pages with HTTP requests, a rendering browser and spiders, and return clean markdown or structured data. Use when extracting content from websites.",
    "moli-websearch": "Search the web by keyword and return ranked sources. Use when looking up recent facts online.",
    "voicestudio": "Generate local speech with saved voices, transcribe audio and automate narration through a local REST API. Use for offline text to speech.",
    "earshot": "Transcribe recorded audio files to text with a local model that runs offline. Use when a recording needs a transcript.",
    "para-memory-files": "Use a file-based memory system to store, retrieve and organize durable knowledge across agent sessions. Use when an agent must remember facts later.",
    "memory-leak-debugging": "Diagnose and fix memory leaks in JavaScript applications. Use when memory usage keeps growing.",
    "social": "Create, schedule and optimize social media content for LinkedIn, Instagram and other networks. Use when planning posts.",
    "ig-plan": "Plan an Instagram content calendar with themes and formats. Use for a posting schedule.",
    "operator-approval-loop": "Operator approval contract for agent-drafted outbound messages: hashed drafts, explicit decisions, durable delivery. Use when a message must be approved before it is sent.",
    "cold-email": "Write B2B cold outbound emails and follow-ups that get replies. Use for prospecting.",
    "founder-brand": "Name the business, with the trademark, domain and handle checks to run before choosing a name, and write the brand voice. Use when picking a brand or domain name.",
    "domain-modeling": "Build and sharpen the domain model of a codebase and its glossary. Use when discussing code terminology.",
    "antislop": "Rules that stop generic AI slop in copy, design and code. Use when output sounds machine-made or generic.",
    "humanizer": "Rewrite machine-sounding text so it reads naturally. Use when prose feels robotic.",
    "copywriting": "Write or improve marketing copy for landing pages and headlines. Use for homepage text.",
    "regex-vs-llm-structured-text": "Decide between regular expressions and a language model for parsing structured text. Use when extracting fields from text.",
}

# (request, names of acceptable first results)
QUERIES = [
    ("scrape a website to markdown", {"scrapling-official"}),
    ("offline text to speech", {"voicestudio"}),
    ("agent memory", {"para-memory-files"}),
    ("social media scheduling draft", {"social", "ig-plan"}),
    ("approval before sending outbound message", {"operator-approval-loop"}),
    ("domain name availability research", {"founder-brand"}),
    ("transcribe audio offline", {"earshot", "voicestudio"}),
    ("anti AI slop copywriting", {"antislop"}),
    ("transcribir audio sin conexion", {"earshot", "voicestudio"}),
    ("memoria de agentes", {"para-memory-files"}),
    ("raspar una pagina web a markdown", {"scrapling-official"}),
]

NEW_CLUSTERS = {
    "agent-memory": "prefer-by-context",
    "voice-audio": "prefer-by-context",
    "social-publishing": "owner-pin",
    "anti-slop-writing": "compose",
    "marketing-skills": "prefer-by-context",
    "output-approval": "owner-pin",
    "agent-security": "compose",
    "trading": "owner-pin",
}


def registry():
    return [{"id": "cold/" + name, "name": name, "description": text, "when_to_use": ""} for name, text in CORPUS.items()]


class ColdSkillRecallTests(unittest.TestCase):
    def test_find_returns_the_expected_cold_skill_first(self):
        entries = registry()
        for query, expected in QUERIES:
            with self.subTest(query=query):
                ranked = rank(entries, query, k=3)
                self.assertTrue(ranked, "no result for %r" % query)
                self.assertIn(ranked[0][1]["name"], expected)


class ColdClusterTests(unittest.TestCase):
    def setUp(self):
        self.data = load_conflicts(os.path.join(DATA, "conflicts.json"))

    def test_shipped_clusters_are_valid_and_new_ones_keep_their_policy(self):
        self.assertEqual(validate_conflicts(self.data), [])
        by_id = {c["id"]: c for c in self.data["clusters"]}
        for cluster_id, policy in NEW_CLUSTERS.items():
            self.assertEqual(by_id[cluster_id]["policy"], policy, cluster_id)

    def test_web_access_covers_scraping_and_forbids_bot_detection_evasion(self):
        reg = [{"id": "tools/scrapling-official"}, {"id": "tools/agent-desktop"}, {"id": "x/browser-use"}]
        hits = match_clusters(self.data, reg, skill_id="tools/scrapling-official")
        self.assertIn("web-access", [c["id"] for c in hits])
        web = [c for c in hits if c["id"] == "web-access"][0]
        self.assertEqual(len(web["present"]), 3)
        self.assertIn("bot detection", web["guidance"])

    def test_marketing_pack_cluster_prefers_the_installed_copy(self):
        reg = [{"id": "marketingskills/copywriting"}, {"id": "claude-user/copywriting"}, {"id": "marketingskills/social"}]
        hits = {c["id"]: c for c in match_clusters(self.data, reg)}
        self.assertEqual(len(hits["marketing-skills"]["present"]), 3)
        self.assertIn("claude-user", hits["marketing-skills"]["guidance"])

    def test_approval_skill_belongs_to_the_social_and_approval_clusters(self):
        hits = match_clusters(self.data, [{"id": "ecc/operator-approval-loop"}], skill_id="ecc/operator-approval-loop")
        self.assertEqual({"social-publishing", "output-approval"}, {c["id"] for c in hits})


class ColdProfileTests(unittest.TestCase):
    def test_profiles_include_the_new_domains(self):
        directory = os.path.join(DATA, "profiles")
        cases = {
            "business": "marketingskills/seo-audit",
            "docs": "anti-slop/antislop-copywriting",
            "research": "tools/scrapling-official",
        }
        for name, skill_id in cases.items():
            with self.subTest(profile=name):
                kept = filter_entries([{"id": skill_id}, {"id": "x/unrelated"}], load_profile(name, [directory]))
                self.assertEqual([e["id"] for e in kept], [skill_id])


if __name__ == "__main__":
    unittest.main()
