"""Phase 9 — single entry point: evaluation + failure analysis + prompt compare.

Runs the whole Phase 9 engineering review OFFLINE on the deterministic fake
provider and prints a concise summary with an explicit PASS/FAIL. In order it:

  1. Runs the evaluation harness (``evaluation.evaluation_harness``) and prints
     the per-dimension scorecards, the gating confusion matrix, the consistency
     (K=3) result, the safety scorecard and the explicit go/no-go.
  2. Runs the failure analysis (``evaluation.failure_analysis``) and prints its
     before/after summary for the tc-05 gating defect.
  3. Re-runs the Phase 3 prompt comparison by calling
     ``evaluation.prompt_compare.main([])`` — this REFRESHES
     ``data/evaluation/phase3_comparison.{json,md}`` (the mechanism is NOT
     duplicated here).
  4. Writes ``data/evaluation/phase9_evaluation.{json,md}`` and
     ``data/evaluation/phase9_failure_analysis.{json,md}`` (unless ``--no-save``).
  5. Prints ``RESULT: PASS``/``FAIL`` where PASS requires every quality gate met
     AND the safety scorecard passing (safety is a hard blocker), and the failure
     analysis resolving. Exits 0 on PASS, non-zero on FAIL.

Everything is offline/deterministic: no API key or network is needed regardless
of what ``.env`` selects, as long as ``SENTINEL_LLM=fake`` /
``SENTINEL_EMBEDDINGS=fake`` are set (the documented verification prefix). No
secret or PII is ever printed or written — the report payloads are redacted via
the Phase 8 ``redact`` filter before any write.

Usage (from capstone_agent/):
    python scripts/run_phase9_eval.py
    python scripts/run_phase9_eval.py --no-retrieval
    python scripts/run_phase9_eval.py --no-retrieval --no-save
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Make stdout UTF-8 so emoji/box-drawing print safely on Windows consoles.
try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")  # type: ignore[assignment]

import os  # noqa: E402

from agent.env_config import load_env  # noqa: E402

# Capture any offline provider selection the caller set on the shell BEFORE
# load_env (which loads .env with override=True and would otherwise clobber it).
# The documented verification prefix sets SENTINEL_LLM/SENTINEL_EMBEDDINGS=fake to
# force offline determinism, and that choice must win here — we never read or
# modify .env itself, only re-assert the caller's explicit offline selection.
_SHELL_LLM = os.environ.get("SENTINEL_LLM")
_SHELL_EMB = os.environ.get("SENTINEL_EMBEDDINGS")

load_env(verbose=False)

if _SHELL_LLM:
    os.environ["SENTINEL_LLM"] = _SHELL_LLM
if _SHELL_EMB:
    os.environ["SENTINEL_EMBEDDINGS"] = _SHELL_EMB

from evaluation import evaluation_harness as harness  # noqa: E402
from evaluation import failure_analysis as failure  # noqa: E402
from evaluation import prompt_compare  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 9 evaluation & engineering review")
    p.add_argument("--no-retrieval", action="store_true",
                   help="disable RAG (avoids needing a FAISS index)")
    p.add_argument("--no-save", action="store_true",
                   help="do not write the phase9_* artifacts")
    args = p.parse_args(argv)
    use_retrieval = not args.no_retrieval

    print("EventHub Ops Sentinel — Phase 9 evaluation & engineering review")
    print(f"Provider : LLM={os.environ.get('SENTINEL_LLM', 'fake')} "
          f"EMBEDDINGS={os.environ.get('SENTINEL_EMBEDDINGS', 'fake')}")
    print(f"Retrieval: {'enabled' if use_retrieval else 'disabled'}")
    print("=" * 72)

    # --- (1) Evaluation harness --------------------------------------------
    report = harness.run_evaluation(use_retrieval=use_retrieval)
    print()
    print(harness.to_markdown(report))

    # --- (2) Failure analysis ----------------------------------------------
    fa = failure.run_failure_analysis(use_retrieval=use_retrieval)
    print()
    print("=" * 72)
    print("FAILURE ANALYSIS (tc-05 gating defect)")
    print(f"  before mismatches: {fa['before']['mismatch_count']}  "
          f"after mismatches: {fa['after']['mismatch_count']}  "
          f"resolved: {fa['resolved']}")

    # --- (3) Refresh Phase 3 prompt comparison -----------------------------
    print()
    print("=" * 72)
    print("PROMPT COMPARISON (Phase 3 artifact refresh)")
    print("=" * 72)
    prompt_compare.main([])  # writes data/evaluation/phase3_comparison.{json,md}

    # --- (4) Save phase9 artifacts -----------------------------------------
    if not args.no_save:
        ej, em = harness.save_report(report)
        fj, fm = failure.save_report(fa)
        print(f"\n[saved]\n  {ej}\n  {em}\n  {fj}\n  {fm}")

    # --- (5) PASS / FAIL ----------------------------------------------------
    passed = bool(report["go"] and fa["resolved"])
    print()
    print("=" * 72)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}  "
          f"(go={report['go']}, safety_passed={report['safety_passed']}, "
          f"failure_resolved={fa['resolved']})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
