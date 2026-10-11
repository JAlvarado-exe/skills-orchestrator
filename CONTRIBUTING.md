# Contributing

Thanks for helping. This project is small on purpose: a standard-library Python package, a handful of JSON data files, and one skill. Contributions that keep it that way are the easiest to merge.

## Ground rules

- **English only** in code, data, docs, commits and issues.
- **Python 3.9+, standard library only.** No third-party dependencies, no network access at runtime.
- **Tests first.** Write a failing test, then the code that makes it pass.
- **One change per pull request.** If you notice something unrelated, open a separate issue or pull request.
- **No personal data.** No machine-specific paths, email addresses, tokens or private names anywhere in the tree. Use `~` for home folders. `scripts/check_privacy.py` enforces this.
- **Judgment goes in data.** Platform paths, conflict clusters, synonyms and profiles are JSON under `orchestrator/data/`. Code loads and matches; it does not hard-code opinions.

## Workflow

1. Fork the repository and create a branch from `main`.
2. Open an issue first for anything larger than a data tweak or a small fix.
3. Write the test. Run it and watch it fail for the right reason.
4. Make the change.
5. Run all checks (below). Every one must pass.
6. Update docs and [CHANGELOG.md](CHANGELOG.md) (the `Unreleased` section) when behavior or data changes.
7. Open a pull request using the template and fill in the evidence section.

## Checks

Run from the repository root. CI runs the same commands on Ubuntu, Windows and macOS with Python 3.9 to 3.14.

```text
python -m unittest discover -s tests -t .
python scripts/render_catalog.py --check
python scripts/check_english.py
python scripts/check_privacy.py
python -m orchestrator scan --root skills::self --check
```

If `render_catalog.py --check` fails after you edit `catalog/catalog.json`, run `python scripts/render_catalog.py` and commit the regenerated `docs/CATALOG.md`. Never edit `docs/CATALOG.md` by hand.

Do not weaken or delete an existing test to make a change pass. If a test is wrong, explain why in the pull request and fix the test in its own commit.

## Commit style

Conventional Commits, in English, imperative mood:

```text
feat: add Zed adapter to platforms.json
fix: skip unreadable directories during scan
docs: clarify the cold-library workflow
test: cover the held-out recall set
chore: bump CI action versions
```

Use `feat`, `fix`, `docs`, `test`, `refactor`, `perf` or `chore`. Keep the subject under about 72 characters.

## Proposing a platform adapter

Adapters are records in `orchestrator/data/platforms.json`. See [docs/ADAPTERS.md](docs/ADAPTERS.md) for the format.

- Give evidence: observed behavior (best) or a link to official documentation. State the platform version if you know it.
- Choose the lowest status the evidence supports: `documented-only`, `present` or `verified-live`.
- Use `~` and relative paths only.
- Update the platform table in `docs/ADAPTERS.md` and the README.

## Proposing a conflict cluster

Clusters live in `orchestrator/data/conflicts.json`. See [docs/CONFLICTS.md](docs/CONFLICTS.md).

- Name two or more real skills or tools that a user could install together, and describe the overlap.
- Pick a `relation` (`alternatives`, `complementary`, `contradictory`) and a `policy` (`compose`, `prefer-by-context`, `owner-pin`) and explain the choice.
- Write guidance as behavior the agent can follow. Do not present vendor claims as facts.
- The cluster must pass `validate_conflicts` in `orchestrator/conflicts.py`.

## Proposing a vet rule

Rules are in `orchestrator/vet.py`. See [docs/SECURITY.md](docs/SECURITY.md).

- Describe the real-world pattern, with a link if public, and the scope it applies to (`skill`, `hook`, `install`).
- Add tests in `tests/test_vet.py`: one case that must fire and at least one near-miss that must not.
- Choose severity by what the pattern allows, not by how common it is. Remember that a rule that fires mostly on documentation text produces noise.
- Add the rule to the table in `docs/SECURITY.md`.

## Proposing a synonym group or phrase

Synonyms are in `orchestrator/data/synonyms.json` and only expand the query, at half weight.

- Start from a real prompt that missed, and the skill it should have found.
- Add the smallest group or phrase that fixes it.
- Show recall on a held-out set did not drop. See [docs/TUNING.md](docs/TUNING.md).
- Add a test to `tests/test_search_quality.py`.

## Reporting security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the MIT license in [LICENSE](LICENSE).
