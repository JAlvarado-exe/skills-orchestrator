"""Discover SKILL.md files under a set of roots and build a deduplicated registry."""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import sys

from .jsonio import read_json
from .sanitize import sanitize
from .skillfile import read_skill

EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".trash"}
# Folders inside a cloned repo that hold copies for other tools, docs or fixtures rather than the skills it ships.
INTERNAL_DIRS = {"configs", "docs", "examples", "tests", "test", "evals", "worked", "website", "fixtures"}
SKILL_FILE = "SKILL.md"
DESCRIPTION_STORE_LIMIT = 4000
SOURCE_LIMIT = 100
LISTING_DESC_LIMIT = 1536  # per-entry cap Claude Code applies to description + when_to_use


def _inside(real_root: str, real: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(real_root), os.path.normcase(real)]) == os.path.normcase(real_root)
    except ValueError:  # different drives
        return False


def spec_contain(spec: dict) -> bool:
    """Cloned third-party repositories are walked without leaving their own tree unless the spec says otherwise."""
    if "contain" in spec:
        return bool(spec["contain"])
    return spec.get("source_from") == "first-child"


def find_skill_files(root: str, max_depth: int = 12, contain: bool = False):
    """Return real SKILL.md paths under root. Follows links, guarded against loops.

    With contain=True nothing whose real path lies outside the root is entered or indexed.
    """
    found = []
    visited = set()
    root = os.path.abspath(root)
    real_root = os.path.realpath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if contain and not _inside(real_root, real):
            dirs[:] = []
            continue
        if real in visited:
            dirs[:] = []
            continue
        visited.add(real)
        if dirpath.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        # visible folders before hidden ones: when a hidden folder links to a visible one, the visible path is kept
        dirs[:] = sorted((d for d in dirs if d not in EXCLUDE_DIRS), key=lambda d: (d.startswith("."), d))
        if SKILL_FILE in files:
            skill_path = os.path.join(dirpath, SKILL_FILE)
            if not contain or _inside(real_root, os.path.realpath(skill_path)):
                found.append(skill_path)
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
        source = parts[0]
    elif mode == "plugin-cache" and parts:
        source = "plugin:" + (parts[1] if len(parts) >= 2 else parts[0])
    else:
        source = root_spec.get("source") or os.path.basename(root.rstrip("\\/")) or "unknown"
    return sanitize(source, SOURCE_LIMIT) or "unknown"


def _is_internal(root_spec: dict, root: str, skill_dir: str) -> bool:
    """Only meaningful for cloned-repo roots (first-child): copies for other tools or dev-only skills."""
    if root_spec.get("source_from") != "first-child":
        return False
    inside = _rel_parts(root, skill_dir)[1:]
    return any(part.startswith(".") or part in INTERNAL_DIRS for part in inside)


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def catalog_entries(path: str):
    """Entries for tools that have no SKILL.md (CLIs, MCP servers, hooks), read from a catalog JSON file."""
    data = read_json(path)
    items = data.get("items", []) if isinstance(data, dict) else None
    if not isinstance(items, list):
        print("warning: catalog %s is not an object with an items list: ignored" % path, file=sys.stderr)
        return []
    entries = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            print("warning: catalog item %d is not an object: skipped" % index, file=sys.stderr)
            continue
        if item.get("kind") not in ("cli", "mcp", "hook", "gateway"):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            print("warning: catalog item %d has no text name: skipped" % index, file=sys.stderr)
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()[:8]
        upstream = _text(item.get("upstream"))
        entries.append({
            "id": "catalog/" + slug, "name": name, "source": "catalog", "sources": ["catalog"], "platforms": [],
            "hot": False, "hot_platforms": [], "internal": False, "kind": "tool",
            "description": (_text(item.get("what")) + " " + _text(item.get("impact")))[:DESCRIPTION_STORE_LIMIT],
            "when_to_use": _text(item.get("activation"))[:DESCRIPTION_STORE_LIMIT],
            "path": upstream, "upstream": upstream, "paths": [], "variants": [],
            "sha256": hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8", "replace")).hexdigest(), "bytes": 0,
            "frontmatter_ok": True, "listed": False, "est_tokens": 0, "rating": item.get("rating"), "risk": item.get("risk"),
        })
    return sorted(entries, key=lambda e: e["id"])


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
        paths = find_skill_files(root, contain=spec_contain(spec))
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
            better = (internal, depth) < (record["internal"], record["depth"])
            record["internal"] = record["internal"] and internal
            if better:
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
        if info.get("truncated"):
            entry["truncated"] = True
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
