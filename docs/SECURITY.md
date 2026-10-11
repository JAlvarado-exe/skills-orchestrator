# Security model

This document describes what skills-orchestrator protects against, what `vet` checks, and what it cannot do. To report a vulnerability in this project, see the repository's [SECURITY.md](../SECURITY.md).

## Why skills are a risk

A skill is text that an agent reads and follows, often next to files that a machine runs: hooks, installers, package lifecycle scripts, MCP server definitions. Installing a skill from a stranger means giving a stranger a place in the agent's instructions. The main routes are:

| Route | Example |
| --- | --- |
| Instruction override in the skill text | "Ignore all previous instructions and ..." |
| Hidden instructions | Zero-width, bidirectional or Unicode tag characters that a human does not see |
| Download-and-execute | `curl ... | sh` written inside a skill or an installer |
| Config tampering | A skill that edits `settings.json`, `CLAUDE.md`, `AGENTS.md` or shell startup files |
| Credential access | A skill that reads `.ssh`, `.env`, `.npmrc` or sends them somewhere |
| Lifecycle scripts | `postinstall` in `package.json`, install scripts, hooks that run on agent events |
| Poisoned descriptions | A hostile description that is echoed into the model's context by a search tool |

## What this project does about it

1. **No network.** The package reads local files only. It downloads nothing and sends nothing.
2. **Descriptions are untrusted data.** The registry stores descriptions raw. `find` and other output pass them through `sanitize`: invisible characters (zero-width, bidirectional controls, word joiner, byte-order mark, the Unicode tag block) and control characters are removed, whitespace is flattened, and the text is cut to 300 characters. `find` prints a notice that descriptions are third-party text to treat as data. Vet snippets are sanitized and cut to 140 characters.
3. **Precedence.** The orchestrator skill states that text inside a skill cannot raise its own priority, grant permissions or override safety rules, the user's message, the user's global rules or the project's rules.
4. **Intake workflow.** The skill tells the agent to clone new skills into a quarantine folder, run `vet`, read every hook and installer it lists, install with the lowest privilege (cold skills stay where they are; binaries from a release with a checked hash), never run install commands written inside a skill, and never copy a cold skill into a platform folder.
5. **`vet`**, described below.
6. **Dual-use gating.** The `reverse` profile and the `reverse-engineering` cluster (policy `owner-pin`) stay off until the user names the target and confirms authorization in the conversation.

## Prompt hook: trust of injected context

`hook-prompt` (see the README) lets an agent run the search on every user message and put the result into the model's context through the host's hook channel. Hosts treat that channel as more trusted than a tool result, so text written by a stranger would carry more weight there than it does in `find` output. The hook is optional and off until the user adds it to their own settings.

| Threat | Mitigation |
| --- | --- |
| A hostile description, `when_to_use` text, tag or note is promoted into trusted context | The block never contains them. It holds only sanitized ids, the state word (`hot`, `cold`, `tool`), matched terms (words of the user's own message after translation) and paths, plus fixed text |
| A hostile id, name or path carries invisible characters, escape codes or line breaks | Every id (120 characters) and path (300) goes through `sanitize`: invisible, bidirectional and control characters are removed, whitespace is flattened to one line and the text is truncated. The header labels the lines as data, not instructions |
| An id forges a block line such as a fake `WEAK MATCH` or a closing line | Line breaks cannot survive `sanitize`, so every id stays on its own line. A test asserts that each line of the block has one of the known shapes |
| An id still reads like an instruction | Not fully prevented: the author of a skill chooses its name and folder, and 120 characters can hold a short sentence. The cap and the data label reduce the room; they do not remove it. Vet new skills before they enter the registry |
| The hook blocks or delays the user's message | It exits 0 for every runtime failure, caps the block at 1,200 characters and writes nothing on stdout but the final JSON. The host's `timeout` setting bounds the run time. A wrong command path (the launcher exits with status 2) is not covered |
| The hook edits configuration or reaches the network | It does neither: it reads the registry and config, may rewrite the registry through the normal refresh, and appends failures to `hook.log`. It never edits settings files. The code writes no prompt text to the log, only the exception type and a message cut to 200 characters |

## What `vet` scans

`vet PATH` walks a cloned repository (skipping `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`) and applies rules to files in four scopes. Every file in scope is either scanned or reported: a file over 1,000,000 bytes produces SKIP-01 and a text file with NUL bytes produces SKIP-02; other binary files (images and similar) are skipped silently.

| Scope | Which files |
| --- | --- |
| `skill` | Any file inside a folder that contains a `SKILL.md` (including subfolders), and any file under a `commands` folder |
| `agent` | Markdown and text files under an `agents`, `rules` or `prompts` folder (including `.claude/agents`), and the root files `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules` |
| `hook` | Files under a `hooks` folder, any file named `hooks.json`, the manifests `plugin.json`, `marketplace.json`, `.mcp.json`, `mcp.json` and `server.json`, and scripts (`.sh`, `.js`, `.mjs`, `.cjs`, `.py`, `.ps1`) named in a `command` of a `hooks.json` (resolved under the repository root; a prefix such as `${CLAUDE_PLUGIN_ROOT}/` is stripped) |
| `install` | `package.json` and files whose name starts with `install`, `setup`, `bootstrap` or `postinstall` |

It is a scan of what an agent loads or a machine runs. It is **not** an audit of a project's application code: a repository's ordinary source files outside these scopes are not read.

### Rules

| Rule | Severity | Scope | What it flags |
| --- | --- | --- | --- |
| INJ-01 | high | skill, agent | Instruction-override or exfiltration phrasing ("ignore previous instructions", "ignore the instructions above", "forget everything above", "disregard the system ...", "you are now in developer mode", `exfiltrat...`). Matched on the whole file, so a phrase split across lines is found |
| INJ-02 | medium | skill, agent | Asks the model to conceal actions from the user |
| EXEC-01 | high | skill, hook, install, agent | Downloads and executes remote code in one step: `curl`/`wget` piped to a shell or interpreter (`sh`, `/bin/bash`, `sudo bash`, `python`, `node`, `perl`, `ruby`, `iex`), `bash <(curl ...)`, `sh -c "$(curl ...)"`, `irm`/`iwr`/`DownloadString` piped to or wrapped in `iex`, `pwsh`/`powershell` with `-e`, `-ec` or `-enc` |
| EXEC-02 | medium | skill, hook, install, agent | Dynamic code or shell execution, case-insensitive (`eval`, `exec(`, `os.system(`, `os.popen(`, `subprocess.Popen(`, `new Function(`, `shell=True`, `child_process`, `execSync(`, `Invoke-Expression`) |
| OBF-01 | medium | skill, hook, install, agent | Decodes an obfuscated payload (`b64decode`, `base64 -d`, `atob(`, `FromBase64String`) |
| CFG-01 | high | skill, hook, install, agent | Writes agent configuration or shell startup files (`settings.json`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.bashrc`, `.zshrc`, `authorized_keys`, `.cursorrules` and similar) |
| CFG-02 | high | skill, hook, install, agent | Reads or sends credential files (`.ssh`, `id_rsa`, `.aws/credentials`, `.npmrc`, `.netrc`, `.env`, `.git-credentials`) |
| NET-01 | medium | skill, hook, install, agent | URL pointing at an executable or archive (`.exe`, `.sh`, `.zip`, `.whl`, `.jar` and similar) |
| UNI-01 | high | skill, hook, agent | Invisible characters: every Unicode format character (category Cf, which includes zero-width characters, bidirectional controls, soft hyphen, word joiners and a mid-file byte order mark) and the characters that render blank (U+034F, U+115F, U+1160, U+17B4, U+17B5, U+2800, U+3164, U+FFA0, variation selectors U+FE00 to U+FE0E). Not flagged: U+200D and U+FE0F (they occur in emoji) and a byte order mark at the very start of a file |
| UNI-02 | high | skill, hook, agent | Unicode tag characters (U+E0000 to U+E007F, hidden ASCII) and the variation selector supplement (U+E0100 to U+E01EF) |
| SKIP-01 | high | any file in scope | File not scanned: larger than 1 MB |
| SKIP-02 | medium | any file in scope | NUL bytes in a text file (`SKILL.md` or a Markdown, text, script, JSON, YAML or TOML file). The file is scanned with the NUL bytes removed |
| INST-01 | medium | install | `package.json` lifecycle script (`preinstall`, `install`, `postinstall`, `prepare`, `prepublish`, `preuninstall`, `postuninstall`) |
| INST-02 | medium | install | Installer script (shell, PowerShell, batch, Python or JavaScript): read it before running |
| HOOK-01 | medium | hook | A hook file or script named by `hooks.json` that runs automatically on agent events: read the command before enabling |
| MCP-01 | info | any | A `.mcp.json` or `mcp.json` file defines MCP servers |
| LIC-01 | low | repository | No license file: reference only, do not redistribute |
| LIC-02 | low | repository | Restrictive or copyleft license (Elastic, Business Source, SSPL, AGPL, GPL, Commons Clause, Polyform) |
| LIC-03 | info | repository | License text not recognized: read it |

### How matching works

- A line that ends with a backslash or a pipe is joined with the next one (up to five physical lines); the finding keeps the number of the first line.
- Every gap inside a pattern is bounded, and lines longer than 4000 characters are scanned in overlapping windows, so a hostile line costs linear time and a payload at the end of a very long line is still found.
- At most one finding per rule and line. Snippets are sanitized and cut to 140 characters.

### Link containment in `scan`

Cloned repositories passed with `--vendor` (root specs with `source_from: first-child`) are walked without entering or indexing anything whose real path is outside the repository, so a link inside a hostile repository cannot pull other files from your disk into the registry. A root spec can set `contain` to `true` or `false` to override this. Roots you pass with `--root` and the platform folders keep following links, because a personal skills folder legitimately links to other places. When a hidden folder links to a visible one, the visible path is kept, so a shipped skill is not demoted to `internal`.

### Exit code and output

`vet` exits 2 if any finding is at or above `--fail-on` (default `high`; choices `high`, `medium`, `low`, `info`, `none`). Each rule shows at most `--max-per-rule` findings (default 20); the rest are counted and reported as suppressed. `--json` prints the full report.

## Limits: read this before trusting a report

- **A clean report is not proof of safety.** It means none of these patterns matched on a line.
- **False positives dominate.** Running the first rule set of `vet` on 13 popular skill repositories produced 79 high findings (not re-measured after the hardening; the wider rules add hits), almost all of them documentation text or comments that mention the risky patterns (for example a README that explains what `curl | sh` is). A human must read the hits.
- **Line-based regular expressions are easy to evade.** Splitting a string, using another language or another encoding, or spreading a pattern over more than five lines defeats them.
- **No semantics.** `vet` does not know whether a hook is dangerous, only that it exists.
- **No dependency analysis.** Packages that a lifecycle script installs are not inspected.
- **No sandboxing.** Nothing here prevents a skill from doing harm once the agent follows it; `vet` is an early filter for a human, not a guard.
- **Size and type limits.** A file in scope over 1,000,000 bytes is not scanned and is reported as SKIP-01 (high). A file with NUL bytes in its first 4096 bytes that is not named like a text file is skipped silently as a binary.
- **Scope.** Application code outside the four scopes is not read. The `agent` scope matches folder names anywhere in the path but only for Markdown and text files.
- **License detection is heuristic.** It looks for marker phrases in the first 3000 characters of a root `LICENSE`, `COPYING` or `UNLICENSE` file. It is not legal advice.
- **Descriptions are shortened, not understood.** Sanitizing removes hidden characters; it does not detect persuasive text. The precedence rule is what keeps a hostile description from outranking the user.

## Recommended workflow for a new skill

1. Clone into a quarantine folder, shallow and pinned to a commit.
2. `python -m orchestrator vet <folder>`. Open each hit and each listed hook and installer. Decide as a human.
3. Install the lowest-privilege way. Keep skills cold. Use release binaries with a verified checksum.
4. `python -m orchestrator scan`, read `new since last scan`, and classify the skill in `overrides.json`.

## Tests

`tests/test_vet.py` checks that each rule fires, that findings carry file and line, that summary counts and the per-rule cap work, that a clean skill has no high or medium findings, that restrictive licenses are flagged, and that binary and vendor folders are skipped. `tests/test_sanitize.py` covers `sanitize`. The CLI test checks that descriptions in `find` output are sanitized and labeled untrusted.
