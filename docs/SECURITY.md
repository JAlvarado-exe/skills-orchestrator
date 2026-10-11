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

## What `vet` scans

`vet PATH` walks a cloned repository (skipping `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`; skipping files over 1,000,000 bytes and binary files) and applies line-based rules to files in three scopes.

| Scope | Which files |
| --- | --- |
| `skill` | Any file inside a folder that contains a `SKILL.md` (including subfolders), and any file under a `commands` folder |
| `hook` | Files under a `hooks` folder, and any file named `hooks.json` |
| `install` | `package.json` and files whose name starts with `install`, `setup`, `bootstrap` or `postinstall` |

It is a scan of what an agent loads or a machine runs. It is **not** an audit of a project's application code: a repository's ordinary source files outside these scopes are not read.

### Rules

| Rule | Severity | Scope | What it flags |
| --- | --- | --- | --- |
| INJ-01 | high | skill | Instruction-override or exfiltration phrasing ("ignore previous instructions", "disregard the system ...", "you are now in developer mode", `exfiltrat...`) |
| INJ-02 | medium | skill | Asks the model to conceal actions from the user |
| EXEC-01 | high | skill, hook, install | Downloads and executes remote code in one step (`curl`/`wget` piped to a shell, `irm`/`iwr` piped to `iex`, PowerShell `-enc`) |
| EXEC-02 | medium | skill, hook, install | Dynamic code or shell execution (`eval`, `exec(`, `os.system(`, `shell=True`, `child_process`, `execSync(`, `Invoke-Expression`) |
| OBF-01 | medium | skill, hook, install | Decodes an obfuscated payload (`b64decode`, `base64 -d`, `atob(`, `FromBase64String`) |
| CFG-01 | high | skill, hook, install | Writes agent configuration or shell startup files (`settings.json`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.bashrc`, `.zshrc`, `authorized_keys`, `.cursorrules` and similar) |
| CFG-02 | high | skill, hook, install | Reads or sends credential files (`.ssh`, `id_rsa`, `.aws/credentials`, `.npmrc`, `.netrc`, `.env`, `.git-credentials`) |
| NET-01 | medium | skill, hook, install | URL pointing at an executable or archive (`.exe`, `.sh`, `.zip`, `.whl`, `.jar` and similar) |
| UNI-01 | high | skill, hook | Invisible or bidirectional characters |
| UNI-02 | high | skill, hook | Unicode tag characters (hidden ASCII) |
| INST-01 | medium | install | `package.json` lifecycle script (`preinstall`, `install`, `postinstall`, `prepare`, `prepublish`, `preuninstall`, `postuninstall`) |
| INST-02 | medium | install | Installer script (shell, PowerShell, batch, Python or JavaScript): read it before running |
| HOOK-01 | medium | hook | A hook file that runs automatically on agent events: read the command before enabling |
| MCP-01 | info | any | A `.mcp.json` or `mcp.json` file defines MCP servers |
| LIC-01 | low | repository | No license file: reference only, do not redistribute |
| LIC-02 | low | repository | Restrictive or copyleft license (Elastic, Business Source, SSPL, AGPL, GPL, Commons Clause, Polyform) |
| LIC-03 | info | repository | License text not recognized: read it |

### Exit code and output

`vet` exits 2 if any finding is at or above `--fail-on` (default `high`; choices `high`, `medium`, `low`, `info`, `none`). Each rule shows at most `--max-per-rule` findings (default 20); the rest are counted and reported as suppressed. `--json` prints the full report.

## Limits: read this before trusting a report

- **A clean report is not proof of safety.** It means none of these patterns matched on a line.
- **False positives dominate.** Running `vet` on 13 popular skill repositories produced 79 high findings, almost all of them documentation text or comments that mention the risky patterns (for example a README that explains what `curl | sh` is). A human must read the hits.
- **Line-based regular expressions are easy to evade.** Splitting a string, using another language or another encoding, or spreading a pattern over several lines defeats them.
- **No semantics.** `vet` does not know whether a hook is dangerous, only that it exists.
- **No dependency analysis.** Packages that a lifecycle script installs are not inspected.
- **No sandboxing.** Nothing here prevents a skill from doing harm once the agent follows it; `vet` is an early filter for a human, not a guard.
- **Size and type limits.** Files over 1,000,000 bytes and binary files are skipped.
- **Scope.** Application code outside the three scopes is not read.
- **License detection is heuristic.** It looks for marker phrases in the first 3000 characters of a root `LICENSE`, `COPYING` or `UNLICENSE` file. It is not legal advice.
- **Descriptions are shortened, not understood.** Sanitizing removes hidden characters; it does not detect persuasive text. The precedence rule is what keeps a hostile description from outranking the user.

## Recommended workflow for a new skill

1. Clone into a quarantine folder, shallow and pinned to a commit.
2. `python -m orchestrator vet <folder>`. Open each hit and each listed hook and installer. Decide as a human.
3. Install the lowest-privilege way. Keep skills cold. Use release binaries with a verified checksum.
4. `python -m orchestrator scan`, read `new since last scan`, and classify the skill in `overrides.json`.

## Tests

`tests/test_vet.py` checks that each rule fires, that findings carry file and line, that summary counts and the per-rule cap work, that a clean skill has no high or medium findings, that restrictive licenses are flagged, and that binary and vendor folders are skipped. `tests/test_sanitize.py` covers `sanitize`. The CLI test checks that descriptions in `find` output are sanitized and labeled untrusted.
