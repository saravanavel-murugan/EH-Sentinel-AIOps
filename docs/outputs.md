# Outputs — Possible Outputs

**Project:** EventHub Ops – Sentinel
**Phase 1 artifact** — defines every output Sentinel produces: per-agent outputs (A1–A8),
the incident record, ticket payloads, stakeholder notifications, dashboard views, and audit records.

> **Advisory by default.** Every output is advisory/read-only unless explicitly marked as
> requiring human approval. No production mutation happens without an approval gate.

---

## 1. Output categories

| Category | Produced by | Consumer |
|----------|-------------|----------|
| Agent decision outputs (typed) | A1–A8 | Coordinator, dashboard, audit store |
| Incident record | A6 (built from A1–A5, A8) | ITSM, dashboard, audit |
| Ticket payload | A6 | ITSM (ServiceNow/Jira sandbox) |
| Stakeholder notifications | A7 | Paging/email/chat channels |
| Recovery/closure outputs | A8 | Incident record, dashboard |
| Audit records | All agents + policy gate | Immutable audit store |
| Dashboard views | Aggregation of above | Operators, Incident Commander |

---

## 2. Per-agent outputs and guardrails (requirements §7)

| Agent | Output fields | Approval? | Key guardrail |
|-------|---------------|-----------|---------------|
| **A1** Signal Validation / Anomaly Triage | `classification` (confirmed/likely/transient/noise/insufficient), `anomaly_score`, `evidence_refs`, `missing_data`, `rationale` | Advisory | Must not suppress high-risk security or critical-service alerts on LLM judgment alone |
| **A2** Correlation & Topology | `incident_candidate_id`, `correlated_signal_ids`, `dependency_path`, `correlation_rationale` | Advisory | Correlation is reversible; keep links to all original alerts |
| **A3** Severity & Business Impact | `severity` (P1–P4), `impact`, `affected_services`, `rationale`, `review_required`, confidence, escalation deadline | Advisory | Final severity policy owned by incident governance; escalate conservatively; never downgrade critical on low confidence |
| **A4** Root-Cause Hypothesis | `hypotheses[]` (rank), `confidence`, `supporting_refs`, `contradicting_refs`, `next_checks` | Advisory | Never state a single root cause as confirmed without sufficient evidence; no fabricated evidence |
| **A5** Remediation Recommendation | `actions[]`, `expected_effect`, `risk`, `preconditions`, `verification`, `rollback` | Recommend only; action requires approval | Read-only by default; never invent commands; never act outside allow-list |
| **A6** Incident Summary & Ticket | `ticket_payload`, `timeline`, `summary`, `evidence_links` | Advisory (idempotent write to ITSM sandbox) | Idempotency key; no secrets/payloads; no unsupported claims |
| **A7** Stakeholder Communication & Escalation | `recipients_by_role`, `message`, `channel`, `escalation_reason`, `delivery_status` | Advisory | Recipients only from approved directory/on-call source — never guessed |
| **A8** Recovery Verification & Feedback | `recovery_status`, `metrics_before_after`, `closure_recommendation`, `feedback_record` | Advisory; closure is deterministic policy | Alert disappearance alone is not proof of recovery |

---

## 3. Incident record (requirements §10.2)

The incident record is the single authoritative output per incident, assembled by A6.

```
incident_id, idempotency_key, status, created_at, updated_at, environment,
severity, severity_confidence,
affected_assets[], affected_business_services[], correlated_signal_ids[], evidence_refs[],
observed_facts[],
hypotheses[]  (rank, confidence, evidence_for[], evidence_against[], next_checks[]),
business_impact, current_mitigation, recommended_actions[], approval_state,
assigned_owner, stakeholders_notified[],
timeline[], recovery_checks[], closure_criteria,
final_root_cause  (ONLY after confirmation),
operator_feedback, audit_refs
```

Notes:
- `affected_business_services[]` and `business_impact` are populated using
  `events_stakeholder_summary.md`.
- `final_root_cause` is written **only after confirmation** — never from a hypothesis.
- `approval_state` tracks approve / reject / edit / defer / request-more-evidence.

---

## 4. Ticket payload (A6)

A concise, idempotent ITSM payload containing:

- summary, severity, timestamps;
- impacted assets and business services;
- business impact narrative;
- evidence links (citations), hypotheses, action plan;
- assigned owner and next update time.

Excludes secrets, customer payloads, and unsupported claims. Uses an idempotency key so repeated
processing does not create duplicate tickets (FR-10).

---

## 5. Stakeholder notifications (A7)

Resolved from `events_stakeholder_summary.md` and the severity channel policy.

| Field | Description |
|-------|-------------|
| `recipients_by_role` | App Owner, Business Owner, Prod Support, SRE, on-call/IC (from approved directory) |
| `message` | Audience-appropriate: business-impact framing for Business Owners, evidence framing for technical teams |
| `channel` | Page / call / email / chat per severity policy |
| `escalation_reason` | Why an escalation fired (threshold, SLA timer, worsening impact) |
| `delivery_status` | Confirmed from a tool result — never assumed delivered |

Content always includes severity, known impact, uncertainty, actions underway, and next update time.

---

## 6. Recovery & closure outputs (A8)

| Output | Description |
|--------|-------------|
| `recovery_status` | recovered / monitoring / not-recovered / worsening |
| `metrics_before_after` | Explicit metric comparison against recovery criteria |
| `closure_recommendation` | close / continue-monitoring / escalate |
| `feedback_record` | Operator corrections to severity/RCA/action usefulness + outcome labels |

Closure obeys deterministic policy and closure criteria — not alert disappearance.

---

## 7. Audit records (FR-15)

For every decision/action, record (without secrets):

- input evidence references, agent outputs, model/prompt/rule versions, confidence;
- approvals (who/when/what), tool calls and arguments, notifications, action results;
- timestamps and final outcome.

Audit records are immutable and searchable, and feed the evaluation harness.

---

## 8. Dashboard views (FR-16)

- Incident queue filtered by environment, cluster, service, severity, status, time.
- Incident detail: timeline, correlated alerts, asset graph, metric/log links, hypotheses with evidence for/against.
- Recommended actions with risk, preconditions, verification, rollback; approve/reject/edit/request-more-evidence controls where authorized.
- Ticket/notification status, ownership, audit history, recovery verification.
- Clear confidence and stale/missing-data indicators; **does not rely on color alone** (accessibility).

---

## 9. Output → example-question mapping

Ties outputs back to the Phase 1 example user questions in `problem_framing.md`:

| Example question | Output that answers it |
|------------------|------------------------|
| Real incident or noise? | A1 `classification` + `anomaly_score` + `evidence_refs` |
| Business impact & severity? | A3 `severity` + `impact` + `affected_services` (via `events_stakeholder_summary.md`) |
| Likely root causes & safest check? | A4 `hypotheses[]` + `next_checks` |
| Who to notify & which channel? | A7 `recipients_by_role` + `channel` |
| Actually recovered? | A8 `recovery_status` + `metrics_before_after` |

Success criteria and how outputs are evaluated: see `success_criteria.md` and `evaluation_plan.md`.
