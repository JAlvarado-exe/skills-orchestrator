"""The user's policy: skills that must never be suggested (``blocked``) and skills to rank higher (``preferred``).

Both come from the user's config and may be extended by a project file ``.skills-orchestrator.json``, looked up
from the current folder up to the project root (the first folder with a ``.git`` entry). A pattern is a skill id, a
source name or a glob over either, matched without regard to case. A project file can only add patterns and change
the two thresholds: it cannot remove a blocked entry, and a preferred entry is reordered within a bounded boost,
never shown past the confidence gates.
"""
from __future__ import annotations

import os
import sys
from fnmatch import fnmatchcase

from .jsonio import read_json
from .sanitize import sanitize

PROJECT_FILE = ".skills-orchestrator.json"
PREFERRED_BOOST = 1.25
PROJECT_KEYS = ("blocked", "preferred", "min_score", "min_terms")


def matches(entry: dict, patterns) -> bool:
    """True when the entry's id, source or one of its sources matches one of the patterns."""
    if not patterns:
        return False
    names = [entry.get("id", "")] + [entry.get("source", "")] + list(entry.get("sources", []) or [])
    names = [name.lower() for name in names if isinstance(name, str) and name]
    for pattern in patterns:
        pattern = pattern.lower()
        if any(name == pattern or fnmatchcase(name, pattern) for name in names):
            return True
    return False


def find_project_file(cwd: str, home: str = None):
    """The nearest project policy file between cwd and the project root, or None. Never looks inside the home folder."""
    if not cwd or not os.path.isdir(cwd):
        return None
    home = os.path.normcase(os.path.realpath(home or os.path.expanduser("~")))
    current = os.path.abspath(cwd)
    while os.path.normcase(os.path.realpath(current)) != home:
        candidate = os.path.join(current, PROJECT_FILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if os.path.exists(os.path.join(current, ".git")) or parent == current:
            return None
        current = parent
    return None


def _patterns(value):
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def load_policy(config: dict, cwd: str = None, home: str = None) -> dict:
    """{"blocked", "preferred", "min_score", "min_terms", "project_file"} from the config plus the project file."""
    policy = {"blocked": list(config.get("blocked", [])), "preferred": list(config.get("preferred", [])),
              "min_score": config.get("min_score"), "min_terms": config.get("min_terms"), "project_file": None}
    path = find_project_file(cwd, home) if cwd else None
    if not path:
        return policy
    try:
        data = read_json(path)
    except (OSError, ValueError, RecursionError) as exc:
        print("warning: project policy %s cannot be read (%s): ignored" % (sanitize(path, 300), sanitize(str(exc), 120)), file=sys.stderr)
        return policy
    if not isinstance(data, dict):
        return policy
    policy["project_file"] = path
    policy["blocked"] += _patterns(data.get("blocked"))
    policy["preferred"] += _patterns(data.get("preferred"))
    score = data.get("min_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and score >= 0:
        policy["min_score"] = float(score)
    terms = data.get("min_terms")
    if isinstance(terms, int) and not isinstance(terms, bool) and terms >= 1:
        policy["min_terms"] = terms
    return policy


def allowed(entries, policy: dict, show_blocked: bool = False):
    """The entries that are not blocked (all of them with show_blocked)."""
    if show_blocked or not policy.get("blocked"):
        return list(entries)
    return [entry for entry in entries if not matches(entry, policy["blocked"])]
