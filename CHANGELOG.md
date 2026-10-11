# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-11

First release. Pre-release quality: documented limits are listed in the README.

### Added

- `scan`: builds a JSON registry of `SKILL.md` files from platform folders, plugin caches (`--root PATH::SOURCE`) and directories of cloned repositories (`--vendor DIR`). Identical content is merged under several paths; different content under the same source and name becomes `variants`. Skills that ship only in hidden or docs/config folders of a cloned repository are flagged `internal`. Prints "new since last scan". `--check` verifies the registry covers every `SKILL.md` on disk. `--catalog FILE` adds CLI, MCP, hook and gateway items as searchable tool entries.
- `find`: BM25 search over name (weighted three times), description and `when_to_use`, with a light stemmer and query-only synonym groups and phrases at half weight (`orchestrator/data/synonyms.json`). Profiles (`core`, `code`, `docs`, `research`, `business`, `reverse`) filter by id glob. Options: `--profile`, `--profiles-dir`, `--overrides`, `-k`, `--all`, `--json`.
- Output hygiene: descriptions are stored raw but returned sanitized (300 characters, zero-width, bidirectional and control characters removed) and labeled untrusted.
- `overrides.json` next to the registry for per-skill tags, notes and the `internal` flag; never overwritten by a scan.
- `overlaps`: name collisions and keyword-overlap pairs between skills from different sources.
- `conflicts`: 12 curated conflict clusters (`tdd`, `plan-and-spec`, `clarifying-questions`, `debugging`, `code-review`, `process-weight`, `output-compression`, `code-intelligence`, `web-access`, `prose-style`, `business-validation`, `reverse-engineering`) with relations (alternatives, complementary, contradictory) and policies (compose, prefer-by-context, owner-pin). `--id` shows the clusters that list one skill.
- `doctor`: checks for broken paths, duplicate names across sources, descriptions over 1536 characters, frontmatter, estimated listing budget against 1% of the context window, and hook collisions between known output-rewriting tools (`rtk`, `context-mode`).
- `vet`: static safety scan with 17 rules (INJ-01, INJ-02, EXEC-01, EXEC-02, OBF-01, CFG-01, CFG-02, NET-01, UNI-01, UNI-02, INST-01, INST-02, HOOK-01, MCP-01, LIC-01, LIC-02, LIC-03). Exit code 2 when a finding is at or above `--fail-on` (default `high`).
- Platform adapters as data (`orchestrator/data/platforms.json`): Claude Code (verified-live), the universal agents folder and OpenAI Codex (present), GitHub Copilot, Cursor, Gemini CLI, OpenCode and Windsurf (documented-only).
- The `skills-orchestrator` skill and a launcher, `skills/skills-orchestrator/run.py`, that works from any folder. Environment variable `SKILLS_ORCHESTRATOR_REGISTRY` and default registry `~/.skills-orchestrator/registry.json`.
- Claude Code plugin manifest and marketplace file in `.claude-plugin/`.
- A reviewed catalog of third-party skills and tools (`catalog/catalog.json`, rendered to `docs/CATALOG.md`).
- 106 unit tests (standard library `unittest`), including a hermetic recall fixture of 20 prompts over a 30-skill synthetic corpus.
- Repository checks: `scripts/render_catalog.py --check`, `scripts/check_english.py`, `scripts/check_privacy.py`.
- GitHub Actions workflow for Ubuntu, Windows and macOS on Python 3.9 to 3.13. It is written but had not run on GitHub at the time of this release.
- Documentation: README, architecture, adapters, conflicts, security model, tuning and roadmap, prior art, contributing guide, security policy, and a guide for coding agents.

### Known limitations

- Search is lexical; paraphrases that share no words with a skill are missed.
- Adapters for most platforms are documented-only.
- Skills injected by a host service (not on disk) are invisible to `scan`.
- `est_tokens` is a characters-divided-by-4 estimate.
- `tune` (usage-driven suggestions) is planned for v0.2 and is not implemented.

[Unreleased]: https://github.com/JAlvarado-exe/skills-orchestrator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/JAlvarado-exe/skills-orchestrator/releases/tag/v0.1.0
