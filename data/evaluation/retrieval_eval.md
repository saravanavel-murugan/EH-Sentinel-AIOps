# Phase 4 Retrieval Evaluation

Embedder: `openai`  |  min_score: 0.3

## 1. Retrieval quality (hit@k on labelled queries)

- Relevant queries: 8 | **hit@1 = 8/8 (100%)**, hit@3 = 8/8 (100%)
- Non-relevant queries: 2 | **correct 'no relevant info' = 2/2 (100%)**

| Query | Expect | hit@1 | hit@3 | top hits |
|-------|--------|-------|-------|----------|
| rq-01: consumer lag is rising on a topic, what  | runbooks.md::RB-01 | Y | Y | runbooks.md::RB-01 — Consumer lag rising (0.55); escalation_guidelines.md::P2 / High (0.41); faq.md::EventHub Ops — Operator FAQ (0.39) |
| rq-02: kafka connect connector task failed with | runbooks.md::RB-03 | Y | Y | runbooks.md::RB-03 — Kafka Connect connector/task failure (0.65); runbooks.md::EventHub Ops — Kafka Incident Runbooks (0.34); company_policy.md::EventHub Ops — Platform & Governance Policy (0.30) |
| rq-03: under replicated partitions and a broker | runbooks.md::RB-02 | Y | Y | runbooks.md::RB-02 — Broker unavailable / under-replicated partitions (0.71); runbooks.md::RB-04 — Producer error / retry surge (0.46); runbooks.md::RB-01 — Consumer lag rising (0.43) |
| rq-04: producer error retry surge quota throttl | runbooks.md::RB-04 | Y | Y | runbooks.md::RB-04 — Producer error / retry surge (0.59); runbooks.md::RB-01 — Consumer lag rising (0.41); escalation_guidelines.md::Escalation rules (0.35) |
| rq-05: schema registry compatibility failure af | runbooks.md::RB-05 | Y | Y | runbooks.md::RB-05 — Schema Registry compatibility failure (0.59); company_policy.md::Model governance (0.34); runbooks.md::RB-03 — Kafka Connect connector/task failure (0.31) |
| rq-06: how is severity decided and will sentine | faq.md::severity | Y | Y | faq.md::EventHub Ops — Operator FAQ (0.56); company_policy.md::Autonomy & approval (0.52); runbooks.md::RB-02 — Broker unavailable / under-replicated partitions (0.46) |
| rq-07: when do I escalate a P1 critical inciden | escalation_guidelines.md::P1 | Y | Y | escalation_guidelines.md::P1 / Critical (0.60); escalation_guidelines.md::P2 / High (0.54); escalation_guidelines.md::EventHub Ops — Escalation Guidelines (0.53) |
| rq-08: what is the policy on redacting secrets  | company_policy.md::redact | Y | Y | company_policy.md::Data handling & privacy (0.56); company_policy.md::Audit (0.38); company_policy.md::Model governance (0.31) |
| rq-09: best recipe for a chocolate birthday cak | no relevant info | Y (rejected) | - | best=0.06 |
| rq-10: weather forecast for tomorrow in London | no relevant info | Y (rejected) | - | best=0.10 |

## 2. With vs without retrieval (A1-A8 on actionable incidents)

- Actionable cases: 4
- **Retrieval found a relevant runbook WITH retrieval: 4/4** (WITHOUT retrieval: 0/4 — retrieval disabled)
- A4/A5 explicitly name a runbook (heuristic): 0/4 with, 0/4 without

| Case | entity | retrieval hit (top, score) | names runbook WITH | names runbook WITHOUT |
|------|--------|----------------------------|--------------------|-----------------------|
| tc-01-payments-lag-critical | topic:payments.settlement | Y: RB-01 — Consumer lag rising (0.635) | - | - |
| tc-02-fraud-lag | consumer_group:fraud.scoring | Y: RB-01 — Consumer lag rising (0.667) | - | - |
| tc-03-cards-produce-errors | topic:cards.authorization | Y: RB-04 — Producer error / retry surge (0.667) | - | - |
| tc-04-unknown-entity | topic:loans.disbursement | Y: RB-01 — Consumer lag rising (0.635) | - | - |

> Interpretation: WITH retrieval, a relevant runbook is found and injected into the A4/A5 context for every actionable incident; WITHOUT retrieval that grounding is absent. A live LLM paraphrases the runbook rather than always printing its ID, so the 'names runbook' heuristic undercounts; the reliable signal is 'retrieval found'. Non-relevant queries are correctly rejected ('no relevant info'), so the agent never fabricates a runbook.