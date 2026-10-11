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


### Sanitized live dataset assembly

`email-corpus-forge assemble-release --runs RUN_A RUN_B RUN_C --out NEW_RELEASE --authorization authorization.json --qa-exclusions excluded-ids.json` assembles an immutable directory offline. It never generates or publishes. The authorization JSON supplies `release_name`, semantic `version`, `rights_holder`, `publication_reference`, `terms_evidence`, and explicit `dataset_release_approved` and `redistribution_rights_confirmed` booleans. These are caller declarations, not legal clearance. QA exclusions are a JSON list of source record IDs.

Only complete, settled, declared fresh synthetic runs with matching source and rubric may enter. Final reviewed decisions determine labels. Unknown, disagreeing, failed, duplicate-quarantined and QA-excluded rows are omitted. Public tables contain subject/body, final labels and limited family provenance; raw API responses and hidden reasoning stay private. The MIT data license is distinct from the code license. Outputs are machine-labeled, not gold; family descendants and scenarios sharing factual themes are correlated. Atomic directory publication refuses existing destinations on macOS, Linux with renameat2, and Windows; other platforms fail closed. Power-loss durability is not guaranteed.

Explicit provider authorization retains a $10 default ceiling. Larger bounded runs require a separately supplied integer `approved_cap_micro` matching the actual approval, up to the library maximum $30. Multi-run controllers must enforce a shared cumulative budget; per-run authorization alone is insufficient. Near-duplicate index/candidate limits can be explicitly raised to2048 for small complete cohorts while remaining bounded.
