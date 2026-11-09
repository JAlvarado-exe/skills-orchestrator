# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Eight conflict clusters (agent memory, voice, social publishing, anti-slop writing, marketing, output approval, agent security, trading) and a broader `web-access` cluster that bans bot-detection evasion. Social publishing, output approval and trading are owner-pinned.
- Spanish and English vocabulary for voice, transcription, scraping, social media, drafts and approvals, domains and brand names, trading and anti-slop; cold-skill recall tests.
- Extended `business`, `docs` and `research` profiles.
- `vet` recognizes the Functional Source License as a restrictive license (LIC-02).

## [0.1.2] - 2026-10-11

Automatic search: an optional hook runs the skill search on every user message, so finding a skill no longer depends on the model remembering to call `find`.

### Added

- `hook-prompt` command and `orchestrator/hook.py`. It reads a `UserPromptSubmit` JSON payload on stdin, searches the registry with the message and prints `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ...}}`. The block (at most 1,200 characters) lists up to 5 results with state and matched terms, a path for the first 3, name matches, the `WEAK MATCH` line when the `find` weak rule applies, and a fixed line pointing to the Coverage rule. It holds only sanitized ids, paths and matched terms, never descriptions. Optional flags: `--config`, `--registry`, `--top`.
- Skip rules: messages under 8 characters, slash commands, fewer than two query terms, and the `SKILLS_ORCHESTRATOR_HOOK` switch (`0`, `off` or `false`).
- The hook uses the payload's `cwd` for the project skill folders, prints nothing on stdout except the final JSON, and always exits 0. Any failure is swallowed and logged as one line to `hook.log` next to the registry (`SKILLS_ORCHESTRATOR_HOOK_LOG` overrides the path).
- README section "Automatic hook (optional)", an architecture section and a threat table about the trust of hook context in `docs/SECURITY.md`.
- Orchestrator skill: a paragraph under "Two sources, every time" that tells the agent what a `[skills-orchestrator]` block is and that the Coverage rule still applies.
- 40 new unit tests in `tests/test_hook.py` (300 in total), including subprocess tests of the exit code and UTF-8 stdin handling.

### Changed

- `ensure_registry` and `_is_current` accept an optional `cwd` (default: the process folder), so the hook can search the project of the payload.
- `main` returns 0 when `hook-prompt` receives a bad flag (the usage text still goes to stderr), because a non-zero status can block the user's message.
- `SKILL.md` stays at 110 lines: the "Two sources, every time" paragraph was rewrapped to make room.
- Version assertions in `tests/test_discovery.py` now expect 0.1.2.

### Known limitations

- The hook cannot see skills a host injects, and the search is lexical like `find`.
- The output format follows the Claude Code hook format; it was exercised here with synthetic payloads, not inside a live session, and other agents were not tested.
- If the command path is wrong or the package cannot be imported, `run.py` exits with status 2, which some agents treat as blocking the message.

## [0.1.1] - 2026-10-11

Guaranteed discovery: the tool can search every skill the user has, in any project and in two languages, and a weak result is never mistaken for "no skill".

### Added

- User config (`~/.skills-orchestrator/config.json`, the `SKILLS_ORCHESTRATOR_CONFIG` variable or `--config FILE`) with the optional keys `registry`, `extra_roots`, `vendor`, `catalogs`, `exclude_paths`, `use_platform_roots`, `use_cwd_project_roots`, `max_age_hours`, `overrides` and `profiles_dir`. A malformed file warns once and is treated as empty. Schema in the README and `docs/ARCHITECTURE.md`.
- Project roots: the skill folders of the current project (`.claude/skills`, `.agents/skills`, `.github/skills`, `.cursor/skills`, `.gemini/skills`, `.opencode/skills`, `.codex/skills`) in the current directory and each parent up to the first `.git`, as sources named `project:<folder>`.
- Automatic refresh: `find`, `list`, `overlaps`, `conflicts` and `doctor` rebuild the registry when it is missing or unreadable, older than `max_age_hours`, or built from other roots than the current directory and config give; `--refresh` forces it and `--no-auto-scan` disables it. An existing `--registry FILE` is used as is. The registry now stores `roots_signature` and `built_with`.
- `list [--names] [--source S] [--profile P] [--all] [--json]`: every non-internal skill with its state (`hot`, `cold` or `tool`), so the whole inventory can be read when search is weak.
- Spanish support: accent folding on queries and documents, Spanish stopwords, and a `translations` table (about 570 words and phrases) in `orchestrator/data/synonyms.json` whose English equivalents count as the user's own query words.
- `find --also "phrasing"` (repeatable): extra wordings of the same request, merged by id with the best score.
- `find` weak-match signal: an `also consider (name match)` list (up to 10 entries whose id contains a query word of four or more characters) and a `WEAK MATCH` line when the best score is below 3.0 or fewer than 3 skills matched; `--json` adds `also_consider` and `coverage` (`weak`, `best_score`, `hint`).
- 70 new unit tests in `tests/test_discovery.py` (260 in total), including a hermetic fixture of 12 Spanish requests over a 26-skill synthetic corpus (synthetic: it shows the mapping works, not general recall). `tests/__init__.py` points the config and registry environment variables at a folder that is never created, so no test reads the real home directory.

### Changed

- `scan` with no `--root` and no `--vendor` now builds from the config, the platform folders and the current project, and writes to the configured registry. Before, it indexed only the platform folders and silently replaced a registry that also held a cold library or other projects' skills. With explicit roots it behaves as before unless `--config FILE` is passed, and prints a note when that replaces the default registry.
- Default registry path: `registry` from the config, then `SKILLS_ORCHESTRATOR_REGISTRY`, then `~/.skills-orchestrator/registry.json`.
- A `--catalog` file that cannot be read is a warning instead of an exception.
- `find` shows `matched:` for each result (the terms of the request, after translation, that the skill contains) and prints `WEAK MATCH` also when no shown result contains at least two of those terms, so one shared word such as "server" is never read as a match.
- The orchestrator skill (`SKILL.md`, now under 110 lines) works for requests in any language and any project. The startup `scan` step and the instruction to continue without a skill when the best score is weak are gone. New sections: "Two sources, every time", "Search in English" and "Coverage rule (mandatory)".

### Known limitations

- Spanish support covers the listed words only; other languages are not covered.
- Skills injected by a host service (not on disk) are still invisible to the registry; the skill tells the agent to check the platform's own list.
- The weak-match thresholds (3.0 and 3 results) are rough guards chosen on small registries.

## [0.1.0] - 2026-10-11

First release. Pre-release quality: documented limits are listed in the README.

### Added

- `scan`: builds a JSON registry of `SKILL.md` files from platform folders, plugin caches (`--root PATH::SOURCE`) and directories of cloned repositories (`--vendor DIR`). Identical content is merged under several paths; different content under the same source and name becomes `variants`. Skills that ship only in hidden or docs/config folders of a cloned repository are flagged `internal`. Prints "new since last scan". `--check` verifies that merging and de-duplication lost none of the `SKILL.md` files the walker found (it does not prove discovery found everything). `--catalog FILE` adds CLI, MCP, hook and gateway items as searchable tool entries.
- `find`: BM25 search over name (weighted three times), description and `when_to_use`, with a light stemmer and query-only synonym groups and phrases at half weight (`orchestrator/data/synonyms.json`). Profiles (`core`, `code`, `docs`, `research`, `business`, `reverse`) filter by id glob. Options: `--profile`, `--profiles-dir`, `--overrides`, `-k`, `--all`, `--json`.
- Output hygiene: descriptions are stored raw but returned sanitized (300 characters, zero-width, bidirectional and control characters removed) and labeled untrusted.
- `overrides.json` next to the registry for per-skill tags, notes and the `internal` flag; never overwritten by a scan.
- `overlaps`: name collisions and keyword-overlap pairs between skills from different sources.
- `conflicts`: 12 curated conflict clusters (`tdd`, `plan-and-spec`, `clarifying-questions`, `debugging`, `code-review`, `process-weight`, `output-compression`, `code-intelligence`, `web-access`, `prose-style`, `business-validation`, `reverse-engineering`) with relations (alternatives, complementary, contradictory) and policies (compose, prefer-by-context, owner-pin). `--id` shows the clusters that list one skill.
- `doctor`: checks for broken paths, duplicate names across sources, descriptions over 1536 characters, frontmatter, estimated listing budget against 1% of the context window, and hook collisions between known output-rewriting tools (`rtk`, `context-mode`).
- `vet`: static safety scan with 19 rules (INJ-01, INJ-02, EXEC-01, EXEC-02, OBF-01, CFG-01, CFG-02, NET-01, UNI-01, UNI-02, SKIP-01, SKIP-02, INST-01, INST-02, HOOK-01, MCP-01, LIC-01, LIC-02, LIC-03). Exit code 2 when a finding is at or above `--fail-on` (default `high`).
- Platform adapters as data (`orchestrator/data/platforms.json`): Claude Code (verified-live), the universal agents folder and OpenAI Codex (present), GitHub Copilot, Cursor, Gemini CLI, OpenCode and Windsurf (documented-only).
- The `skills-orchestrator` skill and a launcher, `skills/skills-orchestrator/run.py`, that works from any folder. Environment variable `SKILLS_ORCHESTRATOR_REGISTRY` and default registry `~/.skills-orchestrator/registry.json`.
- Claude Code plugin manifest and marketplace file in `.claude-plugin/`.
- A reviewed catalog of third-party skills and tools (`catalog/catalog.json`, rendered to `docs/CATALOG.md`).
- 183 unit tests (standard library `unittest`), including a hermetic recall fixture of 20 prompts over a 30-skill synthetic corpus.
- Repository checks: `scripts/render_catalog.py --check`, `scripts/check_english.py`, `scripts/check_privacy.py`.
- GitHub Actions workflow for Ubuntu, Windows and macOS on Python 3.9 to 3.14. It is written but had not run on GitHub at the time of this release.
- Documentation: README, architecture, adapters, conflicts, security model, tuning and roadmap, prior art, contributing guide, security policy, and a guide for coding agents.

### Security hardening

Found by an adversarial review before the first release; each item has a regression test in `tests/test_hardening.py`.

- `vet` cannot be stalled by a crafted file: every pattern gap is bounded and long lines are scanned in overlapping windows.
- `vet` no longer passes silently over files it cannot read: SKIP-01 (high) for files over 1 MB and SKIP-02 (medium) for NUL bytes in text files, which are scanned with the NUL bytes removed.
- `vet` evasions closed: continuation lines (backslash or trailing pipe), injection phrases split across lines, more pipe targets (`/bin/bash`, `sudo`, `python`, `node`, `perl`, `ruby`, `iex`), `bash <(curl ...)`, `sh -c "$(curl ...)"`, `iex` with a download, `pwsh -enc`/`-e`/`-ec`, case-insensitive EXEC-02 with `subprocess.Popen`, `os.popen` and `new Function(`, and more override phrasings.
- Invisible characters: every Unicode format character (Cf), blank-rendering fillers, Braille blank and variation selectors are stripped by `sanitize` and flagged by UNI-01/UNI-02. U+200D, U+FE0F and a leading byte order mark are allowed.
- `vet` scope extended: new `agent` scope (agent, rule and prompt files, root `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`); plugin and MCP manifests and scripts named in `hooks.json` are scanned as hook files.
- Third-party strings (names, sources, ids, paths, platforms, upstream URLs, vet file names, roots and snippets) are sanitized and capped when read and when printed; `\x0b`, `\x0c` and `\x1c` to `\x1f` become spaces.
- `find`, `vet`, `doctor` and the other commands write UTF-8 to piped output whatever the console code page.
- `scan` writes the registry atomically (serialize, write a temporary file, replace) and survives a wrong-shaped previous registry or a folder name with a lone surrogate.
- `--vendor` roots (and root specs with `contain`) do not follow links that leave the repository; a hidden alias of a visible folder no longer marks a shipped skill as `internal`; the shipped copy beats a shallower internal copy.
- `SKILL.md` reads are capped at 2 MB (`truncated` flag) and only regular files are read.
- JSON files are read with BOM tolerance; `doctor` skips malformed hook documents and warns about unreadable ones; invalid `--catalog` items are skipped with a warning and never produce an empty id.
- Search: `create`, `creating` and `created` (also `cache` and `generate` forms) share one stem, stop words are checked on the stem, and synonym expansion adds half the best match per group instead of summing, with phrases matched on word boundaries.
- CLI: `vet` on a missing path exits 2; profile names are restricted to letters, digits, `-` and `_`; a malformed profile or a deeply nested registry exits 2; text `find` shows kind and upstream.
- `scripts/check_privacy.py` also catches escaped, forward-slash and Git Bash Windows paths and exempts its own files by repository-relative path.
- CI: job timeout, Python 3.14 in the matrix, actions pinned to commit SHAs. The launcher prints a one-line error when the `orchestrator` package is missing.

### Known limitations

- Search is lexical; paraphrases that share no words with a skill are missed.
- Adapters for most platforms are documented-only.
- Skills injected by a host service (not on disk) are invisible to `scan`.
- `est_tokens` is a characters-divided-by-4 estimate.
- `tune` (usage-driven suggestions) is planned for v0.2 and is not implemented.

[Unreleased]: https://github.com/JAlvarado-exe/skills-orchestrator/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/JAlvarado-exe/skills-orchestrator/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/JAlvarado-exe/skills-orchestrator/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/JAlvarado-exe/skills-orchestrator/releases/tag/v0.1.0
