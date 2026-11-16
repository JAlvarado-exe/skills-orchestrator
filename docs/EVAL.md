# Evaluation

`eval` runs a JSON file of cases through the same selection the prompt hook uses and prints precision at 3,
hit at 3, how many must-be-silent cases printed nothing, and how many forbidden ids were shown.

```text
python -m orchestrator eval tests/fixtures/eval/cases.json --config tests/fixtures/eval/config.json
```

## Metrics

| Metric | Definition |
| --- | --- |
| precision@3 | For each case that expects results: expected ids among the first 3 results shown, divided by the results shown (at most 3). A case with no results scores 0. Averaged over those cases. |
| hit@3 | Share of those cases with at least one expected id in the first 3. |
| silent | Must-be-silent cases for which the hook printed nothing at all. |
| silenced wrongly | Cases that expect results but got none. |
| forbidden shown | Forbidden ids that appeared in any result list. |

Session memory and usage feedback are never applied during `eval`, so the numbers are repeatable.

## The shipped cases

`tests/fixtures/eval/` holds a synthetic corpus of 45 skills and 3 catalog tools. Every description was written for this
repository. The corpus includes distractors that reproduce the problems seen in real use: a tool whose description is
full of generic words, an image generator, an instruction-file improver, three slightly different copies of one
skill, two copies of another, and a source that the config blocks (it stands in for a banned model gateway).

`cases.json` has 40 cases: 30 that expect a skill (14 English, 16 Spanish) and 10 that must stay silent (task
notification, system reminder, local command, interruption, cross-session message, small talk in two languages,
two quota questions, a thank-you). The cases were written before the retrieval changes and are frozen: do not edit
them to make a change pass. The corpus is small and was written by the same author as the code, so treat the
numbers as a regression check, not as a measure of real-world quality.

## Results

| Version | precision@3 | hit@3 | silent | silenced wrongly | forbidden shown |
| --- | --- | --- | --- | --- | --- |
| 0.1.2 (baseline, before retrieval v2) | 0.389 | 1.000 | 0/10 | 0 | 7 |
