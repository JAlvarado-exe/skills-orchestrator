"""Discover explicitly registered local guides and resolve their next eligible phases."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .jsonio import read_json


IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")


def local_file(folder, relative, suffix):
    if not isinstance(relative, str) or not relative or Path(relative).anchor:
        raise ValueError("expected a relative file name")
    root = Path(folder).resolve(strict=True)
    target = (root / relative).resolve(strict=True)
    if root not in target.parents or target.suffix.lower() != suffix or not target.is_file():
        raise ValueError("instruction file must stay inside its guide")
    return target


def catalog_workflow(catalog, item):
    slug, name = item.get("id"), item.get("name")
    if not isinstance(slug, str) or not IDENTIFIER.fullmatch(slug) or not isinstance(name, str) or not name.strip():
        raise ValueError("expected a workflow id and display name")
    overview = local_file(Path(catalog).parent, item.get("entry"), ".md")
    ident = "workflow/" + slug
    return {"id": ident, "dup_group": ident, "name": name, "source": "workflow", "sources": ["workflow"],
            "kind": "workflow", "path": str(overview), "platforms": [], "hot_platforms": [], "hot": False,
            "internal": False, "description": str(item.get("description", ""))[:2000], "when_to_use": "",
            "paths": [], "variants": [], "listed": False, "est_tokens": 0, "frontmatter_ok": True,
            "sha256": hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest(), "bytes": 0}


def phase_status(entry, completed, approved):
    folder = Path(entry["path"]).parent
    data = read_json(local_file(folder, "workflow.json", ".json"))
    phases = data.get("phases") if isinstance(data, dict) else None
    if not isinstance(phases, list) or not phases:
        raise ValueError("workflow.json must define an ordered list of phases")
    done, consent, known, ready, waiting = set(completed), set(approved), set(), [], []
    for phase in phases:
        ident = phase.get("id") if isinstance(phase, dict) else None
        if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident) or ident in known:
            raise ValueError("invalid or duplicate phase id")
        requires = phase.get("requires", [])
        gated = phase.get("requires_approval", False)
        if not isinstance(requires, list) or not all(isinstance(p, str) and p in known for p in requires):
            raise ValueError("prerequisites must refer to earlier phases")
        if not isinstance(gated, bool):
            raise ValueError("requires_approval must be a boolean")
        path = local_file(folder, phase.get("instructions"), ".md")
        known.add(ident)
        missing = [p for p in requires if p not in done]
        if ident in done:
            if missing or (gated and ident not in consent):
                raise ValueError("completed phase lacks a prerequisite or approval")
        elif missing:
            waiting.append({"id": ident, "requires": missing})
        elif gated and ident not in consent:
            ready.append({"id": ident, "status": "requires-approval"})
        else:
            ready.append({"id": ident, "status": "ready", "instructions": str(path)})
    if (done | consent) - known:
        raise ValueError("unknown phase id")
    return {"id": entry["id"], "done": sorted(done), "ready": ready, "waiting": waiting, "complete": done == known}
