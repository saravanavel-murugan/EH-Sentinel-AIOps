"""EventHub Ops Sentinel — multi-agent (A1-A8) pipeline package.

Implements requirements section 7 as eight distinct LangGraph agent nodes,
orchestrated into one bounded incident workflow. This lives alongside the
Phase 3 single-node ``LLMAgent`` (which is left unchanged).
"""

from __future__ import annotations

import json
from typing import Any

from .contracts import AGENT_NAMES
from .orchestrator import build_multiagent_graph
from .state import IncidentState


class MultiAgentSentinel:
    """Runs a signal through the A1-A8 pipeline and renders a consolidated view."""

    version = "phase3b-multiagent-0.1.0"

    def __init__(self, chat_model: Any = None, use_retrieval: bool = True,
                 retriever: Any = None):
        from ..llm import get_chat_model, provider_name

        self.provider = provider_name()
        self._chat_model = chat_model or get_chat_model()

        # Phase 4: attach a retriever when enabled and an index exists.
        self.retrieval_enabled = False
        self._retriever = None
        if use_retrieval:
            self._retriever = retriever or self._try_build_retriever()
            self.retrieval_enabled = self._retriever is not None

        self._graph = build_multiagent_graph(self._chat_model, retriever=self._retriever)

    @staticmethod
    def _try_build_retriever() -> Any:
        """Build a Retriever if a FAISS index is present; else None (graceful)."""
        try:
            from ..retrieval_bridge import load_retriever
            return load_retriever()
        except Exception:  # noqa: BLE001 - retrieval is optional
            return None

    def run_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        state: IncidentState = self._graph.invoke({"signal": signal})
        return {
            "mode": "signal",
            "agent": "multiagent",
            "provider": self.provider,
            "retrieval_enabled": self.retrieval_enabled,
            "retrieval": state.get("retrieval", {}),
            "entity": state.get("context", {}).get("entity_key"),
            "entity_known": state.get("context", {}).get("entity_known"),
            "trace": state.get("trace", []),
            "stop_reason": state.get("stop_reason"),
            "errors": state.get("errors", []),
            "agents": {k: state.get(k) for k in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8") if state.get(k)},
            "response": self._render(signal, state),
        }

    def handle(self, user_input: str) -> dict[str, Any]:
        """Accept a signal JSON string; free text returns guidance."""
        from ..core_agent import BaselineAgent

        signal = BaselineAgent._try_parse_signal(user_input)
        if signal is None:
            return {
                "mode": "text",
                "agent": "multiagent",
                "provider": self.provider,
                "response": "Multi-agent pipeline expects a normalized-signal JSON (see docs/inputs.md).",
            }
        return self.run_signal(signal)

    @staticmethod
    def _render(signal: dict[str, Any], state: IncidentState) -> str:
        entity = signal.get("entity", {}) or {}
        lines = ["=== MULTI-AGENT INCIDENT (A1-A8 / LangGraph) ==="]
        lines.append(f"Entity : {entity.get('type', 'n/a')}:{entity.get('id', 'n/a')}")
        lines.append(f"Trace  : {' -> '.join(state.get('trace', []))}")
        rinfo = state.get("retrieval", {})
        if rinfo.get("enabled"):
            if rinfo.get("found"):
                srcs = ", ".join(f"{h['source']}::{h['heading']} ({h['score']:.2f})"
                                 for h in rinfo.get("hits", [])[:3])
                lines.append(f"Retrieval: {rinfo.get('embedder')} -> {srcs}")
            else:
                lines.append(f"Retrieval: {rinfo.get('embedder')} -> NO relevant knowledge "
                             f"(best {rinfo.get('best_score')})")
        else:
            lines.append("Retrieval: disabled")

        a1 = state.get("a1", {})
        lines.append("")
        lines.append(f"[A1 {AGENT_NAMES['A1']}] classification={a1.get('classification')} "
                     f"score={a1.get('anomaly_score')}")
        if a1.get("rationale"):
            lines.append(f"     rationale: {a1.get('rationale')}")

        if state.get("stop_reason"):
            lines.append("")
            lines.append(f"GATE: {state['stop_reason']}")
            lines.append("Pipeline stopped at A1 (watch state). No incident opened.")
            return "\n".join(lines)

        a2 = state.get("a2", {})
        lines.append(f"[A2 {AGENT_NAMES['A2']}] incident={a2.get('incident_candidate_id')} "
                     f"correlated={a2.get('correlated_signal_ids')}")

        a3 = state.get("a3", {})
        lines.append(f"[A3 {AGENT_NAMES['A3']}] severity={a3.get('severity')} "
                     f"review_required={a3.get('review_required')}")
        if a3.get("impact"):
            lines.append(f"     impact: {a3.get('impact')}")

        a4 = state.get("a4", {})
        hyps = a4.get("hypotheses", [])
        lines.append(f"[A4 {AGENT_NAMES['A4']}] {len(hyps)} hypothesis(es)")
        for h in hyps:
            lines.append(f"     - ({h.get('confidence')}) {h.get('cause')} | next: {h.get('next_check')}")

        a5 = state.get("a5", {})
        acts = a5.get("actions", [])
        lines.append(f"[A5 {AGENT_NAMES['A5']}] {len(acts)} action(s), read_only={a5.get('read_only')}")
        for a in acts:
            lines.append(f"     - {a.get('action')} (approval_required={a.get('requires_approval')})")

        a6 = state.get("a6", {})
        lines.append(f"[A6 {AGENT_NAMES['A6']}] incident_id={a6.get('incident_id')} "
                     f"(consolidated record)")
        if a6.get("summary"):
            lines.append(f"     summary   : {a6.get('summary')}")
        lines.append(f"     1.issue   : {a6.get('issue')}")
        lines.append(f"     2.RCA     : {a6.get('root_cause')}")
        lines.append(f"     3.corr    : {a6.get('correlation')}")
        lines.append(f"     4.severity: {a6.get('severity')} - {a6.get('severity_rationale')}")
        remedy = a6.get("remediation") or []
        lines.append(f"     5.remedy  : {len(remedy)} recommended action(s):")
        for i, r in enumerate(remedy, 1):
            lines.append(f"        {i}. {r}")
        if not remedy:
            lines.append("        (none proposed)")
        lines.append(f"     6.impact  : {a6.get('business_impact')}")
        lines.append(f"     7.notify  : {', '.join((a6.get('stakeholders') or {}).keys()) or 'none'}")

        a7 = state.get("a7", {})
        lines.append(f"[A7 {AGENT_NAMES['A7']}] channel={a7.get('channel')} "
                     f"delivery_status={a7.get('delivery_status')}")
        recips = a7.get("recipients_by_role", {})
        for role, contact in recips.items():
            lines.append(f"     - {role}: {contact}")
        if a7.get("escalation_reason"):
            lines.append(f"     escalation: {a7.get('escalation_reason')}")

        a8 = state.get("a8", {})
        lines.append(f"[A8 {AGENT_NAMES['A8']}] recovery_status={a8.get('recovery_status')} "
                     f"closure={a8.get('closure_recommendation')}")

        if state.get("errors"):
            lines.append("")
            lines.append(f"Diagnostics: {len(state['errors'])} agent note(s): {state['errors']}")

        lines.append("")
        lines.append("NOTE: advisory only; production actions require human approval.")
        return "\n".join(lines)


__all__ = ["MultiAgentSentinel", "build_multiagent_graph", "AGENT_NAMES"]
