# Platform adapters

An adapter is a record in `orchestrator/data/platforms.json`. It tells `scan` where a platform keeps skills and whether the platform lists them in its menu. There is no per-platform code. The scanner itself works on any folder that contains `SKILL.md` files; adapters only supply default roots and the `hot` flag.

## What is tested

Be careful reading the table: **only Claude Code was observed live.** CI does not exercise any real platform. The unit tests use synthetic folders and a fake home directory to check that roots are expanded and missing roots are reported.

| Platform id | Name | Status | Roots in `roots` | Notes |
| --- | --- | --- | --- | --- |
| `claude` | Claude Code | verified-live | `~/.claude/skills`, `~/.claude/plugins/cache` | The platform was observed listing skills from these roots. Project folder: `.claude/skills` |
| `agents` | Universal agents folder | present | `~/.agents/skills` | Folder exists on the author's machine; loading not verified. The data records it as the folder used by the `npx skills` CLI and documented by setup guides for Copilot, Gemini CLI, OpenCode and Command Code |
| `codex` | OpenAI Codex | present | `~/.codex/skills` | Folder exists on the author's machine; loading not verified. The data notes that Codex starts from each skill name and description and loads the rest on demand |
| `copilot` | GitHub Copilot | documented-only | none | Project folders `.github/skills`, `.agents/skills`, `.claude/skills`; user-level folder is the `agents` entry |
| `cursor` | Cursor | documented-only | `~/.cursor/skills` | Project folder `.cursor/skills` |
| `gemini` | Gemini CLI | documented-only | `~/.gemini/skills` | Project folders `.gemini/skills`, `.agents/skills` |
| `opencode` | OpenCode | documented-only | none | Project folders `.opencode/skills`, `.agents/skills`, `.claude/skills`; the data notes it also reads `~/.agents/skills` and `~/.claude/skills` |
| `windsurf` | Windsurf | documented-only | none | No skills folder, only `.windsurfrules`; the data says to paste or reference skills from there |

Status meanings (from the file itself):

- `verified-live`: the platform was observed listing skills from these roots.
- `present`: the folder exists on the author's machine, but loading was not verified.
- `documented-only`: taken from a third-party repository setup guide, not tested here.

The paths for `documented-only` platforms may be wrong or out of date. If you use one of them, please verify and report (see below).

## File format

```json
{
  "version": 1,
  "note": "free text",
  "platforms": [
    {
      "id": "claude",
      "name": "Claude Code",
      "status": "verified-live",
      "roots": [
        {"path": "~/.claude/skills", "hot": true, "source": "claude-user"},
        {"path": "~/.claude/plugins/cache", "hot": true, "source_from": "plugin-cache"}
      ],
      "project_roots": [".claude/skills"],
      "instructions_file": "~/.claude/CLAUDE.md",
      "settings_file": "~/.claude/settings.json",
      "usage_file": "~/.claude.json"
    }
  ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Short platform id. Recorded in each entry's `platforms` and used by `doctor --platform` |
| `name` | yes | Display name |
| `status` | yes | One of the three statuses above. Defaults to `documented-only` when missing |
| `roots[].path` | yes | Folder to scan. A leading `~` expands to the home directory (or `scan --home` for testing); environment variables are expanded |
| `roots[].hot` | no | `true` if the platform lists skills from this folder in its menu. `doctor` counts only hot skills against the listing budget |
| `roots[].source` | no | Source name for every skill in this root (default: the platform id) |
| `roots[].source_from` | no | `fixed` (default), `first-child` (each child folder is a source) or `plugin-cache` (`plugin:<name>` from the folder layout) |
| `project_roots` | no | Folders relative to a repository. Informational: pass them to `scan --root` when you want them indexed |
| `instructions_file`, `settings_file`, `usage_file`, `lock_file`, `read_by`, `note` | no | Informational. Not used by the scanner |

Roots that do not exist on disk are skipped and counted under `missing_roots` in the registry.

## How scan uses adapters

- `scan` with no `--root` and no `--vendor` reads the bundled `platforms.json`.
- `scan --platforms FILE` reads your own file, and combines its roots with any `--root` or `--vendor` you also pass.
- `scan --root PATH::SOURCE` with no `--platforms` indexes only what you list. Those roots are not hot unless you describe them in a platforms file.

Getting `hot` right matters: a root marked hot when the platform does not list it makes `doctor` over-count the budget; a hot root marked cold makes it under-count.

## Adding or correcting a platform

1. Find evidence. Best: observe the platform listing a skill you placed in the folder. Otherwise cite official documentation. Third-party guides are acceptable only as `documented-only`.
2. Add or edit the record in `orchestrator/data/platforms.json`. Choose the lowest status the evidence supports. Do not put personal paths in it; use `~`.
3. Add or extend a test in `tests/test_doctor_platforms_cli.py` if you introduce a new field or behavior. A pure data change needs no new test, but the existing tests must pass.
4. Update the table in this file and in the README.
5. Run the checks listed in [CONTRIBUTING.md](../CONTRIBUTING.md).
6. In the pull request, state what you observed or link the documentation, with the date and the platform version if you know it.

To promote a platform from `documented-only` to `present` or `verified-live`, say in the pull request exactly how you verified it. "The folder exists" earns `present`; "the platform listed my test skill from this folder" earns `verified-live`.
