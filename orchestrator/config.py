"""User configuration: where the skills are, so the registry can always cover all of them.

The config is one optional JSON file (``~/.skills-orchestrator/config.json``, or the path in the
``SKILLS_ORCHESTRATOR_CONFIG`` environment variable, or ``--config FILE``). Every key is optional.
Paths accept ``~`` and environment variables; a relative path is resolved against the config file's
folder. See docs/ARCHITECTURE.md for the schema.
"""
from __future__ import annotations

import os
import sys

from .jsonio import read_json
from .platforms import load_platforms, resolve_roots
from .sanitize import sanitize

CONFIG_ENV = "SKILLS_ORCHESTRATOR_CONFIG"
REGISTRY_ENV = "SKILLS_ORCHESTRATOR_REGISTRY"
DEFAULT_MAX_AGE_HOURS = 12
SOURCE_FROM_MODES = ("first-child", "fixed", "plugin-cache")
# Skill folders the supported tools read inside a project, relative to the project folder.
PROJECT_SKILL_DIRS = (".claude/skills", ".agents/skills", ".github/skills", ".cursor/skills", ".gemini/skills",
                      ".opencode/skills", ".codex/skills")
BUNDLED_PLATFORMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "platforms.json")


def _home() -> str:
    return os.path.expanduser("~")


def default_config_path() -> str:
    return os.environ.get(CONFIG_ENV) or os.path.join(_home(), ".skills-orchestrator", "config.json")


def registry_path(config: dict) -> str:
    """Configured registry, else the environment variable, else the per-user default."""
    return config.get("registry") or os.environ.get(REGISTRY_ENV) or os.path.join(_home(), ".skills-orchestrator", "registry.json")


def _defaults() -> dict:
    return {"path": None, "registry": None, "extra_roots": [], "vendor": [], "catalogs": [], "exclude_paths": [],
            "use_platform_roots": True, "use_cwd_project_roots": True, "max_age_hours": DEFAULT_MAX_AGE_HOURS,
            "overrides": None, "profiles_dir": None}


def _warn(path: str, message: str) -> None:
    print("warning: config %s %s" % (sanitize(path, 300), message), file=sys.stderr)


def _expand(text: str, base: str) -> str:
    text = os.path.expanduser(os.path.expandvars(text.strip()))
    if not os.path.isabs(text):
        text = os.path.join(base, text)
    return os.path.normpath(text)


def _text_path(value, base: str, key: str, problems: list):
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return _expand(value, base)
    problems.append(key)
    return None


def _path_list(value, base: str, key: str, problems: list):
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(key)
        return []
    paths = []
    for item in value:
        if isinstance(item, str) and item.strip():
            paths.append(_expand(item, base))
        else:
            problems.append(key)
    return paths


def _flag(data: dict, key: str, problems: list) -> bool:
    value = data.get(key, True)
    if isinstance(value, bool):
        return value
    problems.append(key)
    return True


def _extra_roots(value, base: str, problems: list):
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append("extra_roots")
        return []
    specs = []
    for item in value:
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"].strip():
            problems.append("extra_roots")
            continue
        source_from, contain = item.get("source_from", "first-child"), item.get("contain", False)
        if source_from not in SOURCE_FROM_MODES or not isinstance(contain, bool):
            problems.append("extra_roots")
            continue
        # detect_internal False: a hidden folder inside a project (.claude/skills) is a real skill there, not a contributor copy
        specs.append({"path": _expand(item["path"], base), "source_from": source_from, "contain": contain, "hot": False,
                      "platform": None, "detect_internal": False})
    return specs


def load_config(path: str = None, explicit: bool = False) -> dict:
    """Read the config file. A missing file means defaults; an unreadable one warns once and also means defaults."""
    path = path or default_config_path()
    config = _defaults()
    config["path"] = path
    if not os.path.isfile(path):
        if explicit:
            _warn(path, "was not found: using defaults")
        return config
    try:
        data = read_json(path)
    except (OSError, ValueError, RecursionError) as exc:
        _warn(path, "cannot be read (%s): using defaults" % sanitize(str(exc), 120))
        return config
    if not isinstance(data, dict):
        _warn(path, "must hold a JSON object: using defaults")
        return config
    base = os.path.dirname(os.path.abspath(path))
    problems = []
    config["registry"] = _text_path(data.get("registry"), base, "registry", problems)
    config["overrides"] = _text_path(data.get("overrides"), base, "overrides", problems)
    config["profiles_dir"] = _text_path(data.get("profiles_dir"), base, "profiles_dir", problems)
    config["extra_roots"] = _extra_roots(data.get("extra_roots"), base, problems)
    config["vendor"] = _path_list(data.get("vendor"), base, "vendor", problems)
    config["catalogs"] = _path_list(data.get("catalogs"), base, "catalogs", problems)
    config["exclude_paths"] = [os.path.realpath(p) for p in _path_list(data.get("exclude_paths"), base, "exclude_paths", problems)]
    config["use_platform_roots"] = _flag(data, "use_platform_roots", problems)
    config["use_cwd_project_roots"] = _flag(data, "use_cwd_project_roots", problems)
    age = data.get("max_age_hours", DEFAULT_MAX_AGE_HOURS)
    if isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0:
        config["max_age_hours"] = age
    else:
        problems.append("max_age_hours")
    if problems:
        _warn(path, "ignored invalid values for: %s" % ", ".join(sorted(set(problems))))
    return config


def _same_folder(first: str, second: str) -> bool:
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def project_roots(cwd: str, home: str = None):
    """Skill folders of the project around cwd: cwd and each parent up to and including the first one with a .git entry.

    The walk never enters the home folder (its skill folders are platform roots) or goes above the filesystem root.
    Folders are contained: a link that leaves a freshly cloned project is not followed.
    """
    home = home or _home()
    current = os.path.abspath(cwd)
    specs = []
    while not _same_folder(current, home):
        name = os.path.basename(current.rstrip("\\/")) or "root"
        for rel in PROJECT_SKILL_DIRS:
            folder = os.path.join(current, *rel.split("/"))
            if os.path.isdir(folder):
                specs.append({"path": folder, "source": "project:" + name, "hot": False, "platform": None, "contain": True})
        parent = os.path.dirname(current)
        if os.path.exists(os.path.join(current, ".git")) or parent == current:
            break
        current = parent
    return specs


def assemble_roots(config: dict, cwd: str, use_platforms: bool = True, platforms_file: str = None, home: str = None):
    """Every root spec the user's skills can live in: platform folders, this project, configured folders and cloned libraries."""
    specs = []
    if use_platforms and config.get("use_platform_roots", True):
        roots, _missing = resolve_roots(load_platforms(platforms_file or BUNDLED_PLATFORMS), home=home)
        specs.extend(dict(root) for root in roots)
    if config.get("use_cwd_project_roots", True):
        seen = {os.path.normcase(os.path.realpath(spec["path"])) for spec in specs}
        for spec in project_roots(cwd, home):
            if os.path.normcase(os.path.realpath(spec["path"])) not in seen:
                specs.append(spec)
    for spec in config.get("extra_roots", []):
        specs.append(dict(spec, exclude=list(config.get("exclude_paths", []))))
    for path in config.get("vendor", []):
        specs.append({"path": path, "source_from": "first-child", "contain": True, "hot": False, "platform": "vendor"})
    return specs
