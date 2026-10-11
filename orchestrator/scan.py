"""Discover SKILL.md files under a set of roots and build a deduplicated registry."""
from __future__ import annotations

import datetime
import math
import os

from .skillfile import read_skill

EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".trash"}
SKILL_FILE = "SKILL.md"
DESCRIPTION_STORE_LIMIT = 4000
LISTING_DESC_LIMIT = 1536  # per-entry cap Claude Code applies to description + when_to_use


def find_skill_files(root: str, max_depth: int = 12):
    """Return real SKILL.md paths under root. Follows links, guarded against loops."""
    found = []
    visited = set()
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in visited:
            dirs[:] = []
            continue
        visited.add(real)
        if dirpath.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        if SKILL_FILE in files:
            found.append(os.path.join(dirpath, SKILL_FILE))
    return sorted(found)


def count_skill_files(root: str) -> int:
    """Independent, simpler count (does not follow links). Used to cross-check scans."""
    total = 0
    for _dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        total += sum(1 for name in files if name == SKILL_FILE)
    return total


def _source_for(root_spec: dict, root: str, skill_dir: str) -> str:
    mode = root_spec.get("source_from", "fixed")
    rel = os.path.relpath(skill_dir, root)
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if mode == "first-child" and parts:
        return parts[0]
    if mode == "plugin-cache" and parts:
        return "plugin:" + (parts[1] if len(parts) >= 2 else parts[0])
    return root_spec.get("source") or os.path.basename(root.rstrip("\\/")) or "unknown"


def estimate_tokens(name: str, description: str, when_to_use: str) -> int:
    text = (description + " " + when_to_use).strip()
    return int(math.ceil((len(name) + min(len(text), LISTING_DESC_LIMIT) + 30) / 4.0))


def build_registry(root_specs):
    """Build the registry. Identical file content is one entry with several paths."""
    by_real = {}
    root_report = []
    missing = []
    for spec in root_specs:
        root = os.path.abspath(spec["path"])
        if not os.path.isdir(root):
            missing.append({"path": root, "platform": spec.get("platform"), "source": spec.get("source")})
            continue
        paths = find_skill_files(root)
        root_report.append({"path": root, "platform": spec.get("platform"), "files": len(paths)})
        for path in paths:
            real = os.path.realpath(path)
            record = by_real.setdefault(real, {"path": real, "specs": []})
            record["specs"].append((spec, root, os.path.dirname(path)))

    by_sha = {}
    errors = []
    for real in sorted(by_real):
        try:
            info = read_skill(real)
        except OSError as exc:
            errors.append({"path": real, "error": str(exc)})
            continue
        entry = by_sha.get(info["sha256"])
        spec, root, skill_dir = by_real[real]["specs"][0]
        source = _source_for(spec, root, skill_dir)
        platforms = sorted({s.get("platform") for s, _r, _d in by_real[real]["specs"] if s.get("platform")})
        hot_platforms = sorted({s.get("platform") or "unknown" for s, _r, _d in by_real[real]["specs"] if s.get("hot")})
        if entry is None:
            entry = {
                "name": info["name"],
                "source": source,
                "sources": [source],
                "platforms": platforms,
                "hot": bool(hot_platforms),
                "hot_platforms": hot_platforms,
                "description": info["description"][:DESCRIPTION_STORE_LIMIT],
                "when_to_use": info["when_to_use"][:DESCRIPTION_STORE_LIMIT],
                "path": real,
                "paths": [real],
                "sha256": info["sha256"],
                "bytes": info["bytes"],
                "frontmatter_ok": info["frontmatter_ok"],
                "listed": info["listed"],
            }
            by_sha[info["sha256"]] = entry
        else:
            entry["paths"].append(real)
            if source not in entry["sources"]:
                entry["sources"].append(source)
            entry["platforms"] = sorted(set(entry["platforms"]) | set(platforms))
            entry["hot_platforms"] = sorted(set(entry["hot_platforms"]) | set(hot_platforms))
            entry["hot"] = entry["hot"] or bool(hot_platforms)

    entries = sorted(by_sha.values(), key=lambda e: (e["source"], e["name"], e["sha256"]))
    used = {}
    for entry in entries:
        base = "%s/%s" % (entry["source"], entry["name"])
        entry["id"] = base if base not in used else "%s@%s" % (base, entry["sha256"][:8])
        used[entry["id"]] = True
        entry["est_tokens"] = estimate_tokens(entry["name"], entry["description"], entry["when_to_use"]) if entry["listed"] else 0
    entries.sort(key=lambda e: e["id"])
    return {
        "version": 1,
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "roots": root_report,
        "missing_roots": missing,
        "files": len(by_real),
        "errors": errors,
        "entries": entries,
    }
