"""The eight agent nodes (A1-A8) for the multi-agent LangGraph pipeline.

Each node:
  1. assembles a grounded context (deterministic rules + upstream agent outputs),
  2. invokes the LLM with that agent's prompt,
  3. parses the JSON into the agent's typed contract (safe on failure),
  4. applies deterministic GUARDRAILS that override unsafe LLM output.

The LLM reasons; deterministic controls enforce policy (Phase 1 principle).
"""

from __future__ import annotations

import json
from typing import Any

from .agent_prompts import AGENT_PROMPTS
from .contracts import (
    A1Output,
    A2Output,
    A3Output,
    A4Output,
    A5Output,
    A6Output,
    A7Output,
    A8Output,
)
from .state import IncidentState


def _strip_code_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[:-3]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


def _invoke_agent(chat_model: Any, agent_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Render the agent prompt, call the model, return (parsed_json, error)."""
    prompt = AGENT_PROMPTS[agent_id]
    context_json = json.dumps(context, ensure_ascii=False)
    messages = prompt.format_messages(agent_id=agent_id, context_json=context_json)
    try:
        resp = chat_model.invoke(messages)
        content = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        return {}, f"{agent_id} LLM error: {type(exc).__name__}: {exc}"
    try:
        parsed = json.loads(_strip_code_fence(content))
        if isinstance(parsed, dict):
            return parsed, None
        return {}, f"{agent_id} output was not a JSON object"
    except (json.JSONDecodeError, TypeError):
        return {}, f"{agent_id} output was not valid JSON"


def _record(state: IncidentState, agent_id: str, error: str | None) -> dict[str, Any]:
    trace = list(state.get("trace", [])) + [agent_id]
    errors = list(state.get("errors", []))
    if error:
        errors.append(error)
    return {"trace": trace, "errors": errors}


# --------------------------------------------------------------------------
# A1 — Signal Validation / Anomaly Triage
# --------------------------------------------------------------------------
def a1_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = state["context"]
        parsed, err = _invoke_agent(chat_model, "A1", ctx)
        try:
            out = A1Output(**parsed) if parsed else A1Output(
                classification=ctx.get("rule_classification", "insufficient_evidence"),
                rationale="Fallback to deterministic rule classification.",
            )
        except Exception:  # noqa: BLE001
            out = A1Output(classification=ctx.get("rule_classification", "insufficient_evidence"))

        # GUARDRAIL: never let the LLM relax a deterministic confirmed/likely on a
        # critical-tier entity down to noise. Enforce the rule classification floor.
        rule_cls = ctx.get("rule_classification", "insufficient_evidence")
        if ctx.get("criticality_tier") == 1 and rule_cls in ("confirmed", "likely"):
            if out.classification in ("noise", "transient"):
                out.classification = rule_cls
                out.rationale = (out.rationale + " [guardrail: critical-tier signal not downgraded to noise.]").strip()

        # NOVEL-SIGNAL PATH: a metric with no deterministic rule would otherwise be
        # classified 'insufficient_evidence' and gated off. A novel metric
        # (numeric value, just no rule / no runbook) is routed to LLM root-cause
        # analysis instead of being dropped. This holds EVEN FOR AN UNKNOWN ENTITY:
        # the LLM can still reason about the symptom; only stakeholder resolution
        # (A7) degrades to "escalate to a human" because the entity isn't in the
        # approved directory.
        if out.classification == "insufficient_evidence" and ctx.get("novel_metric"):
            out.classification = "likely"
            out.missing_data = [m for m in out.missing_data
                                if "entity not in catalogue" not in m]
            if ctx.get("entity_known"):
                note = ("[novel signal: no deterministic rule/runbook for this metric; "
                        "routed to LLM root-cause analysis for a human-validated assessment.]")
            else:
                note = ("[novel signal on an UNCATALOGUED entity: no rule, runbook, or "
                        "directory entry; routed to LLM inference. Recipients cannot be "
                        "auto-resolved - A7 will escalate to a human.]")
                if "entity not in catalogue - recipients unresolved" not in out.missing_data:
                    out.missing_data.append("entity not in catalogue - recipients unresolved")
            out.rationale = ((out.rationale + " ").strip() + note).strip()

        base = _record(state, "A1", err)
        base["a1"] = out.model_dump()
        # gate decision stored for the conditional edge
        if out.classification in ("noise", "insufficient_evidence"):
            base["stop_reason"] = f"A1 classified '{out.classification}' - watch state, no incident."
        return base

    return node


# --------------------------------------------------------------------------
# A2 — Correlation & Topology
# --------------------------------------------------------------------------
def a2_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        ctx["a1"] = state.get("a1", {})
        parsed, err = _invoke_agent(chat_model, "A2", ctx)
        try:
            out = A2Output(**parsed) if parsed else A2Output()
        except Exception:  # noqa: BLE001
            out = A2Output()
        # GUARDRAIL: always preserve a link to the originating signal id.
        sig_id = state["signal"].get("signal_id", "signal")
        if sig_id not in out.correlated_signal_ids:
            out.correlated_signal_ids = [sig_id, *out.correlated_signal_ids]
        if not out.incident_candidate_id:
            out.incident_candidate_id = f"inc-{sig_id}"
        base = _record(state, "A2", err)
        base["a2"] = out.model_dump()
        return base

    return node


# --------------------------------------------------------------------------
# A3 — Severity & Business Impact
# --------------------------------------------------------------------------
def a3_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        ctx["a1"] = state.get("a1", {})
        ctx["a2"] = state.get("a2", {})
        parsed, err = _invoke_agent(chat_model, "A3", ctx)
        try:
            out = A3Output(**parsed) if parsed else A3Output(
                severity=ctx.get("rule_severity"),
                impact=ctx.get("business_impact"),
                affected_services=ctx.get("business_services", []),
            )
        except Exception:  # noqa: BLE001
            out = A3Output(severity=ctx.get("rule_severity"))

        # GUARDRAIL: never downgrade a critical-tier confirmed signal below the
        # deterministic rule severity. Enforce the stricter (lower P-number) floor.
        rule_sev = ctx.get("rule_severity")
        if ctx.get("criticality_tier") == 1 and rule_sev:
            out.severity = _max_severity(out.severity, rule_sev)
            out.review_required = True
        if not out.affected_services:
            out.affected_services = ctx.get("business_services", [])
        if not out.impact:
            out.impact = ctx.get("business_impact")
        base = _record(state, "A3", err)
        base["a3"] = out.model_dump()
        return base

    return node


def _max_severity(a: str | None, b: str | None) -> str | None:
    """Return the more severe (lower P-number) of two P1-P4 strings."""
    order = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
    candidates = [s for s in (a, b) if s in order]
    if not candidates:
        return a or b
    return min(candidates, key=lambda s: order[s])


# --------------------------------------------------------------------------
# A4 — Root-Cause Hypothesis
# --------------------------------------------------------------------------
def a4_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        ctx["a1"] = state.get("a1", {})
        ctx["a3"] = state.get("a3", {})
        parsed, err = _invoke_agent(chat_model, "A4", ctx)
        try:
            out = A4Output(**parsed) if parsed else A4Output()
        except Exception:  # noqa: BLE001
            out = A4Output()
        # Provenance: the knowledge base is the source of truth on coverage, so
        # force analysis_source to match whether retrieval actually grounded this
        # signal (the LLM must not claim runbook grounding when none was found).
        grounded = bool(ctx.get("knowledge_grounded"))
        out.analysis_source = "knowledge_base" if grounded else "llm_inference"
        if not grounded and out.hypotheses:
            note = "No matching runbook/FAQ found; hypotheses inferred by LLM (validate before acting)."
            if note not in out.observed_facts:
                out.observed_facts = [note, *out.observed_facts]
        base = _record(state, "A4", err)
        base["a4"] = out.model_dump()
        return base

    return node


# --------------------------------------------------------------------------
# A5 — Remediation Recommendation
# --------------------------------------------------------------------------
def a5_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        ctx["a4"] = state.get("a4", {})
        # Carry the knowledge-coverage flag (and A4's provenance) to A5.
        ctx["knowledge_grounded"] = bool(ctx.get("knowledge_grounded"))
        parsed, err = _invoke_agent(chat_model, "A5", ctx)
        try:
            out = A5Output(**parsed) if parsed else A5Output()
        except Exception:  # noqa: BLE001
            out = A5Output()
        # GUARDRAIL: read-only by default; force every action to require approval.
        out.read_only = True
        for action in out.actions:
            action.requires_approval = True
        # Provenance mirrors retrieval coverage (same reasoning as A4).
        grounded = bool(ctx.get("knowledge_grounded"))
        out.analysis_source = "knowledge_base" if grounded else "llm_inference"
        base = _record(state, "A5", err)
        base["a5"] = out.model_dump()
        return base

    return node


# --------------------------------------------------------------------------
# A6 — Incident Summary & Ticket
# --------------------------------------------------------------------------
def a6_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        a1 = state.get("a1", {}) or {}
        a2 = state.get("a2", {}) or {}
        a3 = state.get("a3", {}) or {}
        a4 = state.get("a4", {}) or {}
        a5 = state.get("a5", {}) or {}
        ctx["a1"], ctx["a2"], ctx["a3"], ctx["a4"], ctx["a5"] = a1, a2, a3, a4, a5

        # Ask the LLM for the narrative summary (free-form prose).
        parsed, err = _invoke_agent(chat_model, "A6", ctx)
        try:
            out = A6Output(**parsed) if parsed else A6Output()
        except Exception:  # noqa: BLE001
            out = A6Output()

        signal = state["signal"]
        entity = ctx.get("entity_key", "unknown")
        metric = ctx.get("metric_or_event", "n/a")
        value = ctx.get("value")
        unit = ctx.get("unit", "")

        # GUARDRAIL: deterministic idempotency key from the incident candidate.
        incident_id = a2.get("incident_candidate_id") or f"inc-{signal.get('signal_id', 'x')}"
        out.incident_id = incident_id
        out.idempotency_key = f"idem-{incident_id}"

        # --- Consolidate the 7 sections deterministically from upstream facts ---

        # 1. Actual issue from the signal
        out.issue = (f"{entity}: {metric} = {value} {unit}".strip()
                     + f" (classification: {a1.get('classification', 'n/a')}, "
                       f"anomaly_score: {a1.get('anomaly_score', 'n/a')}) "
                       f"in {ctx.get('environment', 'n/a')}.")

        # 2. RCA (top hypotheses from A4) + provenance (runbook vs LLM inference)
        a4_source = a4.get("analysis_source", "knowledge_base")
        source_label = ("runbook-grounded" if a4_source == "knowledge_base"
                        else "LLM-inferred (no matching runbook; validate before acting)")
        hyps = a4.get("hypotheses", []) or []
        if hyps:
            out.root_cause = (
                f"[source: {source_label}] " + "; ".join(
                    f"[{h.get('confidence', '?')}] {h.get('cause', '')} "
                    f"(next check: {h.get('next_check', '')})"
                    for h in hyps[:3]
                )
            )
        else:
            out.root_cause = f"[source: {source_label}] No ranked hypotheses available."
        # Expose the analysis source on the record for downstream/UI use.
        ctx["analysis_source"] = a4_source

        # 3. Correlation, if any (from A2)
        correlated = a2.get("correlated_signal_ids", []) or []
        dep = a2.get("dependency_path", []) or []
        out.correlation = (
            f"candidate={a2.get('incident_candidate_id', incident_id)}; "
            f"correlated_signals={correlated or 'none'}; "
            f"dependency_path={' -> '.join(dep) if dep else 'n/a'}"
        )

        # 4. Priority / severity (from A3)
        out.severity = a3.get("severity") or ctx.get("rule_severity")
        out.severity_rationale = a3.get("rationale") or ctx.get("rule_severity_rationale", "")

        # 5. Remediation recommendation (from A5)
        out.remediation = [
            f"{a.get('action', '')} (approval_required={a.get('requires_approval', True)}; "
            f"verify: {a.get('verification', '')}; rollback: {a.get('rollback', '')})"
            for a in (a5.get("actions", []) or [])
        ]

        # 6. Business impact (A3 impact or entity table)
        out.business_impact = a3.get("impact") or ctx.get("business_impact") or "Unknown / entity not in catalogue."

        # 7. Stakeholders to notify (from the grounded entity table — same source A7 uses)
        out.stakeholders = ctx.get("stakeholders", {}) or {}

        out.timeline = ["signal received", "validated (A1)", "correlated (A2)",
                        "severity assessed (A3)", "RCA (A4)", "remediation proposed (A5)",
                        "incident recorded (A6)"]
        out.evidence_links = [f"metric:{metric}"] + (a1.get("evidence_refs", []) or [])

        # Knowledge-base evidence: which documents (runbooks/FAQ/policy/past
        # incidents) grounded A4/A5, taken from the retrieval diagnostics. This is
        # the RAG citation trail embedded in the incident record itself.
        retrieval = state.get("retrieval", {}) or {}
        if retrieval.get("enabled") and retrieval.get("found"):
            out.knowledge_references = [
                f"{h.get('source')} :: {h.get('heading')} (score={round(float(h.get('score', 0.0)), 3)})"
                for h in retrieval.get("hits", [])
            ]
        elif retrieval.get("enabled"):
            out.knowledge_references = [
                "(no matching knowledge-base document - root cause & remediation "
                "were LLM-inferred from Kafka domain reasoning; validate before acting)"
            ]
        else:
            out.knowledge_references = [
                "(retrieval disabled - root cause & remediation were LLM-inferred)"
            ]
        # Make the citations available to the closure-document renderer.
        ctx["knowledge_references"] = out.knowledge_references

        # Build the full, human-readable closure document (used at close time).
        out.closure_document = _build_closure_document(out, ctx)

        out.ticket_payload = {
            "incident_id": incident_id,
            "severity": out.severity,
            "entity": entity,
            "issue": out.issue,
            "business_impact": out.business_impact,
        }

        base = _record(state, "A6", err)
        base["a6"] = out.model_dump()
        return base

    return node


def _build_closure_document(out: A6Output, ctx: dict[str, Any]) -> str:
    """Render the consolidated 7-section incident record as markdown."""
    stake_lines = "\n".join(f"  - {role}: {contact}"
                            for role, contact in (out.stakeholders or {}).items()) or "  - (none resolved; escalate to a human)"
    rem_lines = "\n".join(f"  - {r}" for r in out.remediation) or "  - (none proposed)"
    kref_lines = "\n".join(f"  - {k}" for k in (out.knowledge_references or [])) or "  - (none)"
    src = ctx.get("analysis_source", "knowledge_base")
    src_line = ("Knowledge-base (runbook/FAQ) grounded." if src == "knowledge_base"
                else "LLM-inferred - this signal is NOT covered by the knowledge base; "
                     "root cause & remediation were derived by the LLM and must be "
                     "human-validated before any action.")
    return (
        f"# Incident {out.incident_id}\n\n"
        f"**Summary:** {out.summary or out.issue}\n\n"
        f"**Analysis source:** {src_line}\n\n"
        f"## 1. Issue (from signal)\n{out.issue}\n\n"
        f"## 2. Root-cause analysis (A4)\n{out.root_cause}\n\n"
        f"## 3. Correlation (A2)\n{out.correlation}\n\n"
        f"## 4. Priority / Severity (A3)\n{out.severity} - {out.severity_rationale}\n\n"
        f"## 5. Remediation recommendation (A5)\n{rem_lines}\n\n"
        f"## 6. Business impact\n{out.business_impact}\n\n"
        f"## 7. Stakeholders to notify\n{stake_lines}\n\n"
        f"## Knowledge referenced (RAG evidence)\n{kref_lines}\n"
    )


# --------------------------------------------------------------------------
# A7 — Stakeholder Communication & Escalation
# --------------------------------------------------------------------------
def a7_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        ctx["a3"] = state.get("a3", {})
        ctx["a6"] = state.get("a6", {})
        parsed, err = _invoke_agent(chat_model, "A7", ctx)
        try:
            out = A7Output(**parsed) if parsed else A7Output()
        except Exception:  # noqa: BLE001
            out = A7Output()
        # GUARDRAIL: recipients ONLY from the approved directory (deterministic table).
        approved = ctx.get("stakeholders", {})
        out.recipients_by_role = approved  # overwrite any LLM-suggested recipients
        if not approved:
            out.escalation_reason = (out.escalation_reason or "") + \
                " [guardrail: no approved recipients for this entity; escalate to a human.]"
        # GUARDRAIL: never claim delivery without a tool result.
        out.delivery_status = "not_sent"
        base = _record(state, "A7", err)
        base["a7"] = out.model_dump()
        return base

    return node


# --------------------------------------------------------------------------
# A8 — Recovery Verification & Feedback
# --------------------------------------------------------------------------
def a8_node(chat_model: Any):
    def node(state: IncidentState) -> dict[str, Any]:
        ctx = dict(state["context"])
        ctx["a3"] = state.get("a3", {})
        ctx["a6"] = state.get("a6", {})
        parsed, err = _invoke_agent(chat_model, "A8", ctx)
        try:
            out = A8Output(**parsed) if parsed else A8Output()
        except Exception:  # noqa: BLE001
            out = A8Output()
        # GUARDRAIL: on first pass there is no post-action telemetry, so recovery
        # cannot be claimed. Alert disappearance != recovery.
        if not ctx.get("post_action_metrics"):
            out.recovery_status = "monitoring"
            out.closure_recommendation = "continue_monitoring"
        base = _record(state, "A8", err)
        base["a8"] = out.model_dump()
        return base

    return node
