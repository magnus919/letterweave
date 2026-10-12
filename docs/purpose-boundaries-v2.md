# Purpose boundaries, revision2

Tooling 0.7.0 introduces opt-in `mail-realism-v2`. The original v1 and compact profiles are unchanged. The exact added boundary text follows. It is supplied to generation and blind review, with intended labels excluded from review.

Boundary policy lw-purpose-boundaries-v2. Judge the current communicative act, not topic words, sender brand, or generic footer. Scheduling covers a concrete invitation, booking negotiation, reschedule, cancellation or joining an already-booked event; historical invitation text in a recap is not scheduling. A pure human slot negotiation is scheduling alone: no distinct account record, triggered system notice or substantive personal advice. A recorder notes-ready recap is an operational alert, even when the template says someone invited a recorder, shows a date, or counts action items. A service-issued reminder to join a booked event is both scheduling and alert; a general future-event listing is not automatically an operational alert. A masked-account statement available through a link and an existing subscription's upcoming charge are both account records and alerts; a price quote or unaccepted consultation offer is not a transaction. A bland application acknowledgment/rejection is an alert; individualized reasoning, advice or feedback can additionally be correspondence. A short shared-document notice is an alert; the linked document's unknown content is not evidence of other purposes. Subscriber welcome/onboarding is an alert when it announces the new subscription or delivery setup; newsletter brand alone does not establish publication. Curated educational material, recurring editorial content and a multi-item changelog may be publication; promotional rhetoric and material invitations to buy, register, subscribe or join a commercial offering may independently establish promotion. Modest related-reading/social/unsubscribe footers alone do not establish promotion. Commercial sender identity alone does not establish promotion. Security news inside an editorial article is not an account alert. Ignore obsolete quoted requests, signature booking links and compliance boilerplate. If a boundary lacks enough visible evidence, return unknown for that purpose; do not force one of several defensible labels. All seven purposes are independently judged; related purposes are not mutually exclusive.

The 0.3.0 batch used the experimental v1 profile with this exact boundary text appended before the named v2 profile shipped. The policy-file SHA256, including its final newline, is `88df2df8c3280ecee3c25c241bd67817324b8634eeff92134f2b2ab9a0e0c1b1`. The named v2 generation marker differs; do not claim byte-identical wire requests across profile names.

```python
provider = RoleRoutedNousProvider(transport, authorization=authorization,
    content_profile="mail-realism-v2", max_input_tokens=24000, max_output_tokens=6000)
```

```sh
python tools/build_contrast_plan.py --out contrasts.json --groups groups.json --splits splits.json
```

This reproduces 160 invented generation families,320 planned variants, and30 contrast suite/context groups. The generation pipeline assigns family splits; downstream model preparation must apply the exported group split map to every related family, documenting each override. Existing released splits are unchanged. Exact current dataset overrides are available in the dataset’s HF `contrast-split-overrides.json`. Intended labels are design hypotheses; the reviewer may disagree or abstain.

No private source emails or identifiers are needed by this builder. Inspect actual request payloads and candidate text locally before publication; never upload raw responses, hidden reasoning or credentials. Screens do not prove complete absence of every possible personal fact or independently correct labels.
