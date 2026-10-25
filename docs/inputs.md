# Inputs — All Possible Signals

**Project:** EventHub Ops – Sentinel
**Phase 1 artifact** — defines every input/signal Sentinel can ingest and the canonical schema
all signals are normalized into.

> Related input: `events_stakeholder_summary.md` provides the **business-context input** —
> the lookup that turns a signal's entity ID into affected business services, business impact,
> and the stakeholders to alert.

---

## 1. Input categories

Sentinel consumes three broad classes of input:

1. **Telemetry signals** — alerts, metrics, logs, and platform/application events from observability sources.
2. **Context inputs** — topology/lineage, service criticality, SLOs, recent changes/deployments, runbooks, on-call roster (see `events_stakeholder_summary.md`).
3. **Operator inputs** — approvals, severity/RCA/action corrections, and feedback (captured by A8).

This document focuses on (1) and the schema; (2) is detailed in
`events_stakeholder_summary.md`; (3) is described in `outputs.md` (feedback record).

---

## 2. Telemetry sources

| Source | Examples of what it provides |
|--------|------------------------------|
| Confluent Cloud / Platform APIs, Control Center | Broker and client metrics, cluster/topic/partition health, consumer group state |
| Kafka Connect | Connector/task status, source & sink error rates, worker logs |
| Schema Registry | Subject/version info, compatibility check results, registry events |
| Metrics / APM — Prometheus, Grafana, AppDynamics, OpenTelemetry | Time-series metrics, baselines, traces, app latency |
| Logs — ELK / OpenSearch / Splunk (or approved platform) | Broker/client/application log lines |
| Change / deployment events | Deploy markers, config changes, maintenance windows |
| CMDB / service catalogue, on-call roster | Ownership, service criticality, routing (context input) |

> **Untrusted-data note.** Log lines, topic names, ticket text, and runbook contents are
> treated as **data, not instructions**. They are never allowed to override system policy
> (prompt-injection resistance).

---

## 3. Signal catalog (source → entity → example metric/event → unit)

| # | Source | Entity type | Example metric / event | Unit |
|---|--------|-------------|------------------------|------|
| 1 | Confluent / Control Center | consumer_group | `consumer_lag` | messages |
| 2 | Confluent / Control Center | partition | `under_replicated_partitions` | count |
| 3 | Confluent / Control Center | broker | `broker_down` / `broker_unreachable` | boolean/state |
| 4 | Confluent / Control Center | partition | `isr_shrink` (ISR change) | count |
| 5 | Prometheus / Grafana | broker | `request_queue_depth` | requests |
| 6 | Prometheus / Grafana | broker | `disk_usage` / `network_latency` | % / ms |
| 7 | Kafka Connect | connector | `connector_task_failed` | state |
| 8 | Kafka Connect | connector | `sink_error_rate` / `source_error_rate` | errors/s |
| 9 | Schema Registry | schema | `schema_compatibility_failure` | event |
| 10 | Confluent / client metrics | producer (application) | `produce_error_rate` / `retry_surge` | errors/s |
| 11 | Confluent / client metrics | application | `quota_throttling` / `capacity_saturation` | % / state |
| 12 | Confluent / security | topic/cluster | `auth_failure` / `acl_denied` | event |
| 13 | APM / OTel | application | `consumer_throughput_drop` / `app_latency` | msg/s / ms |
| 14 | Logs platform | any | error signatures, rebalance events | event |
| 15 | Change system | any | deployment / config change marker | event |

This catalog is representative, not exhaustive; new signal types are added via versioned
configuration (FR-18) without changing agent code.

---

## 4. Canonical normalized-signal schema

Every ingested signal is validated and mapped into this canonical schema (requirements §10.1).
Malformed records are quarantined rather than silently dropped.

```json
{
  "signal_id": "source-stable-id-or-generated-id",
  "source": "confluent|control_center|prometheus|appdynamics|elk|other",
  "observed_at": "ISO-8601 timestamp",
  "environment": "prod|preprod|dev",
  "cluster_id": "logical cluster identifier",
  "entity": {
    "type": "topic|broker|partition|consumer_group|connector|schema|application",
    "id": "stable-id"
  },
  "metric_or_event": "consumer_lag",
  "value": 125000,
  "unit": "messages",
  "threshold_or_baseline": { "type": "static|dynamic", "value": 50000 },
  "severity_source": "source-provided severity if present",
  "labels": {},
  "evidence_uri": "approved deep link",
  "redaction_status": "passed",
  "correlation_id": "optional",
  "ingested_at": "ISO-8601 timestamp"
}
```

### 4.1 Field reference

| Field | Meaning | Notes |
|-------|---------|-------|
| `signal_id` | Stable or generated ID for the signal | Used for dedup fingerprinting |
| `source` | Originating system | Drives adapter-specific normalization |
| `observed_at` | When the condition was observed | Timezone-normalized to UTC |
| `environment` | prod / preprod / dev | Scopes policy and routing |
| `cluster_id` | Logical Kafka cluster | Part of topology lookup |
| `entity.type` / `entity.id` | The impacted asset | Key for `events_stakeholder_summary.md` lookup |
| `metric_or_event` | What was measured/observed | e.g., `consumer_lag`, `connector_task_failed` |
| `value` / `unit` | Measured value and unit | Units validated during normalization |
| `threshold_or_baseline` | Static threshold or dynamic baseline | Supports deterministic anomaly gate |
| `severity_source` | Source-provided severity, if any | Advisory; final severity set by A3 policy |
| `labels` | Free-form key/value metadata | Treated as untrusted data |
| `evidence_uri` | Approved deep link to evidence | Supports explainability / citations |
| `redaction_status` | `passed` only after redaction | No PII/secrets/payloads reach the model |
| `correlation_id` | Optional cross-source correlation key | Aids A2 correlation |
| `ingested_at` | When Sentinel received it | Used for latency/staleness checks |

---

## 5. Data-minimization & redaction constraints (on input)

- Prefer **metadata and metrics** over payloads.
- Redact credentials, tokens, customer identifiers, and message payloads **before** any model call.
- A signal is only eligible for model reasoning when `redaction_status = passed`.
- Preserve source, timestamp, environment, entity identity, and correlation IDs for auditability (FR-01).

---

## 6. How inputs flow into the agents

1. **Ingestion (FR-01)** — adapters pull/receive raw signals from §2 sources.
2. **Normalization (FR-02)** — map to the §4 canonical schema; validate fields/units; quarantine malformed records.
3. **Deduplication (FR-03)** — fingerprint by asset + symptom + time window; keep occurrence count and first/last seen.
4. **Enrichment (FR-04)** — resolve `entity.id` against topology and `events_stakeholder_summary.md` for business context.
5. **Anomaly gate** — deterministic thresholds/baselines feed A1.

The resulting enriched, canonical signals are the inputs the agents reason over.
Outputs produced from these signals are defined in `outputs.md`.
