import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import check_english  # noqa: E402
import check_privacy  # noqa: E402
from tests.helpers import write  # noqa: E402


class EnglishCheckTests(unittest.TestCase):
    def test_flags_spanish_prose(self):
        hits = check_english.scan_text("Esta es una herramienta para los agentes y el usuario.")
        self.assertTrue(hits)

    def test_plain_english_passes(self):
        self.assertEqual(check_english.scan_text("This tool helps agents find the right skill for a task."), [])

    def test_ignores_single_ambiguous_words(self):
        self.assertEqual(check_english.scan_text("The con artist took a pro rata share."), [])


class PrivacyCheckTests(unittest.TestCase):
    def test_flags_user_paths_and_emails(self):
        text = "see C:\\Users\\someone\\project and mail someone@example.com or /home/someone/x or /Users/someone/y"
        kinds = {kind for kind, _ in check_privacy.scan_text(text)}
        self.assertEqual(kinds, {"windows-user-path", "email", "posix-home-path"})

    def test_clean_text_passes(self):
        self.assertEqual(check_privacy.scan_text("Use ~/.claude/skills and %USERPROFILE%\\.claude."), [])

    def test_extra_terms_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            terms = write(tmp, "terms.txt", "secret-employer\n# comment\n\nOtherTerm\n")
            loaded = check_privacy.load_terms(terms)
            self.assertEqual(loaded, ["secret-employer", "otherterm"])
            kinds = {kind for kind, _ in check_privacy.scan_text("I worked at Secret-Employer once", loaded)}
            self.assertEqual(kinds, {"private-term"})

    def test_repository_tree_is_clean(self):
        problems = check_privacy.scan_tree(ROOT)
        self.assertEqual(problems, [], problems)
        problems = check_english.scan_tree(ROOT)
        self.assertEqual(problems, [], problems)


if __name__ == "__main__":
    unittest.main()
