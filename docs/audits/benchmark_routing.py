"""Reproduce the November routing audit on generated skills using the public CLI."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
TOPICS = (
    "pricing margin subscription", "invoice payment receipts", "warehouse freight logistics",
    "charts diagrams legends", "slides keynote layout", "backup restore snapshots",
    "database migration schema", "calendar meeting agenda", "proofreading spelling grammar",
    "design typography palette", "contract clause review", "photos portrait lighting",
    "queue worker latency", "translation localization glossary", "cashflow forecast variance",
    "packaging shipping parcels",
)
QUERY = "inspect glacier sediment stratigraphy"


def command(args, stdin=None):
    started = time.perf_counter()
    process = subprocess.run(
        [sys.executable, "-B", "-m", "orchestrator", *args], cwd=ROOT, input=stdin,
        capture_output=True, encoding="utf-8", check=True, timeout=120,
    )
    return round(1000 * (time.perf_counter() - started), 1), process.stdout


def percentiles(samples):
    ordered = sorted(samples)
    return {"median_ms": round(statistics.median(ordered), 1),
            "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1]}


def benchmark(folder, count):
    library = folder / "skills"
    for index in range(count):
        source = "collection-%d" % (index % 7)
        name = "glacier-sediment" if index == 0 else "guide-%05d" % index
        subject = "glacier sediment stratigraphy" if index == 0 else TOPICS[index % len(TOPICS)]
        target = library / source / name
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(
            "---\nname: %s\ndescription: Inspect %s for project teams.\n---\n\nDocument %s.\n"
            % (name, subject, subject), encoding="utf-8",
        )
    registry = folder / "registry.json"
    config = folder / "config.json"
    config.write_text(json.dumps({"vendor": ["skills"], "registry": str(registry),
                                  "use_platform_roots": False, "use_cwd_project_roots": False}),
                      encoding="utf-8")
    common = ["--config", str(config)]
    hook = ["hook-prompt", *common]
    payload = json.dumps({"prompt": QUERY, "cwd": str(folder)})

    def invoke_hook():
        elapsed, output = command(hook, payload)
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        if "collection-0/glacier-sediment" not in context:
            raise ValueError("Expected skill missing from rendered hook")
        return elapsed

    cold = invoke_hook()
    entries = json.loads(registry.read_text(encoding="utf-8"))["entries"]
    if len(entries) != count:
        raise ValueError("Unexpected registry count")
    warm = [invoke_hook() for _ in range(20)]
    find = ["find", QUERY, "--also", "glacier layers", "--also", "inspect sediment", "--json", *common]
    elapsed_find = []
    for _ in range(5):
        elapsed, output = command(find)
        if json.loads(output)["results"][0]["id"] != "collection-0/glacier-sediment":
            raise ValueError("Unexpected first find result")
        elapsed_find.append(elapsed)
    overlaps, _ = command(["overlaps", "--json", *common])
    return {"entries": count, "registry_bytes": registry.stat().st_size, "cold_hook_ms": cold,
            "warm_hook": percentiles(warm), "three_phrasing_find_median_ms": statistics.median(elapsed_find),
            "overlaps_ms": overlaps}


def benchmark_copies(folder, shared_names):
    """Hold file count and body text fixed while varying how many names require comparison."""
    library = folder / "skills"
    for family, subject in enumerate(TOPICS[:10]):
        paragraphs = ["Step %d. Inspect %s, record the evidence, and review the result with the team."
                      % (step, subject) for step in range(28)]
        for edition in range(4):
            name = "guide-%02d" % family if shared_names else "guide-%02d-%d" % (family, edition)
            target = library / ("collection-%d" % edition) / name
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(
                "---\nname: %s\ndescription: Inspect %s.\n---\nEdition %d.\n%s\n"
                % (name, subject, edition, "\n".join(paragraphs)), encoding="utf-8",
            )
    registry = folder / "registry.json"
    config = folder / "config.json"
    config.write_text(json.dumps({"vendor": ["skills"], "use_platform_roots": False,
                                  "use_cwd_project_roots": False}), encoding="utf-8")
    elapsed, _ = command(["scan", "--config", str(config), "--out", str(registry)])
    entries = json.loads(registry.read_text(encoding="utf-8"))["entries"]
    groups = len({entry["dup_group"] for entry in entries})
    expected = 10 if shared_names else 40
    if len(entries) != 40 or groups != expected:
        raise ValueError("Unexpected copy grouping")
    return {"shared_names": shared_names, "entries": len(entries), "copy_groups": groups, "scan_ms": elapsed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copies-only", action="store_true", help="only compare unique and repeated skill names")
    args = parser.parse_args()
    # Keep ephemeral inventory and state inside the specified skill checkout.
    if os.environ.get("SKILLS_ORCHESTRATOR_HOOK", "").lower() in ("off", "0", "false"):
        raise SystemExit("The hook must be enabled in this benchmark process.")
    with tempfile.TemporaryDirectory(dir=ROOT) as scratch:
        if not args.copies_only:
            for size in (100, 520, 1000, 2500):
                print(json.dumps(benchmark(Path(scratch) / str(size), size)), flush=True)
        for shared in (False, True):
            print(json.dumps(benchmark_copies(Path(scratch) / ("shared" if shared else "unique"), shared)), flush=True)
