# Implementation and fresh-release readiness — proposed v0.5 mixed-model continuation

## Verified implementation

Original generator tooling provides frozen taxonomy/scenario plans, isolated content-only reviews, preserved first/latest/final judgments, uncertainty handling, immutable evidence, resumable checkpoints, family lineage, bounded requests, conservative cost reservations and duplicate diagnostics. Controller consensus never overwrites a disagreement with the latest answer. Mechanical literal-anchor/format checks do not establish semantic fact preservation.

Code PR 1 is merged at `0cb3f105`; reviewed head `7e642f6` passed remote CI with **155 tests and 35 critical mutation checks**. The standalone dataset and scenario-plan verifiers have25 focused tests. The full local and isolated installed suites each passed180 tests. Verification covers software behavior, not gold labels or real-inbox accuracy.

A sanitized offline assembler is implemented. It builds a new immutable release from compatible settled fresh runs, excludes unresolved/duplicate/QA-excluded records, writes content, labels, limited lineage, license and checksums, and refuses existing destinations. No publishing or generation occurs during assembly.

## Fresh cohort in progress

Planned denominator: **1,000 candidates / 900 families**, with 75% ordinary, 20% challenge and 5% context-sensitive messages. The challenge slice has 100 two-message parent/child families. All data is freshly synthetic; fixture outputs and historical private pilots are excluded. Retained, held, rejected, excluded and unattempted counts are not yet known and must not be inferred from planned totals.

The 247 existing generated records retain Sol provenance. Future content generation/mutation uses Nous `openai/gpt-6-luna`, canonical `openai/gpt-6-luna-20260922`, with requested reasoning effort `low`. Review/re-review stays on Nous `openai/gpt-6.1-sol`. Actual record/stage models must be recorded in final provenance. Blind reviewer contexts exclude intended labels, family/split metadata, previous answers and controller rationale. Existing Sol-generated/Sol-reviewed records retain same-model correlation; mixed-model continuation does not establish statistical independence. Native QA is an additional unbilled review activity, not a ground-truth labeling claim. Resource failures, missing context and semantic disagreement remain separate diagnostics.

## Remaining release checks

Complete the fresh cohort's settled accounting and final QA; run global duplicate, family-leakage and integrity checks across strata; assemble the retained subset; verify joins and checksums; and fill observed slice/label distributions and exclusions in the data card. An observed all-negative or unknown quota is not required. Never claim 1,000 accepted messages simply because 1,000 slots were planned.

The dataset is synthetic and machine-labeled, not gold. Related factual themes, selected scenarios and controlled descendants limit independence and representativeness. No population accuracy or real-inbox performance is established.

Public terms review establishes no express dataset-only publication ban or general written-permission requirement. Applicable upstream agreement for the exact Nous Sol route remains unidentified; record this uncertainty without treating model-training restrictions as a demonstrated dataset-publication ban. Dataset MIT applies only to publisher-held rights. Publication is a separate authorized external action; implementation tests do not clear third-party rights.

## Continuation evidence and accounting

Native QA covered 247 existing records: the first 100 were nonopaque and the later 147 opaque. Seventeen exclusions are provisional, not final retained counts. Disclose the mixed blinding conditions and preserve original evidence.

Verified Luna catalog rates per million: prompt $0.10, completion $0.50 inclusive of reasoning, cache-write $0.125; conservative input reservation $0.225. Subscription/catalog accounting does not establish actual invoice attribution. The fresh $25 and cumulative $30 caps remain unchanged. No completion or public dataset release is asserted.
