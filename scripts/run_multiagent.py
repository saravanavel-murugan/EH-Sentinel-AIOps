"""CLI entrypoint for the A1-A8 multi-agent Sentinel pipeline (LangGraph).

Usage (from capstone_agent/):
    python scripts/run_multiagent.py --query-file data/evaluation/sample_signal.json
    python scripts/run_multiagent.py --batch data/evaluation/phase2_demo_inputs.txt
    python scripts/run_multiagent.py            # interactive

Provider from SENTINEL_LLM (fake=offline default, openai=live with OPENAI_API_KEY).
Each run is logged to logs/mcp_events.log as a JSON line (one incident per run,
with the agent trace and per-agent outputs).
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

load_env()  # .env is authoritative (override=True)

from agent.agents import MultiAgentSentinel  # noqa: E402

_LOG_PATH = _REPO_ROOT / "logs" / "mcp_events.log"


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _log(user_input: str, result: dict) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _utc_now(),
        "pipeline_version": MultiAgentSentinel.version,
        "provider": result.get("provider"),
        "input": user_input,
        "entity": result.get("entity"),
        "entity_known": result.get("entity_known"),
        "trace": result.get("trace"),
        "stop_reason": result.get("stop_reason"),
        "errors": result.get("errors"),
        "agents": result.get("agents"),
    }
    with _LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_once(agent: MultiAgentSentinel, user_input: str) -> dict:
    result = agent.handle(user_input)
    _log(user_input, result)
    print(result["response"])
    print()
    return result


def _run_batch(agent: MultiAgentSentinel, batch_path: Path) -> int:
    if not batch_path.exists():
        print(f"ERROR: batch file not found: {batch_path}", file=sys.stderr)
        return 2
    count = 0
    for raw in batch_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        count += 1
        print(f"----- incident {count} -----")
        _run_once(agent, line)
    print(f"Logged {count} run(s) to {_LOG_PATH}")
    return 0


def _run_interactive(agent: MultiAgentSentinel) -> int:
    print(f"EventHub Ops Sentinel - multi-agent A1-A8 pipeline (provider={agent.provider})")
    print("Paste a normalized-signal JSON. 'exit' to quit.\n")
    while True:
        try:
            user_input = input("sentinel-ma> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue
        _run_once(agent, user_input)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A1-A8 multi-agent Sentinel pipeline")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", help="single input (signal JSON or free text)")
    group.add_argument("--query-file", dest="query_file", help="read single input from a file")
    group.add_argument("--batch", help="path to a file of inputs, one per line")
    args = parser.parse_args(argv)

    agent = MultiAgentSentinel()

    if args.query is not None:
        _run_once(agent, args.query)
        return 0
    if args.query_file is not None:
        qpath = Path(args.query_file)
        if not qpath.exists():
            print(f"ERROR: query file not found: {qpath}", file=sys.stderr)
            return 2
        _run_once(agent, qpath.read_text(encoding="utf-8").strip())
        return 0
    if args.batch is not None:
        return _run_batch(agent, Path(args.batch))
    return _run_interactive(agent)


if __name__ == "__main__":
    raise SystemExit(main())
