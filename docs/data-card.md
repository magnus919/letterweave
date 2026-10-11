# Data card — development template

Status: no generated corpus release. Current fixture outputs are deterministic software test artifacts, not a corpus, and make no model-quality claims. Complete this card from a verified run before publication.

## Purpose and provenance

Fresh synthetic English email subject/body text with seven overlapping communicative-purpose categories. No private Gmail content, copied upstream corpus or upstream implementation is used. Spam detection and model training/deployment are outside scope. Any eventual release must say **synthetic, machine-labeled, not gold**.

Record release name/version, maintainer, taxonomy/schema/prompt versions and hashes, code revision, provider/model/settings, applicable terms evidence, authorization reference, run manifest hash, export checksums and actual spend. Do not include credentials or private configuration.

## Labels

Categories: correspondence; transactions/records; alerts/updates; newsletters/publications; promotions/outreach; community/discussions; scheduling/invitations. They are non-exclusive binary purposes, not statistically independent outcomes. Preserve intended and reviewed labels separately. Preserve present/absent/unknown judgments; accepted records need a complete decided vector. All-negative is valid, while uncertainty, unreadability, insufficient context and failed review remain held.

Evaluate the current message's observable subject/body purpose. Quoted replies do not automatically transfer purpose; explicit adopted forwards can. Signatures and incidental links do not establish purpose. Missing attachments/history must not be invented. Subjectless and subject-only legitimate mail can qualify. Scheduling is not automatically promotional; a personalized automated greeting is not automatically correspondence.

## Sampling and review

Historical planning proposed 24 families × five variants. Actual private development evidence is versioned and unpooled: initial pilot 24 actual emails, v0.2 30 actual emails, and the same v0.3/v0.3.1 diagnostic 21 actual emails (the stopped v0.3 two-email prefix is carried, not another corpus). See readiness-report.md for reconciled counts. These are selected single-purpose, overlap and boundary examples. No successful no-match quota is imposed. Report per-label positive/negative/near-negative family coverage and vary topic, tone and format across labels to avoid shortcuts. The whole pilot is development evidence; any 16/4/4 family split tests leakage mechanics only. Descendants inherit family assignments.

The fresh blind reviewer receives only opaque randomized ID, rubric/anchors, subject/body and schema. No conversation, intended labels, family/split metadata or previous answers/rationales; no tools/retrieval. Preserve immutable first-pass judgments before controller comparison. Positive evidence spans support applicable labels; quotations are not required to prove absence. Bounded blind re-review cannot establish gold truth; persistent uncertainty/disagreement is quarantined. Repair malformed/incoherent text only, or create an explicit descendant, never modify valid text to force agreement. No human labeling is required.

## Required release report

Report original candidate/family denominators, accepted/held/rejected/unattempted counts before and after repair; per-label support, unknowns and family coverage; intended/reviewed disagreements; duplicates and English exceptions; repairs, failure reasons, lineage, billed tokens and cost. Distinguish semantic ambiguity, missing context and technical failures. Disclose reviewer/model relationship and correlated-error risk. Optional agreement audit is separately costed and cannot be called accuracy.

## Limitations and rights

Synthetic sampling does not represent inbox prevalence. Machine labels can contain shared-model errors even after agreement. No real-inbox performance, training suitability or benchmark validity is established. Public release requires verified redistribution rights for generated text, labels and judgments, separate intended dataset MIT licensing and explicit publication approval. A provider's output-ownership clause alone is insufficient. No fixture export should be published as the corpus.

## Current implementation versus observed data

Offline v0.3.2 preserves supported English typography and rejects characteristic split-contraction corruption without silently rewriting output. It has no new live-quality evidence. The v0.3.1 flagged raw variant and native exclusion remain unchanged; automated acceptance is separate from native quality screening. Live corpus export remains disabled. No accepted all-negative example or gold label set has been established.
