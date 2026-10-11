"""Static safety scan for a cloned skill repository.

vet looks at what an agent will *load* (SKILL.md files and everything in their folders, slash
commands) and what a machine will *run* (hooks, installers, package lifecycle scripts). It does
not audit a project's whole application source. A clean report is not proof of safety: it only
means none of these patterns matched. Read hooks and installers yourself before running them.
"""
from __future__ import annotations

import json
import os
import re

from .sanitize import sanitize

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAX_FILE_BYTES = 1000000
SEVERITIES = ("high", "medium", "low", "info")
_I = re.IGNORECASE

# (rule id, severity, scopes, regex, message)
TEXT_RULES = [
    ("INJ-01", "high", ("skill",), re.compile(
        r"(ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?|context)"
        r"|disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|system)\b"
        r"|override\s+(the\s+)?(system|safety)\s+(prompt|instructions?|rules?)"
        r"|you\s+are\s+now\s+(in\s+)?(developer|dan|jailbreak|unrestricted)"
        r"|\bexfiltrat)", _I), "instruction-override or exfiltration phrasing"),
    ("INJ-02", "medium", ("skill",), re.compile(
        r"\b(do\s+not|don't|never)\s+(tell|inform|mention|reveal|notify)\b[^\n]{0,40}\buser\b"
        r"|without\s+(telling|informing|notifying)\s+the\s+user", _I), "asks the model to conceal actions from the user"),
    ("EXEC-01", "high", ("skill", "hook", "install"), re.compile(
        r"\b(curl|wget)\b[^\n|;]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b"
        r"|\b(irm|iwr|Invoke-RestMethod|Invoke-WebRequest)\b[^\n|]*\|\s*(iex|Invoke-Expression)\b"
        r"|powershell[^\n]*\s-enc(odedcommand)?\b", _I), "downloads and executes remote code in one step"),
    ("EXEC-02", "medium", ("skill", "hook", "install"), re.compile(
        r"(\beval\s*[(\$\"'`]|\bexec\s*\(|\bos\.system\s*\(|shell\s*=\s*True|\bchild_process\b|\bexecSync\s*\(|\bInvoke-Expression\b)"),
     "dynamic code or shell execution"),
    ("OBF-01", "medium", ("skill", "hook", "install"), re.compile(
        r"(b64decode|base64\s+(-d|--decode)|\batob\s*\(|FromBase64String)", _I), "decodes an obfuscated payload"),
    ("CFG-01", "high", ("skill", "hook", "install"), re.compile(
        r"\b(write|writes|append|add|modify|edit|overwrite|replace|patch|echo|inject)\b[^\n]{0,60}"
        r"(settings(\.local)?\.json|CLAUDE\.md|AGENTS\.md|GEMINI\.md|\.bashrc|\.zshrc|\.bash_profile|\$PROFILE|authorized_keys|\.cursorrules)",
        _I), "modifies agent configuration or shell startup files"),
    ("CFG-02", "high", ("skill", "hook", "install"), re.compile(
        r"\b(cat|read|type|get-content|copy|cp|scp|upload|send|curl|post)\b[^\n]{0,40}"
        r"(\.ssh[/\\]|id_rsa|id_ed25519|\.aws[/\\]credentials|\.npmrc|\.netrc|\.env\b|credentials\.json|\.git-credentials)", _I),
     "reads or sends credential files"),
    ("NET-01", "medium", ("skill", "hook", "install"), re.compile(
        r"https?://[^\s'\"<>)]+\.(exe|msi|dll|ps1|sh|bat|cmd|zip|tar\.gz|tgz|whl|jar|dmg|pkg|deb|rpm)\b", _I),
     "downloads an executable or archive"),
]
INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩]")
TAG_BLOCK = re.compile("[\U000e0000-\U000e007f]")
LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish", "preuninstall", "postuninstall")
RESTRICTIVE = ("elastic license", "business source license", "server side public", "affero", "gnu general public",
               "commons clause", "polyform")
PERMISSIVE = ("mit license", "apache license", "bsd", "isc license", "unlicense", "cc0", "permission is hereby granted")
INSTALLER_EXT = (".sh", ".bash", ".ps1", ".bat", ".cmd", ".py", ".js", ".mjs", ".cjs")
CODE_EXT = (".sh", ".bash", ".ps1", ".bat", ".cmd", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml", ".toml")


def _is_text(path: str):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


def _scopes(rel_parts, name, skill_dirs, root, dirpath):
    scopes = set()
    probe = dirpath
    while True:
        if probe in skill_dirs:
            scopes.add("skill")
            break
        if probe == root or os.path.dirname(probe) == probe:
            break
        probe = os.path.dirname(probe)
    lowered = [p.lower() for p in rel_parts[:-1]]
    if "commands" in lowered:
        scopes.add("skill")
    if "hooks" in lowered or name.lower() == "hooks.json":
        scopes.add("hook")
    base = name.lower()
    if base == "package.json" or re.match(r"^(install|setup|bootstrap|postinstall)[._-]?", base):
        scopes.add("install")
    return scopes


def detect_license(root: str):
    for name in sorted(os.listdir(root)):
        if re.match(r"^(licen[sc]e|copying|unlicense)", name, _I) and os.path.isfile(os.path.join(root, name)):
            head = (_is_text(os.path.join(root, name)) or "")[:3000].lower()
            if any(marker in head for marker in RESTRICTIVE):
                return {"file": name, "kind": "restrictive"}
            if any(marker in head for marker in PERMISSIVE):
                return {"file": name, "kind": "permissive"}
            return {"file": name, "kind": "unknown"}
    return {"file": None, "kind": "none"}


def vet_path(root: str, max_per_rule: int = 20) -> dict:
    root = os.path.abspath(root)
    files = []
    skill_dirs = set()
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if "SKILL.md" in names:
            skill_dirs.add(dirpath)
        for name in sorted(names):
            files.append((dirpath, name))

    findings = []
    counts = {}
    suppressed = {}

    def add(rule, severity, rel, line, snippet, msg):
        counts[rule] = counts.get(rule, 0) + 1
        if counts[rule] > max_per_rule:
            suppressed[rule] = suppressed.get(rule, 0) + 1
            return
        findings.append({"rule": rule, "severity": severity, "file": rel, "line": line, "snippet": snippet, "msg": msg})

    for dirpath, name in files:
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, root)
        parts = rel.replace("\\", "/").split("/")
        scopes = _scopes(parts, name, skill_dirs, root, dirpath)
        lowered = name.lower()
        if lowered in (".mcp.json", "mcp.json"):
            add("MCP-01", "info", rel, 1, "", "defines MCP server(s)")
        if not scopes:
            continue
        if "hook" in scopes and lowered.endswith(CODE_EXT):
            add("HOOK-01", "medium", rel, 1, "", "hook runs automatically on agent events: read the command before enabling")
        if "install" in scopes and lowered.endswith(INSTALLER_EXT):
            add("INST-02", "medium", rel, 1, "", "installer script: read it before running")
        text = _is_text(path)
        if text is None:
            continue
        if lowered == "package.json":
            try:
                scripts = json.loads(text).get("scripts", {})
            except (ValueError, AttributeError):
                scripts = {}
            for key in LIFECYCLE:
                if isinstance(scripts, dict) and scripts.get(key):
                    add("INST-01", "medium", rel, 1, sanitize("%s: %s" % (key, scripts[key]), 140),
                        "package lifecycle script runs during install")
        for number, line in enumerate(text.splitlines(), 1):
            if "skill" in scopes or "hook" in scopes:
                match = INVISIBLE.search(line)
                if match:
                    add("UNI-01", "high", rel, number, "U+%04X at col %d" % (ord(match.group()), match.start() + 1),
                        "invisible or bidirectional character")
                match = TAG_BLOCK.search(line)
                if match:
                    add("UNI-02", "high", rel, number, "U+%04X at col %d" % (ord(match.group()), match.start() + 1),
                        "Unicode tag character (hidden ASCII)")
            for rule, severity, rule_scopes, regex, msg in TEXT_RULES:
                if scopes & set(rule_scopes) and regex.search(line):
                    add(rule, severity, rel, number, sanitize(line, 140), msg)

    license_info = detect_license(root)
    if license_info["kind"] == "none":
        add("LIC-01", "low", "", 0, "", "no LICENSE file: reference only, do not redistribute")
    elif license_info["kind"] == "restrictive":
        add("LIC-02", "low", license_info["file"], 1, "", "restrictive or copyleft license: do not redistribute inside another project")
    elif license_info["kind"] == "unknown":
        add("LIC-03", "info", license_info["file"], 1, "", "license text not recognized: read it")

    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (rank[f["severity"]], f["rule"], f["file"], f["line"]))
    summary = {s: sum(1 for f in findings if f["severity"] == s) + sum(
        suppressed.get(rule, 0) for rule, sev in _rule_severity().items() if sev == s) for s in SEVERITIES}
    summary["total"] = sum(summary[s] for s in SEVERITIES)
    return {"root": root, "license": license_info, "summary": summary, "suppressed": suppressed, "findings": findings}


def _rule_severity():
    table = {rule: sev for rule, sev, _scopes, _rx, _m in TEXT_RULES}
    table.update({"UNI-01": "high", "UNI-02": "high", "INST-01": "medium", "INST-02": "medium", "HOOK-01": "medium",
                  "MCP-01": "info", "LIC-01": "low", "LIC-02": "low", "LIC-03": "info"})
    return table
