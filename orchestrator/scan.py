"""Discover SKILL.md files under a set of roots and build a deduplicated registry."""
from __future__ import annotations

import datetime
import difflib
import hashlib
import json
import math
import os
import re
import sys

from .jsonio import read_json
from .sanitize import sanitize
from .search import tokenize, tokenizer_id
from .skillfile import read_skill

EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".trash"}
# Folders inside a cloned repo that hold copies for other tools, docs or fixtures rather than the skills it ships.
INTERNAL_DIRS = {"configs", "docs", "examples", "tests", "test", "evals", "worked", "website", "fixtures"}
SKILL_FILE = "SKILL.md"
DESCRIPTION_STORE_LIMIT = 4000
SOURCE_LIMIT = 100
LISTING_DESC_LIMIT = 1536  # per-entry cap Claude Code applies to description + when_to_use
REGISTRY_VERSION = 2
NEAR_COPY_RATIO = 0.90    # same name and at least this share of equal text: an old or edited copy of one skill
COPY_CACHE_VERSION = 1
MAX_COPY_DECISIONS = 4096


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


def find_skill_files(root: str, max_depth: int = 12, contain: bool = False, exclude=()):
    """Return real SKILL.md paths under root. Follows links, guarded against loops.

    With contain=True nothing whose real path lies outside the root is entered or indexed.
    ``exclude`` lists directory prefixes: a directory whose real path is inside one is never walked.
    """
    found = []
    visited = set()
    root = os.path.abspath(root)
    real_root = os.path.realpath(root)
    excluded = [os.path.realpath(path) for path in exclude]
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if contain and not _inside(real_root, real):
            dirs[:] = []
            continue
        if excluded and any(_inside(prefix, real) for prefix in excluded):
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
    if root_spec.get("source_from") != "first-child" or root_spec.get("detect_internal") is False:
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
        if item.get("kind") == "workflow":
            from .workflows import catalog_workflow
            try:
                entries.append(catalog_workflow(path, item))
            except (OSError, ValueError, RuntimeError):
                print("warning: invalid local workflow at catalog item %d: skipped" % index, file=sys.stderr)
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
            "when_to_use": _text(item.get("activation"))[:DESCRIPTION_STORE_LIMIT], "availability": "documented-only",
            "path": upstream, "upstream": upstream, "paths": [], "variants": [],
            "sha256": hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8", "replace")).hexdigest(), "bytes": 0,
            "frontmatter_ok": True, "listed": False, "est_tokens": 0, "rating": item.get("rating"), "risk": item.get("risk"),
            "dup_group": "catalog/" + slug,
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


def build_registry(root_specs, previous=None):
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
        paths = find_skill_files(root, contain=spec_contain(spec), exclude=spec.get("exclude", ()))
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
        origins = [{"path": real, "source": _source_for(s, r, d), "platform": s.get("platform"),
                    "hot": bool(s.get("hot")), "internal": _is_internal(s, r, d), "sha256": info["sha256"]}
                   for s, r, d in occurrences]
        platforms = sorted({s.get("platform") for s, _r, _d in occurrences if s.get("platform")})
        hot_platforms = sorted({s.get("platform") or "unknown" for s, _r, _d in occurrences if s.get("hot")})
        internal = all(_is_internal(s, r, d) for s, r, d in occurrences)
        depth = len(_rel_parts(root, skill_dir))
        record = by_sha.get(info["sha256"])
        if record is None:
            by_sha[info["sha256"]] = {
                "info": info, "source": source, "sources": [source], "platforms": platforms, "hot_platforms": hot_platforms,
                "internal": internal, "depth": depth, "path": real, "paths": [real], "origins": origins,
            }
        else:
            record["paths"].append(real)
            record["origins"].extend(origins)
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
    normalized = {}
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
            "origins": [origin for m in members for origin in m["origins"]],
            "sha256": info["sha256"],
            "bytes": info["bytes"],
            "frontmatter_ok": info["frontmatter_ok"],
            "listed": info["listed"],
            "auto_eligible": info["listed"],
            "norm_sha": info["norm_sha256"],
        }
        normalized[entry["id"]] = info["normalized"]
        if info.get("truncated"):
            entry["truncated"] = True
        entry["est_tokens"] = estimate_tokens(name, entry["description"], entry["when_to_use"]) if info["listed"] else 0
        entries.append(entry)
    entries.sort(key=lambda e: e["id"])
    cache = (previous or {}).get("copy_cache", {})
    decisions = cache.get("pairs") if isinstance(cache, dict) and cache.get("version") == COPY_CACHE_VERSION else None
    pairs = assign_dup_groups(entries, normalized, decisions if isinstance(decisions, dict) else {})
    for entry in entries:
        entry["tok"] = entry_tokens(entry)
    return {
        "version": REGISTRY_VERSION,
        "tokenizer": tokenizer_id(),
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "roots": root_report,
        "missing_roots": missing,
        "files": len(by_real),
        "errors": errors,
        "entries": entries,
        "copy_cache": {"version": COPY_CACHE_VERSION, "pairs": pairs},
    }


def entry_tokens(entry: dict) -> dict:
    """Name and body tokens stored in the registry so a search does not tokenize every description again."""
    return {"name": tokenize(entry.get("name", "")),
            "body": tokenize(entry.get("description", "") + " " + entry.get("when_to_use", ""))}


class _CopyMatcher(difflib.SequenceMatcher):
    """Use large exact blocks to accelerate difflib's no-junk comparison of edited prose."""

    def find_longest_match(self, alo=0, ahi=None, blo=0, bhi=None):
        a, b = self.a, self.b
        ahi = len(a) if ahi is None else ahi
        bhi = len(b) if bhi is None else bhi
        if min(ahi - alo, bhi - blo) >= 1024:
            # Every match of length >= 2*step contains an entire aligned step-sized slice
            # of a. Expand all occurrences in b, preserving difflib's earliest-position ties.
            step = max(32, (ahi - alo) // 32)
            best = difflib.Match(alo, blo, 0)
            probes = 0
            for i in range(alo, ahi - step + 1, step):
                word = a[i:i + step]
                j = b.find(word, blo, bhi)
                while j >= 0:
                    probes += 1
                    if probes > 128:
                        break
                    if not (best.a <= i < best.a + best.size and i - best.a == j - best.b):
                        start, other, size = i, j, step
                        while start > alo and other > blo and a[start - 1] == b[other - 1]:
                            start -= 1
                            other -= 1
                            size += 1
                        while start + size < ahi and other + size < bhi and a[start + size] == b[other + size]:
                            size += 1
                        if size > best.size or (size == best.size and (start, other) < (best.a, best.b)):
                            best = difflib.Match(start, other, size)
                    j = b.find(word, j + 1, bhi)
                if probes > 128:
                    break
            if probes <= 128 and best.size >= 2 * step:
                return best
        return super().find_longest_match(alo, ahi, blo, bhi)


def _near_copy(first: str, second: str) -> bool:
    total = len(first) + len(second)
    if not total:
        return True
    if 2 * min(len(first), len(second)) / total < NEAR_COPY_RATIO:
        return False
    # With autojunk disabled SequenceMatcher always takes a longest common block first.
    # A single matching edge this long already guarantees its final ratio reaches the gate.
    required = math.ceil(NEAR_COPY_RATIO * total / 2)
    if first[:required] == second[:required] or first[-required:] == second[-required:]:
        return True
    matcher = _CopyMatcher(None, first, second, autojunk=False)
    return matcher.quick_ratio() >= NEAR_COPY_RATIO and matcher.ratio() >= NEAR_COPY_RATIO


def assign_dup_groups(entries, normalized, previous=None):
    """Give copies of one skill the same ``dup_group``: same normalized text, or same name and at least
    NEAR_COPY_RATIO equal text, measured character by character (old versions and lightly edited copies)."""
    parent = {e["id"]: e["id"] for e in entries}
    hashes = {e["id"]: e["norm_sha"] for e in entries}
    previous = previous or {}
    pairs = {}

    def find(ident):
        while parent[ident] != ident:
            parent[ident] = parent[parent[ident]]
            ident = parent[ident]
        return ident

    def join(first, second):
        a, b = find(first), find(second)
        if a != b:
            parent[max(a, b)] = min(a, b)

    by_hash, by_name = {}, {}
    for entry in entries:
        by_hash.setdefault(entry.get("norm_sha"), []).append(entry["id"])
        by_name.setdefault(entry["name"].lower(), []).append(entry["id"])
    for ids in by_hash.values():
        for other in ids[1:]:
            join(ids[0], other)
    for ids in by_name.values():
        for index, first in enumerate(ids):
            for second in ids[index + 1:]:
                if find(first) == find(second):
                    continue
                # Keep argument order: difflib tie-breaking is not symmetric.
                key = hashes[first] + ":" + hashes[second]
                same = previous.get(key)
                if not isinstance(same, bool):
                    same = _near_copy(normalized[first], normalized[second])
                if len(pairs) < MAX_COPY_DECISIONS:
                    pairs[key] = same
                if same:
                    join(first, second)
    for entry in entries:
        entry["dup_group"] = find(entry["id"])
    return pairs


def upgrade_registry(registry: dict) -> dict:
    """Bring an older registry (or one tokenized with other stopwords) to the current format, in memory."""
    if not isinstance(registry, dict) or not isinstance(registry.get("entries"), list):
        return registry
    current = tokenizer_id()
    retokenize = registry.get("tokenizer") != current
    for entry in registry["entries"]:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("norm_sha", entry.get("sha256"))
        entry.setdefault("dup_group", entry.get("id"))
        if retokenize or not isinstance(entry.get("tok"), dict):
            entry["tok"] = entry_tokens(entry)
    registry["tokenizer"] = current
    registry["version"] = max(REGISTRY_VERSION, registry.get("version", 1) if isinstance(registry.get("version"), int) else 1)
    return registry


def roots_signature(specs, catalogs=()):
    """Fingerprint of what a registry was built from: root paths (this includes the current project's skill
    folders), catalog files and excluded prefixes. A different cwd or config gives a different signature."""
    def path_key(path):
        return os.path.normcase(os.path.abspath(path))

    paths = [path_key(spec["path"]) for spec in specs]
    # The first root covering a path chooses its canonical source, so preserve order.
    options = [[path, spec.get("source"), spec.get("source_from", "fixed"), spec.get("platform"),
                bool(spec.get("hot")), spec_contain(spec), spec.get("detect_internal") is not False,
                sorted(path_key(p) for p in spec.get("exclude", ()))]
               for path, spec in zip(paths, specs)]
    files = []
    for path in catalogs:
        try:
            info = os.stat(path)
            stamp = [info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        except OSError:
            stamp = None
        files.append([path_key(path), stamp])
    digest = hashlib.sha256(json.dumps([options, files], ensure_ascii=True).encode("ascii")).hexdigest()
    return paths + ["inputs:" + digest]


def make_registry(specs, catalogs=(), built_with: str = "explicit", previous=None):
    """build_registry plus catalog tool entries, the roots signature and how the registry was built ("config"|"explicit")."""
    catalogs = list(dict.fromkeys(catalogs))
    specs = list(specs)
    registry = build_registry(specs, previous)
    for path in catalogs:
        try:
            extra = catalog_entries(path)
        except (OSError, ValueError, RecursionError) as exc:
            print("warning: cannot read catalog %s (%s): ignored" % (sanitize(path, 300), sanitize(str(exc), 120)), file=sys.stderr)
            continue
        registry["entries"] = sorted(registry["entries"] + extra, key=lambda e: e["id"])
    registry["roots_signature"] = roots_signature(specs, catalogs)
    registry["built_with"] = built_with
    return registry
