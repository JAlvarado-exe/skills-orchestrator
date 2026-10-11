import os
import tempfile
import unittest

from orchestrator.skillfile import parse_frontmatter, read_skill
from tests.helpers import write


class ParseFrontmatterTests(unittest.TestCase):
    def test_plain_fields(self):
        fields, ok = parse_frontmatter("---\nname: tdd\ndescription: Write tests first.\n---\nBody")
        self.assertTrue(ok)
        self.assertEqual(fields["name"], "tdd")
        self.assertEqual(fields["description"], "Write tests first.")

    def test_quoted_values_keep_colons(self):
        fields, ok = parse_frontmatter('---\nname: "a"\ndescription: "Use when: tests fail"\n---\n')
        self.assertTrue(ok)
        self.assertEqual(fields["description"], "Use when: tests fail")

    def test_unquoted_colon_is_lenient(self):
        fields, ok = parse_frontmatter("---\nname: x\ndescription: Use when: tests fail\n---\n")
        self.assertTrue(ok)
        self.assertEqual(fields["description"], "Use when: tests fail")

    def test_folded_block_scalar(self):
        text = "---\nname: x\ndescription: >\n  first line\n  second line\nother: y\n---\n"
        fields, ok = parse_frontmatter(text)
        self.assertTrue(ok)
        self.assertEqual(fields["description"], "first line second line")
        self.assertEqual(fields["other"], "y")

    def test_literal_block_scalar_keeps_newlines(self):
        fields, _ = parse_frontmatter("---\nname: x\ndescription: |\n  one\n  two\n---\n")
        self.assertEqual(fields["description"], "one\ntwo")

    def test_plain_multiline_continuation(self):
        fields, _ = parse_frontmatter("---\nname: x\ndescription: starts here\n  and continues\n---\n")
        self.assertEqual(fields["description"], "starts here and continues")

    def test_list_values(self):
        fields, _ = parse_frontmatter("---\nname: x\nallowed-tools:\n  - Read\n  - Grep\n---\n")
        self.assertEqual(fields["allowed-tools"], ["Read", "Grep"])

    def test_crlf_and_bom(self):
        text = "﻿---\r\nname: x\r\ndescription: crlf ok\r\n---\r\nbody"
        fields, ok = parse_frontmatter(text)
        self.assertTrue(ok)
        self.assertEqual(fields["description"], "crlf ok")

    def test_missing_frontmatter(self):
        fields, ok = parse_frontmatter("# Just a heading\n\ntext")
        self.assertFalse(ok)
        self.assertEqual(fields, {})

    def test_unterminated_frontmatter(self):
        fields, ok = parse_frontmatter("---\nname: x\ndescription: never closed\n")
        self.assertFalse(ok)


class ReadSkillTests(unittest.TestCase):
    def test_reads_metadata_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "tdd/SKILL.md", "---\nname: tdd\ndescription: Red green refactor.\n---\nBody\n")
            info = read_skill(path)
            self.assertEqual(info["name"], "tdd")
            self.assertEqual(info["description"], "Red green refactor.")
            self.assertTrue(info["frontmatter_ok"])
            self.assertEqual(len(info["sha256"]), 64)

    def test_falls_back_to_directory_name_and_first_paragraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "my-skill/SKILL.md", "# Title\n\nFirst paragraph here.\n\nSecond.\n")
            info = read_skill(path)
            self.assertEqual(info["name"], "my-skill")
            self.assertEqual(info["description"], "First paragraph here.")
            self.assertFalse(info["frontmatter_ok"])

    def test_when_to_use_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "s/SKILL.md", "---\nname: s\ndescription: d\nwhen_to_use: trigger words\n---\n")
            self.assertEqual(read_skill(path)["when_to_use"], "trigger words")


if __name__ == "__main__":
    unittest.main()
