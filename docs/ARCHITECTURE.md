# Architecture

skills-orchestrator is a small, offline Python package (`orchestrator/`) plus one skill (`skills/skills-orchestrator/`) that teaches an agent how to use it. This document describes what each part does and why. Everything here was read from the v0.1.2 source; where behavior is a design choice rather than a measurement, it says so.

## Design in one paragraph

Third-party skills stay **cold** on disk. A registry indexes them, and rebuilds itself when it is missing, stale, or built for other roots than the current project and config give. Only the orchestrator skill and a few core skills appear in the platform's skill menu, so the listing stays small. When a task starts, the agent runs `find`, reads the winning `SKILL.md` by path, and, if several skills compete, runs `conflicts`. Counting, ranking and scanning are deterministic code; the model reads results and applies the chosen skill.

Constraints that shape the code:

| Constraint | Consequence |
| --- | --- |
| Python 3.9+, standard library only | No third-party search, YAML or HTTP libraries. A small lenient frontmatter parser and a hand-written BM25 are included |
| No network at runtime | `scan`, `find`, `doctor`, `vet` only read local files. Nothing is downloaded, checked against a server or sent anywhere |
| Works on any agent that can read files and run Python | The platform is data (`platforms.json`), not code |
| Descriptions come from strangers | Output is sanitized and labeled untrusted before it reaches a model |

## Data flow

```text
roots (config extra_roots and vendor, platform folders, plugin caches, this project's skill folders, --root, --vendor)
   -> find_skill_files          walk, follow links, loop guard, depth 12, exclude_paths
   -> read_skill                frontmatter + sha256 + listed flag
   -> build_registry            dedupe by content, merge by source/name, flag internal and hot
   -> registry.json             entries + roots + missing_roots + errors + roots_signature + built_with
   -> ensure_registry           rebuild first if missing, stale or built for other roots (not with an existing --registry)
   -> find / list / overlaps / conflicts / doctor      read registry (+ overrides.json)
vet PATH                         reads a repository directly, does not use the registry
hook-prompt  (agent hook, stdin JSON)   -> build_context: skip rules, ensure_registry(cwd from payload), rank, format a capped block
                                        -> {"hookSpecificOutput": {"additionalContext": ...}} on stdout, exit 0 always
```

## Modules

| File | Responsibility |
| --- | --- |
| `orchestrator/cli.py` | Argument parsing, `ensure_registry` and the eight commands: `scan`, `find`, `list`, `overlaps`, `conflicts`, `doctor`, `vet`, `hook-prompt` |
| `orchestrator/hook.py` | The prompt hook: `build_context` (skip rules, search, capped block) and `run_hook` (payload parsing, JSON output, failure log) |
| `orchestrator/config.py` | Read the user config and assemble the root specs: platform folders, the current project's skill folders, `extra_roots`, `vendor` |
| `orchestrator/scan.py` | Walk roots, build the registry and its roots signature, estimate listing tokens, turn catalog items into tool entries |
| `orchestrator/skillfile.py` | Parse `SKILL.md` frontmatter (a YAML subset), hash the file, read `disable-model-invocation` |
| `orchestrator/search.py` | Accent folding, tokenizer, stemmer, Spanish word table, query expansion, BM25 ranking, weak-match rule, name matches |
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
| `orchestrator/data/synonyms.json` | Query-expansion groups and phrases, Spanish stopwords, and the Spanish-to-English `translations` table | Maintainers, from missed prompts |
| `orchestrator/data/profiles/*.json` | `core`, `code`, `docs`, `research`, `business`, `reverse` id filters | Maintainers; users can add their own with `--profiles-dir` |
| `config.json` (user-owned) | Where the user's skills live; see Configuration. Never written by the tool | The user |
| `registry.json` (generated) | The index. Contains local paths; git-ignored | `scan` |
| `overrides.json` (user-owned) | Per-skill tags, note, `internal` flag. Never overwritten by `scan` | The user |

## Registry

Top-level keys: `version`, `generated`, `roots`, `missing_roots`, `files`, `errors`, `entries`, `roots_signature` (sorted root paths, catalog files and excluded prefixes the registry was built from; the current project's skill folders are roots) and `built_with` (`config` or `explicit`).

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

## Configuration and discovery

An optional user config makes sure the registry can cover every skill the user has. Default path `~/.skills-orchestrator/config.json`; override with the `SKILLS_ORCHESTRATOR_CONFIG` environment variable or `--config FILE`. Every key is optional; `~` and environment variables are expanded; a relative path is resolved against the config file's folder. The file is read with `jsonio.read_json`; a malformed one prints a one-line warning to stderr and is treated as empty, and a wrongly typed value is ignored with one warning.

| Key | Default | Meaning |
| --- | --- | --- |
| `"registry"` | `SKILLS_ORCHESTRATOR_REGISTRY`, else `~/.skills-orchestrator/registry.json` | Registry file to write and read |
| `"extra_roots"` | `[]` | Paths or `{"path", "source_from", "contain"}` objects, searched recursively for `SKILL.md` to depth 12. `source_from` defaults to `first-child`, `contain` to `false`. Internal-copy detection is off for these roots, so a skill in a project's `.claude/skills` is found |
| `"vendor"` | `[]` | Directories of cloned repositories: `first-child` sources, `contain` true, internal-copy detection on (same as `scan --vendor`) |
| `"catalogs"` | `[]` | `catalog.json` files added as tool entries; an unreadable one is a warning |
| `"exclude_paths"` | `[]` | Directory prefixes compared by real path; any directory under one is never walked under `extra_roots` |
| `"use_platform_roots"` | `true` | Include the roots of `platforms.json` that exist |
| `"use_cwd_project_roots"` | `true` | Include the current project's skill folders |
| `"max_age_hours"` | `12` | Registry age after which it is rebuilt on next use |
| `"overrides"` | next to the registry | Overrides file; ignored when `--registry` is explicit |
| `"profiles_dir"` | none | Extra profile folder, searched after `--profiles-dir` |

```json
{
  "registry": "~/.skills-orchestrator/registry.json",
  "extra_roots": ["~/work", {"path": "~/more-projects", "source_from": "first-child", "contain": false}],
  "vendor": ["~/skills-cold"],
  "catalogs": ["~/skills-cold/catalog.json"],
  "exclude_paths": ["~/work/old-archive"],
  "use_platform_roots": true,
  "use_cwd_project_roots": true,
  "max_age_hours": 12,
  "overrides": "~/.skills-orchestrator/overrides.json",
  "profiles_dir": "~/.skills-orchestrator/profiles"
}
```

**Root assembly** (`config.assemble_roots(config, cwd, use_platforms=True)`) returns, in this order: the platform roots that exist; the project folders `.claude/skills`, `.agents/skills`, `.github/skills`, `.cursor/skills`, `.gemini/skills`, `.opencode/skills` and `.codex/skills` found in `cwd` and each parent up to and including the first directory with a `.git` entry (source `project:<folder name>`, not hot, contained so a link leaving a freshly cloned project is not followed; the walk never enters the home folder and never goes above the filesystem root; a folder that is already a platform root is not listed twice); `extra_roots` with `exclude_paths` applied; `vendor`. Catalogs are added when the registry is built.

**`scan`.** With no `--root` and no `--vendor` it uses the assembly (config, platforms, current project) and writes to the configured registry. With explicit `--root` or `--vendor` it indexes only those (plus `--platforms` when given), as in v0.1.0, unless `--config FILE` is also passed; it then prints a note to stderr if no `--out` was given, because the default registry is replaced and the next `find` rebuilds it.

**Automatic refresh.** `ensure_registry(args)` runs first in `find`, `list`, `overlaps`, `conflicts` and `doctor`. It rebuilds the registry (atomically, through the same code as `scan` with no arguments) and prints `registry rebuilt: N entries` to stderr when the file is missing or unreadable, older than `max_age_hours` (file modification time), has a `roots_signature` different from the one the current directory and config would produce (a registry without one always differs), or `--refresh` is given. `--no-auto-scan` disables it. An explicit `--registry FILE` that exists is used as is unless `--refresh` is given; a missing one keeps the old error (`conflicts` still treats it as an empty registry). If the rebuilt registry cannot be written, a warning is printed and the in-memory copy is searched.

## Search

1. Fold and tokenize: Unicode NFKD, combining marks removed, lowercase; then Unicode word characters, dropping stopwords (English, plus the Spanish list in the `stopwords` array of `synonyms.json`) and single characters. Documents and queries go through the same folding, so accented and plain spellings match.
2. Stem lightly: `ies` becomes `y`; `ing` and `ed` are stripped (with doubled-consonant handling); a trailing `s` is dropped except `ss`. Tokens of three characters or fewer are left alone.
3. Document text is the name repeated three times plus the description plus `when_to_use` (which includes any tags from `overrides.json`).
4. Translation, queries only: a folded query word found in `translations` (as typed, then without a trailing `s` or `es`) adds its English words to the query as the user's own words, at full weight; the typed word stays. Keys with spaces (such as a two-word phrase) match as phrases. Words without an entry match nothing. Skills are written in English, so this is a bridge, not a second index.
5. Query expansion, from `data/synonyms.json`: words in the same group, and the extra words of a matching phrase, are added to the query at **half weight**. They only widen the query; documents are never expanded, and the user's own words always outrank guesses.
6. BM25 with `k1=1.5`, `b=0.75`. Only entries with a score above zero are returned, up to `-k` (default 5).
7. `--profile` filters the pool first, using `fnmatch` patterns on ids.
8. `find --also "phrasing"` (repeatable) ranks each phrasing separately and merges by id, keeping the highest score.
9. After the results, `find` lists up to 10 other entries whose id contains (as a substring) a query word of at least four characters after translation (`also consider (name match)`; more distinct hits first), and decides whether the result is weak: best score below `WEAK_BEST_SCORE` (3.0) or fewer than `WEAK_MIN_RESULTS` (3) matched entries. Both constants sit at the top of `search.py`; BM25 scores grow with corpus size, so they are rough guards. A weak result prints a fixed `WEAK MATCH` line (`coverage.hint` in JSON): rephrase in English with two more wordings, check the platform's own skill list, and run `list --names`.

`list` prints every non-internal entry sorted by id (`id  [hot|cold|tool]  description cut to 100 characters`; `--names` prints one id per line after a count line) so an agent can read the whole inventory when search is weak. Its output is sanitized like `find`.

There are no embeddings. A paraphrase with no shared words will miss; see [TUNING.md](TUNING.md) for measured recall and the roadmap.

## Prompt hook

`orchestrator/hook.py` runs the search without the model. `hook-prompt` reads one JSON payload from stdin (decoded as UTF-8, a byte-order mark tolerated). `run_hook` returns `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "<block>"}}`, or an empty string when there is nothing to add. `build_context(prompt, cwd, config_path, registry_path, top)` is the pure part:

1. Skip, with an empty result: `SKILLS_ORCHESTRATOR_HOOK` is `0`, `off` or `false`; the prompt is not a string, is shorter than 8 characters after trimming, or starts with `/`; or the first 2,000 characters have fewer than 2 query terms (`search.query_terms`). The registry is not touched in these cases.
2. `ensure_registry(args, cwd=<payload cwd>)`: the same rebuild rules as `find`, but the project skill folders and the roots signature come from the payload's folder (when it is an existing absolute directory) instead of the process folder. A registry that cannot be read gives an empty result. The rebuild message goes to stderr; stdout carries only the final JSON.
3. `search.rank` over the non-internal entries, with the weak rule of `find` (`is_weak`, `is_covered`) applied to the one phrasing, plus up to 5 name matches (`name_matches`).
4. Format: a fixed header; up to `--top` (default 5, at most 10) lines `N. <id> (<state>) matched: <terms>`; a `read:` line (an `upstream:` line for a tool) for the first 3 results; `Also by name:`; the fixed `WEAK MATCH` line when the result is weak (also when nothing matched); and a fixed closing line that points to the Coverage rule, because the block cannot see skills a host injects. Ids are sanitized to 120 characters and paths to 300. If the block would exceed 1,200 characters, path lines, then results, then name matches are dropped; the header, the weak line and the closing line always stay.

`run_hook` never raises. A malformed payload gives an empty result; any other exception is swallowed and one line (time, exception type, message cut to 200 characters) is appended to `hook.log` next to the registry (`SKILLS_ORCHESTRATOR_HOOK_LOG` sets another path; a log that cannot be written is ignored). `cli.main` returns 0 for `hook-prompt` even after a usage error, because a non-zero status can block the user's message. The block never includes descriptions, `when_to_use` text, tags or notes; the threat model is in [SECURITY.md](SECURITY.md).

## Conflicts

`conflicts.json` is hand-written because only a human, or a model reading both skills, knows whether two similar skills are rivals or phases of one flow. Code matches member patterns against registry ids and reports which members are installed. `overlaps` is the discovery aid for new clusters: it lists same-name skills and skills whose keyword sets overlap (overlap coefficient, at least 4 shared keywords, threshold 0.4 by default), skipping pairs from the same source. See [CONFLICTS.md](CONFLICTS.md).

## Doctor

Checks: `broken-paths` (fail), `duplicate-names` (warn, only across sources), `long-descriptions` (warn, over 1536 characters), `frontmatter` (warn), `listing-budget` (fail when the estimated hot listing exceeds 1% of `--window`, default 1,000,000 tokens), and `hook-collisions` (warn, only when `--settings` or `--plugin-hooks` is given). A collision is two different known output-rewriting tools (`rtk` and `context-mode`) on overlapping tools of the same `PreToolUse` or `PostToolUse` event. Several ordinary hooks on one matcher are legal and are not flagged. The command exits 1 if any check fails.

## Vet

See [SECURITY.md](SECURITY.md) for the rules, scope and limits.

## The orchestrator skill

`skills/skills-orchestrator/SKILL.md` is the only part the model needs to load. Its protocol: there is no startup scan (the registry rebuilds itself; `scan` runs after installing a skill, followed by `vet` and a classification in `overrides.json`); for each new kind of task translate the request into English keywords, choose a profile, run `find` with two `--also` phrasings, read the whole winning `SKILL.md`, run `conflicts --id` if skills compete, and say in one line which skill was used. A coverage rule forbids saying that no skill applies before searching in English with two `--also` phrasings, checking the platform's own skill list (the registry cannot see skills a host injects) and, after a `WEAK MATCH`, reading `list --names`. It states the precedence order and a short list of things never to do (copy a cold skill into a platform folder, follow install commands written inside a skill, let a skill edit the user's instruction files, use the `reverse` profile without confirmed authorization, present scores as certainty).

## Trade-offs and failure modes

| Choice | Benefit | Cost |
| --- | --- | --- |
| Lexical BM25 instead of embeddings | No dependencies, no model calls, reproducible, explainable | Misses paraphrases with no shared words |
| Cold library | Platform listing stays small | Relies on the model choosing to call `find`, unless the optional prompt hook runs the search on every message |
| Prompt hook with a fixed-shape block | The search no longer depends on the model; the block holds no third-party prose | About 250 to 350 estimated tokens and one Python start per message; sees only what is on disk |
| Curated conflicts as data | Honest about judgment; reviewable in a diff | Needs maintainer effort; covers 12 topics only |
| Estimated tokens | Offline and fast | Approximate; differs from the host's real counting |
| Registry as one JSON file | Simple, diffable, no service | Contains local paths; rebuilt automatically when stale, which walks every configured root (slow for a very large `extra_roots`) |
| Index only what is on disk | Simple, deterministic scan | Skills injected by a host service are invisible to `scan`; the orchestrator skill tells the agent to check the platform's own list too |
| Spanish word table instead of a translation model | Offline, deterministic, reviewable in a diff | Covers listed words only and has no grammar; English keywords stay the reliable path |
