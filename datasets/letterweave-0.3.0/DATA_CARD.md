# Letterweave 0.3.0

Original synthetic English email subjects/bodies and seven overlapping communicative-purpose labels. **Machine-labeled, not gold.** MIT, limited to publisher-held rights. This release contains1,471 emails from1,136 generation families:1,158 retained0.2.0 records plus313 new fully reviewed examples. All earlier payloads, labels and split assignments are preserved. Related fresh scenario-suite/context families share a downstream model split, with documented overrides. Counts:942 train,270 development,259 test; fresh187/62/64. Split grouping reduces direct variant leakage but does not prove semantic independence.

## Creation and retained evidence

The supplement planned320 candidates across160 generation families. Nous `openai/gpt-6-luna` generated invented content; blind `openai/gpt-6.1-sol` review received email and rubric with policy `lw-purpose-boundaries-v2`, never intended labels. Actual normalized/raw model identities and source code/manifest hashes are in provenance. The experimental profile was mail-realism-v1 plus the exact v2 boundary text, later exposed as named mail-realism-v2 in tooling 0.7.0. Model-produced labels are not human annotations.

New contrasts cover past recaps versus invitations/reminders, current replies versus quoted history, statements/upcoming charges versus offers, terse shared-document notices, warm hiring outcomes, editorial material versus substantial pitches, and personal/group communication. Unknown labels stay held; they never become negatives. Earlier 0.1.0 retained quality flags and provider-applicability limitations remain; records were not silently relabeled under the new guidance.

Only313 fresh rows were retained. Two slots were held as uncertain, three reviews returned401 authentication failures without usage, and two slots were not generated. Terminal failures and504,000micro-dollar pending reservations were preserved; no retry or assumed-zero billing. Each accepted row’s completed, settled generation/review, raw hashes and record anchors were checked locally. The full batch was incomplete: public payload verification does not assert source-run completion. Together with an inherited unresolved reservation, the manifest declares four unresolved attempts and509,700micro-dollars. Earlier source accounting limitations remain in the0.1.0 documentation. No new lexical duplicate quarantines or purpose-disclaimer QA exclusions occurred.

## Privacy and evaluation limits

Abstract failure patterns from100 private development emails informed scenario design. No private email text, subjects, names, addresses, original identifiers, attachment contents or hostnames were sent to generation or included in training. All636 saved request payloads and all1,471 synthetic subject/body inputs passed local identity/address/phone/exact-subject and20-word-passage screens. Generic protocol/publication-phrase false positives were reviewed and documented; no personal-name/address exceptions. These checks and an input-only builder support privacy, but do not prove absence of every conceivable personal fact. Raw responses, hidden reasoning, private messages, credentials and operational paths are not distributed.

Those 100 emails are known development material, not an unseen test. Assistant review is `model_teacher`, not human gold. Comparing published Letterweave 1.0 and 1.1 under the same original review, acceptable label sets changed from 39 to 79 and missing required alerts from 51 to 9. Meeting recaps changed from 0/9 to 9/9 acceptable. These are published-release comparisons only. The remaining errors matter: development agreement and synthetic held-out agreement do not establish general real-world accuracy or safe automatic mailbox action.

## Use

`inputs.jsonl`, `labels.jsonl` and `provenance.jsonl` align by row; each label vector contains seven decided present/absent judgments. Model training uses only the train split. Unknown/failed slots are excluded. Provenance retains generation family and planned/model split; source hashes identify generation runs. The HF package adds native train/validation/test rows, a data loader configuration and exact contrast-group overrides.

Code and datasets: https://github.com/magnus919/letterweave
Model: https://huggingface.co/Groktopus/Letterweave-1.1-E2B
Dataset: https://huggingface.co/datasets/Groktopus/Letterweave-0.3.0

MIT data license does not license provider models/services, trademarks, or third-party rights. Provider upstream applicability remains unresolved as documented for 0.1.0; no new legal clearance is claimed.
