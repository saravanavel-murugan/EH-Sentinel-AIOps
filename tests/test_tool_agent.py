"""ToolAgent tests: tool selection, guardrails, and in-process vs MCP parity.

All runs use the deterministic fake chat model so the router is reproducible.
"""

from __future__ import annotations

import pytest

from agent.tool_agent import ToolAgent

# (request, expected tool) for the deterministic fake router.
SELECTION_CASES = [
    ("who should I notify for a P1 on topic:payments.settlement", "escalate_incident"),
    ("what is the recent consumer_lag value on topic:payments.settlement", "lookup_metric"),
    ("how do I handle rising consumer lag on a topic", "search_knowledge"),
]


def _first_tool(out: dict) -> str:
    for step in out["steps"]:
        if step.get("tool") and step["tool"] != "none":
            return step["tool"]
    return "none"


# -- transport wiring ----------------------------------------------------

def test_default_transport_in_process(fake_chat):
    agent = ToolAgent(chat_model=fake_chat)
    assert agent.transport == "in-process"


def test_mcp_transport(fake_chat):
    agent = ToolAgent(chat_model=fake_chat, use_mcp=True)
    assert agent.transport == "mcp"
    assert set(agent.registry.names()) == {"search_knowledge", "lookup_metric",
                                           "escalate_incident"}


# -- correct tool selection ---------------------------------------------

@pytest.mark.parametrize("request_text,expected_tool", SELECTION_CASES)
def test_tool_selection_in_process(fake_chat, request_text, expected_tool):
    out = ToolAgent(chat_model=fake_chat).handle(request_text)
    assert _first_tool(out) == expected_tool


@pytest.mark.parametrize("request_text,expected_tool", SELECTION_CASES)
def test_tool_selection_over_mcp(fake_chat, request_text, expected_tool):
    out = ToolAgent(chat_model=fake_chat, use_mcp=True).handle(request_text)
    assert out["transport"] == "mcp"
    assert _first_tool(out) == expected_tool


# -- in-process vs MCP parity -------------------------------------------

@pytest.mark.parametrize("request_text,_t", SELECTION_CASES)
def test_in_process_and_mcp_produce_same_tool_result(fake_chat, request_text, _t):
    """The MCP boundary must be transparent: same selection + same tool result,
    only the transport label differs."""
    local = ToolAgent(chat_model=fake_chat).handle(request_text)
    remote = ToolAgent(chat_model=fake_chat, use_mcp=True).handle(request_text)

    assert local["transport"] == "in-process"
    assert remote["transport"] == "mcp"
    assert _first_tool(local) == _first_tool(remote)

    def _result(out):
        for s in out["steps"]:
            if s.get("ok"):
                return s.get("result")
        return None

    assert _result(local) == _result(remote)


# -- approval gate -------------------------------------------------------

def test_escalate_approval_gate(fake_chat):
    out = ToolAgent(chat_model=fake_chat, use_mcp=True).handle(
        "who should I notify for a P1 on topic:payments.settlement"
    )
    step = next(s for s in out["steps"] if s.get("tool") == "escalate_incident")
    assert "approval" in step                       # approval note attached
    assert step["result"]["delivery_status"] == "not_sent"


# -- guardrails via the registry facade ---------------------------------

def test_mcp_registry_rejects_disallowed_tool(mcp_client):
    ok, why = mcp_client.validate("restart_broker", {"x": 1})
    assert ok is False
    assert "allow-list" in why


def test_loop_prevention_caps_repeated_calls(fake_chat):
    """A degenerate router that always returns the same call must be stopped by
    the repeated-call guard, not loop forever."""
    from tools.tool_registry import build_default_registry

    class RepeatRouter:
        """Chat stub whose router output is always the same tool call."""
        def invoke(self, messages):
            class R:
                content = (
                    '{"tool":"lookup_metric",'
                    '"args":{"entity_id":"topic:payments.settlement",'
                    '"metric":"consumer_lag"},"reason":"always same"}'
                )
            return R()

    agent = ToolAgent(chat_model=RepeatRouter(), registry=build_default_registry(),
                      max_iterations=4)
    out = agent.handle("loop please")
    # Either it succeeds once and stops, or the repeated-call guard trips; in no
    # case does it run the identical call more than once successfully.
    successful = [s for s in out["steps"] if s.get("ok")]
    assert len(successful) <= 1
    assert out["n_steps"] <= agent.max_iterations
