r"""Multi-agent LangGraph orchestrator for the A1-A8 Sentinel pipeline.

Topology (bounded, no uncontrolled loops):

    enrich -> A1 -> (gate) --actionable--> A2 -> A3 -> A4 -> A5 -> A6 -> A7 -> A8 -> END
                       \--noise/insufficient--> END  (watch state, no incident)

'enrich' builds the deterministic grounded context once (classification,
thresholds, business impact, stakeholders). A1 validates; a conditional edge
short-circuits to END for noise/insufficient-evidence signals. Otherwise the
typed incident state flows A2..A8, each agent reading upstream outputs.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..planner import _build_context  # reuse Phase 3 deterministic grounding
from .nodes import (
    a1_node,
    a2_node,
    a3_node,
    a4_node,
    a5_node,
    a6_node,
    a7_node,
    a8_node,
)
from .state import IncidentState


def _retrieval_query(signal: dict[str, Any], context: dict[str, Any]) -> str:
    """Build a retrieval query focused on the SYMPTOM (metric + entity type).

    We intentionally emphasize the metric/symptom and repeat it, and expand common
    metric names to their runbook phrasing, so retrieval targets the matching
    runbook rather than incidental business-impact wording.
    """
    metric = str(context.get("metric_or_event") or "")
    etype = str((signal.get("entity") or {}).get("type") or "")
    expansion = {
        "consumer_lag": "consumer lag rising on a topic or consumer group",
        "under_replicated_partitions": "under-replicated partitions broker unavailable ISR",
        "broker_down": "broker unavailable or down",
        "connector_task_failed": "kafka connect connector task failure",
        "sink_error_rate": "kafka connect sink connector errors",
        "source_error_rate": "kafka connect source connector errors",
        "produce_error_rate": "producer error retry surge quota ACL",
        "schema_compatibility_failure": "schema registry compatibility failure",
    }
    phrase = expansion.get(metric, metric.replace("_", " "))
    # repeat the metric token to up-weight it in lexical embedders
    parts = [phrase, metric, metric, etype]
    return " ".join(p for p in parts if p).strip() or "kafka incident"


def _make_enrich_node(retriever: Any):
    """Build the enrich node. If a retriever is supplied, attach retrieved
    runbook/FAQ snippets to the grounded context (RAG); otherwise mark retrieval
    as disabled so A4/A5 run on deterministic context only (for comparison)."""

    def _enrich_node(state: IncidentState) -> dict[str, Any]:
        context = _build_context(state["signal"])
        retrieval_info: dict[str, Any] = {"enabled": retriever is not None}
        if retriever is not None:
            query = _retrieval_query(state["signal"], context)
            res = retriever.retrieve(query)
            context["retrieved_knowledge"] = retriever.format_snippets(res)
            context["retrieval_found"] = res["found"]
            retrieval_info.update({
                "query": query,
                "found": res["found"],
                "best_score": res["best_score"],
                "embedder": res["embedder"],
                "hits": [
                    {"source": h["source"], "heading": h["heading"], "score": h["score"]}
                    for h in res["hits"]
                ],
            })
        else:
            context["retrieved_knowledge"] = "RETRIEVAL_DISABLED"
            context["retrieval_found"] = False
        # Whether this signal is covered by the knowledge base. When False (no
        # relevant runbook/FAQ matched, or retrieval disabled), A4/A5 fall back
        # to LLM domain reasoning and tag their output analysis_source="llm_inference".
        context["knowledge_grounded"] = bool(context.get("retrieval_found"))
        return {"context": context, "trace": [], "errors": [], "retrieval": retrieval_info}

    return _enrich_node


def _a1_gate(state: IncidentState) -> str:
    """Conditional edge after A1: continue to A2 or stop (watch state)."""
    if state.get("stop_reason"):
        return "stop"
    return "continue"


def build_multiagent_graph(chat_model: Any, retriever: Any = None):
    """Compile and return the bounded A1-A8 multi-agent graph.

    If ``retriever`` is provided, the enrich node augments the grounded context
    with retrieved knowledge (RAG); if None, retrieval is disabled (used for the
    with/without-retrieval comparison).
    """
    g = StateGraph(IncidentState)

    g.add_node("enrich", _make_enrich_node(retriever))
    g.add_node("A1", a1_node(chat_model))
    g.add_node("A2", a2_node(chat_model))
    g.add_node("A3", a3_node(chat_model))
    g.add_node("A4", a4_node(chat_model))
    g.add_node("A5", a5_node(chat_model))
    g.add_node("A6", a6_node(chat_model))
    g.add_node("A7", a7_node(chat_model))
    g.add_node("A8", a8_node(chat_model))

    g.add_edge(START, "enrich")
    g.add_edge("enrich", "A1")
    g.add_conditional_edges("A1", _a1_gate, {"continue": "A2", "stop": END})
    g.add_edge("A2", "A3")
    g.add_edge("A3", "A4")
    g.add_edge("A4", "A5")
    g.add_edge("A5", "A6")
    g.add_edge("A6", "A7")
    g.add_edge("A7", "A8")
    g.add_edge("A8", END)

    return g.compile()
