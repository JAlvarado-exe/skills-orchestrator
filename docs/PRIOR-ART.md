# Prior art

Consulted on 2026-10-11. These tools change quickly; check the linked pages for their current behavior. This page describes what each one is as far as this project could verify, and where skills-orchestrator differs. It is not a ranking.

## Related tools

| Tool | What it is | Source |
| --- | --- | --- |
| Claude Code native skill management | The host's own handling of skills: a capped listing (1% of the context window), `/doctor`, `/skill-doctor`, the `skillOverrides` setting (on, name-only, user-invocable-only, off; not for plugin skills) and `skillListingBudgetFraction` | [Claude Code docs](https://code.claude.com/docs/en/skills) |
| Vercel skills CLI and skills.sh | Install and manage skill packages for many agents | [Vercel docs](https://vercel.com/docs/agent-resources/skills) |
| meta-router | A hook that searches a local skill index and injects the top matches into the conversation. Its README claims that skills past roughly 30 to 50 get dropped; this project has not verified that claim | [Go package page](https://pkg.go.dev/github.com/dmmdea/meta-router) |

## How skills-orchestrator differs

| Aspect | Native Claude Code controls | Vercel skills CLI and skills.sh | meta-router | skills-orchestrator |
| --- | --- | --- | --- | --- |
| Main job | Manage what the host lists | Install and manage packages across agents | Inject likely skills per prompt | Index, search, arbitrate and vet a cold library |
| Platforms | Claude Code | Many agents | As described by its documentation | Any agent that can read files and run Python; only Claude Code was observed live (see [ADAPTERS.md](ADAPTERS.md)) |
| Skills the model can search | Those the host still lists | Not its purpose | Skills in its local index | Everything in the registry, by an explicit `find` call |
| Conflict handling | Not its purpose | Not its purpose | Not described here | 12 curated clusters with three policies ([CONFLICTS.md](CONFLICTS.md)) |
| Safety scan of new skills | Not its purpose | Not described here | Not described here | `vet` ([SECURITY.md](SECURITY.md)) |
| Mechanism | Host controls | Package manager | Hook that injects text | The model calls `find` and reads the file by path |

"Not its purpose" and "not described here" mean the source this project read does not describe that feature, not that the tool lacks it.

### Where they fit together

- Installing: a package manager such as the Vercel skills CLI can put skills on disk. The platform data lists `~/.agents/skills` as the folder used by the `npx skills` CLI, and `scan` can index it.
- Native controls: Claude Code's `skillOverrides` and budget settings act on what the host lists. skills-orchestrator acts on what stays outside the listing.
- Hook injection: meta-router pushes matches into the conversation from a hook. skills-orchestrator leaves the choice to the model, which costs a tool call but adds no hook. The two approaches could be compared; this project has not done so.

## What this project adds

- A cross-platform registry that does not depend on one host's listing.
- A cold library with lexical search, so the platform menu stays small.
- Curated conflict arbitration as reviewable data.
- A static safety scan, `vet`, for what an agent loads or a machine runs.

## Platform risk

The owner of an agent platform may add native skill search or a larger listing budget. If that happens, the search part of this project becomes less necessary on that platform. The parts expected to stay useful are cross-platform support (one registry across agents), conflict arbitration across skills from different sources, and `vet`, because a host that lists skills does not necessarily decide whether a stranger's skill is safe to install.

This is a judgment, not a measurement. If a host ships equivalent features, the right outcome for users is to use them, and this project's scope should shrink accordingly.
