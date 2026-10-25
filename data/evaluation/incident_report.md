# Incident Summary — incident-001

- Generated: `2026-10-19T21:52:24.156240+00:00`
- Provider: `openai`  ·  Pipeline: `phase3b-multiagent-0.1.0`
- Entity: `topic:payments.settlement` (known=True)
- Agent trace: A1 -> A2 -> A3 -> A4 -> A5 -> A6 -> A7 -> A8

**Summary:** A consumer lag of 60,000 messages has been detected in the Payments Settlement service, exceeding the static threshold of 50,000, indicating potential issues with downstream processing or consumer capacity. This situation poses a risk of delayed or failed payments, settlement backlog, and potential SLA/regulatory violations.

## 1. Issue (from signal)
topic:payments.settlement: consumer_lag = 60000 messages (classification: likely, anomaly_score: 0.635) in prod.

## 2. Root-cause analysis (A4)
[high] Downstream consumer slow or under-capacity (next check: Compare consumer throughput vs input (produce) rate for the group.); [medium] Consumer errors causing repeated rebalances (next check: Check consumer group status for errors or rebalances.); [medium] Hot partition / key skew concentrating load (next check: Analyze partition load distribution metrics.)

## 3. Correlation (A2)
candidate=incident-001; correlated_signals=['sig-sample', 'consumer_lag']; dependency_path=Payments Settlement -> consumer_lag

## 4. Priority / Severity (A3)
P2 — The consumer lag of 60000 messages exceeds the static threshold of 50000, indicating a likely issue with downstream processing or consumer capacity.

## 5. Remediation recommendation (A5)
- Compare consumer throughput vs input (produce) rate for the group. (approval_required=True; verify: Throughput metrics should be available for comparison.; rollback: No rollback necessary as this is a read-only action.)
- Check consumer group status for errors or rebalances. (approval_required=True; verify: Check for any reported errors or rebalances in the consumer group.; rollback: No rollback necessary as this is a read-only action.)
- Analyze partition load distribution metrics. (approval_required=True; verify: Metrics should indicate load distribution across partitions.; rollback: No rollback necessary as this is a read-only action.)
- Check the number of consumer instances against the partition count. (approval_required=True; verify: Compare the number of consumer instances to the number of partitions.; rollback: No rollback necessary as this is a read-only action.)

## 6. Business impact
Payments delayed or failed; settlement backlog; SLA/regulatory risk

## 7. Stakeholders to notify
- app_owner: payments-app-owner@example.com
- business_owner: payments-biz-owner@example.com
- prod_support: prodsupport-payments@example.com
- sre: sre-streaming@example.com
- on_call: pager:payments-oncall / #inc-payments

## Knowledge referenced (RAG evidence)

- runbooks.md :: RB-01 — Consumer lag rising (score=0.635)
- escalation_guidelines.md :: P2 / High (score=0.346)
- runbooks.md :: RB-04 — Producer error / retry surge (score=0.344)

### Retrieved documents (with snippets)

- embedder: `openai`  ·  query: `consumer lag rising on a topic or consumer group consumer_lag consumer_lag topic`  ·  best_score: `0.6349446773529053`

| # | source | heading | score |
|---|--------|---------|-------|
| 1 | `runbooks.md` | RB-01 — Consumer lag rising | 0.635 |
| 2 | `escalation_guidelines.md` | P2 / High | 0.346 |
| 3 | `runbooks.md` | RB-04 — Producer error / retry surge | 0.344 |

---

_Advisory only; production actions require human approval. Recipients resolved from the approved directory._