"""Phase 7 demo — adaptive behaviour from operator feedback (offline-capable).

Shows a clean BEFORE vs AFTER on the SAME entity:

  1. BEFORE — a signal turn with NO feedback on record (behaves exactly like
     Phase 6; nothing adapted).
  2. several NON-SENSITIVE negative feedback signals are recorded for that
     entity/incident (repeated ``severity_too_low`` and ``too_verbose``).
  3. AFTER — the SAME entity signal runs again; the response now carries an
     ADAPTATION (advisory) section: a concise body, an advisory severity nudge,
     and a stronger recurrence banner.
  4. a clear BEFORE-vs-AFTER comparison plus the adaptation explanations.

Adaptation is ADVISORY only. It never changes A1-A8 output, never auto-approves
an action, and never suppresses escalation — the safety NOTE is always present.

By default it uses a temp feedback + memory dir so the demo is reproducible and
does not touch logs/. Pass --persist to use the real stores.

Usage (from capstone_agent/):
    python scripts/run_phase7_feedback_demo.py
    python scripts/run_phase7_feedback_demo.py --no-retrieval
    python scripts/run_phase7_feedback_demo.py --persist
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

_SIGNAL_BEFORE = (
    '{"signal_id": "sig-p7-before", "source": "control_center", '
    '"entity": {"type": "topic", "id": "payments.settlement"}, '
    '"metric_or_event": "consumer_lag", "value": 60000, '
    '"unit": "messages", "environment": "prod"}'
)
_SIGNAL_AFTER = (
    '{"signal_id": "sig-p7-after", "source": "control_center", '
    '"entity": {"type": "topic", "id": "payments.settlement"}, '
    '"metric_or_event": "consumer_lag", "value": 72000, '
    '"unit": "messages", "environment": "prod"}'
)

# Non-sensitive feedback submitted between the before/after turns. Notes are
# deliberately generic — NO secrets, NO PII.
_FEEDBACK = [
    {"category": "severity_too_low", "signal": "down",
     "note": "operator felt the assessed severity understated the business risk"},
    {"category": "severity_too_low", "signal": "down",
     "note": "second operator agreed severity looked too low"},
    {"category": "too_verbose", "signal": "down",
     "note": "response was longer than needed for triage"},
    {"category": "too_verbose", "signal": "down",
     "note": "prefer a concise summary during an incident"},
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 7 adaptive-behaviour demo")
    p.add_argument("--persist", action="store_true",
                   help="use the real logs/ stores (default: temp files)")
    p.add_argument("--no-retrieval", action="store_true",
                   help="disable RAG (avoids needing a FAISS index)")
    p.add_argument("--no-save", action="store_true",
                   help="do not write the evidence transcript "
                        "(default writes data/evaluation/phase7_feedback_transcript.{txt,json})")
    args = p.parse_args(argv)

    tmp: tempfile.TemporaryDirectory | None = None
    if args.persist:
        mem_path = None       # session defaults (logs/)
        fb_path = None
    else:
        tmp = tempfile.TemporaryDirectory(prefix="sentinel_phase7_")
        mem_path = Path(tmp.name) / "incident_memory.json"
        fb_path = Path(tmp.name) / "feedback.json"

    session = SentinelSession(
        use_retrieval=not args.no_retrieval,
        memory_path=mem_path,
        feedback_path=fb_path,
    )

    print("EventHub Ops Sentinel — Phase 7 adaptive-behaviour demo "
          f"(provider={session.provider}, retrieval={session.retrieval_enabled})")
    print(f"Feedback store: {'logs/feedback.json' if args.persist else fb_path}")
    print("=" * 72)

    # --- (1) BEFORE: no feedback on record -> identical to Phase 6 ---
    print("\n>>> [BEFORE] signal turn with NO feedback on record")
    out_before = session.handle_turn(_SIGNAL_BEFORE)
    print(out_before["response"])
    print(f"\n[adaptation applied? {_applied(out_before)}]")
    print("-" * 72)

    # --- (2) record several NON-SENSITIVE negative feedback signals ---
    print("\n>>> [FEEDBACK] recording operator feedback (non-sensitive)")
    recorded: list[dict] = []
    for fb in _FEEDBACK:
        res = session.record_feedback(**fb)
        recorded.append({**fb, **{k: res.get(k) for k in
                                  ("feedback_id", "negative", "count_for_entity")}})
        print(f"  - {res.get('feedback_id')}  {fb['category']:17s} "
              f"negative={res.get('negative')}")
    print("-" * 72)

    # --- (3) AFTER: same entity signal -> adapted presentation ---
    print("\n>>> [AFTER] SAME entity signal — adapted (advisory) presentation")
    out_after = session.handle_turn(_SIGNAL_AFTER)
    print(out_after["response"])
    print("-" * 72)

    # --- (4) BEFORE vs AFTER comparison ---
    print("\n=== BEFORE vs AFTER ===")
    print(f"BEFORE adaptation flags: {out_before['adaptation']}")
    print(f"AFTER  adaptation flags: {out_after['adaptation']}")
    print("\nAdaptation explanations (AFTER):")
    for note in out_after["adaptation"].get("explanations", []):
        print(f"  - {note}")
    print("\nSafety invariant: both responses keep the advisory safety NOTE and "
          "neither auto-approves actions or suppresses escalation.")

    if not args.no_save:
        _write_transcript(session, out_before, recorded, out_after)

    if tmp is not None:
        tmp.cleanup()
    return 0


def _applied(out: dict) -> bool:
    a = out.get("adaptation", {}) or {}
    return bool(a.get("severity_nudge") or a.get("concise") or a.get("recurrence_emphasis"))


def _eval_dir() -> Path:
    cand = _REPO_ROOT / "data" / "evaluation"
    if cand.exists():
        return cand
    alt = _REPO_ROOT / "data"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


def _write_transcript(session, out_before: dict, recorded: list[dict],
                      out_after: dict) -> None:
    """Write the before-vs-after evidence transcript (txt + json)."""
    out_dir = _eval_dir()
    report = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "provider": session.provider,
        "retrieval_enabled": session.retrieval_enabled,
        "before": {
            "input": _SIGNAL_BEFORE,
            "adaptation": out_before.get("adaptation"),
            "response": out_before.get("response"),
        },
        "feedback_recorded": recorded,
        "after": {
            "input": _SIGNAL_AFTER,
            "adaptation": out_after.get("adaptation"),
            "response": out_after.get("response"),
        },
        "feedback_summary": session.snapshot().get("feedback"),
    }
    json_path = out_dir / "phase7_feedback_transcript.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    lines = [
        "# Phase 7 — adaptive-behaviour evidence transcript (before vs after)",
        f"# generated: {report['generated_at']}",
        f"# provider: {report['provider']}  retrieval: {report['retrieval_enabled']}",
        "",
        "Demonstrates: identical-to-Phase-6 behaviour with NO feedback, then an",
        "ADAPTED (advisory-only) presentation after repeated negative operator",
        "feedback on the SAME entity. Adaptation never changes A1-A8 output,",
        "auto-approves actions, or suppresses escalation.",
        "",
        "## BEFORE (no feedback)",
        f"- input: {report['before']['input']}",
        f"- adaptation flags: {report['before']['adaptation']}",
        "",
        "```",
        (report["before"]["response"] or "").rstrip(),
        "```",
        "",
        "## Feedback recorded (non-sensitive)",
    ]
    for r in recorded:
        lines.append(f"- {r.get('feedback_id')}  {r['category']}  "
                     f"negative={r.get('negative')}  note: {r['note']}")
    lines += [
        "",
        "## AFTER (post-feedback, adapted)",
        f"- input: {report['after']['input']}",
        f"- adaptation flags: {report['after']['adaptation']}",
        "",
        "```",
        (report["after"]["response"] or "").rstrip(),
        "```",
        "",
        "## Adaptation explanations (AFTER)",
    ]
    for note in (report["after"]["adaptation"] or {}).get("explanations", []):
        lines.append(f"- {note}")
    txt_path = out_dir / "phase7_feedback_transcript.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[saved transcript]\n  {json_path}\n  {txt_path}")


if __name__ == "__main__":
    raise SystemExit(main())
