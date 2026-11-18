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
   -> read_skill                frontmatter + sha256 + normalized-text hash + listed flag
   -> build_registry            dedupe by content, merge by source/name, flag internal and hot, copy groups, stored tokens
   -> registry.json (v2)        entries + roots + missing_roots + errors + roots_signature + built_with + tokenizer
   -> ensure_registry           rebuild first if missing, stale, older format or built for other roots; upgrade v1 in memory
   -> find / list / overlaps / conflicts / doctor      read registry (+ overrides.json, policy)
   -> retrieval.retrieve        BM25F + confidence gates, order factors, one result per copy group
vet PATH                         reads a repository directly, does not use the registry
hook-prompt  (agent hook, stdin JSON)   -> select: input filter, ensure_registry(cwd from payload), policy, intent,
                                           session memory, retrieve, top 3; silent when nothing passes
                                        -> {"hookSpecificOutput": {"additionalContext": ...}} on stdout, exit 0 always
eval FILE                        runs cases through the hook's select (stateless) and prints precision at 3 and silence
```

## Modules

| File | Responsibility |
| --- | --- |
| `orchestrator/cli.py` | Argument parsing, `ensure_registry` and the commands: `scan`, `find`, `list`, `used`, `stats`, `eval`, `overlaps`, `conflicts`, `doctor`, `vet`, `hook-prompt` |
| `orchestrator/hook.py` | The prompt hook: `user_text` (input filter), `select` (the decision as data), `format_context` (capped block) and `run_hook` (payload parsing, JSON output, failure log) |
| `orchestrator/retrieval.py` | The one pipeline behind `find`, the hook and `eval`: gates, order factors, copy groups, and labels for skills, tools and workflows |
| `orchestrator/policy.py` | `blocked` and `preferred` patterns from the config and the project file `.skills-orchestrator.json` |
| `orchestrator/intent.py` | Keyword classification of the request (build, review, debug, research, write, decide, operate) |
| `orchestrator/session.py` | The hook's per-session memory of shown ids |
| `orchestrator/feedback.py` | `usage.jsonl`, shown counts and the bounded order factor |
| `orchestrator/evaluate.py` | Case files, precision at 3, silence and forbidden ids |
| `orchestrator/config.py` | Read the user config and assemble the root specs: platform folders, the current project's skill folders, `extra_roots`, `vendor` |
| `orchestrator/scan.py` | Walk roots, build the registry and its roots signature, estimate listing tokens, turn catalog items into tool entries |
| `orchestrator/skillfile.py` | Parse `SKILL.md` frontmatter (a YAML subset), hash the file, read `disable-model-invocation` |
| `orchestrator/search.py` | Script-aware tokenizer, local vocabulary, query expansion, BM25F ranking, confidence gates, name matches |
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
| `orchestrator/data/conflicts.json` | 20 hand-written conflict clusters | Maintainers |
| `orchestrator/data/synonyms.json` | Query-expansion groups and phrases, English (`stopwords_en`) and Spanish (`stopwords`) stopwords including generic task words, and the Spanish-to-English `translations` table | Maintainers, from missed prompts |
| `orchestrator/data/intents.json` | Intent keywords (English and folded Spanish) and the profile each intent ranks higher | Maintainers |
| `orchestrator/data/hook_skip.json` | Wrapper tags and prefixes of messages the harness writes, which the hook ignores | Maintainers, only with evidence from real transcripts |
| `orchestrator/data/profiles/*.json` | `core`, `code`, `docs`, `research`, `business`, `reverse` id filters | Maintainers; users can add their own with `--profiles-dir` |
| `config.json` (user-owned) | Where the user's skills live; see Configuration. Never written by the tool | The user |
| `registry.json` (generated) | The index. Contains local paths; git-ignored | `scan` |
| `overrides.json` (user-owned) | Per-skill tags, note, `internal` flag. Never overwritten by `scan` | The user |

## Registry

Top-level keys: `version` (2), `tokenizer` (fingerprint of the stopword lists and stemmer that produced the stored tokens), `generated`, `roots`, `missing_roots`, `files`, `errors`, `entries`, `roots_signature` (sorted root paths, catalog files and excluded prefixes the registry was built from; the current project's skill folders are roots) and `built_with` (`config` or `explicit`).

Each entry is keyed `source/name` (the `id`) and carries: `name`, `source`, `sources`, `platforms`, `hot`, `hot_platforms`, `internal`, `description`, `when_to_use`, `path`, `paths`, `variants`, `sha256`, `bytes`, `frontmatter_ok`, `listed`, `est_tokens`, and since version 2 `norm_sha` (hash of the text with line endings unified, trailing spaces and outer blank lines removed), `dup_group` (entries that are copies of one skill share it: same `norm_sha`, or the same name and at least 90% equal text by `difflib`) and `tok` (stored name and body tokens).

A version 1 registry, or one whose `tokenizer` differs from the running code, is upgraded in memory on load (`scan.upgrade_registry`: `norm_sha` falls back to `sha256`, `dup_group` to the id, tokens are recomputed). The automatic refresh treats either as stale and rewrites the file as version 2.

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
| `"blocked"` | `[]` | Ids, sources or glob patterns (case-insensitive) never shown by `find`, `list`, `eval` or the hook; `--all` shows them in `find` and `list` |
| `"preferred"` | `[]` | Same patterns; matching results are ordered higher (x1.25), never let through the gates |
| `"min_score"` | `1.7` | Lowest normalized score a result may have (see Search) |
| `"min_terms"` | `2` | Distinct request terms a result must share; grows for long requests |
| `"hook_min_chars"` | `8` | Messages shorter than this (after the input filter) are ignored by the hook |
| `"hook_skip_tags"` | `[]` | More wrapper tags for the hook to ignore, added to `data/hook_skip.json` |
| `"hook_top"` | `3` | Results the hook shows (at most 10; `--top` overrides) |
| `"state_dir"` | `state/` next to the registry | Session memory, `usage.jsonl` and `stats.json` |
| `"session_memory"` | `true` | Turn the hook's per-session suppression off |
| `"feedback"` | `true` | Turn the usage-based order factor and the shown counts off |

A project can add a file `.skills-orchestrator.json` (looked up from the current folder up to the first one with `.git`, never inside the home folder) with `blocked`, `preferred`, `min_score` and `min_terms`. Lists are added to the user's, numbers replace them; other keys are ignored.

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

On the prompt path, a compatible snapshot can be reused after expiry, including a second snapshot for the most recent project switch. The hook checks shortlisted stale files before emitting their paths. Set `"hook_cold_scan": false` to keep cold scans off the prompt path. Use `scan` or interactive `find` to populate a fresh snapshot. Root signatures include scan settings and catalog fingerprints.

Registered workflows enter through the opt-in catalog. The `workflow` command validates phase prerequisites and resolves local instruction files. See [Workflow guides](WORKFLOWS.md).

## Search

1. Fold and tokenize with script-aware normalization. Latin accents fold and combining marks significant to other scripts are retained. The tokenizer separates adjacent scripts.
2. Stem English terms lightly and preserve recognized exact product identifiers.
3. Index the name, tags, description and usage hints. Localized terms contribute shared concepts. See [Language coverage](LANGUAGES.md).
4. Keep lexical evidence tied to independent query units, including when a recognized phrase has multiple token forms. Spanish query translations remain available alongside the shared vocabulary.
5. Query expansion, from `data/synonyms.json`: words in the same group, and the extra words of a matching phrase, are added to the query at **half weight**. They only widen the query; documents are never expanded, and the user's own words always outrank guesses.
6. BM25F with `k1=1.2`, `b=0.75`: each field's term frequency is normalized by that field's average length (over the entries that have the field) and weighted name 3, tags 2, body 1 before saturation.
7. Confidence gates (`search.confident_matches`). The score is divided by the weight of a word found in one entry only (`unit_weight`), so it reads roughly as a count of rare-word matches and the same threshold works for any registry size. A result passes when its normalized score is at least `min_score` (1.7; half of it for a one-word request), it shares at least `required_terms` distinct terms with the request (all of them for a request of one or two terms, else 2, plus one per 12 terms up to 5; a synonym group with a hit counts once), and it scores at least 0.35 times the best result. The gates use this score only.
8. Order factors (`retrieval.retrieve`), applied after the gates: `preferred` x1.25; members of the profile of the detected intent x1.2 (`intent.classify` over `data/intents.json`, printed as `# intent:`); the usage factor (see Feedback). They reorder results; none can make a result appear.
9. Copies: results with the same `dup_group` become one, shown as the best-placed copy (hot, then a platform's user folder, a project, a configured folder, a cloned library, a catalog tool) with `(+N copies)`.
10. `--profile` filters the pool first, using `fnmatch` patterns on ids. `find --also "phrasing"` (repeatable) gates each phrasing separately and keeps each entry's best score.
11. Output: each result is labeled `SKILL` (read its `read:` path) or `TOOL` (a program; `run (see its docs):` URL). When nothing passes, `find` prints the single line `NO CONFIDENT MATCH` (JSON: `"confident": false` and a fixed `hint`). After results, `find` lists up to 10 other entries whose id contains a query word of at least four characters (`also consider (name match)`).

`list` prints every non-internal entry sorted by id (`id  [hot|cold|tool]  description cut to 100 characters`; `--names` prints one id per line after a count line) so an agent can read the whole inventory after `NO CONFIDENT MATCH`. Blocked entries are left out unless `--all` is given. Its output is sanitized like `find`.

There are no embeddings. A paraphrase with no shared words will miss; see [TUNING.md](TUNING.md) for measured recall and the roadmap.

## Prompt hook

`orchestrator/hook.py` runs the search without the model. `hook-prompt` reads one JSON payload from stdin (decoded as UTF-8, a byte-order mark tolerated). `run_hook` returns `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "<block>"}}`, or an empty string when there is nothing to add. `select(prompt, cwd, ..., session_id, stateful)` returns the decision as data; `format_context` turns it into the block. Silence is the normal outcome:

1. Input filter (`user_text`): whole `<tag>...</tag>` blocks of the wrapper tags in `data/hook_skip.json` (task notifications, which is also how background agents report back; system reminders; local command echoes; CI monitor events) and of the config's `hook_skip_tags` are removed, and an unclosed listed tag hides the rest of the message. If what is left starts with a listed prefix (an interruption notice, a loaded skill's base directory, a continued-session summary), is shorter than `hook_min_chars`, starts with `/`, or has fewer than 2 query terms in its first 2,000 characters, the hook prints nothing. `<pasted_content>` is the user's text and is kept. `SKILLS_ORCHESTRATOR_HOOK` set to `0`, `off` or `false` turns the hook off. The registry is not touched in these cases.
2. `ensure_registry(args, cwd=<payload cwd>)`: the same rebuild rules as `find`, but the project skill folders and the roots signature come from the payload's folder (when it is an existing absolute directory). The rebuild message goes to stderr; stdout carries only the final JSON.
3. Policy from the config and the project file of the payload's folder; blocked entries are removed from the pool.
4. Session memory (`session.py`, when the payload has a `session_id` of letters, digits, `-` and `_`): an id shown twice in the session and not recorded with `used` since the session started is not shown again in it. Session files older than 7 days are deleted when one is written.
5. `retrieval.retrieve` with the usage factor, at most `hook_top` (3) results. No result means no output.
6. Format: a fixed header with the detected intent; per result `N. <id> SKILL|TOOL <state>[ (+N copies)] matched: <terms>` and a `read:` line (`run (see its docs):` for a tool); a fixed closing line that asks for `used` and points to the Coverage rule. Ids are sanitized to 120 characters and paths to 300. If the block would exceed 1,200 characters, path lines, then results, are dropped. Name matches are not listed by the hook.
7. When something was shown: the ids are added to the session file and to the shown counts in `stats.json`.

`eval` calls `select` with `stateful=False`, so neither session memory nor feedback is read or written.

`run_hook` never raises. A malformed payload gives an empty result; any other exception is swallowed and one line (time, exception type, message cut to 200 characters) is appended to `hook.log` next to the registry (`SKILLS_ORCHESTRATOR_HOOK_LOG` sets another path; a log that cannot be written is ignored). `cli.main` returns 0 for `hook-prompt` even after a usage error, because a non-zero status can block the user's message. The block never includes descriptions, `when_to_use` text, tags or notes; the threat model is in [SECURITY.md](SECURITY.md).

## Feedback

`used <id> [--helped yes|no]` appends `{"ts", "id", "helped"}` to `<state_dir>/usage.jsonl`; an id that is not in the registry (for example a skill the platform injects) is recorded with a warning. The hook counts how often it showed each id in `stats.json`. The order factor of an id is `1 + min(0.3, 0.1 x helpful uses) - min(0.3, 0.02 x (times shown - 5))`, and negative feedback can lower the rank. `stats [--top N] [--json]` prints the most used and the most ignored (shown, never used) ids. Nothing leaves the machine.

## Evaluation

`eval FILE` is described in [EVAL.md](EVAL.md), with the shipped cases and the recorded results.

## Conflicts

`conflicts.json` is hand-written because only a human, or a model reading both skills, knows whether two similar skills are rivals or phases of one flow. Code matches member patterns against registry ids and reports which members are installed. `overlaps` is the discovery aid for new clusters: it lists same-name skills and skills whose keyword sets overlap (overlap coefficient, at least 4 shared keywords, threshold 0.4 by default), skipping pairs from the same source. See [CONFLICTS.md](CONFLICTS.md).

## Doctor

Checks: `broken-paths` (fail), `duplicate-names` (warn, only across sources), `long-descriptions` (warn, over 1536 characters), `frontmatter` (warn), `listing-budget` (fail when the estimated hot listing exceeds 1% of `--window`, default 1,000,000 tokens), and `hook-collisions` (warn, only when `--settings` or `--plugin-hooks` is given). A collision is two different known output-rewriting tools (`rtk` and `context-mode`) on overlapping tools of the same `PreToolUse` or `PostToolUse` event. Several ordinary hooks on one matcher are legal and are not flagged. The command exits 1 if any check fails.

## Vet

See [SECURITY.md](SECURITY.md) for the rules, scope and limits.

## The orchestrator skill

`skills/skills-orchestrator/SKILL.md` gives the agent the routing procedure. Search the original request, an English rendering and a related wording. The intent profile adjusts order, while an explicit profile restricts eligibility. Check host-visible skills, and use `list --names` when the registry search abstains. Read the selected skill or use the phase resolver for a workflow. An owner pin takes precedence over the instruction path. Record feedback after observing the outcome. Independent reports or prompts help measure whether applied skills improve downstream work.

## Trade-offs and failure modes

| Choice | Benefit | Cost |
| --- | --- | --- |
| Lexical BM25 instead of embeddings | No dependencies, no model calls, reproducible, explainable | Misses paraphrases with no shared words |
| Cold library | Platform listing stays small | Relies on the model choosing to call `find`, unless the optional prompt hook runs the search on every message |
| Prompt hook with a fixed-shape block | The search no longer depends on the model; the block holds no third-party prose | One Python start per message; sees only what is on disk |
| Confidence gates and silence | The hook speaks only with evidence; no block for chat, notifications or quota questions | A real but weakly worded request can get no block; the Coverage rule covers it |
| Normalized score | One threshold for any registry size | In a registry of two or three skills almost every word is common, so little passes; `--min-score 0` shows everything |
| Generic words as stopwords | `code`, `file`, `run`, `build` no longer decide results | A skill whose only distinctive word is one of them is found by its other words only |
| Curated conflicts as data | Honest about judgment; reviewable in a diff | Needs maintainer effort; covers 20 topics only |
| Estimated tokens | Offline and fast | Approximate; differs from the host's real counting |
| Registry as one JSON file | Simple, diffable, no service | Contains local paths; rebuilt automatically when stale, which walks every configured root (slow for a very large `extra_roots`) |
| Index only what is on disk | Simple, deterministic scan | Skills injected by a host service are invisible to `scan`; the orchestrator skill tells the agent to check the platform's own list too |
| Offline multilingual vocabulary | Deterministic, reviewable and usable without credentials | Coverage depends on listed terms, document language and phrasing |
