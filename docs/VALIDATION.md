# Release validation

The release targets three outcomes: discover relevant guidance across languages, keep prompt latency low with a large library, and make it possible to resume a methodology at its next eligible phase.

## Routing

The baseline is candidate commit `13ecb2f`. Both versions were evaluated against the same synthetic catalog and skill files. The evaluator reports the IDs actually shown in a capped hook block. The prompts and expected IDs are in [the fixtures](../tests/fixtures/eval/).

| Cases | Baseline hit at 3 | Release hit at 3 | Baseline silence | Release silence |
| --- | ---: | ---: | ---: | ---: |
| Frozen regression set | 30/30 | 30/30 | 10/10 | 10/10 |
| Six parallel task families across 12 languages | 11/72 | 72/72 | — | — |
| Exploratory paraphrases, follow-ups and status messages | 7/14 | 7/14 | 2/4 | 4/4 |

The frozen cases had zero forbidden results. The parallel phrases informed vocabulary work, so treat the gains as regression evidence. Exploratory failures remain useful examples of where context or language coverage needs work. [Evaluation protocol](EVAL.md) · [Language coverage](LANGUAGES.md)

## Scale

One Windows run with CPython 3.12.14 exercised the public synthetic benchmark. Cold includes registry construction and Python startup. Warm is 20 hook processes per size, with feedback and session memory disabled by the harness. Timing depends on filesystem, corpus and machine load.

| Entries | Cold hook | Warm median | Warm P95 | Find, 3 phrasings median | Overlaps |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 0.88 s | 263 ms | 295 ms | 226 ms | 0.23 s |
| 520 | 3.75 s | 257 ms | 272 ms | 247 ms | 0.39 s |
| 1,000 | 6.45 s | 259 ms | 298 ms | 271 ms | 0.87 s |
| 2,500 | 18.33 s | 309 ms | 329 ms | 336 ms | 4.15 s |

The 40-file repeated-name case grouped the files into 10 families in 0.55 seconds, compared with 5.74 seconds in the baseline audit. A private library with 598 skill files and 519 entries rebuilt in 10.35 seconds in memory, down from 134.16 seconds in the audit. An unchanged refresh reused comparison decisions and took 4.78 seconds. Run `python docs/audits/benchmark_routing.py` from the repository root to reproduce the public workloads.

## Mitigations and follow-up

| Finding | Shipped mitigation | What to measure next |
| --- | --- | --- |
| Translated terms and host-exposed skills can be missed | Shared vocabulary, original wording plus English phrasing, documented inventory fallback | Independently authored regional tasks and native skill descriptions across domains |
| Cold scans can exceed host hook timeouts | Faster comparisons, reusable snapshots, freshness checks for stale candidates, opt-out for cold scans | Cold P95 on more operating systems and libraries with dense overlap |
| Discovery does not establish permission, tool availability or phase completion | Owner pins, documentation state for tools, explicit workflow prerequisites and approvals, scanner coverage | Live installation, selection and application across host versions |
| Repeated suggestions can waste context and skew results | Count suggestions actually displayed, scope suppression by session, serialize concurrent updates and bound feedback | Original task completion time, token use and blinded artifact quality with and without the orchestrator |
| Linked launchers and packaged data can diverge | Single checkout is supported and wheel contents are smoke-tested outside source | Repeat install and update tests on host-specific plugin distribution paths |

Use cross-host tasks with a known deliverable, then score the deliverable against the same rubric in both conditions. Record host version, skill library version, language, retries and manual interventions. The routing benchmarks measure selection, while artifact evaluation measures the benefit the agent delivers.
