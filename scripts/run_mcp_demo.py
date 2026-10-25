"""CLI demo for the Phase 5b MCP layer (server + client over JSON-RPC).

Shows three things, all offline-capable (SENTINEL_LLM=fake works):

  1. PROTOCOL  - raw MCP handshake + tools/list + tools/call over the client,
                 printing the JSON-RPC messages that cross the boundary.
  2. GUARDRAILS - a disallowed tool and a schema-invalid call become MCP
                 tool-level errors (isError), not crashes.
  3. AGENT     - the Phase 5 ToolAgent run with use_mcp=True, so every tool it
                 selects is dispatched through the MCP client/server.

Usage (from capstone_agent/):
    python scripts/run_mcp_demo.py            # full demo
    python scripts/run_mcp_demo.py --protocol # just the protocol trace
    python scripts/run_mcp_demo.py --agent    # just the agent-over-MCP run
    python scripts/run_mcp_demo.py --save     # also save transcript to data/evaluation/

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
from mcp import protocol as P  # noqa: E402
from mcp.client import InProcessTransport, SentinelMCPClient  # noqa: E402
from mcp.server import SentinelMCPServer  # noqa: E402

_LOG = _REPO_ROOT / "logs" / "mcp_events.log"


def _log(kind: str, payload: dict) -> None:
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
           "component": "mcp_demo", "kind": kind, **payload}
    with _LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _pp(label: str, obj) -> None:
    print(f"{label}:")
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    print()


def _protocol_demo() -> None:
    print("###### 1. MCP PROTOCOL TRACE (JSON-RPC over in-process transport) ######\n")
    server = SentinelMCPServer()

    # A transport that echoes each request/response so we can print the wire.
    class TracingTransport(InProcessTransport):
        def send(self, request):
            _pp(">> request (client -> server)", request)
            resp = super().send(request)
            _pp("<< response (server -> client)", resp)
            _log("wire", {"request": request, "response": resp})
            return resp

    client = SentinelMCPClient(TracingTransport(server))

    print("-- initialize (handshake) --")
    client.initialize()
    print(f"   server: {client.server_info}  protocol: {client.protocol_version}\n")

    print("-- tools/list (discover advertised tools) --")
    tools = client.list_tools()
    print(f"   advertised: {[t.name for t in tools]}\n")

    print("-- tools/call: lookup_metric (read-only) --")
    client.call_tool("lookup_metric",
                     {"entity_id": "topic:payments.settlement", "metric": "consumer_lag"})

    print("-- tools/call: escalate_incident (approval-gated, dry-run) --")
    client.call_tool("escalate_incident",
                     {"entity_id": "topic:payments.settlement", "severity": "P1",
                      "message": "settlement consumer lag rising"})


def _guardrail_demo() -> None:
    print("\n###### 2. GUARDRAILS OVER MCP (tool-level errors, not crashes) ######\n")
    client = SentinelMCPClient().connect()

    print("-- disallowed/unknown tool (restart_broker) --")
    res = client.dispatch("restart_broker", {"broker": "broker-3"})
    print(f"   ok={res['ok']} error={res['error']}\n")
    _log("guardrail", {"case": "disallowed_tool", "result": res})

    print("-- schema-invalid (missing required 'metric') --")
    res = client.dispatch("lookup_metric", {"entity_id": "topic:payments.settlement"})
    print(f"   ok={res['ok']} error={res['error']}\n")
    _log("guardrail", {"case": "schema_invalid", "result": res})

    print("-- unknown argument (bad_field) --")
    res = client.dispatch("search_knowledge", {"query": "lag", "bad_field": 1})
    print(f"   ok={res['ok']} error={res['error']}\n")
    _log("guardrail", {"case": "unknown_arg", "result": res})


def _citations_from_steps(out: dict) -> list[str]:
    """Pull 'source :: heading (score)' citations from a search_knowledge step."""
    cites: list[str] = []
    for step in out.get("steps", []):
        if step.get("tool") == "search_knowledge" and step.get("ok"):
            result = step.get("result") or {}
            for hit in result.get("hits", []):
                cites.append(f"{hit.get('source')} :: {hit.get('heading')} "
                             f"({hit.get('score')})")
    return cites


def _agent_demo() -> None:
    print("\n###### 3. TOOLAGENT DISPATCHING OVER MCP ######\n")
    agent = ToolAgent(use_mcp=True)
    print(f"[mcp] agent transport = {agent.transport}; "
          f"tools = {agent.registry.names()}\n")
    for req in [
        "who should I notify for a P1 on topic:payments.settlement",
        "what is the recent consumer_lag value on topic:payments.settlement",
        # A knowledge lookup so the demo shows which DOCUMENTS were referenced
        # by the search_knowledge tool after the MCP tools/call.
        "how do I handle rising consumer lag on a topic",
    ]:
        print(f"--- request: {req}")
        out = agent.handle(req)
        print(out["response"])
        cites = _citations_from_steps(out)
        if cites:
            print("       documents referenced (via search_knowledge over MCP):")
            for c in cites:
                print(f"         - {c}")
        print()
        _log("agent_over_mcp", {"request": req, "transport": out["transport"],
                                "stop_reason": out["stop_reason"],
                                "documents_referenced": cites})


class _Tee:
    """Mirror everything written to stdout into a buffer, so we can also save it."""

    def __init__(self, stream, buffer):
        self._stream = stream
        self._buffer = buffer

    def write(self, text):
        self._stream.write(text)
        self._buffer.write(text)

    def flush(self):
        self._stream.flush()


def _run_sections(args) -> None:
    if args.protocol:
        _protocol_demo()
    elif args.agent:
        _agent_demo()
    else:
        _protocol_demo()
        _guardrail_demo()
        _agent_demo()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 5b MCP demo")
    p.add_argument("--protocol", action="store_true", help="only the protocol trace")
    p.add_argument("--agent", action="store_true", help="only the agent-over-MCP run")
    p.add_argument("--save", nargs="?", const="__default__", default=None,
                   help="save the full transcript to a file "
                        "(default data/evaluation/mcp_demo_transcript.txt)")
    args = p.parse_args(argv)

    if args.save is None:
        _run_sections(args)
        return 0

    # Capture the full transcript while still printing it live.
    import io

    buffer = io.StringIO()
    original = sys.stdout
    sys.stdout = _Tee(original, buffer)
    try:
        _run_sections(args)
    finally:
        sys.stdout = original

    if args.save == "__default__":
        eval_dir = _REPO_ROOT / "data" / "evaluation"
        eval_dir.mkdir(parents=True, exist_ok=True)
        out_path = eval_dir / "mcp_demo_transcript.txt"
    else:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    header = (f"# MCP demo transcript\n"
              f"# generated: {_dt.datetime.now(_dt.timezone.utc).isoformat()}\n\n")
    out_path.write_text(header + buffer.getvalue(), encoding="utf-8")
    print(f"\n[saved transcript] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
