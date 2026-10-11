"""Fail if the tree leaks machine-specific paths, email addresses, or terms from a private list.

The private list is never committed: pass it with --terms FILE (one term per line, # for comments).
"""
import argparse
import os
import re
import sys

PATTERNS = [
    # drive paths in any spelling: single or escaped backslashes (JSON, source code) and forward slashes
    ("windows-user-path", re.compile(r"[A-Za-z]:(?:\\{1,2}|/)Users(?:\\{1,2}|/)(?!<|\{|%|\.\.\.)[^\\/\s'\"]+", re.IGNORECASE)),
    # MSYS / Git Bash spelling of a drive path
    ("windows-user-path", re.compile(r"(?<![\w.~])/[A-Za-z]/Users/(?!<|\{|%|\.\.\.)[^/\s'\"]+", re.IGNORECASE)),
    ("posix-home-path", re.compile(r"(?<![\w.~])/(?:home|Users)/(?!<|\{|\.\.\.|you\b|name\b|user\b|username\b)[A-Za-z0-9_.-]+")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]
SUFFIXES = (".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".py", ".cfg", ".ini")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
SELF = {"scripts/check_privacy.py", "tests/test_repo_checks.py"}  # contain example patterns on purpose; paths from the repo root


def load_terms(path):
    terms = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line.lower())
    return terms


def scan_text(text, terms=()):
    hits = []
    for kind, regex in PATTERNS:
        for match in regex.finditer(text):
            hits.append((kind, match.group(0)))
    lowered = text.lower()
    for term in terms:
        if term in lowered:
            hits.append(("private-term", term))
    return hits


def scan_tree(root, terms=()):
    problems = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(SUFFIXES):
                continue
            path = os.path.join(dirpath, name)
            if os.path.relpath(path, root).replace("\\", "/") in SELF:
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for kind, found in scan_text(handle.read(), terms):
                    problems.append("%s: %s (%s)" % (os.path.relpath(path, root), kind, found if kind != "private-term" else "<term>"))
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms", help="file with private terms, one per line (never commit it)")
    args = parser.parse_args()
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = scan_tree(base, load_terms(args.terms) if args.terms else ())
    for item in found:
        print(item)
    print("privacy check: %d problems" % len(found))
    sys.exit(1 if found else 0)
