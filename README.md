# LetterWeave

Original MIT tooling for auditable synthetic English emails with seven overlapping purpose labels. Version 0.3.2. This is a code-only candidate; no public corpus, private pilot raw data, trained model or gold labels are included.

## Run offline

Use Python 3.11 or newer on macOS/Linux. The fixture runtime uses the standard library.

```sh
python -m email_corpus_forge plan --run ./runs/fixture
python -m email_corpus_forge run --run ./runs/fixture
python -m email_corpus_forge status --run ./runs/fixture
python -m email_corpus_forge export --run ./runs/fixture --out ./exports/fixture
python -m unittest discover -s tests -v
python tools/check_mutations.py
```

Fixture exports are explicitly marked software fixtures. Live corpus export is disabled. Optional live adapters require an injected client and frozen authorization, strict structured outputs, bounded calls and retained uncertain reservations; no key or account setup is included here.

## Evidence and limitations

133 isolated installed tests and 32 critical mutation checks pass locally. CI is configured but remote results are pending. The typography guard preserves curly/straight punctuation and rejects characteristic split contractions without rewriting raw text. Formatting checks retain punctuation, numbers and negation. These safeguards do not prove grammar, semantic equivalence or label accuracy.

Private development evidence exists, with unpooled versioned outcomes described in [readiness](docs/readiness-report.md). This code version has no fresh live-quality evidence. A future public corpus will be fresh synthetic, machine-labeled and not gold; unknown and failed items stay separate from accepted binary-label inputs. No private Gmail content or copied upstream code/corpus is used.

Code is [MIT](LICENSE). Intended data licensing is separately documented in [dataset licensing](docs/dataset-license.md). Public data requires applicable route terms, a completed data card and release approval. No full generation, training or publication occurs automatically.
