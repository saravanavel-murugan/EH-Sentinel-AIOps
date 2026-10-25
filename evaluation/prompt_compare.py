"""Prompt-strategy comparison harness (Phase 3).

Runs the SAME test set through the LLM triage graph under each prompt version
(v1, v2, v3) and emits:

  * a per-case, per-version structured record (completeness score + key fields),
  * an aggregate score per version,
  * a Markdown comparison table (Prompt -> Output summary -> What improved/worsened).

This satisfies the Phase 3 "Prompt Comparison Rule": same test set, 2-3 variants,
comparison table. It runs offline with the deterministic fake model (default) or
live with OpenAI (SENTINEL_LLM=openai).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.core_agent import LLMAgent
from agent.prompts import PROMPT_DESCRIPTIONS, PROMPTS
from agent.schemas import TriageResult

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Candidate locations for the shared test set. The canonical repo keeps it under
# data/evaluation/; the flattened per-phase mirror keeps it under data/.
_TESTSET_CANDIDATES = [
    _REPO_ROOT / "data" / "evaluation" / "test_cases.json",
    _REPO_ROOT / "data" / "test_cases.json",
]


def _default_testset() -> Path:
    """Return the first existing default test-set path, so the same code works
    in both the canonical repo and the flattened phase mirror."""
    for candidate in _TESTSET_CANDIDATES:
        if candidate.exists():
            return candidate
    return _TESTSET_CANDIDATES[0]  # canonical default (used in error message)


_DEFAULT_TESTSET = _default_testset()


def load_test_set(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or _default_testset()
    if not path.exists():
        raise FileNotFoundError(
            f"Test set not found at {path}. Looked in: "
            + ", ".join(str(p) for p in _TESTSET_CANDIDATES)
            + ". Pass --test-set <path> explicitly."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


def run_comparison(test_set: list[dict[str, Any]]) -> dict[str, Any]:
    """Run every case under every prompt version. Returns a structured report."""
    versions = list(PROMPTS.keys())
    # One agent per version (same underlying chat model/provider).
    agents = {v: LLMAgent(prompt_version=v) for v in versions}

    per_case: list[dict[str, Any]] = []
    agg_scores: dict[str, int] = {v: 0 for v in versions}

    for case in test_set:
        signal = case["signal"]
        row: dict[str, Any] = {"id": case["id"], "note": case.get("note", ""), "by_version": {}}
        for v in versions:
            out = agents[v].triage_signal(signal, v)
            result = TriageResult(**out["result"])
            score = result.completeness_score()
            agg_scores[v] += score
            row["by_version"][v] = {
                "classification": result.classification,
                "severity": result.severity,
                "has_business_impact": bool(result.business_impact),
                "n_hypotheses": len(result.hypotheses),
                "has_next_check": bool(result.next_check),
                "has_uncertainty": bool(result.uncertainty),
                "n_recipients": len(result.recommended_recipients),
                "completeness_score": score,
                "summary": result.summary,
            }
        per_case.append(row)

    provider = agents[versions[0]].provider
    return {
        "provider": provider,
        "versions": versions,
        "n_cases": len(test_set),
        "aggregate_completeness": agg_scores,
        "max_possible_per_version": 6 * len(test_set),
        "per_case": per_case,
    }


def to_markdown_table(report: dict[str, Any]) -> str:
    """Build the Prompt -> Output -> Improved/Worsened comparison table."""
    versions = report["versions"]
    lines: list[str] = []
    lines.append(f"Provider: `{report['provider']}`  |  cases: {report['n_cases']}  "
                 f"|  max completeness/version: {report['max_possible_per_version']}")
    lines.append("")
    lines.append("## Aggregate completeness (higher = more grounded detail)")
    lines.append("")
    lines.append("| Version | Strategy | Aggregate score | Avg/case |")
    lines.append("|---------|----------|-----------------|----------|")
    for v in versions:
        agg = report["aggregate_completeness"][v]
        avg = agg / report["n_cases"] if report["n_cases"] else 0
        lines.append(f"| {v} | {PROMPT_DESCRIPTIONS[v]} | {agg} | {avg:.2f} |")
    lines.append("")

    lines.append("## Per-case comparison (Prompt -> Output -> What improved / worsened)")
    lines.append("")
    lines.append("| Case | Version | classification/severity | impact | #hyp | next_check | uncertainty | #recips | score |")
    lines.append("|------|---------|--------------------------|--------|------|------------|-------------|---------|-------|")
    for row in report["per_case"]:
        for v in versions:
            d = row["by_version"][v]
            lines.append(
                f"| {row['id']} | {v} | {d['classification']}/{d['severity']} | "
                f"{'Y' if d['has_business_impact'] else '-'} | {d['n_hypotheses']} | "
                f"{'Y' if d['has_next_check'] else '-'} | {'Y' if d['has_uncertainty'] else '-'} | "
                f"{d['n_recipients']} | {d['completeness_score']} |"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Phase 3 prompt-comparison harness")
    parser.add_argument("--test-set", default=None,
                        help="path to the test set (defaults to data/evaluation/ or data/)")
    parser.add_argument("--json-out", default=None,
                        help="output JSON path (defaults next to the test set)")
    parser.add_argument("--md-out", default=None,
                        help="output Markdown path (defaults next to the test set)")
    args = parser.parse_args(argv)

    test_set_path = Path(args.test_set) if args.test_set else _default_testset()
    test_set = load_test_set(test_set_path)
    report = run_comparison(test_set)

    out_dir = test_set_path.parent
    json_out = Path(args.json_out) if args.json_out else out_dir / "phase3_comparison.json"
    md_out = Path(args.md_out) if args.md_out else out_dir / "phase3_comparison.md"

    Path(json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md = to_markdown_table(report)
    Path(md_out).write_text(md, encoding="utf-8")

    print(md)
    print(f"\nWrote {json_out}\nWrote {md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
