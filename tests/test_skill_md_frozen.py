"""The safety-bearing sections of SKILL.md change only on purpose: Precedence, Never and the safe install steps.

The hashes are of each section's text as of 0.1.2. A change to these sections must be deliberate and reviewed;
update the hash in the same commit and say why in its message.
"""
import hashlib
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = {
    "## Precedence": "7ca25210791d5fc96c724cdca183e288639502d0d7e428d846180cec1719b8ec",
    "## Never": "0400bc8139262de4cb41dd3ec3bc4355905eda830e1a1318f978f348c91a26e6",
    "## Adding a skill or tool": "f282357782d31fb735fb78489071acd66b8f61bff7f9f9f9afd08705cdcb31f0",
}
MAX_LINES = 110


def sections():
    with open(os.path.join(ROOT, "skills", "skills-orchestrator", "SKILL.md"), encoding="utf-8") as handle:
        text = handle.read()
    return text, {part.splitlines()[0]: part.strip() for part in re.split(r"(?m)^(?=## )", text) if part.startswith("## ")}


class FrozenSectionTests(unittest.TestCase):
    def test_safety_sections_are_unchanged(self):
        _text, found = sections()
        for heading, digest in FROZEN.items():
            with self.subTest(section=heading):
                self.assertIn(heading, found)
                self.assertEqual(hashlib.sha256(found[heading].encode("utf-8")).hexdigest(), digest)

    def test_skill_md_stays_within_its_length(self):
        text, _found = sections()
        self.assertLessEqual(len(text.splitlines()), MAX_LINES)

    def test_skill_md_documents_the_feedback_command(self):
        text, _found = sections()
        self.assertIn("run.py used <id>", text)
        self.assertIn("NO CONFIDENT MATCH", text)
        self.assertNotIn("WEAK MATCH", text)


if __name__ == "__main__":
    unittest.main()
