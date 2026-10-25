"""Tests for the novel-signal path: when a signal is NOT covered by the knowledge
base, A4/A5 fall back to LLM inference and the incident record is tagged as such.

Runs on the deterministic fake provider (conftest forces SENTINEL_LLM=fake), with
retrieval disabled to simulate "no knowledge-base coverage".
"""

from __future__ import annotations


def _novel_signal() -> dict:
    # A metric with no deterministic threshold rule, on a KNOWN entity.
    return {
        "signal_id": "sig-novel-test",
        "source": "control_center",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "tls_cert_expiry_days",
        "value": 2,
        "unit": "days",
        "environment": "prod",
    }


def _run(use_retrieval: bool):
    from agent.agents import MultiAgentSentinel
    from agent.llm import DeterministicSentinelChatModel

    ma = MultiAgentSentinel(chat_model=DeterministicSentinelChatModel(),
                            use_retrieval=use_retrieval)
    return ma.run_signal(_novel_signal())


def test_novel_signal_runs_full_pipeline_not_gated():
    out = _run(use_retrieval=False)
    # Must NOT gate off at A1 even though there is no deterministic rule.
    assert out.get("stop_reason") in (None, "")
    assert out["trace"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"]


def test_novel_signal_marks_llm_inference():
    out = _run(use_retrieval=False)
    a4 = out["agents"]["a4"]
    a5 = out["agents"]["a5"]
    assert a4["analysis_source"] == "llm_inference"
    assert a5["analysis_source"] == "llm_inference"


def test_novel_signal_produces_hypotheses_and_actions():
    out = _run(use_retrieval=False)
    a4 = out["agents"]["a4"]
    a5 = out["agents"]["a5"]
    assert len(a4["hypotheses"]) >= 1          # LLM inferred, not empty
    assert len(a5["actions"]) >= 1
    # every action stays approval-gated / read-only (safety preserved)
    assert a5["read_only"] is True
    assert all(act["requires_approval"] for act in a5["actions"])


def test_novel_signal_incident_record_flags_provenance():
    out = _run(use_retrieval=False)
    a6 = out["agents"]["a6"]
    # root cause carries the LLM-inferred label
    assert "LLM-inferred" in a6["root_cause"]
    # knowledge references explicitly state no KB document matched
    assert any("LLM-inferred" in k for k in a6["knowledge_references"])
    # closure document surfaces the analysis source
    assert "Analysis source:" in a6["closure_document"]
    assert "NOT covered by the knowledge base" in a6["closure_document"]


def test_novel_signal_unknown_entity_still_runs_via_llm():
    """A novel metric on an UNCATALOGUED entity must also reach LLM inference,
    with recipients safely unresolved (A7 escalates to a human)."""
    from agent.agents import MultiAgentSentinel
    from agent.llm import DeterministicSentinelChatModel

    sig = {
        "signal_id": "sig-unknown-entity",
        "entity": {"type": "topic", "id": "loans.disbursement"},  # not in ENTITY_TABLE
        "metric_or_event": "disbursement_latency_ms",
        "value": 900, "unit": "ms", "environment": "prod",
    }
    out = MultiAgentSentinel(chat_model=DeterministicSentinelChatModel(),
                             use_retrieval=False).run_signal(sig)
    assert out["entity_known"] is False
    assert out.get("stop_reason") in (None, "")
    assert out["trace"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"]
    assert out["agents"]["a4"]["analysis_source"] == "llm_inference"
    # safety: no recipients invented for an uncatalogued entity
    assert out["agents"]["a7"]["recipients_by_role"] == {}
    assert out["agents"]["a7"]["escalation_reason"]


def test_non_numeric_value_still_gated():
    """A non-numeric value is NOT a novel metric and stays gated (garbage-in)."""
    from agent.agents import MultiAgentSentinel
    from agent.llm import DeterministicSentinelChatModel

    sig = {
        "signal_id": "sig-bad-value",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "disbursement_latency_ms",
        "value": "high", "unit": "ms", "environment": "prod",
    }
    out = MultiAgentSentinel(chat_model=DeterministicSentinelChatModel(),
                             use_retrieval=False).run_signal(sig)
    assert out.get("stop_reason")           # gated
    assert out["trace"] == ["A1"]


def test_known_metric_still_knowledge_base_when_grounded():
    """A metric WITH retrieval coverage keeps analysis_source=knowledge_base."""
    out = _run(use_retrieval=True)
    # With the offline fake embedder an index may or may not match; the contract
    # is only that provenance mirrors whether retrieval actually grounded it.
    a4 = out["agents"]["a4"]
    retrieval_found = out.get("retrieval", {}).get("found")
    expected = "knowledge_base" if retrieval_found else "llm_inference"
    assert a4["analysis_source"] == expected
