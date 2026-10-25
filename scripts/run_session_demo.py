"""Phase 6 demo — planning, memory & multi-turn conversation (offline-capable).

Drives a single SentinelSession through a scripted multi-turn conversation to
show the Phase 6 additions end to end:

  1. a signal turn  -> plan decomposition + A1-A8 trace + incident persisted
  2. a follow-up    -> answered from memory + Phase 5 tools (metric lookup)
  3. a follow-up    -> knowledge search (runbook) via tools
  4. the SAME entity signal again -> long-term memory flags RECURRENCE
  5. 'reset'         -> short-term cleared, long-term RETAINED

By default it uses a temp long-term memory file so the demo is reproducible and
does not touch logs/incident_memory.json. Pass --persist to use the real store.

Usage (from capstone_agent/):
    python scripts/run_session_demo.py
    python scripts/run_session_demo.py --persist
    SENTINEL_LLM=openai python scripts/run_session_demo.py   # live (needs key)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.env_config import load_env  # noqa: E402

load_env()

from agent.session import SentinelSession  # noqa: E402

_SIGNAL = (
    '{"signal_id": "sig-demo-1", "source": "control_center", '
    '"entity": {"type": "topic", "id": "payments.settlement"}, '
    '"metric_or_event": "consumer_lag", "value": 60000, '
    '"unit": "messages", "environment": "prod"}'
)
_SIGNAL_AGAIN = (
    '{"signal_id": "sig-demo-2", "source": "control_center", '
    '"entity": {"type": "topic", "id": "payments.settlement"}, '
    '"metric_or_event": "consumer_lag", "value": 72000, '
    '"unit": "messages", "environment": "prod"}'
)

_TURNS = [
    ("signal   ", _SIGNAL),
    ("follow-up", "what is the recent consumer_lag value on topic:payments.settlement"),
    ("follow-up", "how do I handle rising consumer lag on a topic"),
    ("signal   ", _SIGNAL_AGAIN),   # recurrence
    ("control  ", "reset"),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 6 session demo")
    p.add_argument("--persist", action="store_true",
                   help="use the real logs/incident_memory.json (default: temp file)")
    p.add_argument("--no-retrieval", action="store_true",
                   help="disable RAG (avoids needing a FAISS index)")
    p.add_argument("--no-save", action="store_true",
                   help="do not write the evidence transcript "
                        "(default writes data/evaluation/phase6_session_transcript.{txt,json})")
    args = p.parse_args(argv)

    tmp: tempfile.TemporaryDirectory | None = None
    if args.persist:
        mem_path = None  # session default (logs/incident_memory.json)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="sentinel_phase6_")
        mem_path = Path(tmp.name) / "incident_memory.json"

    session = SentinelSession(
        use_retrieval=not args.no_retrieval,
        memory_path=mem_path,
    )

    print("EventHub Ops Sentinel — Phase 6 session demo "
          f"(provider={session.provider}, retrieval={session.retrieval_enabled})")
    print(f"Long-term memory: {'logs/incident_memory.json' if args.persist else mem_path}")
    print("=" * 70)

    # Collect a structured record of the conversation for the evidence transcript.
    turn_records: list[dict] = []
    for label, text in _TURNS:
        print(f"\n>>> [{label}] {text[:72]}{'...' if len(text) > 72 else ''}")
        mem_before = session.snapshot()
        out = session.handle_turn(text)
        mem_after = session.snapshot()
        print(out["response"])
        print("-" * 70)
        turn_records.append({
            "label": label.strip(),
            "input": text,
            "response": out.get("response"),
            "kind": out.get("kind"),
            "memory_before": {
                "short_term_turns": mem_before["conversation"]["turn_count"],
                "long_term_count": mem_before["long_term_memory"]["count"],
            },
            "memory_after": {
                "short_term_turns": mem_after["conversation"]["turn_count"],
                "long_term_count": mem_after["long_term_memory"]["count"],
            },
        })

    # Final snapshot: show that long-term memory survived the reset.
    snap = session.snapshot()
    print("\n=== SESSION SNAPSHOT ===")
    print(f"Short-term turns (post-reset): {snap['conversation']['turn_count']}")
    print(f"Long-term incidents retained : {snap['long_term_memory']['count']}")
    for r in snap["long_term_memory"]["records"]:
        print(f"  - {r['incident_id']}  {r['entity']}  {r['metric']}  "
              f"{r['severity']}  ({r['classification']})")

    if not args.no_save:
        _write_transcript(session, turn_records, snap)

    if tmp is not None:
        tmp.cleanup()
    return 0


def _eval_dir() -> Path:
    cand = _REPO_ROOT / "data" / "evaluation"
    if cand.exists():
        return cand
    alt = _REPO_ROOT / "data"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


def _write_transcript(session, turn_records: list[dict], snap: dict) -> None:
    """Write the multi-turn evidence transcript (txt + json)."""
    out_dir = _eval_dir()
    report = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "provider": session.provider,
        "retrieval_enabled": session.retrieval_enabled,
        "n_turns": len(turn_records),
        "turns": turn_records,
        "final_snapshot": {
            "short_term_turns": snap["conversation"]["turn_count"],
            "long_term_count": snap["long_term_memory"]["count"],
            "long_term_records": snap["long_term_memory"]["records"],
        },
    }
    json_path = out_dir / "phase6_session_transcript.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    lines = [
        "# Phase 6 — multi-turn session evidence transcript",
        f"# generated: {report['generated_at']}",
        f"# provider: {report['provider']}  retrieval: {report['retrieval_enabled']}",
        "",
        "Demonstrates: plan/trace on a signal turn, answer-from-memory follow-ups,",
        "recurrence detection via long-term memory, and reset (short-term cleared,",
        "long-term retained).",
        "",
    ]
    for i, t in enumerate(turn_records, 1):
        lines.append(f"## Turn {i} [{t['label']}] (kind={t.get('kind')})")
        lines.append(f"- input: {t['input']}")
        lines.append(f"- short-term turns: {t['memory_before']['short_term_turns']} "
                     f"-> {t['memory_after']['short_term_turns']}; "
                     f"long-term: {t['memory_before']['long_term_count']} "
                     f"-> {t['memory_after']['long_term_count']}")
        lines.append("")
        lines.append("```")
        lines.append((t.get("response") or "").rstrip())
        lines.append("```")
        lines.append("")
    lines.append("## Final snapshot")
    lines.append(f"- short-term turns (post-reset): "
                 f"{report['final_snapshot']['short_term_turns']}")
    lines.append(f"- long-term incidents retained: "
                 f"{report['final_snapshot']['long_term_count']}")
    for r in report["final_snapshot"]["long_term_records"]:
        lines.append(f"  - {r['incident_id']}  {r['entity']}  {r['metric']}  "
                     f"{r['severity']}  ({r['classification']})")
    txt_path = out_dir / "phase6_session_transcript.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[saved transcript]\n  {json_path}\n  {txt_path}")


if __name__ == "__main__":
    raise SystemExit(main())
