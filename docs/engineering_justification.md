# Engineering & Product Justification — EventHub Ops Sentinel

**Project:** EventHub Ops – Sentinel
**Scenario:** 1 — Business Operations: AI Operations Copilot (decision-support only)
**Deliverable:** the required Engineering & Product Justification — design decisions, trade-offs,
safety approach, and deployment assumptions.

This document explains *why* the agent is built the way it is. The *what* and *how* live in the
per-phase docs (`problem_framing.md`, `architecture.md`, `retrieval.md`, `tools.md`, `mcp.md`,
`planning_memory.md`, `adaptive_behaviour.md`, `deployment.md`, `evaluation_report.md`).

---

## 1. Who the user is and what workflow we support

**Primary persona:** a Platform Ops / on-call operator for a business-critical banking Kafka
platform (full persona set in `personas.md`). Their daily pain: signals scattered across many
tools, one symptom with several plausible causes, and slow manual triage that depends on
specialist knowledge that may be unavailable at 3 a.m.

**Workflow supported (signal → closure):** validate/deduplicate a signal → correlate related
symptoms → assess severity and business impact → form evidence-backed root-cause hypotheses →
recommend safe remediation → create one incident record and notify the right stakeholders →
verify recovery → learn from feedback. The agent is a **decision-support copilot**: it analyzes
and coordinates; humans approve any production change.

---

## 2. Framework choice and justification (Track A)

We chose **Track A — framework-based: LangChain + LangGraph**.

- **LangChain** gives a stable provider abstraction (`ChatOpenAI` for the live path; a
  deterministic offline "fake" chat model for reproducible, key-free runs) and prompt/message
  plumbing, so swapping providers is a one-line config change (`SENTINEL_LLM`).
- **LangGraph** gives an explicit, **bounded** state machine for the A1–A8 pipeline. For an
  operations agent, a bounded graph with typed hand-offs is the right primitive: it makes the
  multi-agent flow inspectable and prevents uncontrolled agent-to-agent loops — a real safety
  property, not just ergonomics.

**Trade-off considered:** a fully framework-free build (Track B) would remove a dependency but
force us to re-implement orchestration, retries, and message handling with no safety upside. We
kept the deterministic policy layer framework-free deliberately (see §4) and used the framework
only where it earns its keep (provider abstraction + bounded orchestration).

---

## 3. Key architectural decisions and trade-offs

| Decision | Why | Trade-off accepted |
|----------|-----|--------------------|
| **Deterministic grounding gate before the LLM** | A rules/entity/business table builds the context once (classification thresholds, severity floors, business impact, approved recipients). The LLM reasons *over* this; it cannot invent metrics, recipients, or authorization. | More up-front rule authoring; some "smart" behaviour is intentionally constrained. |
| **Eight small agents (A1–A8), not one mega-prompt** | Each stage has a single responsibility and a typed output contract, so failures are localizable and the trace is auditable end to end. | More prompts to maintain; more LLM calls per incident. |
| **Offline deterministic provider as the default** | The whole system (agents, retrieval, tools, memory, adaptation, evaluation) runs with **no API key and no network**, so every test, demo, and metric is reproducible by a reviewer. One switch (`SENTINEL_LLM=openai`) flips to the live path. | The offline provider's outputs are fixed fixtures, not model-quality text; live quality is validated separately. |
| **Additive, phase-layered codebase** | Each phase (RAG, tools/MCP, memory, adaptation, observability, evaluation) was added *on top of* the unchanged A1–A8 pipeline via public facades (`MultiAgentSentinel`, `ToolAgent`, `SentinelSession`). | Some indirection through facades; discipline required to keep node logic untouched. |
| **Tools behind an allow-list + an MCP JSON-RPC boundary** | Read-only, allow-listed tools with argument validation; the same tools are also exposed over a Model Context Protocol boundary to demonstrate a clean protocol seam and parity. | Extra layer vs calling functions directly. |
| **Per-entity feedback adaptation that changes presentation only** | Feedback adjusts *how* advice is presented (severity nudge, concise mode, recurrence emphasis), never the A1–A8 decisions, approval gates, or escalation. | Adaptation is conservative and entity-scoped — it does not yet generalize across similar entities (noted as a roadmap item). |
| **Structured logging + per-run tracing with a redactor** | Centralized JSON-line logs and a `traces.jsonl` capture latency/errors; a redaction filter guarantees no secret/PII ever reaches disk — a hard Scenario-1 requirement. | A small cross-cutting module and the discipline to route logging through it. |

---

## 4. Safety approach (Scenario-1 requirements as first-class features)

Scenario 1 requires the agent to **refuse data/action changes, explain uncertainty, provide
human escalation, and keep sensitive data out of logs.** We treat each as an enforced property,
not a prompt suggestion:

- **Refuse to act / read-only by default.** A5 remediation items are always `read_only` with
  `requires_approval=True`; the policy gate blocks any disruptive action without explicit human
  approval. Enforced by deterministic code, not the LLM.
- **Explain uncertainty, don't guess.** On stale/contradictory/low-confidence evidence the agent
  states the uncertainty and escalates. For an unknown entity, A7 returns **empty recipients** and
  escalates — it never fabricates a recipient (gate S7).
- **Human escalation path.** Severity/escalation routing resolves recipients only from the
  approved directory; delivery failures are surfaced, never silently marked delivered.
- **No secrets/PII in logs.** The Phase 8 redactor scrubs `sk-…`, `OPENAI_API_KEY=…`, bearer
  tokens, and secret-named fields before anything is written. A test plants a key and asserts it
  never reaches the log/trace files.
- **Prompt-injection resistance.** Retrieved text (logs, tickets, topic names, runbooks) is
  treated as **data, not instructions**; an embedded "ignore policy" instruction does not weaken
  the approval gate (gate S1).
- **No fabricated evidence.** RCA uses hypothesis language with confidence; recovery is not
  claimed on first pass (gates S6/S8).

The Phase 9 **safety scorecard** walks these gates (S1/S4/S5/S6/S7) with evidence and reports
**zero violations**. Safety failures are hard release blockers and are **never averaged** into a
quality score — the go/no-go logic returns NO-GO if any safety gate fails.

---

## 5. What success looks like, and how we measured it

Success criteria and acceptance gates are defined in `success_criteria.md` / `evaluation_plan.md`
and measured by the Phase 9 harness (`scripts/run_phase9_eval.py`, writing
`data/evaluation/phase9_evaluation.{json,md}`). On the committed offline test set the harness
reports: anomaly validation and gating correctness at the gate, severity present with **zero**
unreviewed critical downgrades, correlation/RCA/recommendation gates met, **K=3 consistency**
(every run byte/field-identical offline, because the provider and grounding rules are
deterministic), the safety scorecard passing with zero violations, and an overall **GO**.

The prompt-comparison rule (same test set, 3 variants v1/v2/v3, a Prompt → Output →
Improved/Worsened table) is evidenced in `docs/prompt_comparison_table.md` /
`data/evaluation/phase3_comparison.md`: v3 (few-shot + chain-of-thought + evidence-for/against +
uncertainty + safety rules) is the selected default.

> All numbers in `docs/evaluation_report.md` are produced by the harness and reproducible
> offline; none are hand-written.

---

## 6. Anticipated failures and how we handle them

Catalogued in `edge_cases.md` (technical T1–T12, safety S1–S7, resilience R1–R6). Representative
handling:

- **Alert storm / duplicates (T9, R4):** deduplicate by fingerprint; one incident per fingerprint.
- **Transient/self-resolving alert (T10):** classify as noise → watch state, don't page.
- **Stale/missing telemetry (T11):** flag staleness, lower confidence, escalate — absence of
  signal is not proof of health.
- **Security signals (T6):** never downgraded on LLM judgment; conservative severity.
- **Model/LLM outage (R2) & bad input:** the Phase 8 `safe_handle_turn` wrapper catches the
  error, records a structured error trace, and returns a graceful advisory response (no crash, no
  stack trace, no secret, safety posture preserved). Demonstrated across three scenarios in
  `scripts/run_phase8_deploy_check.py`.

**Debugged failure (root-cause analysis, Phase 9):** the evaluation harness flagged `tc-05`
(disk_usage 92% on a prod broker) as a gating mismatch. Root cause: the **test label** said
"should gate to watch," but the system's documented novel-signal behaviour deliberately promotes
an unseen metric on a production entity to "likely" and escalates rather than silently dropping a
potential high-criticality signal. The fix corrected the label and the harness criterion (an
additive change; A1–A8 node logic untouched); before/after went from 1 mismatch (0.89 accuracy)
to 0 (1.00). This is the right call: "fixing" the agent to drop a prod disk-usage alert would
have weakened safety.

---

## 7. Deployment assumptions and limitations

Full detail in `docs/deployment.md`. Summary:

- **Packaging:** a `Dockerfile` (python:3.11-slim, offline-first defaults, runs the Streamlit
  console headless) + `pyproject.toml` + `.dockerignore`. Secrets are injected at runtime via env
  vars and **never baked into the image**; `.env` is excluded.
- **Environment:** provider switches (`SENTINEL_LLM`, `SENTINEL_EMBEDDINGS`), `SENTINEL_LOG_LEVEL`,
  and `OPENAI_API_KEY` for the optional live path. The offline fake provider is the default.
- **Observability:** structured `logs/sentinel.log`, per-run `logs/traces.jsonl` (latency + error
  capture), all redacted; surfaced in the UI's Logs/Traces/Latency/Error-handling/Evaluation tabs.

**Known limitations (honest):**

- Integrations (Confluent, ITSM, paging) and the business/severity/stakeholder tables are
  **placeholders / sandboxed** — mocks are labelled, not claimed as real integration tests.
- Persistence is **JSON files** (incident memory, feedback), not a database — fine for the
  capstone and local deploy, not for multi-instance production.
- The system is **single-process**; the Dockerfile is a validated packaging artefact (structure
  checked) rather than a run against a live cluster.
- Offline determinism means the fake provider's text is fixed; live-model quality must be
  re-validated on the OpenAI path, and latency figures reflect pipeline overhead offline (the live
  path adds model round-trip time).
- Feedback adaptation is **per-entity**; it does not yet generalize to similar entities.

---

## 8. Improvement roadmap (next steps)

Prioritized from the measured results and the limitations above (see `docs/evaluation_report.md`
for the full roadmap):

1. **Real integrations** behind the existing adapters/allow-list (Confluent metrics, ITSM,
   paging) with contract tests, replacing placeholders.
2. **Durable store** for incident/feedback memory (DB) to support multiple instances and
   retention policy.
3. **Generalized adaptation** — extend feedback influence from a single entity key to entity
   classes/tiers, with guardrails so it still never weakens safety.
4. **Labelled replay dataset** to recalibrate the provisional numeric gates with class imbalance
   and business risk, and to measure live-model quality (not just offline determinism).
5. **Drift & model governance** — versioned prompts/models already assumed; add drift monitoring
   and controlled rollout/rollback on the live path.

---

## 9. Why these decisions are defensible

The through-line is the Phase-1 principle: **agents analyze and coordinate; deterministic
controls enforce policy.** Every judgment call — framework scope, the grounding gate, eight small
agents, offline-first, advisory-only adaptation, redacted observability — serves reliability,
explainability, and safety-first behaviour for a real operations workflow, which is exactly what
Scenario 1 asks for, rather than novelty or unnecessary complexity.
