# EventHub Ops — Kafka Incident Runbooks

Operational runbooks for the banking Confluent Kafka platform. Each runbook lists symptoms,
likely causes, safe diagnostic steps, and remediation. All remediation that changes production
requires human approval and a change record (read-only/advisory by default).

> PII-safe: contacts/commands are placeholders. Real runbooks live in the approved runbook store.

---

## RB-01 — Consumer lag rising

**Symptoms:** `consumer_lag` growing beyond baseline; downstream processing delayed; app latency up.

**Likely causes:**
- Downstream consumer slow or under-capacity (most common).
- Consumer errors causing repeated rebalances.
- Hot partition / key skew concentrating load.
- Insufficient consumer instances for the partition count.

**Safe diagnostics (read-only, do first):**
1. Compare consumer throughput vs input (produce) rate for the group.
2. Check consumer group rebalance frequency and member count.
3. Inspect per-partition lag to detect skew (one partition far ahead).
4. Review recent deployments of the consumer application.

**Remediation (requires approval):**
- Scale out consumer instances up to the partition count.
- Roll back a recent consumer deployment if lag started after it.
- Rebalance/repartition only during an approved change window.

**Verification:** lag trend reverses and returns toward baseline over the agreed observation window.
**Rollback:** revert scaling / redeploy previous consumer version.

---

## RB-02 — Broker unavailable / under-replicated partitions

**Symptoms:** `broker_down`, `under_replicated_partitions` > 0, ISR shrink, elevated request queue.

**Likely causes:**
- Broker process crash or host failure.
- Network partition / degradation between brokers.
- Disk pressure or I/O saturation on a broker.
- Planned maintenance mistaken for an incident.

**Safe diagnostics:**
1. Confirm broker liveness and recent restarts.
2. Correlate with change/maintenance calendar before declaring an incident.
3. Check disk usage, network latency, and replica fetch lag.

**Remediation (requires approval):**
- Restart an unhealthy broker only with platform-ops approval.
- Reassign partitions away from a failing broker during a change window.

**Verification:** `under_replicated_partitions` returns to 0 and ISR is restored.
**Rollback:** partition reassignment is reversible; keep the prior assignment plan.

---

## RB-03 — Kafka Connect connector/task failure

**Symptoms:** `connector_task_failed`, rising `sink_error_rate` / `source_error_rate`, worker log errors.

**Likely causes:**
- Credentials/ACL expiry on the connector.
- Schema mismatch between connector and destination.
- Destination (sink) outage or throttling.
- Transformation (SMT) error.

**Safe diagnostics:**
1. Read connector/task status and worker logs (read-only).
2. Check destination health and authentication.
3. Validate the schema/subject the connector uses.

**Remediation (requires approval):**
- Restart the connector/task after the root cause is addressed.
- Rotate credentials via the vault (never inline secrets).

**Verification:** task state RUNNING and error rate back to baseline.
**Rollback:** re-pause the connector; restore prior config.

---

## RB-04 — Producer error / retry surge

**Symptoms:** `produce_error_rate` spike, retries, auth failures, quota metrics near limit.

**Likely causes:**
- Quota/throttling or capacity saturation.
- ACL/authentication rejection.
- Broker load or schema rejection.

**Safe diagnostics:**
1. Check quota and throttling metrics for the client/principal.
2. Check ACL denials and auth failures for the producer.
3. Correlate with broker load and schema registry errors.

**Remediation (requires approval):**
- Raise quota for the principal via approved change.
- Fix ACL binding; redeploy producer with corrected schema.

**Verification:** produce error rate returns to baseline; no new auth/quota denials.
**Rollback:** revert quota/ACL change.

---

## RB-05 — Schema Registry compatibility failure

**Symptoms:** `schema_compatibility_failure`, producer errors right after a deployment.

**Likely causes:**
- Incompatible schema change (breaking field change).
- Wrong subject naming strategy.
- Environment mismatch (dev schema in prod).
- Stale client schema cache.

**Safe diagnostics:**
1. Read the registry compatibility result for the subject/version.
2. Correlate with the most recent deployment event.
3. Confirm the subject strategy matches convention.

**Remediation (requires approval):**
- Roll back the incompatible schema or the deploying service.
- Register a compatible schema version.

**Verification:** producers succeed; no new compatibility errors.
**Rollback:** revert to the last known-good schema version.
