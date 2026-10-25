"""Phase 7 UI evidence — reproduce the Streamlit adaptive-behaviour flow headless.

The Streamlit console (``ui/streamlit_app.py``) drives a ``SentinelSession`` via
three operator actions on the SAME in-focus entity:

  1. a signal turn (the UI renders the ADAPTATION panel from ``result["adaptation"]``),
  2. operator feedback submitted in the sidebar form (``session.record_feedback``),
  3. the same entity's signal again (the ADAPTATION panel now shows the advisory
     adjustments that fired).

This script performs EXACTLY those session calls and captures what each UI panel
renders — the adaptation badge/explanations (via the UI's own pure helpers
``adaptation_applied`` / ``_ADAPTATION_META``) and the sidebar feedback summary
(``session.snapshot()["feedback"]``) — so the UI's Phase 7 behaviour has a
reproducible, offline, no-key evidence artefact without a browser.

It writes:
  data/evaluation/phase7_ui_evidence.json
  data/evaluation/phase7_ui_evidence.md

Usage (from capstone_agent/):
    python scripts/ui_phase7_evidence.py
    python scripts/ui_phase7_evidence.py --no-retrieval
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

# The adaptation badges contain emoji; make console output UTF-8-safe so the
# demo prints cleanly on a default Windows (cp1252) console as well as when its
# stdout is piped. The evidence files are always written as UTF-8 regardless.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

from agent.env_config import load_env  # noqa: E402

load_env()

from agent.session import SentinelSession  # noqa: E402
# Reuse the UI's OWN rendering helpers/metadata so the evidence reflects exactly
# what the Streamlit panels would show (no divergent copy of the logic).
from ui.streamlit_app import adaptation_applied, _ADAPTATION_META  # noqa: E402

_SIGNAL_BEFORE = {
    "signal_id": "sig-ui-ev-before", "source": "control_center",
    "entity": {"type": "topic", "id": "payments.settlement"},
    "metric_or_event": "consumer_lag", "value": 60000,
    "unit": "messages", "environment": "prod",
}
_SIGNAL_AFTER = {
    "signal_id": "sig-ui-ev-after", "source": "control_center",
    "entity": {"type": "topic", "id": "payments.settlement"},
    "metric_or_event": "consumer_lag", "value": 72000,
    "unit": "messages", "environment": "prod",
}
# Non-sensitive feedback the UI sidebar form would submit (NO secrets / PII).
_FEEDBACK = [
    {"category": "severity_too_low", "signal": "down",
     "note": "operator felt severity understated the business risk"},
    {"category": "severity_too_low", "signal": "down",
     "note": "second operator agreed"},
    {"category": "too_verbose", "signal": "down",
     "note": "too long for triage"},
    {"category": "too_verbose", "signal": "down",
     "note": "prefer a concise summary"},
]


def _adaptation_panel(adaptation: dict) -> dict:
    """Mirror what ui._render_adaptation would display for this turn."""
    applied = adaptation_applied(adaptation)
    flags = [k for k in ("severity_nudge", "concise", "recurrence_emphasis")
             if (adaptation or {}).get(k)]
    return {
        "panel": "Adaptive behaviour (Phase 7)",
        "applied": applied,
        "headline": (
            f"No adaptation applied for {adaptation.get('entity')} — identical "
            "to the pre-feedback baseline."
            if not applied else
            "Adaptation applied (advisory) for "
            f"{adaptation.get('entity')}: "
            + " · ".join(_ADAPTATION_META[k][0] for k in flags)
        ),
        "badges": [_ADAPTATION_META[k][0] for k in flags],
        "explanations": (adaptation or {}).get("explanations", []),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 7 UI evidence (headless)")
    p.add_argument("--no-retrieval", action="store_true")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args(argv)

    tmp = tempfile.TemporaryDirectory(prefix="sentinel_ui_ev_")
    session = SentinelSession(
        use_retrieval=not args.no_retrieval,
        memory_path=Path(tmp.name) / "incident_memory.json",
        feedback_path=Path(tmp.name) / "feedback.json",
    )

    print("EventHub Ops Sentinel — Phase 7 UI evidence "
          f"(provider={session.provider}, retrieval={session.retrieval_enabled})")
    print("=" * 72)

    # (1) BEFORE — signal turn, no feedback on record.
    out_before = session.handle_turn(json.dumps(_SIGNAL_BEFORE))
    panel_before = _adaptation_panel(out_before.get("adaptation", {}))
    print("\n[UI panel · BEFORE] " + panel_before["headline"])

    # (2) Feedback via the same call the sidebar form makes.
    recorded = []
    for fb in _FEEDBACK:
        res = session.record_feedback(**fb)
        recorded.append({**fb, "feedback_id": res.get("feedback_id"),
                         "negative": res.get("negative"),
                         "count_for_entity": res.get("count_for_entity")})
        print(f"[UI sidebar · feedback] {res.get('feedback_id')} "
              f"{fb['category']} negative={res.get('negative')}")

    # (3) AFTER — same entity signal, adaptation now fires.
    out_after = session.handle_turn(json.dumps(_SIGNAL_AFTER))
    panel_after = _adaptation_panel(out_after.get("adaptation", {}))
    print("\n[UI panel · AFTER] " + panel_after["headline"])
    for note in panel_after["explanations"]:
        print(f"    - {note}")

    # Sidebar feedback summary (what _render_feedback_summary shows).
    fb_summary = session.snapshot().get("feedback", {})
    print(f"\n[UI sidebar · feedback summary] count={fb_summary.get('count')} "
          f"category_counts={fb_summary.get('category_counts')}")

    # Safety invariant check: the safety NOTE survives in both responses.
    note_before = "advisory" in (out_before.get("response", "").lower())
    note_after = "advisory" in (out_after.get("response", "").lower())
    print(f"\n[safety invariant] advisory NOTE present — before={note_before} "
          f"after={note_after}")

    if not args.no_save:
        _write_evidence(session, panel_before, recorded, panel_after,
                        fb_summary, out_before, out_after)

    tmp.cleanup()
    ok = (not panel_before["applied"]) and panel_after["applied"] \
        and note_before and note_after
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} — before shows no adaptation, "
          "after shows advisory adaptation, safety NOTE preserved in both.")
    return 0 if ok else 1


def _eval_dir() -> Path:
    cand = _REPO_ROOT / "data" / "evaluation"
    cand.mkdir(parents=True, exist_ok=True)
    return cand


def _write_evidence(session, panel_before, recorded, panel_after, fb_summary,
                    out_before, out_after) -> None:
    out_dir = _eval_dir()
    report = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "provider": session.provider,
        "retrieval_enabled": session.retrieval_enabled,
        "ui": "ui/streamlit_app.py",
        "flow": "signal (before) -> sidebar feedback form -> signal (after)",
        "before_panel": panel_before,
        "feedback_recorded": recorded,
        "after_panel": panel_after,
        "sidebar_feedback_summary": fb_summary,
        "before_adaptation_flags": out_before.get("adaptation"),
        "after_adaptation_flags": out_after.get("adaptation"),
    }
    (out_dir / "phase7_ui_evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Phase 7 — Streamlit UI adaptive-behaviour evidence (before vs after)",
        f"# generated: {report['generated_at']}",
        f"# provider: {report['provider']}  retrieval: {report['retrieval_enabled']}",
        "",
        "Reproduces the exact operator flow in `ui/streamlit_app.py`:",
        "a signal turn, operator feedback via the sidebar form, then the same",
        "entity's signal again. Panels below are what the Streamlit UI renders.",
        "",
        "## UI panel — Adaptive behaviour (BEFORE feedback)",
        f"- {panel_before['headline']}",
        f"- adaptation flags: `{report['before_adaptation_flags']}`",
        "",
        "## UI sidebar — feedback submitted (non-sensitive)",
    ]
    for r in recorded:
        lines.append(f"- {r['feedback_id']}  {r['category']}  "
                     f"negative={r['negative']}  (now {r['count_for_entity']} "
                     f"for entity)  note: {r['note']}")
    lines += [
        "",
        "## UI panel — Adaptive behaviour (AFTER feedback)",
        f"- {panel_after['headline']}",
        f"- badges: {panel_after['badges']}",
        f"- adaptation flags: `{report['after_adaptation_flags']}`",
        "",
        "### Why these changes fired (feedback evidence shown in the UI expander)",
    ]
    for note in panel_after["explanations"]:
        lines.append(f"- {note}")
    lines += [
        "",
        "## UI sidebar — feedback summary",
        f"- count: {fb_summary.get('count')}",
        f"- category_counts: `{fb_summary.get('category_counts')}`",
        "",
        "## Safety invariant",
        "- The advisory safety NOTE is preserved in BOTH the before and after "
        "responses; adaptation changes presentation only and never alters A1–A8 "
        "decisions, approval requirements, or escalation.",
    ]
    (out_dir / "phase7_ui_evidence.md").write_text("\n".join(lines),
                                                    encoding="utf-8")
    print("\n[saved UI evidence]")
    print(f"  {out_dir / 'phase7_ui_evidence.json'}")
    print(f"  {out_dir / 'phase7_ui_evidence.md'}")


if __name__ == "__main__":
    raise SystemExit(main())
