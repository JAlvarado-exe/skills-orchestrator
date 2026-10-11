"""Discover SKILL.md files under a set of roots and build a deduplicated registry."""
from __future__ import annotations

import datetime
import math
import os

from .skillfile import read_skill

EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".trash"}
# Folders inside a cloned repo that hold copies for other tools, docs or fixtures rather than the skills it ships.
INTERNAL_DIRS = {"configs", "docs", "examples", "tests", "test", "evals", "worked", "website", "fixtures"}
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


def _rel_parts(root: str, skill_dir: str):
    rel = os.path.relpath(skill_dir, root)
    return [p for p in rel.replace("\\", "/").split("/") if p and p != "."]


def _source_for(root_spec: dict, root: str, skill_dir: str) -> str:
    mode = root_spec.get("source_from", "fixed")
    parts = _rel_parts(root, skill_dir)
    if mode == "first-child" and parts:
        return parts[0]
    if mode == "plugin-cache" and parts:
        return "plugin:" + (parts[1] if len(parts) >= 2 else parts[0])
    return root_spec.get("source") or os.path.basename(root.rstrip("\\/")) or "unknown"


def _is_internal(root_spec: dict, root: str, skill_dir: str) -> bool:
    """Only meaningful for cloned-repo roots (first-child): copies for other tools or dev-only skills."""
    if root_spec.get("source_from") != "first-child":
        return False
    inside = _rel_parts(root, skill_dir)[1:]
    return any(part.startswith(".") or part in INTERNAL_DIRS for part in inside)


def estimate_tokens(name: str, description: str, when_to_use: str) -> int:
    text = (description + " " + when_to_use).strip()
    return int(math.ceil((len(name) + min(len(text), LISTING_DESC_LIMIT) + 30) / 4.0))


def _rank_key(item):
    """Prefer shipped over internal copies, then shallow paths, then the most recently modified."""
    try:
        mtime = os.path.getmtime(item["path"])
    except OSError:
        mtime = 0
    return (item["internal"], item["depth"], -mtime, item["path"])


def build_registry(root_specs):
    """Build the registry.

    Identical file content is one entry with several paths. Different content under the same
    source and name (copies for other tools, old plugin versions) is merged into one entry whose
    other forms are listed under ``variants``.
    """
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
            by_real.setdefault(real, []).append((spec, root, os.path.dirname(path)))

    errors = []
    by_sha = {}
    for real in sorted(by_real):
        try:
            info = read_skill(real)
        except OSError as exc:
            errors.append({"path": real, "error": str(exc)})
            continue
        occurrences = by_real[real]
        spec, root, skill_dir = occurrences[0]
        source = _source_for(spec, root, skill_dir)
        platforms = sorted({s.get("platform") for s, _r, _d in occurrences if s.get("platform")})
        hot_platforms = sorted({s.get("platform") or "unknown" for s, _r, _d in occurrences if s.get("hot")})
        internal = all(_is_internal(s, r, d) for s, r, d in occurrences)
        depth = len(_rel_parts(root, skill_dir))
        record = by_sha.get(info["sha256"])
        if record is None:
            by_sha[info["sha256"]] = {
                "info": info, "source": source, "sources": [source], "platforms": platforms, "hot_platforms": hot_platforms,
                "internal": internal, "depth": depth, "path": real, "paths": [real],
            }
        else:
            record["paths"].append(real)
            if source not in record["sources"]:
                record["sources"].append(source)
            record["platforms"] = sorted(set(record["platforms"]) | set(platforms))
            record["hot_platforms"] = sorted(set(record["hot_platforms"]) | set(hot_platforms))
            record["internal"] = record["internal"] and internal
            if (internal, depth) < (record["internal"], record["depth"]):
                record["depth"], record["path"] = depth, real

    groups = {}
    for record in by_sha.values():
        groups.setdefault((record["source"], record["info"]["name"]), []).append(record)

    entries = []
    for (source, name), members in groups.items():
        members.sort(key=_rank_key)
        primary, others = members[0], members[1:]
        info = primary["info"]
        hot_platforms = sorted({p for m in members for p in m["hot_platforms"]})
        entry = {
            "id": "%s/%s" % (source, name),
            "name": name,
            "source": source,
            "sources": sorted({s for m in members for s in m["sources"]}),
            "platforms": sorted({p for m in members for p in m["platforms"]}),
            "hot": bool(hot_platforms),
            "hot_platforms": hot_platforms,
            "internal": all(m["internal"] for m in members),
            "description": info["description"][:DESCRIPTION_STORE_LIMIT],
            "when_to_use": info["when_to_use"][:DESCRIPTION_STORE_LIMIT],
            "path": primary["path"],
            "paths": sorted(primary["paths"]),
            "variants": [{"sha256": m["info"]["sha256"], "paths": sorted(m["paths"])} for m in others],
            "sha256": info["sha256"],
            "bytes": info["bytes"],
            "frontmatter_ok": info["frontmatter_ok"],
            "listed": info["listed"],
        }
        entry["est_tokens"] = estimate_tokens(name, entry["description"], entry["when_to_use"]) if info["listed"] else 0
        entries.append(entry)
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
