"""Close an incident and document it in the knowledge base (Phase 4+ closure loop).

Runs the A1-A8 pipeline on a signal to produce the consolidated A6 record, then
captures the RESOLUTION and the ACTIONS ACTUALLY TAKEN and writes a resolved-
incident markdown under knowledge/raw/incidents/ for future retrieval.

Usage (from capstone_agent/):
    # interactive: shows the A6 record, prompts for actions taken + resolution
    python scripts/close_incident.py --query-file data/evaluation/sample_signal.json

    # non-interactive (CI / scripted):
    python scripts/close_incident.py --query-file data/evaluation/sample_signal.json \
        --action "Scaled consumer group from 4 to 8 instances" \
        --action "Confirmed lag returned to baseline" \
        --resolution "Lag cleared after scale-out; monitored for 30 min." \
        --root-cause "Under-capacity consumer group" \
        --reindex

After writing, pass --reindex (or run ingest + build_faiss_index) to fold the
new incident doc into the FAISS index.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.env_config import load_env  # noqa: E402

load_env()

from agent.agents import MultiAgentSentinel  # noqa: E402
from knowledge.incident_writer import write_resolved_incident  # noqa: E402


def _load_signal(args: argparse.Namespace) -> dict:
    if args.query_file:
        return json.loads(Path(args.query_file).read_text(encoding="utf-8"))
    if args.query:
        return json.loads(args.query)
    raise SystemExit("Provide --query-file or --query with a normalized-signal JSON.")


def _reindex() -> None:
    print("\nRe-indexing knowledge base (ingest + build FAISS)...")
    for script in ("ingest_documents.py", "build_faiss_index.py"):
        r = subprocess.run([sys.executable, str(_REPO_ROOT / "scripts" / script)],
                           capture_output=True, text=True)
        print(f"  {script}: rc={r.returncode}")
        if r.returncode != 0:
            print(r.stderr[-400:])
            return
    print("Re-index complete. The resolved incident is now retrievable.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Close an incident and document it in knowledge")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--query-file", dest="query_file")
    g.add_argument("--query")
    p.add_argument("--action", action="append", default=[],
                   help="an action actually taken (repeatable)")
    p.add_argument("--resolution", default="")
    p.add_argument("--root-cause", dest="root_cause", default="")
    p.add_argument("--closed-by", dest="closed_by", default="operator")
    p.add_argument("--reindex", action="store_true", help="rebuild the FAISS index after writing")
    args = p.parse_args(argv)

    signal = _load_signal(args)
    agent = MultiAgentSentinel(use_retrieval=True)
    result = agent.run_signal(signal)
    a6 = (result.get("agents") or {}).get("a6")

    if not a6:
        print("No incident was opened (A1 gated the signal to a watch state). Nothing to close.")
        print("Gate reason:", result.get("stop_reason"))
        return 0

    # Show the consolidated A6 record so the operator closes with full context.
    print("\n================ CONSOLIDATED INCIDENT RECORD (A6) ================")
    print(a6.get("closure_document", ""))
    print("==================================================================\n")

    actions_taken = list(args.action)
    resolution = args.resolution
    final_root_cause = args.root_cause

    # Interactive capture if not supplied on the command line.
    interactive = not actions_taken and not resolution and sys.stdin.isatty()
    if interactive:
        print("Enter the ACTIONS ACTUALLY TAKEN (one per line, blank line to finish):")
        while True:
            try:
                line = input("  action> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            actions_taken.append(line)
        resolution = input("Resolution / outcome notes: ").strip()
        final_root_cause = input("Confirmed root cause (optional): ").strip()

    path = write_resolved_incident(
        a6, actions_taken=actions_taken, resolution=resolution,
        final_root_cause=final_root_cause, closed_by=args.closed_by,
    )
    print(f"Wrote resolved incident to: {path}")

    if args.reindex:
        _reindex()
    else:
        print("\nTo make this incident retrievable, run:\n"
              "  python scripts/ingest_documents.py && python scripts/build_faiss_index.py\n"
              "(or re-run this command with --reindex)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
