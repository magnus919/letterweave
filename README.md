# LetterWeave

Original MIT tooling for auditable synthetic English emails with seven overlapping purpose labels. Planned continuation: **v0.5 mixed-model workflow**. The generator and dataset are the deliverables; model training and hosted inference are outside scope.

## Run offline

Python 3.11 or newer; fixture execution uses the standard library.

```sh
python -m email_corpus_forge plan --run ./runs/fixture
python -m email_corpus_forge run --run ./runs/fixture
python -m email_corpus_forge status --run ./runs/fixture
python -m email_corpus_forge export --run ./runs/fixture --out ./exports/fixture
python -m unittest discover -s tests -v
python tools/check_mutations.py
```

Fixtures are software test artifacts, never the corpus. Live adapters require explicit bounded authorization and an injected client; no credential setup is included. Generation, export and publication are separate actions.

## Fresh dataset release

**Fresh release pending final QA.** The new cohort plans 1,000 candidates from 900 families: 750 ordinary messages, 200 controlled challenge messages from 100 parent/child families, and 50 context-sensitive messages. These are candidate counts, not retained or accepted counts. Final counts, distributions, exclusions and checksums will be recorded after QA and assembly. The intended release is LetterWeave 0.1.0; no dataset path is linked until the artifact exists.

Labels describe observable communicative purpose: correspondence, transactions/records, alerts/updates, newsletters/publications, promotions/outreach, community/discussions and scheduling/invitations. They overlap. Intended labels are hypotheses; final content-based review decisions determine released labels. Unknown, failed and disagreeing records are excluded from binary-label inputs. Complete all-negative vectors are valid without a quota.

The corpus is **synthetic, machine-labeled, not gold**. The cohort carries forward 248 actual Sol-produced records (247 previously finalized plus one cached generation). Future content generation and controlled mutations use Nous `openai/gpt-6-luna` (canonical `openai/gpt-6-luna-20260922`), requested reasoning effort `low`; review and re-review remain on `openai/gpt-6.1-sol`. Existing Sol content retains its original provenance. Mixed-model review reduces some shared-model coupling but does not establish independent ground truth. Native QA is separate from billed API generation/review, and does not provide gold annotation. Repeated factual themes and family descendants are correlated. No private Gmail content or copied upstream code/corpus is included. See [data card](docs/data-card.md) and [readiness](docs/readiness-report.md).

## Verification and assembly

The merged code PR's reviewed head passed remote CI: 155 tests and 35 critical mutation checks. The standalone dataset and scenario-plan verifiers have 25 focused integrity tests. The full local and isolated installed suites each passed180 tests. Those are implementation checks, not a claim of corpus accuracy; the current fresh dataset still requires final QA.

`email-corpus-forge assemble-release --runs RUN_A RUN_B RUN_C --out NEW_RELEASE --authorization authorization.json --qa-exclusions excluded-ids.json` performs offline sanitized assembly without generation or publication. It requires explicit release declarations and settled fresh runs. It omits unknown, failed, disagreeing, duplicate-quarantined and QA-excluded rows, retaining limited public lineage alongside separate content and label tables. Raw provider responses, hidden reasoning, credentials and private execution files are not public artifacts. Existing release destinations are never overwritten.

Code is [MIT](LICENSE); corpus licensing is separate. The publisher offers dataset MIT rights only to the extent held, without licensing provider models/services or third-party material. [Dataset licensing](docs/dataset-license.md) and [provider terms review](docs/current-provider-release-terms.md) describe the scope and remaining applicability uncertainty. No express dataset-only publication ban or general written-permission requirement was established. Publication remains an explicit external action.

## Continuation accounting and QA

Verified catalog Luna rates per million tokens: $0.10 prompt, $0.50 completion including reasoning, and $0.125 cache-write. Conservative input reservation uses $0.225/million without assuming cache discounts. Catalog/subscription accounting is not attributable invoice cost. The approved envelopes remain $25 for the fresh cohort and $30 cumulative; these are caps, not promises of completion.

Native QA of the existing 247 records used a nonopaque first batch of 100 and an opaque later batch of 147; 17 exclusions are provisional. This difference must be disclosed rather than claiming all QA was blinded. Final retained counts and model-by-record provenance remain pending. No completed dataset publication is claimed.

## Model-aware assembly and verification — pending final release

The adjunct `tools/assemble_model_release.py` assembles mixed-model provenance offline; `tools/verify_dataset.py` checks dataset schema v1 and model declarations. Neither generates or publishes. Example using local placeholders:

```sh
python tools/assemble_model_release.py --runs ./runs/ordinary ./runs/challenge ./runs/context-sensitive --out ./datasets/letterweave-0.1.0 --authorization ./release-authorization.json --qa-exclusions ./qa-exclusions.json
python tools/verify_dataset.py --dataset ./datasets/letterweave-0.1.0
```

Per record, `generation_model` is the normalized actual alias and `generation_model_version` retains the raw provider generation-model identifier/version; `review_models` and `review_model_versions` similarly preserve normalized actual review aliases and raw versions. Source `role_models` declares planned roles separately from `actual_generation_models`, `actual_generation_model_versions`, `actual_review_models` and `actual_review_model_versions`, which describe accepted-record evidence. A planned Luna generation role must not relabel old cached Sol output as Luna.

There are 248 actual Sol-produced records: 247 previously finalized plus one cached generation. Remaining generation uses Luna; no exact final Luna count is asserted before completion. The native-QA snapshot covers 267 records, including nineteen new Luna records and the cached Sol record. That twenty-record increment has nineteen accepted and one held, with no additional accepted-record exclusions. The earlier seventeen QA exclusions remain provisional quality decisions, not gold labels; the first 100 records used nonopaque IDs. Final retained counts remain pending.

All 208 tests passed locally and in an isolated installed package, including adversarial raw-response and review-history checks. Remote CI evidence remains tied to its exact reviewed commit; the final dataset payload is still pending.
