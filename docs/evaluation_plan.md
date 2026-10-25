# Evaluation Plan

**Project:** EventHub Ops – Sentinel
**Phase 1 artifact** — defines how each success criterion will be measured: the metric, the test
layer that produces it, and the acceptance gate it must meet. Also fixes the mandatory
prompt-comparison method for Phase 3 and references the later-phase evaluation artifacts.

> Numeric gates are **starting hypotheses** (requirements §13), recalibrated with labelled data,
> class imbalance, and business risk. **Safety failures are release blockers** and are never
> averaged away.

---

## 1. Test layers (requirements §12)

| Layer | What it covers |
|-------|----------------|
| Unit | Normalization, time zones, units, fingerprinting, severity calc, redaction, routing, idempotency, schema validation |
| Agent contract | Each agent's typed JSON I/O under representative + adversarial inputs; required evidence/uncertainty fields |
| Integration | Confluent APIs/metrics, logs, APM, CMDB, ticketing, messaging sandboxes; auth expiry, rate limits |
| Scenario / replay | Historical + synthetic incidents (see `edge_cases.md` T1–T12) |
| Safety | Prompt injection, secrets, unauthorized tool calls, approval bypass, destructive-action attempts (S1–S7) |
| Resilience | Agent timeout, model/ITSM outage, telemetry gaps, out-of-order/duplicate, backlog (R1–R6) |
| Performance / load | Burst alerts, sustained rate, large topology, many correlated signals, concurrent incidents |
| User acceptance | Platform Ops, SRE, App owners, Incident managers review evidence, usefulness, communication |

---

## 2. Success criterion → metric → test layer → gate

| Success criterion (from `success_criteria.md`) | Metric | Primary test layer | Acceptance gate |
|-----------------------------------------------|--------|--------------------|-----------------|
| Anomaly validation | Precision / recall vs labelled incidents/noise | Scenario/replay + agent contract | ≥ 90% precision for incident candidates; recall maintained for critical |
| Severity accuracy | Agreement with expert severity; critical under-classification rate | Scenario/replay | ≥ 90% agreement; **zero** unreviewed critical downgrades |
| Correlation quality | Incident grouping F1 (or pairwise P/R) | Scenario/replay | ≥ 85% F1 |
| RCA quality | Top-1 / top-3 cause match; evidence support rate | Scenario/replay + agent contract | Top-3 includes accepted cause ≥ 80% (well-instrumented cases); all claims cite evidence |
| Recommendation usefulness | Operator acceptance; safe-action rate; rollback completeness | UAT + agent contract | ≥ 80% useful in pilot; 100% include preconditions/verification/rollback where applicable |
| Communication routing | Correct recipients; factuality; timeliness | Integration + scenario | 100% correct routing in test matrix; no unsupported impact claims; delivery failures surfaced |
| Efficiency | MTTD, time-to-triage, time-to-RCA, MTTR, alerts/incident | UAT + pilot measurement | Measurable improvement vs baseline (e.g., ~25% lower median triage time) |
| Safety | Unauthorized actions; secret leakage; approval bypass | Safety | **Zero** — any violation blocks release |
| Reliability | Duplicate tickets; dropped signals; retry recovery | Integration + resilience | No untracked loss; idempotency + recovery pass |
| Latency (NFR) | p95 normalization + initial triage | Performance/load | ~30s p95 for standard alert; RCA exposes progress |
| Resilience (NFR) | Graceful degradation on outages | Resilience | Degrades safely; critical escalation not blocked |

---

## 3. Evaluation method & reporting

- **Labelled replay dataset.** Historical incidents labelled with expert severity, accepted root
  cause, and correct routing; plus synthetic fixtures for rare/adversarial cases. Synthetic data
  is labelled as such; mocks are never claimed as real integration tests.
- **Confusion matrix + error analysis.** Report a confusion matrix (e.g., for anomaly validation
  and severity) and concrete examples of failures with root-cause notes.
- **Per-dimension scorecards.** Report each dimension separately; do **not** roll into a single
  score that could hide a safety failure.
- **Go/no-go recommendation.** The evaluation report ends with an explicit go/no-go, with safety
  gates treated as hard blockers.

---

## 4. Mandatory prompt-comparison method (forward reference — Phase 3)

Per `Tasks-to-be-performed.docx`, Phase 3 must demonstrate prompt evaluation using:

- the **same test set** across variants;
- **2–3 prompt variants**;
- a **comparison table** with columns: **Prompt → Output → What Improved / Worsened**.

This is produced in Phase 3 as `docs/prompt_comparison_table.md`. Phase 1 fixes the requirement
here so the later work is scoped correctly.

Template:

| Prompt variant | Output (summary) | What improved | What worsened |
|----------------|------------------|---------------|---------------|
| v1 (baseline) | … | … | … |
| v2 | … | … | … |
| v3 | … | … | … |

---

## 5. Phase-by-phase evaluation focus

| Phase | Evaluation focus | Key artifact |
|-------|------------------|--------------|
| 1 | Docs complete, consistent, traceable | this plan + `phases/phase1/README.md` checklist |
| 2 | Baseline agent limitations logged | sample interaction logs |
| 3 | Prompt comparison (same test set, 2–3 variants) | `docs/prompt_comparison_table.md` |
| 4 | Retrieval vs no-retrieval improvement | retrieval-quality comparison |
| 5 | Correct vs incorrect tool usage; safeguards | tool-usage evidence |
| 6 | Multi-turn/memory quality | multi-turn transcripts |
| 7 | Before/after adaptation from feedback | before/after comparison |
| 8 | Latency/error capture; graceful failure | logs/traces |
| 9 | Full metrics + root-cause analysis + safety/ethics review | `docs/evaluation_report.md` |

---

## 6. Later-phase artifacts referenced

- `docs/prompt_comparison_table.md` — Phase 3 prompt comparison (§4).
- `docs/evaluation_report.md` — Phase 9 full evaluation (metrics, confusion matrix, failure analysis, go/no-go).
- `docs/demo_script.md` — forced demo interactions (final submission).
- `docs/engineering_justification.md` — engineering & product justification (final submission).
- `data/evaluation/test_cases.json` — machine-readable test scenarios (from `edge_cases.md`).

---

## 7. Traceability

| Phase 1 expectation | Covered here |
|---------------------|--------------|
| Evaluation planning | §1–§3 |
| Prompt comparison rule (industry method) | §4 |
| Links metrics to success criteria | §2 (references `success_criteria.md`) |
| Links scenarios to test layers | §1 (references `edge_cases.md`) |
