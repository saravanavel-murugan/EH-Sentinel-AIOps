"""Phase 8 demo — deployment-readiness check (offline-capable).

Exercises the Phase 8 observability layer end to end and writes evidence:

  1. NORMAL run — one signal turn through the traced, safe runtime
     (``safe_handle_turn``). Shows the captured ``latency_ms`` and the structured
     trace record for a successful run.
  2. GRACEFUL FAILURE — the three required scenarios, each returning a structured
     NON-crashing response (no leaked stack trace, no secret, advisory posture
     preserved):
       (a) malformed/invalid input         -> internal error degraded gracefully
       (b) simulated provider/LLM outage    -> hard failure degraded gracefully
       (c) missing/disabled retrieval index -> turn completes without crashing
  3. SUMMARY — a scenario -> outcome -> latency_ms/status table printed and
     written to ``data/evaluation/phase8_deploy_evidence.{txt,json}``.
  4. TRACE TAIL — the last lines of ``logs/traces.jsonl`` to prove the latency +
     error capture landed on disk.

Everything runs OFFLINE on the deterministic fake provider: the sessions are
built with an explicit fake chat model, so no API key or network is ever needed
regardless of what ``.env`` selects. A redacting filter guarantees no secret or
PII reaches the logs/traces/evidence (a HARD Scenario-1 requirement).

By default a temp log dir is used so ``logs/`` is not polluted; pass ``--persist``
to write the real ``logs/sentinel.log`` + ``logs/traces.jsonl``.

Usage (from capstone_agent/):
    python scripts/run_phase8_deploy_check.py
    python scripts/run_phase8_deploy_check.py --no-retrieval
    python scripts/run_phase8_deploy_check.py --persist
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

from agent import observability as obs  # noqa: E402
from agent.llm import DeterministicSentinelChatModel  # noqa: E402
from agent.session import SentinelSession  # noqa: E402

_SIGNAL = (
    '{"signal_id": "sig-p8-normal", "source": "control_center", '
    '"entity": {"type": "topic", "id": "payments.settlement"}, '
    '"metric_or_event": "consumer_lag", "value": 60000, '
    '"unit": "messages", "environment": "prod"}'
)


class _SimulatedProviderOutage(BaseException):
    """A hard, non-recoverable provider failure.

    The A1-A8 nodes deliberately catch ``Exception`` and degrade to the
    deterministic rule fallback, so an ordinary LLM error never crashes a turn
    (that resilience is itself graceful handling). This models a catastrophic
    transport/runtime outage the node layer does NOT swallow, so it reaches the
    runtime wrapper and exercises ``safe_handle_turn``'s own graceful path.
    """


class _RaisingChatModel(DeterministicSentinelChatModel):
    """Offline fake model whose ``invoke`` raises a hard provider outage."""

    def invoke(self, *args, **kwargs):  # noqa: ANN001, D401
        raise _SimulatedProviderOutage("simulated provider outage")


class _RaisingSession:
    """A session whose ``handle_turn`` always raises — models an internal error
    on malformed input without relying on the (tolerant) real turn path."""

    provider = "fake"

    def handle_turn(self, user_input):  # noqa: ANN001
        raise ValueError("malformed input: could not route turn")


def _new_session(chat_model, *, use_retrieval: bool, workdir: Path) -> SentinelSession:
    """Build an isolated, offline session (temp memory/feedback so runs are
    reproducible and do not touch the real stores)."""
    return SentinelSession(
        chat_model=chat_model,
        use_retrieval=use_retrieval,
        memory_path=workdir / "incident_memory.json",
        feedback_path=workdir / "feedback.json",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 8 deployment-readiness check")
    p.add_argument("--persist", action="store_true",
                   help="write the real logs/ (default: temp log dir)")
    p.add_argument("--no-retrieval", action="store_true",
                   help="disable RAG (avoids needing a FAISS index)")
    p.add_argument("--no-save", action="store_true",
                   help="do not write the evidence files "
                        "(default writes data/evaluation/phase8_deploy_evidence.{txt,json})")
    args = p.parse_args(argv)

    use_retrieval = not args.no_retrieval

    tmp_log: tempfile.TemporaryDirectory | None = None
    tmp_work = tempfile.TemporaryDirectory(prefix="sentinel_phase8_work_")
    workdir = Path(tmp_work.name)
    if args.persist:
        log_dir = obs.DEFAULT_LOG_DIR
    else:
        tmp_log = tempfile.TemporaryDirectory(prefix="sentinel_phase8_logs_")
        log_dir = Path(tmp_log.name)

    obs.configure_logging(log_dir=log_dir, force=True)
    trace_path = Path(log_dir) / obs.DEFAULT_TRACE_FILE

    print("EventHub Ops Sentinel — Phase 8 deployment-readiness check")
    print(f"Log dir : {'logs/' if args.persist else log_dir}")
    print(f"Retrieval: {'enabled' if use_retrieval else 'disabled'}")
    print("=" * 72)

    results: list[dict] = []

    # --- (1) NORMAL run through the traced, safe runtime --------------------
    print("\n>>> [NORMAL] signal turn via traced safe_handle_turn")
    normal_session = _new_session(DeterministicSentinelChatModel(),
                                  use_retrieval=use_retrieval, workdir=workdir)
    out_normal = obs.safe_handle_turn(normal_session, _SIGNAL, log_dir=log_dir)
    normal_trace = _last_trace(trace_path)
    normal_latency = normal_trace.get("latency_ms") if normal_trace else None
    normal_ok = out_normal.get("kind") == "signal"
    print(f"  kind={out_normal.get('kind')}  latency_ms={normal_latency}  "
          f"status={normal_trace.get('status') if normal_trace else 'n/a'}")
    print(f"  headline: {(out_normal.get('response') or '').splitlines()[0]}")
    results.append({
        "scenario": "normal_run",
        "description": "signal turn via traced safe runtime",
        "outcome": "success" if normal_ok else "unexpected",
        "kind": out_normal.get("kind"),
        "latency_ms": normal_latency,
        "status": normal_trace.get("status") if normal_trace else None,
    })

    # --- (2a) GRACEFUL: malformed / invalid input ---------------------------
    print("\n>>> [GRACEFUL a] malformed/invalid input")
    out_bad = obs.safe_handle_turn(_RaisingSession(), "???", log_dir=log_dir)
    results.append(_grace_row("malformed_input",
                              "internal error on bad input degraded gracefully",
                              out_bad, _last_trace(trace_path)))
    _print_graceful(out_bad)

    # --- (2b) GRACEFUL: simulated provider/LLM outage -----------------------
    print("\n>>> [GRACEFUL b] simulated provider/LLM outage")
    outage_session = _new_session(_RaisingChatModel(),
                                  use_retrieval=use_retrieval, workdir=workdir)
    out_outage = obs.safe_handle_turn(outage_session, _SIGNAL, log_dir=log_dir)
    results.append(_grace_row("provider_outage",
                              "hard provider failure degraded gracefully",
                              out_outage, _last_trace(trace_path)))
    _print_graceful(out_outage)

    # --- (2c) GRACEFUL: missing / disabled retrieval index ------------------
    print("\n>>> [GRACEFUL c] missing/disabled retrieval index")
    no_idx_session = _new_session(DeterministicSentinelChatModel(),
                                  use_retrieval=False, workdir=workdir)
    out_no_idx = obs.safe_handle_turn(no_idx_session, _SIGNAL, log_dir=log_dir)
    idx_trace = _last_trace(trace_path)
    idx_ok = out_no_idx.get("kind") == "signal"
    print(f"  retrieval_enabled={no_idx_session.retrieval_enabled}  "
          f"kind={out_no_idx.get('kind')}  "
          f"status={idx_trace.get('status') if idx_trace else 'n/a'}  "
          f"(completed without crashing)")
    results.append({
        "scenario": "missing_index",
        "description": "retrieval disabled/missing index completes (no crash)",
        "outcome": "success" if idx_ok else "unexpected",
        "kind": out_no_idx.get("kind"),
        "latency_ms": idx_trace.get("latency_ms") if idx_trace else None,
        "status": idx_trace.get("status") if idx_trace else None,
    })

    # --- (3) SUMMARY TABLE --------------------------------------------------
    print("\n=== SUMMARY (scenario -> outcome -> latency_ms/status) ===")
    print(_render_table(results))

    # --- (4) TRACE TAIL -----------------------------------------------------
    print(f"\n=== TRACE TAIL ({trace_path.name}) — proof latency+errors on disk ===")
    tail = _tail_traces(trace_path, n=5)
    for line in tail:
        rec = json.loads(line)
        print(f"  {rec.get('run_id')}  {rec.get('entry_point')}  "
              f"status={rec.get('status')}  latency_ms={rec.get('latency_ms')}  "
              f"error_type={rec.get('error_type')}")

    # --- PASS / FAIL assessment --------------------------------------------
    passed = _assess(results, tail)
    status_word = "PASS" if passed else "FAIL"
    print("\n" + "=" * 72)
    print(f"RESULT: {status_word}")

    if not args.no_save:
        _write_evidence(results, tail, use_retrieval, passed)

    # Close log handlers before removing the temp log dir (Windows holds the
    # rotating file open otherwise).
    obs.shutdown_logging()
    tmp_work.cleanup()
    if tmp_log is not None:
        tmp_log.cleanup()
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grace_row(scenario: str, description: str, out: dict,
               trace: dict | None) -> dict:
    return {
        "scenario": scenario,
        "description": description,
        "outcome": "graceful_error" if out.get("kind") == "error" else "unexpected",
        "kind": out.get("kind"),
        "error_type": out.get("error_type"),
        "latency_ms": trace.get("latency_ms") if trace else None,
        "status": trace.get("status") if trace else None,
    }


def _print_graceful(out: dict) -> None:
    print(f"  kind={out.get('kind')}  ok={out.get('ok')}  "
          f"run_id={out.get('run_id')}  error_type={out.get('error_type')}")
    print(f"  safety: {out.get('safety')}")
    print(f"  message: {out.get('message')}")


def _last_trace(path: Path) -> dict | None:
    lines = _tail_traces(path, n=1)
    return json.loads(lines[-1]) if lines else None


def _tail_traces(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return lines[-n:]


def _render_table(rows: list[dict]) -> str:
    header = f"{'scenario':<18}{'outcome':<18}{'latency_ms':<12}{'status':<8}"
    out = [header, "-" * len(header)]
    for r in rows:
        out.append(
            f"{r['scenario']:<18}{r['outcome']:<18}"
            f"{str(r.get('latency_ms')):<12}{str(r.get('status')):<8}"
        )
    return "\n".join(out)


def _assess(results: list[dict], tail: list[str]) -> bool:
    by = {r["scenario"]: r for r in results}
    ok = True
    ok &= by.get("normal_run", {}).get("outcome") == "success"
    ok &= isinstance(by.get("normal_run", {}).get("latency_ms"), int)
    ok &= by.get("malformed_input", {}).get("outcome") == "graceful_error"
    ok &= by.get("provider_outage", {}).get("outcome") == "graceful_error"
    ok &= by.get("missing_index", {}).get("outcome") == "success"
    # at least one error trace and one ok trace landed on disk
    statuses = {json.loads(ln).get("status") for ln in tail}
    ok &= "error" in statuses and "ok" in statuses
    # no secret-looking content anywhere in the tail
    blob = "\n".join(tail)
    ok &= "sk-" not in blob and "OPENAI_API_KEY" not in blob
    return bool(ok)


def _eval_dir() -> Path:
    cand = _REPO_ROOT / "data" / "evaluation"
    if cand.exists():
        return cand
    alt = _REPO_ROOT / "data"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


def _write_evidence(results: list[dict], tail: list[str], use_retrieval: bool,
                    passed: bool) -> None:
    out_dir = _eval_dir()
    report = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "provider": "fake",
        "retrieval_enabled": use_retrieval,
        "result": "PASS" if passed else "FAIL",
        "scenarios": results,
        "trace_tail": [json.loads(ln) for ln in tail],
        "notes": [
            "All runs use the offline deterministic fake provider (no key/network).",
            "A redacting filter scrubs api-key/secret patterns before any write.",
            "Graceful responses carry no stack trace and preserve the advisory "
            "read-only safety posture.",
        ],
    }
    json_path = out_dir / "phase8_deploy_evidence.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    lines = [
        "# Phase 8 — deployment-readiness evidence",
        f"# generated: {report['generated_at']}",
        f"# provider: {report['provider']}  retrieval: {report['retrieval_enabled']}",
        f"# result: {report['result']}",
        "",
        "Demonstrates: a traced normal run with a captured latency number, the",
        "three graceful-failure scenarios returning structured non-crashing",
        "responses, and the per-run latency/error traces persisted to disk.",
        "All offline on the deterministic fake provider; no secret/PII is logged.",
        "",
        "## Summary table",
        "```",
        _render_table(results),
        "```",
        "",
        "## Scenario detail",
    ]
    for r in results:
        lines.append(f"- {r['scenario']}: {r['description']}")
        lines.append(f"    outcome={r['outcome']}  kind={r.get('kind')}  "
                     f"latency_ms={r.get('latency_ms')}  status={r.get('status')}"
                     + (f"  error_type={r.get('error_type')}" if r.get('error_type') else ""))
    lines += ["", "## Trace tail (logs/traces.jsonl)", "```"]
    for ln in tail:
        rec = json.loads(ln)
        lines.append(f"{rec.get('run_id')}  {rec.get('entry_point')}  "
                     f"status={rec.get('status')}  latency_ms={rec.get('latency_ms')}  "
                     f"error_type={rec.get('error_type')}")
    lines += ["```", "",
              "## Safety posture",
              "Adaptation/degradation is advisory only; no production action is taken",
              "on failure, and no stack trace or secret ever reaches the user-facing",
              "response, the logs, or this evidence file."]
    txt_path = out_dir / "phase8_deploy_evidence.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[saved evidence]\n  {json_path}\n  {txt_path}")


if __name__ == "__main__":
    raise SystemExit(main())
