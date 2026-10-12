# LetterWeave data card — fresh release pending final QA

## Scope and provenance

LetterWeave is fresh synthetic English email subject/body data with seven overlapping purpose categories. A proposed v0.5 mixed-model continuation supports dataset 0.1.0; final release remains pending. No private Gmail content, upstream corpus/code, fixture exports or historical private-pilot records enter this release. Model training, spam detection and hosted inference are outside scope.

Planned cohort: **1,000 candidates from 900 families**: 750 ordinary, 200 challenge (100 parent/child families), and 50 context-sensitive messages. Final retained/excluded counts and observed label/slice distributions are pending. Planned size is not accepted size.

## Schema and labels

Public inputs contain subject/body only. Zero-based row position joins them to the separate labels and limited family-provenance tables. Corpus inputs do not contain intended labels or scenario rationales. Final labels derive from complete reviewed decisions, not generation intent. Present/absent/unknown are preserved in internal review evidence; unresolved records do not enter binary-label content. A complete all-absent vector is valid.

Categories: correspondence; transactions/records; alerts/updates; newsletters/publications; promotions/outreach; community/discussions; scheduling/invitations. Separate decisions do not imply statistical independence. A receipt may express both records and completion/status. Neutral community participation and scheduling do not automatically establish persuasive outreach. Missing attachments/history affect only decisions actually dependent on missing evidence; hypothetical purposes are not uncertainty. Subjectless/body-light legitimate mail is permitted.

## Generation, review and quality

The cohort preserves 247 existing Sol-generated records. Future generation and controlled mutation use Nous `openai/gpt-6-luna` (canonical `openai/gpt-6-luna-20260922`), requested reasoning effort `low`. Review/re-review remains Nous `openai/gpt-6.1-sol` in isolated requests. Final provenance must identify actual stage/record models; the entire cohort must not be described as Luna-generated. Review packets contain opaque IDs, frozen rubric/anchors, subject/body and schema only. No tools/retrieval or previous answers; email instructions are untrusted data. Positive labels require evidence spans; absence needs no quotation. Preserve first/latest judgments and final stable-consensus decisions separately. Intended labels remain design hypotheses.

Controlled mutations assess applicability, actual content change, mechanical fact anchors and observed label relation separately. Surface preservation is not semantic truth. Unknowns/disagreement remain unresolved; valid text is not rewritten to force agreement. Family descendants inherit lineage/split fixtures. Related scenarios sharing factual themes are also correlated.

Native QA is separate from paid API generation/review and is not gold annotation. Final release verification will report original denominators, retained/held/rejected/excluded/unattempted counts, slice and per-label support, unknowns, duplicate findings, relation outcomes and integrity results. Final counts, cohort manifest hashes, artifact checksums and settled accounting are pending completion.

## Limits and rights

Describe this release as **synthetic, machine-labeled, not gold**. Existing Sol generation/review can preserve shared errors; different generation/review models also remain correlated and fallible. Selected scenarios do not represent inbox prevalence; no population accuracy, semantic ground truth or real-inbox performance is established. Split fixtures are not independently sampled benchmark holdouts.

The publisher offers the dataset under MIT to the extent applicable rights are held. This does not license provider models/services, trademarks or third-party material, nor establish provider authorization for every downstream use. Official terms review found no express dataset-only publication ban; exact upstream agreement applicability remains unresolved. See current-provider-release-terms.md. Raw provider responses, hidden reasoning, credentials and private execution artifacts are excluded from public data.

## Provisional native QA and cost disclosure

Existing-record native QA covered 100 records with nonopaque identifiers and 147 with opaque identifiers. Seventeen exclusions are provisional. These conditions are not equivalent to a uniformly blind audit; final observed distributions and retained counts are still pending.

Luna catalog rates are $0.10 prompt, $0.50 completion including reasoning and $0.125 cache-write per million tokens; conservative input reservation uses $0.225. Subscription-reported charges are not verified attributable invoice cost. Cohort and cumulative caps remain $25 and $30 respectively.
