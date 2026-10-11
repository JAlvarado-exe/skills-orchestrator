"""Health checks for a registry and for the hooks that agents run around tool calls."""
from __future__ import annotations

import os
import re

from .scan import LISTING_DESC_LIMIT

MUTATOR = re.compile(r"\b(rtk|context[-_]mode)\b", re.IGNORECASE)
REGEX_CHARS = set(".*+?^$()[]\\")
MUTATING_EVENTS = ("PreToolUse", "PostToolUse")


def collect_hooks(source: str, data: dict):
    """Flatten a settings.json / hooks.json document into one record per command."""
    flat = []
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return flat
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            matcher = group.get("matcher", "") if isinstance(group, dict) else ""
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if command:
                    flat.append({"source": source, "event": event, "matcher": matcher or "", "command": command})
    return flat


def _universal(matcher: str) -> bool:
    return matcher.strip() in ("", "*") or bool(REGEX_CHARS & set(matcher))


def _overlap(a: str, b: str) -> bool:
    if _universal(a) or _universal(b):
        return True
    return bool({t.strip() for t in a.split("|")} & {t.strip() for t in b.split("|")})


def find_mutator_collisions(hooks):
    """Two different known output-rewriting tools on overlapping tools of the same event."""
    mutators = []
    for hook in hooks:
        match = MUTATOR.search(hook["command"])
        if match and hook["event"] in MUTATING_EVENTS:
            mutators.append((match.group(1).lower().replace("_", "-"), hook))
    collisions = []
    for i in range(len(mutators)):
        for j in range(i + 1, len(mutators)):
            (name_a, a), (name_b, b) = mutators[i], mutators[j]
            if name_a != name_b and a["event"] == b["event"] and _overlap(a["matcher"], b["matcher"]):
                collisions.append({"event": a["event"], "a": {"tool": name_a, "source": a["source"], "matcher": a["matcher"]},
                                   "b": {"tool": name_b, "source": b["source"], "matcher": b["matcher"]}})
    return collisions


def _check(check_id, status, detail, items=None, data=None):
    record = {"id": check_id, "status": status, "detail": detail}
    if items:
        record["items"] = items
    if data:
        record["data"] = data
    return record


def run_doctor(registry: dict, window_tokens: int = 1000000, budget_fraction: float = 0.01, platform: str = None, hooks=None):
    entries = registry.get("entries", [])
    checks = []

    broken = [e["id"] for e in entries if any(not os.path.exists(p) for p in e.get("paths", [e.get("path", "")]))]
    checks.append(_check("broken-paths", "fail" if broken else "ok", "%d entries point at missing files" % len(broken), broken[:20]))

    names = {}
    for entry in entries:
        names.setdefault(entry["name"], []).append(entry)
    # two versions of the same plugin are drift, not a conflict: only count names shared across sources
    dupes = []
    for name, group in sorted(names.items()):
        sources = {s for e in group for s in (e.get("sources") or [e.get("source")])}
        if len(group) > 1 and len(sources) > 1:
            dupes.append("%s: %s" % (name, ", ".join(e["id"] for e in group)))
    checks.append(_check("duplicate-names", "warn" if dupes else "ok",
                         "%d names used by skills from different sources" % len(dupes), dupes[:20]))

    long_ids = [e["id"] for e in entries if len((e.get("description", "") + " " + e.get("when_to_use", "")).strip()) > LISTING_DESC_LIMIT]
    checks.append(_check("long-descriptions", "warn" if long_ids else "ok",
                         "%d descriptions exceed %d characters and are truncated by the listing" % (len(long_ids), LISTING_DESC_LIMIT), long_ids[:20]))

    bad = [e["id"] for e in entries if not e.get("frontmatter_ok", True)]
    checks.append(_check("frontmatter", "warn" if bad else "ok", "%d skills have no valid frontmatter" % len(bad), bad[:20]))

    hot = [e for e in entries if e.get("hot") and e.get("listed", True)
           and (platform is None or platform in e.get("hot_platforms", []))]
    total = sum(e.get("est_tokens", 0) for e in hot)
    budget = int(window_tokens * budget_fraction)
    top = sorted(hot, key=lambda e: -e.get("est_tokens", 0))[:5]
    checks.append(_check(
        "listing-budget", "fail" if total > budget else "ok",
        "estimated listing %d tokens vs budget %d (%.1f%% of a %d-token window); estimate is characters/4, not a measurement"
        % (total, budget, budget_fraction * 100, window_tokens),
        data={"hot_skills": len(hot), "est_tokens": total, "budget_tokens": budget, "overflow": max(0, total - budget),
              "top_contributors": [{"id": e["id"], "est_tokens": e["est_tokens"]} for e in top]}))

    if hooks is not None:
        collisions = find_mutator_collisions(hooks)
        checks.append(_check("hook-collisions", "warn" if collisions else "ok",
                             "%d hooks scanned, %d collisions between known output-rewriting tools" % (len(hooks), len(collisions)),
                             [c for c in collisions]))
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "fail")}
    return {"checks": checks, "summary": summary}
