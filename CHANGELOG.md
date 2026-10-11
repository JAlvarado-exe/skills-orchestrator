# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/JAlvarado-exe/skills-orchestrator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/JAlvarado-exe/skills-orchestrator/releases/tag/v0.1.0
