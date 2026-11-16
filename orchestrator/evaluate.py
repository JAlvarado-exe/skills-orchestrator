"""Offline evaluation of the hook's selection: precision at 3, silence and forbidden ids over a JSON case file.

A case is {"id", "prompt" | "payload", "expected": [ids], "forbidden": [ids], "silent": bool}. Each case runs
through the same selection the hook uses, against a registry built in memory from the given config (or an
existing registry file), so the numbers describe what the agent would see. Session memory and usage feedback
are never applied here: an evaluation must give the same numbers every time.
"""
from __future__ import annotations

import os

from .config import assemble_roots, load_config
from .jsonio import read_json
from .scan import make_registry

TOP = 3


def load_cases(path: str):
    """The case list of a JSON file: either a list or an object with a "cases" list. Raises ValueError otherwise."""
    data = read_json(path)
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        raise ValueError("an eval file must hold a list of case objects (or {\"cases\": [...]})")
    return cases


def load_target(config_path: str = None, registry_path: str = None):
    """(path, registry, config) to evaluate against: the given registry file, else one built in memory from the config."""
    config = load_config(config_path, explicit=bool(config_path))
    if registry_path:
        return registry_path, read_json(registry_path), config
    base = os.path.dirname(os.path.abspath(config["path"]))
    registry = make_registry(assemble_roots(config, base), config["catalogs"], "config")
    # overrides are looked up next to this (never written) path
    return os.path.join(base, "registry.json"), registry, config


def _prompt(case: dict):
    payload = case.get("payload")
    if isinstance(payload, dict):
        return payload.get("prompt"), payload
    return case.get("prompt"), {"prompt": case.get("prompt")}


def run_case(case: dict, loaded, run) -> dict:
    """Score one case. ``run(payload, loaded)`` returns (shown ids, printed text) for the hook path."""
    _text, payload = _prompt(case)
    shown, printed = run(payload, loaded)
    silent = not printed
    top = shown[:TOP] if not silent else []
    expected = set(case.get("expected") or [])
    forbidden = sorted(set(case.get("forbidden") or []) & set(shown if not silent else []))
    row = {"id": case.get("id", ""), "silent_expected": bool(case.get("silent")), "silent": silent, "shown": top,
           "forbidden_shown": forbidden}
    if not row["silent_expected"]:
        hits = len([ident for ident in top if ident in expected])
        row["precision_at_3"] = (hits / float(len(top))) if top else 0.0
        row["hit_at_3"] = bool(hits)
    return row


def summarize(rows) -> dict:
    scored = [row for row in rows if not row["silent_expected"]]
    silent_cases = [row for row in rows if row["silent_expected"]]
    count = len(scored) or 1
    return {
        "cases": len(rows),
        "precision_at_3": round(sum(row["precision_at_3"] for row in scored) / count, 3),
        "hit_at_3": round(sum(1 for row in scored if row["hit_at_3"]) / count, 3),
        "silent_ok": sum(1 for row in silent_cases if row["silent"]),
        "silent_cases": len(silent_cases),
        "silenced_wrongly": sum(1 for row in scored if row["silent"]),
        "forbidden_shown": sum(len(row["forbidden_shown"]) for row in rows),
    }


def evaluate(cases, loaded, run):
    rows = [run_case(case, loaded, run) for case in cases]
    return {"summary": summarize(rows), "rows": rows}
