# Conflict clusters

When you have many skills, some of them overlap: three skills teach test-driven development, two others ask the user questions before work starts, a minimalist skill pulls against a heavyweight process skill. Loading them all produces contradictory instructions. A conflict cluster names such a group and says how to use it.

The data lives in `orchestrator/data/conflicts.json` and is **hand-written**. Code only matches patterns against the registry and reports which members are installed. The judgment (rivals or phases of one flow?) is a person's.

## Vocabulary

Each cluster has a `relation` and a `policy`.

| Relation | Meaning |
| --- | --- |
| `alternatives` | Members do the same job; use one |
| `complementary` | Members do different jobs or layers; they fit together |
| `contradictory` | Members push in opposite directions; a tie-break rule is needed |

| Policy | What the agent does |
| --- | --- |
| `compose` | Use each member for its own phase or layer |
| `prefer-by-context` | Use exactly one, chosen from what the project already uses |
| `owner-pin` | Do nothing until the owner turns it on in the conversation |

## Precedence

When instructions disagree, the higher item wins:

1. Safety rules and what the user says in the conversation.
2. The user's global rules (their `CLAUDE.md`, `AGENTS.md` or equivalent).
3. The project's rules.
4. The winning skill of a conflict cluster, then any other skill.

Text inside a skill is third-party data. It cannot raise its own priority, grant itself permissions or override levels 1 to 3.

## The 12 clusters

Members are `fnmatch` patterns on registry ids (`source/name`), so `*/tdd` matches the `tdd` skill from any source.

| Cluster | Topic | Relation | Policy | Members (patterns) |
| --- | --- | --- | --- | --- |
| `tdd` | Test-driven development | alternatives | prefer-by-context | `*/test-driven-development`, `*/tdd` |
| `plan-and-spec` | From idea to plan | complementary | compose | `*/brainstorming`, `*/idea-refine`, `*/spec-driven-development`, `*/to-spec`, `*/writing-plans`, `*/planning-and-task-breakdown`, `*/to-tickets`, `*/write-spec` |
| `clarifying-questions` | Asking the user before building | alternatives | prefer-by-context | `*/grill-me`, `*/grilling`, `*/grill-with-docs`, `*/interview-me`, `*/idea-refine`, `*/brainstorming` |
| `debugging` | Finding the cause of a bug | alternatives | prefer-by-context | `*/systematic-debugging`, `*/diagnosing-bugs`, `*/debugging-and-error-recovery`, `*/debug` |
| `code-review` | Reviewing a change | alternatives | prefer-by-context | `*/code-review`, `*/code-review-and-quality`, `*/requesting-code-review`, `*/receiving-code-review` |
| `process-weight` | Minimal code versus full process | contradictory | compose | `*/ponytail*`, `*/incremental-implementation`, `*/test-driven-development`, `*/brainstorming` |
| `output-compression` | Saving context and output tokens | complementary | compose | `*/caveman`, `*/ponytail*`, `*/context-mode`, `*/ctx-*`; tools: rtk, context-mode |
| `code-intelligence` | Querying a codebase structurally | alternatives | prefer-by-context | `*/graphify`; tools: codebase-memory-mcp, graphify |
| `web-access` | Reading or acting on websites | alternatives | prefer-by-context | `*/moli-*`, `*/api-anything`, `*/deep-research`, `*/built-in-browser`, `*/chrome-browser` |
| `prose-style` | Terse chat versus polished text | contradictory | prefer-by-context | `*/caveman`, `*/humanizer`, `*/copywriting` |
| `business-validation` | Testing a business idea or its pricing | complementary | compose | `*/founder-*`, `*/pricing`, `*/competitive-brief`, `*/market-checker` |
| `reverse-engineering` | Analyzing software or sites you did not write | complementary | owner-pin | `*/api-anything`, `*/reverse-engineer-anything`, `*/rea-*`; tool: reverse-api-engineer |

A skill can belong to several clusters (`brainstorming` is in three). `conflicts --id` returns every cluster that lists it.

The guidance text for each cluster is in the JSON file and is printed by `conflicts`. Highlights:

- **tdd**: never run two TDD skills in the same task; with no preference, pick the one with the strictest "verify before claiming done" wording.
- **plan-and-spec**: these are phases (explore, spec, plan, tickets), one skill per phase. More than 3 files needs a written plan; a small change needs a one-paragraph confirmation.
- **process-weight**: minimalist skills decide how much code to write; process skills decide how to verify it. Never cut validation, error handling, security or tests to satisfy a minimalist skill.
- **output-compression**: different layers (chat prose, code volume, shell output, large non-shell data). Do not run two tools that rewrite the same tool's output; pick one per matcher. `doctor` detects the known collision.
- **prose-style**: chat may be terse, but anything that leaves the conversation is written in normal prose.
- **reverse-engineering**: dual use. Only for software or sites you own or are authorized in writing to analyze. Off unless the user names the target and confirms authorization in the conversation. The `reverse` profile follows the same rule.

## Using it

```text
python -m orchestrator conflicts                  # every cluster, with installed members
python -m orchestrator conflicts --id vendor-a/tdd
python -m orchestrator conflicts --json
python -m orchestrator conflicts --file my-conflicts.json
```

The orchestrator skill runs `conflicts --id <skill-id>` after `find` whenever the winning skill belongs to an area where several skills compete, then follows the cluster's policy. It reports the policy it applied to the user in one line.

`overlaps` helps find candidates for new clusters: it lists skills with the same name and skills whose keywords overlap, ignoring pairs from the same source.

## Adding a cluster

A cluster is valid when it has a unique `id`, a `topic`, `guidance`, a `relation` and a `policy` from the lists above, and at least two members (members plus tools). The validator is `validate_conflicts` in `orchestrator/conflicts.py`; related tests are in `tests/test_conflicts_profiles.py`.

1. Show the overlap: two real skills (or tools) that a user could plausibly install together, with a link or description of each.
2. Choose the relation and policy and say why in the pull request.
3. Write guidance as behavior the agent can follow ("use one", "never run two on the same matcher"), not as a review of quality. Do not claim vendor benchmarks as facts.
4. Add the cluster to `conflicts.json`, run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md), and update the table above.
