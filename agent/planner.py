"""LangGraph triage state machine for the Phase 3 LLM agent.

A small, BOUNDED graph (no uncontrolled loops) implementing the Phase 1 design
principle: deterministic rules enrich and ground the signal, the LLM reasons over
that grounded context, and the output is parsed/validated deterministically.

Nodes:
    enrich   -> run deterministic rules + entity lookup, build grounded context
    reason   -> render the versioned prompt, call the chat model
    parse    -> parse/validate JSON into a TriageResult (safe on bad output)

Edges: enrich -> reason -> parse -> END  (linear, single pass; bounded).

The graph is prompt-version aware: the version is carried in state so the same
graph can be run under v1/v2/v3 for the comparison harness.
"""

from __future__ import annotations

import json
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import baseline_rules as rules
from .prompts import get_prompt
from .schemas import TriageResult


class TriageState(TypedDict, total=False):
    # inputs
    signal: dict[str, Any]
    prompt_version: str
    # enrichment
    context: dict[str, Any]
    # llm
    raw_llm_output: str
    llm_error: Optional[str]
    # final
    result: dict[str, Any]


def _build_context(signal: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic rules + entity lookup to produce a grounded context block.

    This is the 'controls enforce' half: classification, thresholds, business
    impact, and stakeholders are computed deterministically, NOT by the LLM.
    """
    key = rules.entity_key(signal)
    entity_info = rules.lookup_entity(signal)
    classification = rules.classify_signal(signal)
    severity = None
    if entity_info is not None and classification["classification"] != "insufficient_evidence":
        severity = rules.estimate_severity(signal, entity_info, classification["classification"])

    # A NOVEL metric: no deterministic threshold rule exists for it, yet the
    # signal carries a numeric value. These are precisely the "new signal not in
    # our rulebook/knowledge base" cases the LLM should reason about rather than
    # being silently dropped. (Distinct from a non-numeric/garbage value, which
    # stays insufficient_evidence.)
    metric = signal.get("metric_or_event", "")
    value = signal.get("value")
    novel_metric = (
        rules.STATIC_THRESHOLDS.get(metric) is None
        and isinstance(value, (int, float))
    )

    return {
        "entity_key": key,
        "entity_known": entity_info is not None,
        "metric_or_event": signal.get("metric_or_event"),
        "value": signal.get("value"),
        "unit": signal.get("unit"),
        "environment": signal.get("environment"),
        "rule_classification": classification["classification"],
        "rule_classification_reason": classification["reason"],
        "rule_severity": severity["severity"] if severity else None,
        "rule_severity_rationale": severity["rationale"] if severity else None,
        "novel_metric": novel_metric,
        "business_services": entity_info["business_services"] if entity_info else [],
        "business_impact": entity_info["business_impact"] if entity_info else None,
        "criticality_tier": entity_info["criticality_tier"] if entity_info else None,
        "stakeholders": entity_info["stakeholders"] if entity_info else {},
    }


# --------------------------------------------------------------------------
# Graph nodes
# --------------------------------------------------------------------------

def _enrich_node(state: TriageState) -> TriageState:
    context = _build_context(state["signal"])
    return {"context": context}


def _make_reason_node(chat_model: Any):
    def _reason_node(state: TriageState) -> TriageState:
        version = state.get("prompt_version", "v3")
        prompt = get_prompt(version)
        context_json = json.dumps(state["context"], ensure_ascii=False)
        messages = prompt.format_messages(context_json=context_json)
        try:
            response = chat_model.invoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            return {"raw_llm_output": content, "llm_error": None}
        except Exception as exc:  # noqa: BLE001 - we degrade gracefully by design
            return {"raw_llm_output": "", "llm_error": f"{type(exc).__name__}: {exc}"}

    return _reason_node


def _parse_node(state: TriageState) -> TriageState:
    """Parse LLM JSON into a validated TriageResult, degrading safely on failure."""
    raw = state.get("raw_llm_output", "") or ""
    ctx = state.get("context", {})

    # If the LLM failed, fall back to deterministic rule output only.
    if state.get("llm_error"):
        result = TriageResult(
            classification=ctx.get("rule_classification", "insufficient_evidence"),
            severity=ctx.get("rule_severity"),
            severity_rationale=ctx.get("rule_severity_rationale"),
            affected_services=ctx.get("business_services", []),
            business_impact=ctx.get("business_impact"),
            recommended_recipients=ctx.get("stakeholders", {}),
            uncertainty=f"LLM unavailable ({state['llm_error']}); showing deterministic rule output only.",
            summary=f"{ctx.get('entity_key')}: rule classification {ctx.get('rule_classification')}.",
        )
        return {"result": result.model_dump()}

    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    if not isinstance(parsed, dict) or not parsed:
        # Unparseable -> degrade to deterministic rule output.
        result = TriageResult(
            classification=ctx.get("rule_classification", "insufficient_evidence"),
            severity=ctx.get("rule_severity"),
            affected_services=ctx.get("business_services", []),
            business_impact=ctx.get("business_impact"),
            recommended_recipients=ctx.get("stakeholders", {}),
            uncertainty="LLM output was not valid JSON; showing deterministic rule output only.",
            summary=f"{ctx.get('entity_key')}: rule classification {ctx.get('rule_classification')}.",
        )
        return {"result": result.model_dump()}

    try:
        result = TriageResult(**parsed)
    except Exception:  # noqa: BLE001 - validation error -> keep what we can
        result = TriageResult(
            classification=parsed.get("classification", ctx.get("rule_classification", "insufficient_evidence")),
            severity=parsed.get("severity", ctx.get("rule_severity")),
            summary=str(parsed.get("summary", "")),
            uncertainty="LLM output failed schema validation; coerced to safe defaults.",
        )
    return {"result": result.model_dump()}


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing ``` or ```json fence if the model wrapped JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


# --------------------------------------------------------------------------
# Graph builder
# --------------------------------------------------------------------------

def build_triage_graph(chat_model: Any):
    """Compile and return the bounded triage graph for a given chat model."""
    graph = StateGraph(TriageState)
    graph.add_node("enrich", _enrich_node)
    graph.add_node("reason", _make_reason_node(chat_model))
    graph.add_node("parse", _parse_node)

    graph.add_edge(START, "enrich")
    graph.add_edge("enrich", "reason")
    graph.add_edge("reason", "parse")
    graph.add_edge("parse", END)

    return graph.compile()
