# Language coverage

The prompt hook can search a local registry using the original message. English, Spanish, Portuguese, French, German, Russian, Arabic, Hindi, Chinese, Japanese, Korean and Swahili have test coverage. Coverage varies by vocabulary, inflection, script and task. Names, descriptions, paths and tags retain their supplied spelling. Only the search index is normalized.

## What the index recognizes

The offline tokenizer uses case folding and compatibility normalization. It folds Latin accents, preserves Devanagari vowel signs and kana voicing, and keeps Hangul syllables together. It splits adjacent writing systems so a technical identifier embedded in Chinese or Japanese remains searchable. A mixed-case identifier such as `SQLite` retains its folded literal spelling alongside its stem. Both spellings together contribute at most one exact-word score for that identifier.

The multilingual vocabulary maps words and short expressions to English concepts. The same map applies to skill names, descriptions, usage hints and override tags. A Japanese billing description can therefore match a French query or English keywords. The Spanish query vocabulary in `orchestrator/data/synonyms.json` also supplies English alternatives. Its common domain terms participate in document indexing. Synonyms, BM25F scoring and confidence gates still apply after tokenization.

Chinese and Japanese use longest known vocabulary matches inside unspaced text. Unrecognized stretches stay together. An unknown local name embedded in a longer unspaced string can be missed. Korean handling strips listed particles when the remaining form occurs in the vocabulary, including components of multiword terms. The vocabularies contain selected inflections for other languages. Homographs share an index across languages, and a single spelling can carry a different meaning in another context.

## Extending a local installation

To give one installed skill an organization-specific or regional name, use its existing registry ID and add the words to its tags in the user's `overrides.json`. For example, a French-language cellar skill can carry French and English search terms together.

```json
{
  "team/cellar": {
    "tags": ["vignoble", "barrique", "vineyard", "barrel"]
  }
}
```

To extend vocabulary for all skills, add short aliases under an English concept in the appropriate language section of `orchestrator/data/language_bridges.json`. Choose equivalent terms that occur independently of a particular skill ID. Keep Spanish entries under `translations` in `orchestrator/data/synonyms.json`. Exercise the raw query against unrelated distractors and a skill described in the target language. Changes to the document vocabulary change the tokenizer fingerprint and invalidate older indexed tokens.

When a host can translate, it can retain the raw request as the primary `find` query and pass English keywords or regional synonyms using repeated `--also` arguments. The tool searches each phrasing separately. The hook can run without a translation service, model credentials or a network connection.

## What was measured

These commands use the public synthetic registry. Each evaluation uses the hook's selection logic with session memory and feedback disabled.

```text
python -B -m orchestrator eval tests/fixtures/eval/cases.json --config tests/fixtures/eval/config.json
python -B -m orchestrator eval tests/fixtures/eval/audit_languages.json --config tests/fixtures/eval/config.json
python -B -m orchestrator eval tests/fixtures/eval/audit_cases.json --config tests/fixtures/eval/config.json
python -B -m unittest tests.test_international
```

| Raw hook fixture | Expected skill in top three | Mean precision among results shown, up to three | Positive cases with no suggestion | Correct silence on negatives |
| --- | ---: | ---: | ---: | ---: |
| Frozen English and Spanish regression | 30/30 | 0.961 | 0 | 10/10 |
| Parallel translations against English metadata | 72/72 | 0.993 | 0 | No negatives in fixture |
| Exploratory English and Spanish requests | 7/14 | 0.464 | 5 | 4/4 |

The parallel fixture covers six task families. Each of the twelve languages placed the expected skill first on all six. The Spanish outage request also showed an unrelated deployment skill. Before this implementation the same fixture produced 11/72 hits. The vocabulary was developed with access to these prompts. The translations have no independent native-speaker validation.

The exploratory fixture includes regional paraphrases and a follow-up with an implicit reference. Six of six English positives and one of eight Spanish positives had an acceptable result. Two Spanish requests showed an incorrect suggestion. The frozen regression produced zero forbidden suggestions.

The international unit tests exercise another task family with 12 invoice/payment requests and 12 one-term distractors. All 12 positive requests placed the ledger skill first, and all 12 distractors stayed silent. The reverse direction tests an English query against a skill description in each of the 12 languages. Other checks cover mixed-script identifiers, tags, vowel signs, Korean particles and combinations of domain terms. These authored cases establish specific supported behavior. Independent native-speaker requests, larger registries and live host translations remain unmeasured.
