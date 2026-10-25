"""One-shot smoke test for the whole Sentinel system (no pytest dependency).

Runs the three layers end-to-end on the OFFLINE FAKE providers and prints a
PASS/FAIL summary. Exits non-zero if any check fails, so it works in CI too.

    Layer 1  MCP protocol + server + client + 3 tools
    Layer 2  ToolAgent: in-process vs MCP parity + guardrails
    Layer 3  Phase 2 baseline, Phase 3 LLM, Phase 3b A1-A8 agents

Usage (from capstone_agent/):
    python scripts/test_all.py

For assertable regression coverage with detail, use the pytest suite instead:
    python -m pytest tests/ -q
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Force deterministic offline providers BEFORE importing agent code.
os.environ["SENTINEL_LLM"] = "fake"
os.environ["SENTINEL_EMBEDDINGS"] = "fake"
os.environ.pop("OPENAI_API_KEY", None)

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))
    mark = "PASS" if cond else "FAIL"
    line = f"  [{mark}] {name}"
    if detail and not cond:
        line += f"  -> {detail}"
    print(line)


SIGNAL = {
    "signal_id": "sig-smoke", "source": "control_center",
    "entity": {"type": "topic", "id": "payments.settlement"},
    "metric_or_event": "consumer_lag", "value": 60000,
    "unit": "messages", "environment": "prod",
}


def layer1_mcp() -> None:
    print("\n### Layer 1 — MCP protocol + server + client + tools ###")
    from mcp import connect_in_process
    from mcp import protocol as P

    client = connect_in_process()
    check("handshake negotiates protocol version",
          client.protocol_version == P.PROTOCOL_VERSION, str(client.protocol_version))
    check("server identifies itself",
          client.server_info.get("name") == "eventhub-sentinel-mcp",
          str(client.server_info))
    check("tools/list advertises all 3 tools",
          set(client.names()) == {"search_knowledge", "lookup_metric", "escalate_incident"},
          str(client.names()))

    r = client.call_tool("lookup_metric",
                         {"entity_id": "topic:payments.settlement", "metric": "consumer_lag"})
    check("tools/call lookup_metric ok", r["ok"] and r["result"]["latest"] == 125000)

    esc = client.call_tool("escalate_incident",
                           {"entity_id": "topic:payments.settlement", "severity": "P1",
                            "message": "lag"})
    check("escalate is dry-run + approval-gated",
          esc["ok"] and esc["result"]["delivery_status"] == "not_sent"
          and esc["result"]["requires_approval"] is True)

    bad = client.dispatch("restart_broker", {"x": 1})
    check("disallowed tool rejected (guardrail)", bad["ok"] is False and "allow-list" in bad["error"])
    miss = client.dispatch("lookup_metric", {"entity_id": "topic:payments.settlement"})
    check("missing required arg rejected", miss["ok"] is False and "missing required" in miss["error"])
    unk = client.dispatch("search_knowledge", {"query": "x", "bad": 1})
    check("unknown arg rejected", unk["ok"] is False and "unknown argument" in unk["error"])


def layer2_tool_agent() -> None:
    print("\n### Layer 2 — ToolAgent: in-process vs MCP parity + guardrails ###")
    from agent.llm import DeterministicSentinelChatModel
    from agent.tool_agent import ToolAgent

    def first_tool(out):
        for s in out["steps"]:
            if s.get("tool") and s["tool"] != "none":
                return s["tool"]
        return "none"

    def result(out):
        for s in out["steps"]:
            if s.get("ok"):
                return s.get("result")
        return None

    cases = [
        ("who should I notify for a P1 on topic:payments.settlement", "escalate_incident"),
        ("what is the recent consumer_lag value on topic:payments.settlement", "lookup_metric"),
        ("how do I handle rising consumer lag on a topic", "search_knowledge"),
    ]
    for req, expected in cases:
        local = ToolAgent(chat_model=DeterministicSentinelChatModel()).handle(req)
        remote = ToolAgent(chat_model=DeterministicSentinelChatModel(), use_mcp=True).handle(req)
        check(f"selects {expected} (in-process)", first_tool(local) == expected, first_tool(local))
        check(f"selects {expected} (over MCP)",
              remote["transport"] == "mcp" and first_tool(remote) == expected, first_tool(remote))
        check(f"in-process == MCP result for {expected}", result(local) == result(remote))


def layer3_agents() -> None:
    print("\n### Layer 3 — Phase 2 / 3 / 3b agents (end-to-end) ###")
    from agent.agents import MultiAgentSentinel
    from agent.core_agent import BaselineAgent, LLMAgent
    from agent.llm import DeterministicSentinelChatModel

    base = BaselineAgent().handle(json.dumps(SIGNAL))
    check("baseline agent triages signal",
          base["mode"] == "signal" and base["entity"] == "topic:payments.settlement")

    llm = LLMAgent(chat_model=DeterministicSentinelChatModel()).handle(json.dumps(SIGNAL))
    check("LLM agent triages signal",
          llm["mode"] == "signal" and llm["provider"] == "fake" and bool(llm["classification"]))

    ma = MultiAgentSentinel(chat_model=DeterministicSentinelChatModel(),
                            use_retrieval=False).run_signal(SIGNAL)
    present = all(a in ma["agents"] for a in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"))
    check("multi-agent pipeline runs A1-A8", present, str(list(ma["agents"].keys())))
    a5 = ma["agents"].get("a5", {})
    check("A5 actions all require approval",
          a5.get("read_only") is True
          and all(x.get("requires_approval") for x in a5.get("actions", [])))


def main() -> int:
    print("EventHub Ops Sentinel — full smoke test (offline fake providers)")
    layer1_mcp()
    layer2_tool_agent()
    layer3_agents()

    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n=== SUMMARY: {passed}/{total} checks passed ===")
    failures = [n for n, ok, _ in _results if not ok]
    if failures:
        print("FAILED:")
        for n in failures:
            print(f"  - {n}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
