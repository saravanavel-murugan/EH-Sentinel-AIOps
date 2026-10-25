"""CLI entrypoint for the Phase 2 baseline agent.

Usage:
    # interactive REPL
    python scripts/run_agent.py

    # single free-text question
    python scripts/run_agent.py --query "who do I notify for payments?"

    # single normalized-signal JSON
    python scripts/run_agent.py --query '{"entity":{"type":"topic","id":"payments.settlement"},"metric_or_event":"consumer_lag","value":125000,"unit":"messages","environment":"prod"}'

    # batch: one input per line (JSON or free text)
    python scripts/run_agent.py --batch data/evaluation/phase2_demo_inputs.txt

    # single input read from a file (robust for signal JSON on Windows PowerShell,
    # which strips embedded double quotes from inline --query arguments)
    python scripts/run_agent.py --query-file data/evaluation/sample_signal.json

Every interaction is appended to logs/interactions.log as a JSON line.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

# Make the package importable whether run from repo root or scripts/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.core_agent import BaselineAgent  # noqa: E402

_LOG_PATH = _REPO_ROOT / "logs" / "interactions.log"


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _log_interaction(user_input: str, result: dict) -> None:
    """Append one structured JSON record to logs/interactions.log."""
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _utc_now(),
        "agent_version": BaselineAgent.version,
        "input": user_input,
        "mode": result.get("mode"),
        "intent": result.get("intent"),
        "entity": result.get("entity"),
        "entity_known": result.get("entity_known"),
        "classification": result.get("classification"),
        "severity": result.get("severity"),
        "response": result.get("response"),
    }
    with _LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_once(agent: BaselineAgent, user_input: str, *, echo: bool = True) -> dict:
    result = agent.handle(user_input)
    _log_interaction(user_input, result)
    if echo:
        print(result["response"])
        print()
    return result


def _run_batch(agent: BaselineAgent, batch_path: Path) -> int:
    if not batch_path.exists():
        print(f"ERROR: batch file not found: {batch_path}", file=sys.stderr)
        return 2
    count = 0
    for raw in batch_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        count += 1
        print(f"----- interaction {count} -----")
        print(f"INPUT: {line}")
        _run_once(agent, line)
    print(f"Logged {count} interaction(s) to {_LOG_PATH}")
    return 0


def _run_interactive(agent: BaselineAgent) -> int:
    print("EventHub Ops Sentinel — Phase 2 baseline agent")
    print("Type a question or paste a normalized-signal JSON. 'exit' to quit.\n")
    while True:
        try:
            user_input = input("sentinel> ").strip()
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
    parser = argparse.ArgumentParser(description="Phase 2 baseline Sentinel agent")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", help="single input (free text or signal JSON)")
    group.add_argument(
        "--query-file",
        dest="query_file",
        help="read a single input from a file (robust for signal JSON on PowerShell)",
    )
    group.add_argument("--batch", help="path to a file of inputs, one per line")
    args = parser.parse_args(argv)

    agent = BaselineAgent()

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
