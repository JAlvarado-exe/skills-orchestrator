# Architecture

skills-orchestrator is a small, offline Python package (`orchestrator/`) plus one skill (`skills/skills-orchestrator/`) that teaches an agent how to use it. This document describes what each part does and why. Everything here was read from the v0.1.0 source; where behavior is a design choice rather than a measurement, it says so.

## Design in one paragraph

Third-party skills stay **cold** on disk. A registry indexes them. Only the orchestrator skill and a few core skills appear in the platform's skill menu, so the listing stays small. When a task starts, the agent runs `find`, reads the winning `SKILL.md` by path, and, if several skills compete, runs `conflicts`. Counting, ranking and scanning are deterministic code; the model reads results and applies the chosen skill.

Constraints that shape the code:

| Constraint | Consequence |
| --- | --- |
| Python 3.9+, standard library only | No third-party search, YAML or HTTP libraries. A small lenient frontmatter parser and a hand-written BM25 are included |
| No network at runtime | `scan`, `find`, `doctor`, `vet` only read local files. Nothing is downloaded, checked against a server or sent anywhere |
| Works on any agent that can read files and run Python | The platform is data (`platforms.json`), not code |
| Descriptions come from strangers | Output is sanitized and labeled untrusted before it reaches a model |

## Data flow

```text
roots (platform folders, plugin caches, --root, --vendor)
   -> find_skill_files          walk, follow links, loop guard, depth 12
   -> read_skill                frontmatter + sha256 + listed flag
   -> build_registry            dedupe by content, merge by source/name, flag internal and hot
   -> registry.json             entries + roots + missing_roots + errors
   -> find / overlaps / conflicts / doctor      read registry (+ overrides.json)
vet PATH                         reads a repository directly, does not use the registry
```

## Modules

| File | Responsibility |
| --- | --- |
| `orchestrator/cli.py` | Argument parsing and the six commands: `scan`, `find`, `overlaps`, `conflicts`, `doctor`, `vet` |
| `orchestrator/scan.py` | Walk roots, build the registry, estimate listing tokens, turn catalog items into tool entries |
| `orchestrator/skillfile.py` | Parse `SKILL.md` frontmatter (a YAML subset), hash the file, read `disable-model-invocation` |
| `orchestrator/search.py` | Tokenizer, stemmer, query expansion, BM25 ranking |
| `orchestrator/profiles.py` | Load a profile and filter entries by `fnmatch` patterns on ids |
| `orchestrator/overrides.py` | Apply the user's `overrides.json` (tags, note, internal) |
| `orchestrator/conflicts.py` | Load and validate `conflicts.json`, match clusters to installed ids |
| `orchestrator/overlaps.py` | Name collisions and keyword-overlap pairs |
| `orchestrator/doctor.py` | Registry health checks and hook-collision detection |
| `orchestrator/vet.py` | Static safety scan of a repository |
| `orchestrator/sanitize.py` | Strip invisible and control characters, flatten whitespace, truncate |
| `orchestrator/platforms.py` | Read `platforms.json` and resolve roots that exist on disk |
| `skills/skills-orchestrator/run.py` | Launcher that finds the package and calls `cli.main` from any folder |
| `scripts/` | `render_catalog.py`, `check_english.py`, `check_privacy.py` (repository checks, not part of the package) |

## Data versus code

Judgment that a person edits lives in JSON under `orchestrator/data/`. Code only loads and matches it.

| File | Holds | Edited by |
| --- | --- | --- |
| `orchestrator/data/platforms.json` | Where each platform keeps skills, status, `hot` flags | Maintainers, from documentation or observation |
| `orchestrator/data/conflicts.json` | 12 hand-written conflict clusters | Maintainers |
| `orchestrator/data/synonyms.json` | Query-expansion groups and phrases | Maintainers, from missed prompts |
| `orchestrator/data/profiles/*.json` | `core`, `code`, `docs`, `research`, `business`, `reverse` id filters | Maintainers; users can add their own with `--profiles-dir` |
| `registry.json` (generated) | The index. Contains local paths; git-ignored | `scan` |
| `overrides.json` (user-owned) | Per-skill tags, note, `internal` flag. Never overwritten by `scan` | The user |

## Registry

Top-level keys: `version`, `generated`, `roots`, `missing_roots`, `files`, `errors`, `entries`.

Each entry is keyed `source/name` (the `id`) and carries: `name`, `source`, `sources`, `platforms`, `hot`, `hot_platforms`, `internal`, `description`, `when_to_use`, `path`, `paths`, `variants`, `sha256`, `bytes`, `frontmatter_ok`, `listed`, `est_tokens`.

How entries are formed:

1. **Source.** A root has a fixed source name, or derives it from the folder layout: `first-child` (each child folder of a `--vendor` directory is a source) or `plugin-cache` (`plugin:<name>`, taken from the second path component under the cache root).
2. **Identical content.** Files with the same SHA-256 become one record with several `paths`. Symlinks resolve to a real path first, so a skill reached through two links is one file.
3. **Same source and name, different content.** The records are merged into one entry. The primary is chosen by: not internal first, then shallower path, then most recently modified. The others are listed under `variants`.
4. **`internal`.** Only for `--vendor` roots. A skill is internal when it sits under a hidden folder or one of `configs`, `docs`, `examples`, `tests`, `test`, `evals`, `worked`, `website`, `fixtures` inside a cloned repository (copies for other tools, docs, fixtures). `find` hides internal entries unless `--all` is passed or `overrides.json` sets `internal: false`.
5. **`hot`.** True when a platform root marked `hot` lists the skill. `doctor` sums `est_tokens` over hot, listed skills.
6. **`listed`.** False when the frontmatter sets `disable-model-invocation` to a true value. Unlisted skills have `est_tokens` 0.
7. **`est_tokens`.** `ceil((len(name) + min(len(description + when_to_use), 1536) + 30) / 4)`. It is a characters-divided-by-4 estimate, not a tokenizer measurement.
8. **Descriptions** are stored raw (up to 4000 characters) and sanitized only when returned. Names and sources are sanitized and capped at 100 characters when read, and every third-party string (id, path, platforms, upstream, vet file names) is sanitized again when printed.

Walking rules: excluded folders are `node_modules`, `.git`, `__pycache__`, `.venv`, `venv`, `.trash`; links are followed with a loop guard on real paths, visible folders before hidden ones; roots of cloned repositories (`--vendor`, or a spec with `contain`) do not follow links that leave the repository; maximum depth is 12. Frontmatter parsing is lenient: if `name` is missing the folder name is used; if `description` is missing the first paragraph of the body is used.

`scan --check` writes nothing. It compares the number of distinct real `SKILL.md` files the walker found with the number of paths in the registry and exits 1 on a mismatch. It verifies that merging and de-duplication lost nothing; it does not prove that discovery found everything, because both sides use the same walker. CI uses it on this repository's own `skills/` folder.

`--catalog FILE` adds entries of `kind: tool` (ids `catalog/<slug>`) for CLI, MCP, hook and gateway items in a catalog JSON file, so tools without a `SKILL.md` are searchable. They are never hot and cost 0 estimated tokens.

## Search

1. Tokenize: lowercase, Unicode word characters, drop stopwords and single characters.
2. Stem lightly: `ies` becomes `y`; `ing` and `ed` are stripped (with doubled-consonant handling); a trailing `s` is dropped except `ss`. Tokens of three characters or fewer are left alone.
3. Document text is the name repeated three times plus the description plus `when_to_use` (which includes any tags from `overrides.json`).
4. Query expansion, from `data/synonyms.json`: words in the same group, and the extra words of a matching phrase, are added to the query at **half weight**. They only widen the query; documents are never expanded, and the user's own words always outrank guesses.
5. BM25 with `k1=1.5`, `b=0.75`. Only entries with a score above zero are returned, up to `-k` (default 5).
6. `--profile` filters the pool first, using `fnmatch` patterns on ids.

There are no embeddings. A paraphrase with no shared words will miss; see [TUNING.md](TUNING.md) for measured recall and the roadmap.

## Conflicts

`conflicts.json` is hand-written because only a human, or a model reading both skills, knows whether two similar skills are rivals or phases of one flow. Code matches member patterns against registry ids and reports which members are installed. `overlaps` is the discovery aid for new clusters: it lists same-name skills and skills whose keyword sets overlap (overlap coefficient, at least 4 shared keywords, threshold 0.4 by default), skipping pairs from the same source. See [CONFLICTS.md](CONFLICTS.md).

## Doctor

Checks: `broken-paths` (fail), `duplicate-names` (warn, only across sources), `long-descriptions` (warn, over 1536 characters), `frontmatter` (warn), `listing-budget` (fail when the estimated hot listing exceeds 1% of `--window`, default 1,000,000 tokens), and `hook-collisions` (warn, only when `--settings` or `--plugin-hooks` is given). A collision is two different known output-rewriting tools (`rtk` and `context-mode`) on overlapping tools of the same `PreToolUse` or `PostToolUse` event. Several ordinary hooks on one matcher are legal and are not flagged. The command exits 1 if any check fails.

## Vet

See [SECURITY.md](SECURITY.md) for the rules, scope and limits.

## The orchestrator skill

`skills/skills-orchestrator/SKILL.md` is the only part the model needs to load. Its protocol: at session start run `scan`, vet anything new from outside the owner's own work, and classify it in `overrides.json`; for each new kind of task choose a profile, run `find`, read the whole winning `SKILL.md`, run `conflicts --id` if skills compete, and say in one line which skill was used. It states the precedence order and a short list of things never to do (copy a cold skill into a platform folder, follow install commands written inside a skill, let a skill edit the user's instruction files, use the `reverse` profile without confirmed authorization, present scores as certainty).

## Trade-offs and failure modes

| Choice | Benefit | Cost |
| --- | --- | --- |
| Lexical BM25 instead of embeddings | No dependencies, no model calls, reproducible, explainable | Misses paraphrases with no shared words |
| Cold library | Platform listing stays small | Relies on the model choosing to call `find` |
| Curated conflicts as data | Honest about judgment; reviewable in a diff | Needs maintainer effort; covers 12 topics only |
| Estimated tokens | Offline and fast | Approximate; differs from the host's real counting |
| Registry as one JSON file | Simple, diffable, no service | Contains local paths; must be re-scanned after changes |
| Index only what is on disk | Simple, deterministic scan | Skills injected by a host service are invisible to `scan` |
