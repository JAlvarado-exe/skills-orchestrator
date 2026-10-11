"""Fail if documentation or data files contain Spanish prose. The project language is English.

Heuristic: count unambiguous Spanish function words per line; a line with two or more is flagged.
"""
import os
import re
import sys

SPANISH = re.compile(
    r"\b(el|los|las|una|unos|unas|del|para|pero|porque|tambi[eé]n|usuario|herramienta|herramientas|con|por|que|"
    r"como|desde|sobre|entre|cuando|donde|todo|todos|esta|este|estos|estas|nuestro|nuestra|puede|pueden|debe|deben)\b",
    re.IGNORECASE,
)
AMBIGUOUS = {"con", "por", "que", "como", "este", "esta", "todo", "entre", "sobre", "desde"}  # also valid English or too weak alone
SUFFIXES = (".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".py")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "tests"}
SKIP_FILES = {"check_english.py"}  # holds the Spanish word list as data


def scan_text(text):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        words = [w.lower() for w in SPANISH.findall(line)]
        strong = [w for w in words if w not in AMBIGUOUS]
        if len(strong) >= 2 or len(words) >= 3:
            hits.append((number, line.strip()[:100]))
    return hits


def scan_tree(root):
    problems = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(SUFFIXES) or name in SKIP_FILES:
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for number, snippet in scan_text(handle.read()):
                    problems.append("%s:%d: %s" % (os.path.relpath(path, root), number, snippet))
    return problems


if __name__ == "__main__":
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = scan_tree(base)
    for item in found:
        print(item)
    print("english check: %d suspicious lines" % len(found))
    sys.exit(1 if found else 0)
