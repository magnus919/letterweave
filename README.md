# LetterWeave

Original MIT tooling and versioned synthetic English multi-label email corpora. Dataset 0.3.0 contains1,471 synthetic emails and accompanies Letterweave-1.1-E2B. Model training and hosted inference are outside the generator pipeline.

## Purpose contrasts and model 1.1

Tooling 0.7.0 adds opt-in `mail-realism-v2`, with separately versioned [purpose boundaries](docs/purpose-boundaries-v2.md) and a reproducible contrast inventory. Earlier profiles and datasets remain unchanged. [Dataset 0.3.0](datasets/letterweave-0.3.0/DATA_CARD.md) adds313 fully reviewed invented messages; train/development/test counts942/270/259. Related contrast groups share a model split. Incomplete source calls, excluded slots and unresolved accounting remain declared.

[Model 1.1](https://huggingface.co/Groktopus/Letterweave-1.1-E2B) and [HF dataset0.3.0](https://huggingface.co/datasets/Groktopus/Letterweave-0.3.0) contain usage and provenance documentation. The known 100-email assistant screen compares published Letterweave1.0 and1.1: acceptable label sets39->79 and missed alerts51->9. Meeting recaps improve0/9->9/9; job-match notices remain unacceptable0/4. This is development agreement, not independently labeled unseen accuracy. See [aggregate results](docs/letterweave-1.1-results.json). No private emails or per-message results are distributed.

## Realistic received-mail generation

Tooling 0.6.0 adds an opt-in [mail realism profile](docs/realism-profile.md) and a reproducible 160-family scenario inventory for dataset 0.2.0. It removes the fixed 2,200-byte body cap from this path and uses explicit provider token budgets instead. Long quoted histories, operational templates, and informative subject-only messages now have dedicated scenarios. Synthetic review remains advisory machine labeling.

## Run offline

Python 3.11 or newer; fixtures use the standard library and are software test artifacts, never corpus records.

```sh
python -m email_corpus_forge plan --run ./runs/fixture
python -m email_corpus_forge run --run ./runs/fixture
python -m email_corpus_forge status --run ./runs/fixture
python -m email_corpus_forge export --run ./runs/fixture --out ./exports/fixture
python -m unittest discover -s tests -v
python tools/check_mutations.py
```

Seven overlapping purposes: correspondence; transactions/records; alerts/updates; newsletters/publications; promotions/outreach; community/discussions; scheduling/invitations. Final complete content-based vectors determine labels. Unknown/missing/failed judgments never become negatives; complete all-negative vectors are permitted without a quota. The corpus is **synthetic, machine-labeled, not gold**. No private Gmail or copied upstream code/corpus is used.

## Fresh cohort and quality

Generation completed the planned cohort. Final retained counts, actual model evidence and native QA outcomes are consolidated in the verified dataset section below. Related factual themes and descendants are correlated. Intended labels/mutation relations are design hypotheses; mixed-model agreement is not ground truth.

## Accounting limits

Fresh settled conservative accounting: $8.512091; unresolved fresh reservation: $0.005700. Prior exposure is $1.122584, including an old unresolved $0.114000 reservation. Combined exposure is $9.640375 under the approved $25 fresh/$30 cumulative caps. These are catalog-based conservative estimates/reservations, not verified attributable invoice charges. Native QA is outside the provider ledger. A held uncertain request is not free, all-negative or semantically ambiguous by implication. Continuation does not reconcile its billing outcome.

## Offline assembly and verification

Use the model-aware adjunct as the primary mixed-model assembly route:

```sh
python tools/assemble_model_release.py --runs ./runs/ordinary ./runs/challenge ./runs/context-sensitive --out ./datasets/letterweave-0.1.0 --authorization ./release-authorization.json --qa-exclusions ./qa-exclusions.json
python tools/verify_dataset.py --dataset ./datasets/letterweave-0.1.0
```

Assembly never generates or publishes and refuses existing release destinations. Final content/label tables and limited provenance omit unresolved, duplicate-quarantined and QA-excluded rows. Raw provider responses, hidden reasoning, private execution evidence and credentials are excluded. Dataset schema-v1 verification checks joins, integrity and model evidence; it does not establish label accuracy.

Per-record `generation_model` and `review_models` are actual normalized aliases; `generation_model_version` and `review_model_versions` retain raw provider versions. Source `role_models` records planned roles separately from accepted actual model/version sets. Cached Sol content cannot become Luna merely because a continuation planned Luna generation.

All 217 tests passed locally and in an isolated installed package; all 35 critical mutants were caught. [PR 2](https://github.com/magnus919/letterweave/pull/2) records the exact reviewed head and remote-check evidence. Dataset verification passed; final retained counts are recorded below.

Code is [MIT](LICENSE); data MIT is separate and limited to publisher-held rights. No provider models/services or third-party material are licensed. [Data card](docs/data-card.md), [licensing](docs/dataset-license.md), [readiness](docs/readiness-report.md) and [terms review](docs/current-provider-release-terms.md) describe remaining limits. No express dataset-only publication ban or general written-permission requirement was established; actual upstream applicability remains unresolved. See [dataset 0.1.0](datasets/letterweave-0.1.0/DATA_CARD.md).

## Verified dataset 0.2.0

The revision contains **1,158 retained emails from 978 families**: the original 855 records plus 303 new invented records. Fresh generation planned 320 candidates across 160 families; 15 were held and two were excluded for obvious purpose-signalling disclaimers. No cross-family duplicates were quarantined in the combined retained-corpus lexical screen.

Family splits contain 755 training, 208 development and 195 test messages. The fresh subset contributes 182/65/56 messages respectively. Existing records retain their original labels and family split; new review guidance is separately versioned as `mail-realism-v1`. All labels remain machine-produced. Structural verification, lexical screening, and model review do not establish semantic quality or real-email accuracy. See [the 0.2.0 data card](datasets/letterweave-0.2.0/DATA_CARD.md).

Validation passed all 222 offline tests, all 35 critical safeguard mutations, isolated installed-package checks and dataset payload verification. Public files exclude private messages, identifying information, raw provider responses, credentials and host paths.

## Verified dataset 0.1.0

The assembled dataset contains **855 retained emails from 821 families**, out of 1,000 planned slots/900 families. The 145 excluded slots comprise 77 pipeline holds, 67 manual exclusions from pipeline-accepted rows and one descendant blocked by its excluded parent. A complete global duplicate audit added zero quarantine exclusions.

Retained slices: 712 ordinary, 127 challenge and 16 context-sensitive (schema slice `uncertainty`). Actual retained generation: 624 Luna and 231 Sol; all 855 records have Sol review evidence. Raw provider model identifiers are preserved as observed and are not silently replaced by catalog canonical IDs. Fourteen controlled transitions and three all-negative records are retained.

Per-label support (overlapping): correspondence 300; alerts/updates 303; scheduling/invitations 202; community/discussions 170; transactions/records 166; promotions/outreach 139; newsletters/publications 66. These counts describe machine labels, not independent accuracy measurements.

Native screening covered all 947 actual emails: first 100 nonopaque and subsequent 847 opaque. It recorded 67 accepted-row manual exclusions, 24 content semantic/context holds and 53 separate no-content slots. Independent audit confirmed 205 flagged records among the 855 retained; 60 of the 265 flagged actual records were not released. Focused contraction-pattern and control-character scans found zero matches; this does not establish flawless English. Packet-integrity checks found zero mismatches: 447 carried record files were byte-identical and 500 new blind-review packets matched final content. These checks do not prove naturalness, semantic equivalence or factual correctness.

The immutable payload and model-aware/scenario-plan verifiers passed. Dataset checksums and release commitments are supplied with the payload. [PR 2](https://github.com/magnus919/letterweave/pull/2) records reviewed-head and check evidence.
