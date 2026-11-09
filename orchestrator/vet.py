"""Static safety scan for a cloned skill repository.

vet looks at what an agent will *load* (SKILL.md files and everything in their folders, slash
commands, agent definitions and rule files) and what a machine will *run* (hooks, installers,
package lifecycle scripts, plugin and MCP manifests). It does not audit a project's whole
application source. A clean report is not proof of safety: it only means none of these patterns
matched. Read hooks and installers yourself before running them.

Every file in scope is either scanned or reported: a file that cannot be scanned (SKIP-01, SKIP-02)
produces a finding instead of a silent pass.
"""
from __future__ import annotations

import bisect
import json
import os
import re
import stat

from .sanitize import is_invisible, sanitize

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAX_FILE_BYTES = 1000000
CHUNK = 4000     # long lines are scanned in windows of this many characters ...
OVERLAP = 800    # ... that overlap by more than the longest possible rule match (about 750), so no match is cut in two
_WHITESPACE = re.compile(r"\s+")
MAX_JOIN = 5     # physical lines joined into one logical line (backslash or trailing pipe continuation)
SEVERITIES = ("high", "medium", "low", "info")
_I = re.IGNORECASE

_SHELL = r"(?:ba|z|da|k)?sh"
_CHAIN = r"(?:\|[^\n|]{0,100}){0,3}?"
_PIPE_TARGET = (r"\|\s*(?:/\S{0,100}/)?(?:sudo\s+(?:-\S{1,30}\s+){0,4})?"
                r"(?:" + _SHELL + r"|python\d{0,2}(?!\s+-m\s+json\.tool)|node|perl|ruby|iex)\b")
_DOWNLOAD = r"(?:irm|iwr|Invoke-RestMethod|Invoke-WebRequest|DownloadString|DownloadFile|curl|wget)"
_LEAD = r"(?:(?:all|any|the|your|everything|of|these|those)\s+){0,3}"

INJ_01 = re.compile(
    r"\bignore\s+" + _LEAD + r"(?:\w+\s+){0,2}?(?:previous|prior|above|earlier)\s+(?:\w+\s+)?(?:instructions?|rules?|prompts?|context)"
    r"|\bignore\s+(?:the\s+)?(?:instructions?|rules?|prompts?|context)\s+(?:above|before)\b"
    r"|\bignore\s+(?:everything|all|anything)\s+(?:above|before|earlier|previously)\b"
    r"|\bforget\s+(?:everything|all)\s+(?:above|before|earlier|previously)\b"
    r"|\bforget\s+(?:(?:all|any|your)\s+)?(?:previous|prior|earlier)\s+(?:instructions?|rules?|prompts?|context)"
    r"|\bdisregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|system)\b"
    r"|\boverride\s+(?:the\s+)?(?:system|safety)\s+(?:prompt|instructions?|rules?)"
    r"|\byou\s+are\s+now\s+(?:in\s+)?(?:developer|dan|jailbreak|unrestricted)"
    r"|\bexfiltrat", _I)
EXEC_01 = re.compile(
    r"\b(?:curl|wget)\b[^\n|]{0,200}" + _CHAIN + _PIPE_TARGET
    + r"|\b" + _DOWNLOAD + r"\b[^\n|]{0,200}" + _CHAIN + r"\|\s*(?:iex|Invoke-Expression)\b"
    + r"|\b(?:iex|Invoke-Expression)\b[^\n]{0,100}?\b" + _DOWNLOAD + r"\b"
    + r"|<\(\s*(?:curl|wget)\b"
    + r"|\b(?:" + _SHELL + r"\s+-c|eval)\b[^\n$`]{0,20}(?:\$\(|`)\s*(?:curl|wget)\b"
    + r"|\b(?:powershell|pwsh)(?:\.exe)?\s+(?:-\w+\s+){0,6}-e(?:nc(?:odedcommand)?|c)?\s+[A-Za-z0-9+/=]{8,}", _I)
EXEC_02 = re.compile(
    r"(\beval\s*[(\$\"'`]|\bexec\s*\(|\bos\.system\s*\(|\bos\.popen\s*\(|\bsubprocess\.Popen\s*\(|\bnew\s+Function\s*\("
    r"|shell\s*=\s*True|\bchild_process\b|\bexecSync\s*\(|\bInvoke-Expression\b)", _I)

_ALL = ("skill", "hook", "install", "agent")
# (rule id, severity, scopes, regex, message). Every gap is bounded so a hostile line cannot cost more than linear time.
TEXT_RULES = [
    ("INJ-01", "high", ("skill", "agent"), INJ_01, "instruction-override or exfiltration phrasing"),
    ("INJ-02", "medium", ("skill", "agent"), re.compile(
        r"\b(do\s+not|don't|never)\s+(tell|inform|mention|reveal|notify)\b[^\n]{0,40}\buser\b"
        r"|without\s+(telling|informing|notifying)\s+the\s+user", _I), "asks the model to conceal actions from the user"),
    ("EXEC-01", "high", _ALL, EXEC_01, "downloads and executes remote code in one step"),
    ("EXEC-02", "medium", _ALL, EXEC_02, "dynamic code or shell execution"),
    ("OBF-01", "medium", _ALL, re.compile(
        r"(b64decode|base64\s+(-d|--decode)|\batob\s*\(|FromBase64String)", _I), "decodes an obfuscated payload"),
    ("CFG-01", "high", _ALL, re.compile(
        r"\b(write|writes|append|add|modify|edit|overwrite|replace|patch|echo|inject)\b[^\n]{0,60}"
        r"(settings(\.local)?\.json|CLAUDE\.md|AGENTS\.md|GEMINI\.md|\.bashrc|\.zshrc|\.bash_profile|\$PROFILE|authorized_keys|\.cursorrules)",
        _I), "modifies agent configuration or shell startup files"),
    ("CFG-02", "high", _ALL, re.compile(
        r"\b(cat|read|type|get-content|copy|cp|scp|upload|send|curl|post)\b[^\n]{0,40}"
        r"(\.ssh[/\\]|id_rsa|id_ed25519|\.aws[/\\]credentials|\.npmrc|\.netrc|\.env\b|credentials\.json|\.git-credentials)", _I),
     "reads or sends credential files"),
    ("NET-01", "medium", _ALL, re.compile(
        r"https?://[^\s'\"<>)]{1,200}\.(exe|msi|dll|ps1|sh|bat|cmd|zip|tar\.gz|tgz|whl|jar|dmg|pkg|deb|rpm)\b", _I),
     "downloads an executable or archive"),
]
WHOLE_TEXT_RULES = frozenset({"INJ-01"})  # matched on the whole file so a phrase may span lines
LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish", "preuninstall", "postuninstall")
RESTRICTIVE = ("elastic license", "business source license", "server side public", "affero", "gnu general public",
               "commons clause", "polyform", "functional source license", "fair source")
PERMISSIVE = ("mit license", "apache license", "bsd", "isc license", "unlicense", "cc0", "permission is hereby granted")
INSTALLER_EXT = (".sh", ".bash", ".ps1", ".bat", ".cmd", ".py", ".js", ".mjs", ".cjs")
CODE_EXT = (".sh", ".bash", ".ps1", ".bat", ".cmd", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml", ".toml")
TEXT_EXT = (".md", ".txt") + CODE_EXT
AGENT_EXT = (".md", ".mdc", ".markdown", ".txt", ".prompt")
AGENT_DIRS = {"agents", "rules", "prompts"}
AGENT_ROOT_FILES = {"claude.md", "agents.md", "gemini.md", ".cursorrules"}
MANIFESTS = {"plugin.json", "marketplace.json", ".mcp.json", "mcp.json", "server.json"}
SCRIPT_REF = re.compile(r"[\w./${}-]+\.(?:sh|js|mjs|cjs|py|ps1)\b")
# characters that are allowed to be invisible: emoji joiner and emoji presentation selector
EMOJI_PARTS = {0x200D, 0xFE0F}


def _read_file(path: str, lowered: str):
    """Return (text, issue). issue is None, "big", "nul" or "skip". text is None when the file is not scanned."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None, "skip"
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None, "skip"
    texty = lowered == "skill.md" or lowered.endswith(TEXT_EXT)
    binary = b"\x00" in raw[:4096]
    if len(raw) > MAX_FILE_BYTES:
        return (None, "skip") if binary and not texty else (None, "big")
    if texty and b"\x00" in raw:
        return raw.decode("utf-8", errors="replace").replace("\x00", ""), "nul"
    if binary:
        return None, "skip"
    return raw.decode("utf-8", errors="replace"), None


def _is_text(path: str):
    return _read_file(path, os.path.basename(path).lower())[0]


def _inside(root: str, path: str) -> bool:
    return os.path.normcase(path).startswith(os.path.normcase(root) + os.sep)


def _command_strings(node):
    """Every string stored under a "command" key, at any depth, without recursion."""
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "command" and isinstance(value, str):
                    yield value
                else:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)


def _hook_targets(root: str, files):
    """Scripts that a hooks.json document runs, resolved under the repository root."""
    targets = set()
    for dirpath, name in files:
        if name.lower() != "hooks.json":
            continue
        text = _read_file(os.path.join(dirpath, name), "hooks.json")[0]
        try:
            data = json.loads((text or "").lstrip("\ufeff"))
        except (ValueError, RecursionError):
            continue
        for command in _command_strings(data):
            for match in SCRIPT_REF.finditer(command):
                ref = re.sub(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/*", "", match.group(0))
                while ref.startswith("./"):
                    ref = ref[2:]
                if not ref or ref.startswith("/"):
                    continue
                base = dirpath
                while True:
                    candidate = os.path.normpath(os.path.join(base, ref))
                    if _inside(root, candidate) and os.path.isfile(candidate):
                        targets.add(os.path.normcase(candidate))
                        break
                    if base == root or os.path.dirname(base) == base:
                        break
                    base = os.path.dirname(base)
    return targets


def _scopes(rel_parts, name, skill_dirs, root, dirpath, path, hook_targets):
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
    base = name.lower()
    if "commands" in lowered:
        scopes.add("skill")
    if len(rel_parts) == 1 and base in AGENT_ROOT_FILES:
        scopes.add("agent")
    elif AGENT_DIRS & set(lowered) and base.endswith(AGENT_EXT):
        scopes.add("agent")
    if "hooks" in lowered or base == "hooks.json" or base in MANIFESTS or os.path.normcase(path) in hook_targets:
        scopes.add("hook")
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


def _logical_lines(text: str):
    """Yield (first physical line number, line). A line ending in a backslash or a pipe continues on the next."""
    physical = text.splitlines()
    index = 0
    while index < len(physical):
        start, parts = index, [physical[index]]
        while len(parts) < MAX_JOIN and index + 1 < len(physical):
            tail = parts[-1].rstrip()
            if tail.endswith("\\"):
                parts[-1] = tail[:-1]
            elif not tail.endswith("|"):
                break
            index += 1
            parts.append(physical[index])
        # one space per whitespace run: padding cannot stretch a match beyond the window overlap
        yield start + 1, _WHITESPACE.sub(" ", " ".join(parts) if len(parts) > 1 else parts[0])
        index += 1


def _chunks(line: str):
    if len(line) <= CHUNK:
        yield line
        return
    step = CHUNK - OVERLAP
    for start in range(0, len(line), step):
        yield line[start:start + CHUNK]
        if start + CHUNK >= len(line):
            break


def _window(text: str, start: int, end: int) -> str:
    low = max(0, start - 40) if start > 100 else 0
    return sanitize(text[low:end + 100], 140)


def _line_starts(text: str):
    starts, offset = [], 0
    for piece in text.splitlines(True):
        starts.append(offset)
        offset += len(piece)
    return starts


def _unicode_kinds(text: str):
    """Yield (rule, line number, column, character) for the first invisible and first tag character on each line."""
    for number, line in enumerate(text.splitlines(), 1):
        if line.isascii():
            continue
        seen = set()
        for column, char in enumerate(line):
            code = ord(char)
            if code < 0xAD:
                continue
            if 0xE0000 <= code <= 0xE007F or 0xE0100 <= code <= 0xE01EF:
                rule = "UNI-02"
            elif is_invisible(char) and code not in EMOJI_PARTS and not (code == 0xFEFF and number == 1 and column == 0):
                rule = "UNI-01"
            else:
                continue
            if rule not in seen:
                seen.add(rule)
                yield rule, number, column, char
                if len(seen) == 2:
                    break


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
    hook_targets = _hook_targets(root, files)

    findings = []
    counts = {}
    suppressed = {}

    def add(rule, severity, rel, line, snippet, msg):
        counts[rule] = counts.get(rule, 0) + 1
        if counts[rule] > max_per_rule:
            suppressed[rule] = suppressed.get(rule, 0) + 1
            return
        findings.append({"rule": rule, "severity": severity, "file": rel, "line": line,
                         "snippet": snippet() if callable(snippet) else snippet, "msg": msg})

    for dirpath, name in files:
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, root)
        parts = rel.replace("\\", "/").split("/")
        scopes = _scopes(parts, name, skill_dirs, root, dirpath, path, hook_targets)
        lowered = name.lower()
        if lowered in (".mcp.json", "mcp.json"):
            add("MCP-01", "info", rel, 1, "", "defines MCP server(s)")
        if not scopes:
            continue
        if "hook" in scopes and lowered.endswith(CODE_EXT) and lowered not in MANIFESTS:
            add("HOOK-01", "medium", rel, 1, "", "hook runs automatically on agent events: read the command before enabling")
        if "install" in scopes and lowered.endswith(INSTALLER_EXT):
            add("INST-02", "medium", rel, 1, "", "installer script: read it before running")
        text, issue = _read_file(path, lowered)
        if issue == "big":
            add("SKIP-01", "high", rel, 1, "", "file not scanned: larger than 1 MB")
        elif issue == "nul":
            add("SKIP-02", "medium", rel, 1, "", "NUL bytes in a text file: scanned with the NUL bytes removed")
        if text is None:
            continue
        if lowered == "package.json":
            try:
                scripts = json.loads(text.lstrip("\ufeff")).get("scripts", {})
            except (ValueError, AttributeError, RecursionError):
                scripts = {}
            for key in LIFECYCLE:
                if isinstance(scripts, dict) and scripts.get(key):
                    add("INST-01", "medium", rel, 1, sanitize("%s: %s" % (key, scripts[key]), 140),
                        "package lifecycle script runs during install")
        if scopes & {"skill", "hook", "agent"}:
            for rule, number, column, char in _unicode_kinds(text):
                add(rule, "high", rel, number, "U+%04X at col %d" % (ord(char), column + 1),
                    "invisible or bidirectional character" if rule == "UNI-01" else "Unicode tag character (hidden ASCII)")
        active = [r for r in TEXT_RULES if scopes & set(r[2])]
        starts = None
        for rule, severity, _scopes_, regex, msg in active:
            if rule not in WHOLE_TEXT_RULES:
                continue
            last_line = 0
            for match in regex.finditer(text):
                if starts is None:
                    starts = _line_starts(text)
                number = bisect.bisect_right(starts, match.start())
                if number != last_line:
                    last_line = number
                    add(rule, severity, rel, number, lambda m=match: _window(text, m.start(), m.end()), msg)
        for number, logical in _logical_lines(text):
            for rule, severity, _scopes_, regex, msg in active:
                if rule in WHOLE_TEXT_RULES:
                    continue
                for chunk in _chunks(logical):
                    match = regex.search(chunk)
                    if match:
                        add(rule, severity, rel, number, lambda c=chunk, m=match: _window(c, m.start(), m.end()), msg)
                        break

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
                  "MCP-01": "info", "LIC-01": "low", "LIC-02": "low", "LIC-03": "info", "SKIP-01": "high", "SKIP-02": "medium"})
    return table
