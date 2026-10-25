"""End-to-end agent tests (Phase 2 baseline, Phase 3 LLM, Phase 3b multi-agent).

All run on the deterministic fake provider (set in conftest). These assert the
output *shapes and pipeline behaviour*, not LLM prose quality. The multi-agent
test runs with retrieval disabled so it does not depend on a built FAISS index.
"""

from __future__ import annotations

import json


# -- Phase 2 baseline (no LLM) ------------------------------------------

def test_baseline_agent_signal(sample_signal):
    from agent.core_agent import BaselineAgent

    out = BaselineAgent().handle(json.dumps(sample_signal))
    assert out["mode"] == "signal"
    assert out["entity"] == "topic:payments.settlement"
    assert out["entity_known"] is True
    assert out["classification"]           # some classification produced
    assert "response" in out


def test_baseline_agent_text():
    from agent.core_agent import BaselineAgent

    out = BaselineAgent().handle("how do I handle consumer lag?")
    assert out["mode"] == "text"
    assert out["response"]


# -- Phase 3 single-node LLM agent --------------------------------------

def test_llm_agent_triage(sample_signal, fake_chat):
    from agent.core_agent import LLMAgent

    agent = LLMAgent(chat_model=fake_chat)
    out = agent.handle(json.dumps(sample_signal))
    assert out["mode"] == "signal"
    assert out["agent"] == "llm"
    assert out["provider"] == "fake"
    assert out["entity"] == "topic:payments.settlement"
    assert out["classification"]
    assert isinstance(out["result"], dict)
    assert "=== LLM TRIAGE" in out["response"]


def test_llm_agent_free_text_guidance(fake_chat):
    from agent.core_agent import LLMAgent

    out = LLMAgent(chat_model=fake_chat).handle("hello")
    assert out["mode"] == "text"
    assert out["response"]


# -- Phase 3b multi-agent A1-A8 pipeline --------------------------------

def test_multiagent_pipeline_runs_all_agents(sample_signal, fake_chat):
    from agent.agents import MultiAgentSentinel

    # retrieval disabled -> no dependency on a FAISS index for this test
    agent = MultiAgentSentinel(chat_model=fake_chat, use_retrieval=False)
    out = agent.run_signal(sample_signal)

    assert out["agent"] == "multiagent"
    assert out["provider"] == "fake"
    assert out["entity"] == "topic:payments.settlement"
    assert out["entity_known"] is True

    # A1 must have run; for a known rising-lag signal the pipeline proceeds past
    # the A1 gate, so A2..A8 should also be present.
    agents = out["agents"]
    assert "a1" in agents
    assert out.get("stop_reason") in (None, "")   # not gated off at A1
    for aid in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"):
        assert aid in agents, f"missing {aid} in pipeline output"

    # A1 classification present; trace lists the agents in order.
    assert agents["a1"]["classification"]
    assert out["trace"][0] == "A1"
    assert "=== MULTI-AGENT INCIDENT" in out["response"]


def test_multiagent_a5_actions_require_approval(sample_signal, fake_chat):
    from agent.agents import MultiAgentSentinel

    agent = MultiAgentSentinel(chat_model=fake_chat, use_retrieval=False)
    out = agent.run_signal(sample_signal)
    a5 = out["agents"]["a5"]
    assert a5["read_only"] is True
    for action in a5.get("actions", []):
        assert action["requires_approval"] is True   # no un-approved actions


def test_multiagent_unknown_entity_is_handled(fake_chat):
    """An entity not in the catalogue should not crash; A1 flags missing data."""
    from agent.agents import MultiAgentSentinel

    signal = {
        "signal_id": "sig-unknown",
        "entity": {"type": "topic", "id": "does.not.exist"},
        "metric_or_event": "consumer_lag",
        "value": 999, "unit": "messages", "environment": "prod",
    }
    out = MultiAgentSentinel(chat_model=fake_chat, use_retrieval=False).run_signal(signal)
    assert out["entity_known"] is False
    assert "a1" in out["agents"]
