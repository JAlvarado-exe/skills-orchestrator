# Tuning and roadmap

Two things can be tuned: how well `find` ranks skills, and how much of the platform's listing budget your skills use. This document also states what is measured, what is not, and what is planned.

## Measured recall

All numbers are the author's own measurements on small samples. "Hit" means at least one acceptable skill is in the top 3 results. Ranking is lexical (BM25 with a light stemmer and query-only synonyms); there are no embeddings.

| Set | Corpus | Prompts | Result | How to read it |
| --- | --- | --- | --- | --- |
| CI fixture, `tests/test_recall.py` | 30 synthetic skills written to imitate real descriptions | 20 | 20/20 | Optimistic: the corpus is synthetic and small. CI only asserts at least 80% |
| Author's registry, tuning set | About 150 shipped skills | 20 | 70% to 85% top-3 (14/20 to 17/20) | Gain after adding stemming and synonyms. The set was used to choose them, so it overstates general recall |
| Author's registry, held-out set | Same registry | 12 | 92% (11/12), unchanged | Written beforehand and not used for tuning. No improvement |

What the held-out result says: the changes did not hurt it and did not help it. Known misses are paraphrases that share no words with the skill's name, description or `when_to_use`. Treat `find` scores as keyword ranks, never as certainty. The orchestrator skill tells the agent to continue without a skill when the best score is weak.

## Tuning search

Search quality changes in four places, from least to most invasive.

| Lever | Where | Effect |
| --- | --- | --- |
| Tags and notes | `overrides.json` next to your registry: `{"source/name": {"tags": ["words"], "note": "text"}}` | Tags are appended to `when_to_use`, so they are searchable for that one skill. A note is shown with the result. Never overwritten by `scan` |
| Profiles | `orchestrator/data/profiles/*.json`, or your own folder via `find --profiles-dir` | Narrow the pool by id glob before ranking: `core`, `code`, `docs`, `research`, `business`, `reverse` ship with the package |
| Synonym groups and phrases | `orchestrator/data/synonyms.json` | Words in a group, and the extra words of a matching phrase, are added to the **query** at half weight. They never expand documents, and the user's own words always outrank guesses |
| Ranking code | `orchestrator/search.py` | Stemmer, field weights (name counted three times), BM25 constants |

Rules for synonym changes:

1. Start from a real prompt that missed. Record the prompt and the skill that should have matched.
2. Add the smallest group or phrase that fixes it. Prefer a phrase when a single word is ambiguous.
3. Re-run both your tuning prompts and a held-out set. If the held-out set drops, the change is overfitting.
4. Add a test to `tests/test_search_quality.py` that shows the new behavior, and one showing exact words still outrank synonyms.
5. Do not tune on the held-out set. Write a new one instead.

## Tuning the listing budget

1. `python -m orchestrator scan` then `python -m orchestrator doctor`. The `listing-budget` check compares the estimated tokens of hot, listed skills with 1% of the window (default window 1,000,000 tokens; set `--window` to your model's). The estimate is characters divided by 4, not a measurement, and the host may count differently.
2. Read `top_contributors` in `doctor --json`. Skills with long descriptions cost the most; the host also truncates each listing entry at 1536 characters, which `long-descriptions` reports.
3. Move third-party skills out of the platform's skills folder into a cold folder and index it with `scan --vendor DIR` (or `--root`). Keep the orchestrator skill and a few core skills in the menu.
4. Use the host's own controls where they apply: Claude Code has `skillOverrides` (on, name-only, user-invocable-only, off; not for plugin skills) and `skillListingBudgetFraction`. See the [Claude Code skills documentation](https://code.claude.com/docs/en/skills).
5. Do not copy a cold skill back into the platform folder to "activate" it. Read it by path. Copying spends the budget and can push other skills out of view.

`doctor` also reports names shared by skills from different sources, which are the cheapest conflicts to resolve.

## Roadmap

None of the items below is implemented in v0.1. They are plans, not promises.

| Item | Notes |
| --- | --- |
| v0.2 `tune` command | Usage-driven suggestions. It must count **Read** events on registry paths, not only Skill-tool events: a cold skill is read by path, not invoked through a Skill tool, so counting only Skill events would call every cold skill unused. Claude Code already records `skillUsage` and `pluginUsage` in `~/.claude.json` and has `/skill-doctor`; `tune` should build on that data rather than compete with it. It should **propose** profile diffs and never apply them |
| Optional embedding router | A later, optional layer for paraphrases. Not planned to become a dependency of the core package |
| More adapters | More platforms, each with evidence. See [ADAPTERS.md](ADAPTERS.md) |
| Real CI history | The workflow covers Ubuntu, Windows and macOS on Python 3.9 to 3.14. It is written but had not run on GitHub at the time of writing |

Not verified: how any host counts listing tokens exactly; how `find` recall behaves on registries or prompt styles other than the author's.
