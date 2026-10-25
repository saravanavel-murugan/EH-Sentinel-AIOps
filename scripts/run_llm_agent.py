"""CLI entrypoint for the Phase 3 LLM triage agent (LangChain + LangGraph).

Usage:
    # single signal from a file (recommended on Windows PowerShell)
    python scripts/run_llm_agent.py --query-file data/evaluation/sample_signal.json

    # choose prompt version (v1|v2|v3); defaults to SENTINEL_PROMPT_VERSION or v3
    python scripts/run_llm_agent.py --query-file data/evaluation/sample_signal.json --prompt-version v1

    # batch of signals (one JSON per line)
    python scripts/run_llm_agent.py --batch data/evaluation/phase2_demo_inputs.txt

    # interactive
    python scripts/run_llm_agent.py

Provider comes from SENTINEL_LLM (fake=offline default, openai=live with OPENAI_API_KEY).
Reads .env if python-dotenv is available. Every interaction is logged to
logs/interactions.log as a JSON line.
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

from agent.core_agent import LLMAgent  # noqa: E402

_LOG_PATH = _REPO_ROOT / "logs" / "interactions.log"


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _log_interaction(user_input: str, result: dict) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _utc_now(),
        "agent_version": LLMAgent.version,
        "provider": result.get("provider"),
        "prompt_version": result.get("prompt_version"),
        "input": user_input,
        "mode": result.get("mode"),
        "entity": result.get("entity"),
        "entity_known": result.get("entity_known"),
        "classification": result.get("classification"),
        "severity": result.get("severity"),
        "llm_error": result.get("llm_error"),
        "response": result.get("response"),
    }
    with _LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_once(agent: LLMAgent, user_input: str) -> dict:
    result = agent.handle(user_input)
    _log_interaction(user_input, result)
    print(result["response"])
    print()
    return result


def _run_batch(agent: LLMAgent, batch_path: Path) -> int:
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
        _run_once(agent, line)
    print(f"Logged {count} interaction(s) to {_LOG_PATH}")
    return 0


def _run_interactive(agent: LLMAgent) -> int:
    print(f"EventHub Ops Sentinel — Phase 3 LLM agent "
          f"(provider={agent.provider}, prompt={agent.prompt_version})")
    print("Paste a normalized-signal JSON. 'exit' to quit.\n")
    while True:
        try:
            user_input = input("sentinel-llm> ").strip()
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
    parser = argparse.ArgumentParser(description="Phase 3 LLM Sentinel agent")
    parser.add_argument("--prompt-version", dest="prompt_version", choices=["v1", "v2", "v3"],
                        help="prompt strategy version (default: env or v3)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", help="single input (signal JSON or free text)")
    group.add_argument("--query-file", dest="query_file", help="read single input from a file")
    group.add_argument("--batch", help="path to a file of inputs, one per line")
    args = parser.parse_args(argv)

    agent = LLMAgent(prompt_version=args.prompt_version)

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
