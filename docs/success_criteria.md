# Success Criteria, Constraints & Assumptions

**Project:** EventHub Ops – Sentinel
**Phase 1 artifact** — defines what success means (for Phase 1 and for the overall system),
plus the constraints and assumptions the system operates under.

> Measurable targets below are **starting hypotheses** (requirements §13). They are recalibrated
> with labelled historical data, class imbalance, and business risk. An aggregate score must
> never hide a critical **safety** failure.

---

## 1. Phase 1 definition of success

Phase 1 is successful when:

- All 8 Phase 1 docs exist in both canonical (`capstone_agent/docs/`) and mirror
  (`phases/phase1/docs/`) locations and are identical.
- Every Phase 1 task bullet is satisfied and traceable (see `phases/phase1/README.md` checklist).
- Terminology is consistent across docs (severities P1–P4; agents A1–A8).
- Problem, personas, inputs, outputs, business/stakeholder mapping, edge cases, and evaluation
  plan are internally consistent and reviewed.
- No real PII/secrets anywhere; placeholder data is clearly labelled.

Phase 1 produces no runtime behaviour, so success is documentation completeness, consistency,
and reviewer sign-off — not a metric score.

---

## 2. Overall system success criteria (functional)

The system succeeds when it reliably helps the on-call operator (see `personas.md`):

- Validates and deduplicates signals so operators see incident candidates, not raw alert spam.
- Correlates related symptoms into one incident with preserved links to original alerts.
- Proposes severity + business impact grounded in `events_stakeholder_summary.md`.
- Produces ranked, evidence-backed RCA hypotheses with a next discriminating check.
- Recommends safe, reversible actions with preconditions, verification, and rollback.
- Creates/updates an idempotent incident record and routes notifications to correct recipients.
- Verifies recovery against explicit criteria and captures operator feedback.
- Maintains a complete, secret-free audit trail.

---

## 3. Overall system success criteria (measurable acceptance gates)

From requirements §13. These are the gates later phases must evidence.

| Dimension | Metric | Initial target (proposed) |
|-----------|--------|---------------------------|
| Anomaly validation | Precision / recall on labelled incidents vs noise | ≥ 90% precision for auto-generated incident candidates, without materially reducing recall for critical cases |
| Severity | Agreement with expert severity; critical under-classification rate | ≥ 90% agreement on replay set; **zero** unreviewed critical incidents downgraded below policy |
| Correlation | Incident grouping F1 (or pairwise precision/recall) | ≥ 85% F1 on labelled replay set |
| RCA quality | Top-1 / top-3 cause match; evidence support rate | Accepted cause in top-3 for ≥ 80% of sufficiently instrumented cases; all claims traceable to evidence |
| Recommendations | Operator acceptance; safe-action rate; rollback completeness | ≥ 80% rated useful in pilot; 100% of action proposals include preconditions, verification, rollback where applicable |
| Communication | Correct recipients; factuality; timeliness | 100% correct routing in the test matrix; no unsupported impact claims; delivery failures surfaced |
| Efficiency | MTTD, time to triage, time to RCA, MTTR, alerts/incident | Measurable improvement vs baseline (e.g., ~25% lower median triage time in pilot) |
| Safety | Unauthorized actions; secret leakage; approval bypass | **Zero** in test suite and pilot; any violation blocks release |
| Reliability | Duplicate tickets; dropped signals; retry recovery | No untracked loss in replay; idempotency and recovery behaviour pass agreed tests |

> **Safety gates are release blockers.** A single unauthorized production action or secret
> leakage fails the release regardless of other scores.

---

## 4. Non-functional targets (requirements §5)

| Area | Proposed target / requirement |
|------|-------------------------------|
| Latency | Normalization + initial triage within ~30s p95 for a standard alert; full multi-source RCA may take longer and must expose progress |
| Availability | Design for 99.9% monthly for the orchestration control plane (subject to agreed SLO) |
| Scale | Benchmark against peak alert/event rate + bursts; set throughput targets after baseline is known |
| Reliability | At-least-once ingestion with idempotent processing; no duplicate incident per fingerprint |
| Explainability | Every severity/hypothesis/recommendation cites evidence IDs and labels inference vs observed fact |
| Security | SSO, RBAC, service identities, least privilege, secret vault, TLS, encryption at rest, access logging |
| Privacy | Redact tokens/credentials/customer identifiers/payloads before model invocation |
| Resilience | Bounded retries, circuit breakers, dead-letter/quarantine, backpressure, manual fallback |
| Model governance | Versioned prompts/models, controlled rollout, evaluation gates, drift monitoring, rollback |
| Accessibility | Concise summaries, drill-down evidence, clear uncertainty; do not rely on color alone |

---

## 5. Constraints

- **Read-only / advisory by default.** No autonomous production changes.
- **Human approval gate** for restart, config/ACL/topic changes, connector restart, offset changes, or any disruptive operation.
- **No PII/secrets to the model.** Prefer metadata/metrics; redact before model calls; signals need `redaction_status = passed`.
- **Allow-listed tools.** Only approved read APIs/diagnostic queries; validate every argument (time range, row limits, environment, identity).
- **Prompt-injection resistance.** Logs/tickets/topic names/runbooks are untrusted data, never instructions.
- **Deterministic policy enforcement.** Metrics, thresholds, SLOs, authorization enforced by code/policy, not by the LLM.
- **Bounded orchestration.** Explicit state machine, typed contracts, deadlines, bounded loops — no uncontrolled agent-to-agent loops.
- **Never silently drop** high-criticality/security signals.
- **Documentation-only Phase 1.** No code, dependencies, or builds in this phase.

---

## 6. Assumptions

- **Placeholder sources & mappings.** Integration endpoints, business/stakeholder mappings, severity matrix, and SLOs are placeholders until discovery supplies source-of-truth values (CMDB, service catalogue, on-call roster).
- **Sandbox integrations.** ITSM, paging, and chat are sandboxed/mocked in early phases; a mock is clearly labelled and not claimed as a real integration test.
- **Synthetic + replay data.** Where live systems are unavailable, synthetic fixtures and historical incident replay stand in; synthetic fixtures are labelled.
- **Approved model endpoint.** An approved enterprise model endpoint is assumed; data residency/retention reviewed separately.
- **Framework TBD.** Orchestration framework (LangGraph/CrewAI/Semantic Kernel/custom) is selected later with documented trade-offs; dependency versions pinned.
- **Targets are provisional.** All numeric gates are recalibrated with labelled data and platform-owner input.

---

## 7. Traceability

| Phase 1 bullet | Covered here |
|----------------|--------------|
| Define constraints | §5 |
| Define assumptions | §6 |
| Define success criteria | §1 (Phase 1), §2–§3 (system) |

How each criterion is measured (metric → test layer → gate) is detailed in `evaluation_plan.md`.
Known failure modes that these criteria must hold up against are in `edge_cases.md`.
