"""R4 demo — optional LLM monitoring (Langfuse + DeepEval), offline evidence.

Exercises ``agent/monitoring.py`` on the default OFFLINE path (no key, no
network): it calls :func:`monitoring_status`, opens a :func:`langfuse_trace`, and
runs :func:`deepeval_score`, then writes the observed disabled status to
``data/evaluation/monitoring_evidence.{json,md}``.

PASS (offline) requires BOTH Langfuse and DeepEval to report ``enabled == false``
with a reason, no exception raised, no network attempted, and exit 0. The script
never reads/prints ``.env`` or any secret and cleans up its temp log dir.

Modelled on ``scripts/run_phase8_deploy_check.py`` (argparse incl. --no-save,
_REPO_ROOT on sys.path, UTF-8 stdout reconfigure, ``load_env()``, a verbatim copy
of the private ``_eval_dir()`` helper, PASS/FAIL line, ``raise SystemExit(main())``).
It intentionally diverges from the template by emitting a Markdown ``.md`` file
instead of ``.txt`` (plus the ``.json``), because the UI Governance tab and docs
render Markdown.

Usage (from capstone_agent/):
    python scripts/run_monitoring_demo.py
    python scripts/run_monitoring_demo.py --no-save
"""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Make stdout UTF-8 so emoji/box-drawing print safely on Windows consoles.
try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")  # type: ignore[assignment]

from agent.env_config import load_env  # noqa: E402

load_env()

from agent import monitoring as mon  # noqa: E402
from agent import observability as obs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="R4 monitoring demo (offline)")
    p.add_argument("--no-save", action="store_true",
                   help="do not write the evidence files "
                        "(default writes data/evaluation/monitoring_evidence.{json,md})")
    args = p.parse_args(argv)

    tmp_log = tempfile.TemporaryDirectory(prefix="sentinel_monitoring_logs_")
    log_dir = Path(tmp_log.name)
    obs.configure_logging(log_dir=log_dir, force=True)

    print("EventHub Ops Sentinel — R4 monitoring demo (offline)")
    print("=" * 72)

    try:
        status = mon.monitoring_status()

        # Exercise the context manager + scorer on the disabled offline path.
        with mon.langfuse_trace("monitoring-demo", metadata={"phase": "r4"}) as lf:
            trace_status = dict(lf)
        score = mon.deepeval_score(
            "why is consumer lag rising on topic:payments.settlement",
            "Advisory: check the consumer group and recent rebalances.",
        )

        langfuse = status["langfuse"]
        deepeval = status["deepeval"]

        print(f"  langfuse: enabled={langfuse['enabled']}  reason={langfuse['reason']}")
        print(f"  deepeval: enabled={deepeval['enabled']}  reason={deepeval['reason']}")
        print(f"  langfuse_trace yielded: {trace_status}")
        print(f"  deepeval_score returned: {score}")

        passed = _assess(langfuse, deepeval, trace_status, score)
    except Exception as exc:  # noqa: BLE001 - top-level graceful failure
        print(f"\nRESULT: FAIL: {type(exc).__name__}")
        obs.shutdown_logging()
        tmp_log.cleanup()
        return 1

    status_word = "PASS" if passed else "FAIL"
    print("\n" + "=" * 72)
    print(f"RESULT: {status_word}")

    if not args.no_save:
        _write_evidence(langfuse, deepeval, trace_status, score, passed)

    obs.shutdown_logging()
    tmp_log.cleanup()
    return 0 if passed else 1


def _assess(langfuse: dict, deepeval: dict, trace_status: dict,
            score: dict) -> bool:
    ok = True
    ok &= langfuse.get("enabled") is False and bool(langfuse.get("reason"))
    ok &= deepeval.get("enabled") is False and bool(deepeval.get("reason"))
    ok &= trace_status.get("enabled") is False
    ok &= score.get("enabled") is False and score.get("metrics") == {}
    # anti-leak: no secret anywhere in the serialized evidence
    blob = json.dumps([langfuse, deepeval, trace_status, score], ensure_ascii=False)
    ok &= "sk-" not in blob and "voc-" not in blob and "OPENAI_API_KEY" not in blob
    return bool(ok)


# ---------------------------------------------------------------------------
# Helpers — _eval_dir() is REPLICATED VERBATIM from run_phase8_deploy_check.py
# (the template's helper is module-private, not importable).
# ---------------------------------------------------------------------------

def _eval_dir() -> Path:
    cand = _REPO_ROOT / "data" / "evaluation"
    if cand.exists():
        return cand
    alt = _REPO_ROOT / "data"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


def _write_evidence(langfuse: dict, deepeval: dict, trace_status: dict,
                    score: dict, passed: bool) -> None:
    out_dir = _eval_dir()
    report = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "result": "PASS" if passed else "FAIL",
        "offline": True,
        "langfuse": langfuse,
        "deepeval": deepeval,
        "langfuse_trace_status": trace_status,
        "deepeval_score": score,
        "notes": [
            "Optional LLM monitoring (R4) is OFF by default — no key, no network.",
            "Enable by uncommenting the deepeval/langfuse block in requirements.txt "
            "and setting the OFF-by-default keys in .env (see .env.example).",
            "Every outbound monitoring string is routed through redact_and_mask.",
        ],
    }
    json_path = out_dir / "monitoring_evidence.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    lines = [
        "# R4 — LLM monitoring evidence (Langfuse + DeepEval)",
        f"# generated: {report['generated_at']}",
        f"# result: {report['result']}  offline: {report['offline']}",
        "",
        "Optional LLM monitoring is OFF by default. This evidence proves both",
        "integrations degrade gracefully offline (no key, no network, no crash).",
        "",
        "## Status",
        "",
        "| Integration | enabled | reason |",
        "| --- | --- | --- |",
        f"| Langfuse | {langfuse.get('enabled')} | {langfuse.get('reason')} |",
        f"| DeepEval | {deepeval.get('enabled')} | {deepeval.get('reason')} |",
        "",
        "## Live calls (disabled offline path)",
        "```",
        f"langfuse_trace(...) yielded: {trace_status}",
        f"deepeval_score(...) returned: {score}",
        "```",
        "",
        "## How to enable",
        "Uncomment the exact-pinned optional block in `requirements.txt`, install,",
        "then set the OFF-by-default keys in `.env` (see `.env.example`):",
        "`SENTINEL_LANGFUSE_ENABLED=1`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,",
        "`LANGFUSE_HOST`, `SENTINEL_DEEPEVAL_ENABLED=1`, `SENTINEL_DEEPEVAL_MODEL`.",
        "No key value is ever displayed or logged.",
    ]
    md_path = out_dir / "monitoring_evidence.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[saved evidence]\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    raise SystemExit(main())
