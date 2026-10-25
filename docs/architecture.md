# Architecture & Data Flow — Multi-Agent Sentinel (A1–A8)

**Project:** EventHub Ops – Sentinel
**Scope:** The A1–A8 multi-agent pipeline (requirements §7), built on **LangChain + LangGraph**.
Implemented in `agent/agents/`; run via `scripts/run_multiagent.py`.

> Design principle (Phase 1): **agents analyze and coordinate; deterministic controls enforce
> policy.** The LLM reasons over a grounded context; code enforces thresholds, severity floors,
> approved recipients, idempotency, and human approval for actions.

---

## 1. High-level architecture

```mermaid
flowchart TB
    subgraph SRC[Telemetry & context sources]
        S1[Confluent / Control Center]
        S2[Prometheus / Grafana / APM]
        S3[Kafka Connect / Schema Registry]
        S4[Logs: ELK / OpenSearch / Splunk]
        S5[CMDB / service catalogue / on-call roster]
    end

    SRC --> ING[Secure adapters: ingest + schema validate + redact]
    ING --> NORM[Normalize to canonical signal + deduplicate]
    NORM --> GATE[Deterministic anomaly gate + grounding\nrules + entity/business table]

    GATE --> COORD

    subgraph COORD[Multi-agent coordinator - LangGraph, bounded]
        A1[A1 Signal Validation / Anomaly Triage]
        A2[A2 Correlation & Topology]
        A3[A3 Severity & Business Impact]
        A4[A4 Root-Cause Hypothesis]
        A5[A5 Remediation Recommendation]
        A6[A6 Incident Summary & Ticket]
        A7[A7 Stakeholder Communication & Escalation]
        A8[A8 Recovery Verification & Feedback]
        A1 -->|actionable| A2 --> A3 --> A4 --> A5 --> A6 --> A7 --> A8
        A1 -.->|noise / insufficient| WATCH[Watch state - no incident]
    end

    COORD --> POLICY[Policy / safety gate + human approval\nread-only by default]
    POLICY --> OUT

    subgraph OUT[Outputs]
        O1[ITSM ticket - idempotent]
        O2[Stakeholder notifications - approved recipients]
        O3[Operator dashboard]
    end

    COORD --> AUDIT[Audit store + evaluation feedback loop]
    LLM[(LLM provider:\nChatOpenAI / offline fake)] -. reasons for .- COORD
```

**Notes**
- `GATE` builds the grounded context once (classification, thresholds, business impact,
  stakeholders) — the deterministic half the agents cannot override.
- `COORD` is the LangGraph state machine. Each A-node is a separate agent with its own prompt and
  typed output contract.
- `POLICY` keeps the system read-only by default; A5 actions always carry `requires_approval`.
- The `LLM` is a reasoning component only; it never sources metrics, recipients, or authorization.

---

## 2. Agent pipeline & gate (LangGraph topology)

```mermaid
flowchart LR
    START((start)) --> ENR[enrich\ndeterministic grounding]
    ENR --> A1[A1 validate]
    A1 -->|continue| A2[A2 correlate]
    A1 -->|stop: noise/insufficient| END1((end))
    A2 --> A3[A3 severity+impact]
    A3 --> A4[A4 RCA hypotheses]
    A4 --> A5[A5 remediation]
    A5 --> A6[A6 incident+ticket]
    A6 --> A7[A7 notify+escalate]
    A7 --> A8[A8 recovery+feedback]
    A8 --> END2((end))
```

This matches `agent/agents/orchestrator.py`: `enrich → A1 → (conditional) → A2…A8 → END`, with the
A1 gate short-circuiting to END for `noise`/`insufficient_evidence` (observed live: trace `A1` only).

---

## 3. Data-flow — typed contracts passed between agents

Each agent consumes the grounded context plus selected upstream outputs, and emits a typed
contract (`agent/agents/contracts.py`). Shared `IncidentState` carries them.

```mermaid
flowchart TD
    SIG[/normalized signal/] --> CTX[grounded context\nentity, metric, rule_classification,\nrule_severity, business_impact, stakeholders/]

    CTX --> A1
    A1[A1Output\nclassification, anomaly_score,\nevidence_refs, missing_data] --> A2
    CTX --> A2
    A2[A2Output\nincident_candidate_id,\ncorrelated_signal_ids, dependency_path] --> A3
    CTX --> A3
    A1 --> A3
    A3[A3Output\nseverity, impact,\naffected_services, review_required] --> A4
    A1 --> A4
    A4[A4Output\nranked hypotheses\nevidence_for/against, next_checks] --> A5
    A5[A5Output\nactions: preconditions,\nverification, rollback, requires_approval] --> A6
    A2 --> A6
    A3 --> A6
    A4 --> A6
    A6[A6Output\nincident_id, idempotency_key,\nsummary, timeline, ticket_payload] --> A7
    A3 --> A7
    A7[A7Output\nrecipients_by_role, message,\nchannel, delivery_status] --> A8
    A6 --> A8
    A8[A8Output\nrecovery_status,\nclosure_recommendation, feedback_record]
```

---

## 4. Per-agent contract & guardrail summary (requirements §7)

| Agent | Key outputs | Deterministic guardrail enforced in code |
|-------|-------------|------------------------------------------|
| A1 | classification, anomaly_score, evidence_refs, missing_data | critical-tier confirmed/likely not downgraded to noise; gate stops noise/insufficient |
| A2 | incident_candidate_id, correlated_signal_ids, dependency_path | originating signal id always preserved in correlation |
| A3 | severity, impact, affected_services, review_required | severity floor = deterministic rule severity for critical tier; review_required set |
| A4 | ranked hypotheses (evidence for/against), next_checks | (prompt) no single confirmed cause without evidence |
| A5 | actions (preconditions/verification/rollback) | read_only forced true; every action requires_approval |
| A6 | incident_id, idempotency_key, summary, ticket_payload | deterministic idempotency key; no secrets |
| A7 | recipients_by_role, message, channel, delivery_status | recipients ONLY from approved table; delivery_status=not_sent |
| A8 | recovery_status, closure_recommendation, feedback_record | no "recovered" without post-action telemetry (alert gone ≠ recovered) |

---

## 5. Provider & execution

- **Production:** OpenAI `ChatOpenAI` (`SENTINEL_LLM=openai`, `OPENAI_API_KEY`).
- **Offline verification:** deterministic fake chat model serves per-agent responses keyed on an
  `AGENT_ID` marker, so the full graph + guardrails run without a key.
- **Run:** `python scripts/run_multiagent.py --batch data/evaluation/phase2_demo_inputs.txt`
  (logs each incident to `logs/mcp_events.log` with the agent trace and per-agent outputs).

Rendered diagrams: `docs/diagrams/architecture.svg`, `docs/diagrams/dataflow.svg`.
