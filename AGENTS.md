# AGENTS.md

Guide for coding agents working in this repository. Humans should read [CONTRIBUTING.md](CONTRIBUTING.md); the rules are the same.

## What this repository is

`skills-orchestrator` is a platform-agnostic registry, search and safety scanner for agent skills (`SKILL.md`). It is a Python 3.9+ package (`orchestrator/`) using only the standard library, one skill (`skills/skills-orchestrator/`), JSON data files (`orchestrator/data/`), repository checks (`scripts/`) and tests (`tests/`). Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Commands

Run from the repository root. All of them must pass before you say a task is done.

```text
python -m unittest discover -s tests -t .
python scripts/render_catalog.py --check
python scripts/check_english.py
python scripts/check_privacy.py
python -m orchestrator scan --root skills::self --check
```

Use `python -B` if you do not want `__pycache__` folders. Run one test file with `python -m unittest tests.test_vet`.

## Success criteria

State a machine-checkable criterion before you start, for example "the new test fails, then `python -m unittest discover -s tests -t .` passes and the other four checks pass". "Improve the code" is not a criterion.

## Code conventions

- **Standard library only.** Do not add dependencies.
- **Python 3.9 syntax.** No `match` statements, no `X | Y` type unions evaluated at runtime, no parenthesized multi-item `with`. Modules start with `from __future__ import annotations` as the existing ones do.
- **No network access** at runtime. Nothing may download, upload or check a remote service.
- **Deterministic code decides.** Ranking, counting and scanning are code. Do not put model calls in the package.
- **TDD.** Write the failing test first, in `tests/`, using `unittest` and the helpers in `tests/helpers.py` (`write`, `skill`) to build synthetic skill trees in a temporary folder. Tests must not read the real home directory.
- **Style.** Follow the surrounding code: 4-space indent, double quotes, short docstrings that explain why, no commented-out code.
- **Keep changes small and orthogonal.** Touch only what the task needs. If you see something else to fix, report it instead of fixing it in the same change.
- **Do not weaken tests.** Never delete, skip, loosen or special-case a test to make it pass. If a test is wrong, say so and fix it in its own commit.

## Data versus code

| Change | Edit | Not |
| --- | --- | --- |
| Add or correct a platform | `orchestrator/data/platforms.json` (status must match the evidence) | `cli.py` or `platforms.py` |
| Add a conflict cluster | `orchestrator/data/conflicts.json` | `conflicts.py` |
| Add a synonym or phrase | `orchestrator/data/synonyms.json`, plus a test in `tests/test_search_quality.py` | `search.py` |
| Add a Spanish word or stopword | `translations` or `stopwords` in `orchestrator/data/synonyms.json` (folded, no accents; one entry per line), plus a test in `tests/test_discovery.py` | `search.py` |
| Add or change a profile | `orchestrator/data/profiles/<name>.json` | `profiles.py` |
| Add a vet rule | `TEXT_RULES` (or a dedicated check) in `orchestrator/vet.py`, with tests in `tests/test_vet.py` and a row in `docs/SECURITY.md` | The data files |
| Change the catalog | `catalog/catalog.json`, then `python scripts/render_catalog.py` | `docs/CATALOG.md` by hand (it is generated) |

When adding a vet rule: include one input that must fire and one near-miss that must not; if the rule is not in `TEXT_RULES`, also add its id and severity to `_rule_severity()` so the summary counts suppressed findings correctly.

## Privacy and language

- English only in code, data, docs and commit messages. `scripts/check_english.py` flags Spanish prose. The only Spanish allowed is the word lists in `orchestrator/data/synonyms.json` (`translations`, `stopwords`) and test data in `tests/`.
- Never add personal paths, home directories, email addresses, machine names or tokens. Use `~` for home folders and placeholders such as `<folder>`. `scripts/check_privacy.py` flags Windows and POSIX home paths and email addresses.
- The generated registry (`registry.json`) contains local paths and is git-ignored. Never commit it, paste it into an issue, or use it as a test fixture.
- Keep secrets and environment-variable files out of the repository and out of test fixtures.

## Things to be careful with

- `find` output is third-party text. Keep it sanitized (`orchestrator/sanitize.py`) and labeled untrusted.
- Do not make `scan` overwrite `overrides.json`.
- `est_tokens` is an estimate (characters divided by 4). Do not describe it as a measurement.
- Documentation claims about recall and `vet` results are the author's measurements on small samples. Do not strengthen them; add new numbers only with the method that produced them.
- Platform status values are `verified-live`, `present` and `documented-only`. Do not raise a status without evidence.

## Commits

Conventional Commits in English (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`). Do not commit or push unless the human asks you to.
