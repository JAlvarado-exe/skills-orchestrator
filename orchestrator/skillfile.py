"""Read SKILL.md files with a small, lenient frontmatter parser (a YAML subset, stdlib only)."""
from __future__ import annotations

import hashlib
import os
import re

_KEY = re.compile(r"^([A-Za-z0-9_.\-]+)\s*:(.*)$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        return inner.replace("''", "'")
    return value


def _parse_block(lines):
    fields = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _KEY.match(line) if line and not line[0].isspace() and not line.lstrip().startswith("#") else None
        if not match:
            i += 1
            continue
        key, rest = match.group(1), match.group(2).strip()
        j = i + 1
        cont = []
        while j < len(lines) and (lines[j] == "" or lines[j][0].isspace()):
            cont.append(lines[j])
            j += 1
        while cont and cont[-1].strip() == "":
            cont.pop()
        if rest[:1] in (">", "|"):
            body = [c.strip() for c in cont]
            if rest[0] == ">":
                fields[key] = " ".join(b for b in body if b)
            else:
                fields[key] = "\n".join(body)
        elif rest == "":
            stripped = [c.strip() for c in cont if c.strip()]
            if stripped and all(s.startswith("- ") or s == "-" for s in stripped):
                fields[key] = [_unquote(s[2:].strip()) for s in stripped]
            elif stripped and not any(_KEY.match(s) for s in stripped):
                fields[key] = " ".join(stripped)
            else:
                fields[key] = ""
        else:
            parts = [rest] + [c.strip() for c in cont if c.strip()]
            fields[key] = _unquote(parts[0]) if len(parts) == 1 else " ".join(parts)
        i = j
    return fields


def parse_frontmatter(text: str):
    """Return (fields, ok). ok is False when there is no complete ---/--- block."""
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, False
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return _parse_block(lines[1:i]), True
    return {}, False


def _body(text: str) -> str:
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return "\n".join(lines)


def _first_paragraph(body: str) -> str:
    para = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            if para:
                break
            continue
        if stripped.startswith("#") and not para:
            continue
        para.append(stripped)
    return " ".join(para)


def _truthy(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in ("true", "yes", "on", "1")


def read_skill(path: str) -> dict:
    with open(path, "rb") as handle:
        raw = handle.read()
    text = raw.decode("utf-8", errors="replace")
    fields, ok = parse_frontmatter(text)
    dirname = os.path.basename(os.path.dirname(os.path.abspath(path)))
    name = fields.get("name") if isinstance(fields.get("name"), str) and fields.get("name") else dirname
    description = fields.get("description") if isinstance(fields.get("description"), str) else ""
    if not description:
        description = _first_paragraph(_body(text))
    when = fields.get("when_to_use") if isinstance(fields.get("when_to_use"), str) else ""
    return {
        "name": " ".join(name.split()),
        "description": description,
        "when_to_use": when,
        "frontmatter_ok": ok,
        "listed": not _truthy(fields.get("disable-model-invocation")),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
