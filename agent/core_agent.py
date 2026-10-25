"""Phase 2 baseline agent — EventHub Ops Sentinel.

A deliberately simple, rules/template-based agent. It accepts either:
  * a free-text operator question, or
  * a normalized-signal JSON object (schema in docs/inputs.md),
and returns a templated triage-style response.

NO LLM. NO retrieval. NO memory. NO tools. This is the baseline whose limitations
later phases (3=LLM, 4=retrieval, 5=tools, 6=memory/planning, 7=adaptation)
progressively remove.

The agent is stateless by design: each call is handled in isolation, which is
itself one of the documented baseline limitations (no correlation / no dedup).
"""

from __future__ import annotations

import json
from typing import Any

from . import baseline_rules as rules
from . import baseline_templates as templates


class BaselineAgent:
    """Stateless rules/template responder."""

    version = "phase2-baseline-0.1.0"

    def handle(self, user_input: str) -> dict[str, Any]:
        """Route a single input to the right handler and return a result dict.

        The result dict carries both the human-readable ``response`` and
        structured fields so the CLI can log a machine-readable record.
        """
        signal = self._try_parse_signal(user_input)
        if signal is not None:
            return self._handle_signal(signal)
        return self._handle_text(user_input)

    # -- input routing -----------------------------------------------------

    @staticmethod
    def _try_parse_signal(user_input: str) -> dict[str, Any] | None:
        """Return a parsed signal dict if the input is JSON with an 'entity' or
        'metric_or_event' field; otherwise None (treat as free text)."""
        stripped = user_input.strip()
        if not stripped.startswith("{"):
            return None
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict) and ("entity" in obj or "metric_or_event" in obj):
            return obj
        return None

    # -- handlers ----------------------------------------------------------

    def _handle_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        key = rules.entity_key(signal)
        entity_info = rules.lookup_entity(signal)
        classification = rules.classify_signal(signal)

        severity = None
        if entity_info is not None and classification["classification"] not in (
            "insufficient_evidence",
        ):
            severity = rules.estimate_severity(
                signal, entity_info, classification["classification"]
            )

        response = templates.render_signal_triage(
            signal, classification, entity_info, severity, key
        )
        return {
            "mode": "signal",
            "entity": key,
            "classification": classification["classification"],
            "severity": severity["severity"] if severity else None,
            "entity_known": entity_info is not None,
            "response": response,
        }

    def _handle_text(self, text: str) -> dict[str, Any]:
        intent = rules.classify_intent(text)
        response = templates.render_text_answer(intent, text)
        return {
            "mode": "text",
            "intent": intent,
            "response": response,
        }


# ==========================================================================
# Phase 3 — LLM-backed agent (LangChain + LangGraph)
# ==========================================================================

class LLMAgent:
    """LLM-backed triage agent built on the bounded LangGraph graph.

    Grounds the LLM with deterministic rules (classification, thresholds,
    business impact, stakeholders) so the model reasons but does not invent
    metrics or recipients. Falls back to deterministic rule output if the LLM
    is unavailable or returns unparseable content (handled in planner._parse_node).

    Provider and default prompt version come from the environment
    (SENTINEL_LLM, SENTINEL_PROMPT_VERSION); see .env.example.
    """

    version = "phase3-llm-0.1.0"

    def __init__(self, prompt_version: str | None = None, chat_model: Any = None):
        # Imported here so Phase 2 BaselineAgent has zero LLM dependencies.
        import os

        from .llm import get_chat_model, provider_name
        from .planner import build_triage_graph
        from .prompts import DEFAULT_PROMPT_VERSION

        self.provider = provider_name()
        self.prompt_version = (
            prompt_version
            or os.environ.get("SENTINEL_PROMPT_VERSION", DEFAULT_PROMPT_VERSION).strip()
            or DEFAULT_PROMPT_VERSION
        )
        self._chat_model = chat_model or get_chat_model()
        self._graph = build_triage_graph(self._chat_model)

    def handle(self, user_input: str) -> dict[str, Any]:
        """Handle a single input. Signal JSON goes through the LLM graph; free
        text gets a short guidance response (Phase 3 focuses on signal triage)."""
        signal = BaselineAgent._try_parse_signal(user_input)
        if signal is None:
            return {
                "mode": "text",
                "agent": "llm",
                "provider": self.provider,
                "prompt_version": self.prompt_version,
                "response": (
                    "Phase 3 LLM triage expects a normalized-signal JSON "
                    "(see docs/inputs.md). Free-text Q&A arrives in later phases."
                ),
            }
        return self.triage_signal(signal, self.prompt_version)

    def triage_signal(self, signal: dict[str, Any], prompt_version: str | None = None) -> dict[str, Any]:
        """Run one signal through the graph under a given prompt version."""
        version = prompt_version or self.prompt_version
        state = self._graph.invoke({"signal": signal, "prompt_version": version})
        result = state.get("result", {})
        response = self._render(signal, result)
        return {
            "mode": "signal",
            "agent": "llm",
            "provider": self.provider,
            "prompt_version": version,
            "entity": state.get("context", {}).get("entity_key"),
            "entity_known": state.get("context", {}).get("entity_known"),
            "classification": result.get("classification"),
            "severity": result.get("severity"),
            "llm_error": state.get("llm_error"),
            "result": result,
            "response": response,
        }

    @staticmethod
    def _render(signal: dict[str, Any], result: dict[str, Any]) -> str:
        entity = signal.get("entity", {}) or {}
        lines = ["=== LLM TRIAGE (LangGraph) ==="]
        lines.append(f"Entity        : {entity.get('type', 'n/a')}:{entity.get('id', 'n/a')}")
        lines.append(f"Classification: {result.get('classification')}")
        if result.get("severity"):
            lines.append(f"Severity      : {result.get('severity')}")
        if result.get("severity_rationale"):
            lines.append(f"  rationale   : {result.get('severity_rationale')}")
        if result.get("business_impact"):
            lines.append(f"Business impact: {result.get('business_impact')}")
        if result.get("affected_services"):
            lines.append(f"Affected svc  : {', '.join(result.get('affected_services'))}")
        hyps = result.get("hypotheses") or []
        if hyps:
            lines.append("Hypotheses    :")
            for i, h in enumerate(hyps, 1):
                lines.append(f"  {i}. {h.get('cause')} "
                             f"(for: {h.get('evidence_for')}; against: {h.get('evidence_against')}; "
                             f"conf: {h.get('confidence')})")
        if result.get("next_check"):
            lines.append(f"Next check    : {result.get('next_check')}")
        recips = result.get("recommended_recipients") or {}
        if recips:
            lines.append("Notify        :")
            for role, contact in recips.items():
                lines.append(f"  - {role:13s}: {contact}")
        if result.get("uncertainty"):
            lines.append(f"Uncertainty   : {result.get('uncertainty')}")
        if result.get("summary"):
            lines.append(f"Summary       : {result.get('summary')}")
        lines.append("NOTE: advisory only; production actions require human approval.")
        return "\n".join(lines)
