# MCP Tool-Call Evidence — documents referenced via `search_knowledge`

- Generated: `2026-10-19T21:43:06.636037+00:00`
- Transport: **mcp** (JSON-RPC over MCP)
- Server: `eventhub-sentinel-mcp` (protocol `2024-11-05`)
- Tool: `search_knowledge`  ·  top_k = 3  ·  5 queries

Each query below was sent as an MCP `tools/call`; the rows are the source documents the tool cited (with relevance score), proving the call was grounded in the knowledge base.

## 1. how do I handle rising consumer lag on a topic

- found: **True**  ·  best_score: `0.581212043762207`

| # | source | heading | score |
|---|--------|---------|-------|
| 1 | `runbooks.md` | RB-01 — Consumer lag rising | 0.581 |
| 2 | `faq.md` | EventHub Ops — Operator FAQ | 0.36 |
| 3 | `escalation_guidelines.md` | P2 / High | 0.353 |

> top snippet (runbooks.md :: RB-01 — Consumer lag rising):
> RB-01 — Consumer lag rising
**Symptoms:** `consumer_lag` growing beyond baseline; downstream processing delayed; app latency up.

**Likely causes:**
- Downstream consumer slow or under-capacity (most common).
- Consumer errors causing repea

## 2. what causes under-replicated partitions and how to recover

- found: **True**  ·  best_score: `0.5146209001541138`

| # | source | heading | score |
|---|--------|---------|-------|
| 1 | `runbooks.md` | RB-02 — Broker unavailable / under-replicated partitions | 0.515 |
| 2 | `runbooks.md` | RB-01 — Consumer lag rising | 0.381 |
| 3 | `escalation_guidelines.md` | P2 / High | 0.303 |

> top snippet (runbooks.md :: RB-02 — Broker unavailable / under-replicated partitions):
> RB-02 — Broker unavailable / under-replicated partitions
**Symptoms:** `broker_down`, `under_replicated_partitions` > 0, ISR shrink, elevated request queue.

**Likely causes:**
- Broker process crash or host failure.
- Network partition / d

## 3. producer error rate surge - quota or ACL rejection runbook

- found: **True**  ·  best_score: `0.5984432697296143`

| # | source | heading | score |
|---|--------|---------|-------|
| 1 | `runbooks.md` | RB-04 — Producer error / retry surge | 0.598 |
| 2 | `escalation_guidelines.md` | Escalation triggers (any one fires an escalation) | 0.41 |
| 3 | `escalation_guidelines.md` | Escalation rules | 0.409 |

> top snippet (runbooks.md :: RB-04 — Producer error / retry surge):
> RB-04 — Producer error / retry surge
**Symptoms:** `produce_error_rate` spike, retries, auth failures, quota metrics near limit.

**Likely causes:**
- Quota/throttling or capacity saturation.
- ACL/authentication rejection.
- Broker load or

## 4. how do I escalate a P2 incident and who do I page

- found: **True**  ·  best_score: `0.5664689540863037`

| # | source | heading | score |
|---|--------|---------|-------|
| 1 | `escalation_guidelines.md` | EventHub Ops — Escalation Guidelines | 0.566 |
| 2 | `escalation_guidelines.md` | P2 / High | 0.566 |
| 3 | `escalation_guidelines.md` | P1 / Critical | 0.552 |

> top snippet (escalation_guidelines.md :: EventHub Ops — Escalation Guidelines):
> EventHub Ops — Escalation Guidelines
How and when to escalate, by severity. Channels/recipients are resolved from the approved
directory (see `events_stakeholder_summary.md`); values here are policy, not contacts.

---

## 5. kafka connect connector task failed what to check

- found: **True**  ·  best_score: `0.6838748455047607`

| # | source | heading | score |
|---|--------|---------|-------|
| 1 | `runbooks.md` | RB-03 — Kafka Connect connector/task failure | 0.684 |
| 2 | `runbooks.md` | EventHub Ops — Kafka Incident Runbooks | 0.383 |
| 3 | `company_policy.md` | EventHub Ops — Platform & Governance Policy | 0.336 |

> top snippet (runbooks.md :: RB-03 — Kafka Connect connector/task failure):
> RB-03 — Kafka Connect connector/task failure
**Symptoms:** `connector_task_failed`, rising `sink_error_rate` / `source_error_rate`, worker log errors.

**Likely causes:**
- Credentials/ACL expiry on the connector.
- Schema mismatch between 
