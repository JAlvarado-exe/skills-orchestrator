## Summary

<!-- What changes and why, in one or two sentences. Link the issue: "Closes #123". -->

## Kind of change

- [ ] Fix
- [ ] Feature
- [ ] Data only (platform adapter, conflict cluster, synonym, profile)
- [ ] Vet rule
- [ ] Documentation
- [ ] Other

## Evidence

<!--
Data changes need evidence.
Platform adapter: what you observed, or the documentation link, and the platform version.
Conflict cluster: the overlapping skills or tools, with links.
Vet rule: a public example, and a near-miss that must not match.
Synonym: the prompt that missed, and recall on a held-out set before and after.
-->

## Checklist

- [ ] I wrote the failing test first (or this change is data or documentation only)
- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] `python scripts/render_catalog.py --check` passes
- [ ] `python scripts/check_english.py` passes
- [ ] `python scripts/check_privacy.py` passes
- [ ] `python -m orchestrator scan --root skills::self --check` passes
- [ ] Standard library only, no network access at runtime, Python 3.9 compatible
- [ ] No personal paths, emails, tokens or registry files in the diff
- [ ] English only
- [ ] I did not weaken, skip or delete an existing test
- [ ] Documentation and the `Unreleased` section of CHANGELOG.md are updated
- [ ] The change is limited to what the summary says
