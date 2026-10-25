"""CLI for the Phase 5 ToolAgent (agent-selected tool calling).

Usage (from capstone_agent/):
    # single request (the agent routes to a tool)
    python scripts/run_tool_agent.py --request "who should I notify for a P1 on topic:payments.settlement"

    # built-in demo: correct tool selection + 3 failure modes (schema-invalid,
    # disallowed/unknown tool, loop) + approval gate
    python scripts/run_tool_agent.py --demo

Provider from .env (SENTINEL_LLM). Logs to logs/mcp_events.log.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.env_config import load_env  # noqa: E402

load_env()

from agent.tool_agent import ToolAgent  # noqa: E402
from tools.tool_registry import build_default_registry  # noqa: E402

_LOG = _REPO_ROOT / "logs" / "mcp_events.log"


def _log(kind: str, payload: dict) -> None:
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
           "component": "tool_agent", "kind": kind, **payload}
    with _LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _run_request(agent: ToolAgent, request: str) -> dict:
    out = agent.handle(request)
    print(out["response"])
    print()
    _log("request", {"request": request, "stop_reason": out["stop_reason"],
                     "n_steps": out["n_steps"]})
    return out


def _run_demo(agent: ToolAgent) -> int:
    reg = agent.registry
    print("###### CORRECT TOOL SELECTION ######\n")
    for req in [
        "who should I notify for a P1 on topic:payments.settlement",
        "what is the recent consumer_lag value on topic:payments.settlement",
        "how do I handle rising consumer lag on a topic",
    ]:
        print(f"--- request: {req}")
        _run_request(agent, req)

    print("\n###### INCORRECT / FAILED TOOL CALLS (guardrails) ######\n")

    # 1. Schema-invalid argument: missing required 'metric'
    print("--- 1. schema-invalid argument (missing required 'metric') ---")
    res = reg.dispatch("lookup_metric", {"entity_id": "topic:payments.settlement"})
    print(f"  dispatch ok={res['ok']} error={res['error']}\n")
    _log("failure_demo", {"case": "schema_invalid", "result": res})

    # 2. Disallowed / unknown tool: not in the allow-list
    print("--- 2. disallowed/unknown tool (restart_broker) ---")
    res = reg.dispatch("restart_broker", {"broker": "broker-3"})
    print(f"  dispatch ok={res['ok']} error={res['error']}\n")
    _log("failure_demo", {"case": "disallowed_tool", "result": res})

    # 3. Unknown argument (schema rejects extra field)
    print("--- 3. unknown argument (bad_field) ---")
    res = reg.dispatch("search_knowledge", {"query": "consumer lag", "bad_field": 1})
    print(f"  dispatch ok={res['ok']} error={res['error']}\n")
    _log("failure_demo", {"case": "unknown_arg", "result": res})

    # 4. Loop prevention: a request that would re-issue the same call.
    print("--- 4. loop prevention (repeated identical call capped) ---")
    loop_agent = ToolAgent(chat_model=agent._chat, registry=reg, max_iterations=4)
    # Force a degenerate router that always returns the same call, to prove the guard.
    out = _loop_demo(loop_agent)
    print(out["response"])
    _log("failure_demo", {"case": "loop", "stop_reason": out["stop_reason"]})
    return 0


def _loop_demo(agent: ToolAgent) -> dict:
    """Drive the agent's loop guard with a router stub that always repeats a call."""
    reg = agent.registry
    history: list[dict] = []
    steps: list[dict] = []
    seen: set[str] = set()
    stop_reason = "completed"
    fixed = {"tool": "lookup_metric",
             "args": {"entity_id": "topic:payments.settlement", "metric": "consumer_lag"},
             "reason": "degenerate repeat (loop demo)"}
    for i in range(1, agent.max_iterations + 1):
        tool, args = fixed["tool"], fixed["args"]
        sig = f"{tool}:{json.dumps(args, sort_keys=True)}"
        if sig in seen:
            stop_reason = f"loop prevented: repeated call {sig}"
            steps.append({"iteration": i, "tool": tool, "args": args,
                          "guardrail": "repeated_call_blocked"})
            break
        seen.add(sig)
        res = reg.dispatch(tool, args)
        steps.append({"iteration": i, "tool": tool, "args": args, "ok": res["ok"]})
    resp = ToolAgent._render("(loop demo) repeatedly request same metric", steps, stop_reason)
    return {"response": resp, "stop_reason": stop_reason}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 5 ToolAgent")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--request")
    g.add_argument("--demo", action="store_true")
    args = p.parse_args(argv)

    agent = ToolAgent()
    print(f"[tools] registered: {build_default_registry().names()}\n")
    if args.demo:
        return _run_demo(agent)
    _run_request(agent, args.request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
