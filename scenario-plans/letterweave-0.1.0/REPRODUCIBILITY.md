# LetterWeave 0.1.0 scenario-plan reproducibility

These three original MIT scenario inventories describe the fresh cohort design, not observed labels or a promise of accepted size. They are separate from the strict dataset payload. No execution manifests, authorization records, ledgers, raw responses, account snapshots or private QA evidence are included.

| Plan | Families | Planned candidates | Candidate share |
|---|---:|---:|---:|
| ordinary | 750 | 750 | 75% |
| challenge | 100 | 200 | 20% |
| context_sensitive | 50 | 50 | 5% |
| Total | 900 | 1,000 | 100% |

Each challenge family has a parent and one controlled descendant. Intended labels and mutation relations are design hypotheses, not gold labels. Released content-based labels are determined separately by blind review and final QA. Related catalog factual themes and descendants are correlated, even when family IDs differ. Final observed counts belong in the completed data card.

Execution used implementation v0.4 with code fingerprint `6c036f684f8f822d62d75b9b3baa64173a8aaaf1413b1beeef8543d1147bc69a`. Seed `401` controls family split/order choices; it does not make remote model sampling deterministic. Provider route: Nous alias `openai/gpt-6.1-sol`, requested reasoning effort `low`, local input bound 12,000 and inclusive output ceiling 6,000 tokens (including reasoning). The SDK has no implicit retries. Model/provider evolution and sampling mean replay can differ.

## Canonical commitments

Canonical SHA-256 is calculated over UTF-8 JSON with sorted keys, no ASCII escaping, compact separators and no nonfinite numbers. Inventory hashes can be recomputed from these public files. Run-plan manifest hashes are commitments to the original frozen plans; the full private manifests are not included, so those commitments are not complete public raw-output proof.

| Stratum | Public inventory SHA-256 | Frozen run-plan SHA-256 |
|---|---|---|
| ordinary | `6410fe5f35789b264488192f16a9ea6cfe3cb7654ddcccc17db6d944edcb7379` | `96bcb588446921e7f0a91c731d6a80f30f9d9d50bb82f425ca183cb450aa31db` |
| challenge | `ff3a7df13d2ea0a3350a52632d7c5554f1dc5743890a8846f6f3ae82f2bceef3` | `a928ac97fc1e6c42edfede6c49a64e95a4b64e57394a7f8bbbde5f079e8f881e` |
| context_sensitive | `444f0c5a7d8e57ab41c83f880390c5ee71d529fbc8cf68336a06fef0612442d3` | `33e7fda2ee052fd6a67fe294a416a0be145d4d514af42eeff26ab244c5a58551` |

Public scenario text is offered under MIT to the extent the publisher holds rights. No provider models/services or third-party rights are licensed. Reproducible planning does not establish gold-label accuracy, representative inbox prevalence or semantic fact preservation.
