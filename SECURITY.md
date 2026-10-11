# Security policy

## Reporting a vulnerability

Please report privately. Do not open a public issue or pull request for a vulnerability.

Use GitHub private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. If that option is not visible, open a public issue that says only that you need a private channel, with no technical details, and a maintainer will respond with one.

Include, as far as you can:

- the version (`python -m orchestrator --version`) and your operating system and Python version;
- the command or file that triggers the problem;
- the impact you expect;
- a minimal reproduction, using synthetic files.

Do not include real credentials, your registry file (it contains local paths) or other people's private data.

This is a single-maintainer project. Reports are handled on a best-effort basis with no response-time guarantee. Credit is given in the release notes unless you ask otherwise.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Scope

In scope, for the code and data in this repository:

- Code execution, or file writes outside the paths a command is documented to write, caused by the `orchestrator` package or the `run.py` launcher.
- A way for text from a scanned skill to reach `find`, `conflicts` or `doctor` output without passing through `sanitize` (for example an invisible or control character that survives, or a registry field that is printed unsanitized).
- Path handling bugs in `scan` or `vet`, such as following links in a way that reads files outside the requested roots.
- Denial of service from a crafted skill tree or registry that makes a command hang or exhaust memory.
- A way to make `overrides.json`, profiles or the data files cause code execution when loaded.
- Manifest problems in `.claude-plugin/` that could install something other than what is documented.
- Secrets or personal data committed to the repository.

Out of scope, and better filed as a normal issue or pull request:

- `vet` false negatives for a new or obfuscated pattern. The scan is line-based and incomplete by design (see [docs/SECURITY.md](docs/SECURITY.md)); a rule request is welcome, but it is not a vulnerability.
- `vet` false positives.
- Malicious or unsafe content inside third-party skills. Report that to the skill's own maintainers.
- Wrong or outdated paths in `documented-only` platform adapters.
- Attacks that need an attacker to already control your user account or the registry file on your machine.

## What counts as a good report

A report is most useful when it shows a concrete path from attacker-controlled input (a `SKILL.md`, a frontmatter field, a file name, a hook file, `overrides.json`) to a harmful result (command execution, hidden text reaching a model, a file written elsewhere), with steps a maintainer can run.
