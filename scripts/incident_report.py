"""Incident-summary report with knowledge-reference evidence (A1-A8 + RAG).

Runs a signal through the full multi-agent pipeline and writes a consolidated
INCIDENT SUMMARY that embeds the evidence trail:

  * the A6 7-section record (issue, RCA, correlation, severity, remediation,
    business impact, stakeholders),
  * the KNOWLEDGE REFERENCES that grounded it — which runbooks/FAQ/policy/past
    incidents were retrieved (source, heading, score, snippet),
  * the agent execution trace and retrieval diagnostics.

Artifacts (default data/evaluation/):
    incident_report.md     human-readable incident summary + evidence
    incident_report.json   machine-readable full record

Usage (from capstone_agent/):
    python scripts/incident_report.py --query-file data/evaluation/sample_signal.json
    python scripts/incident_report.py --query-file data/evaluation/sample_signal.json --out-prefix payments_lag

Provider from .env. For grounded RAG evidence set SENTINEL_EMBEDDINGS=openai and
build the index (scripts/ingest_documents.py + scripts/build_faiss_index.py);
offline the fake embedder still produces (lower-scored) citations.
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

load_env()

from agent.agents import MultiAgentSentinel  # noqa: E402


def _eval_dir() -> Path:
    cand = _REPO_ROOT / "data" / "evaluation"
    if cand.exists():
        return cand
    alt = _REPO_ROOT / "data"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


def build_report(signal: dict) -> dict:
    agent = MultiAgentSentinel()           # provider + retrieval from .env
    out = agent.run_signal(signal)
    a6 = (out.get("agents") or {}).get("a6", {}) or {}
    retrieval = out.get("retrieval", {}) or {}

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "provider": out.get("provider"),
        "pipeline_version": MultiAgentSentinel.version,
        "entity": out.get("entity"),
        "entity_known": out.get("entity_known"),
        "trace": out.get("trace", []),
        "stop_reason": out.get("stop_reason"),
        # retrieval evidence (which documents were referenced + full hits)
        "retrieval": {
            "enabled": retrieval.get("enabled"),
            "embedder": retrieval.get("embedder"),
            "query": retrieval.get("query"),
            "found": retrieval.get("found"),
            "best_score": retrieval.get("best_score"),
            "hits": retrieval.get("hits", []),
        },
        # the consolidated incident summary (A6) incl. knowledge citations
        "incident_summary": {
            "incident_id": a6.get("incident_id"),
            "summary": a6.get("summary"),
            "issue": a6.get("issue"),
            "root_cause": a6.get("root_cause"),
            "correlation": a6.get("correlation"),
            "severity": a6.get("severity"),
            "severity_rationale": a6.get("severity_rationale"),
            "remediation": a6.get("remediation", []),
            "business_impact": a6.get("business_impact"),
            "stakeholders": a6.get("stakeholders", {}),
            "knowledge_references": a6.get("knowledge_references", []),
            "evidence_links": a6.get("evidence_links", []),
        },
        "closure_document": a6.get("closure_document", ""),
    }


def _write_md(report: dict, path: Path) -> None:
    inc = report["incident_summary"]
    r = report["retrieval"]
    lines: list[str] = []
    lines.append(f"# Incident Summary — {inc.get('incident_id') or 'n/a'}")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Provider: `{report['provider']}`  ·  "
                 f"Pipeline: `{report['pipeline_version']}`")
    lines.append(f"- Entity: `{report['entity']}` (known={report['entity_known']})")
    lines.append(f"- Agent trace: {' -> '.join(report['trace'])}")
    if report.get("stop_reason"):
        lines.append(f"- Gate: {report['stop_reason']}")
    lines.append("")
    lines.append(f"**Summary:** {inc.get('summary') or inc.get('issue')}")
    lines.append("")

    lines.append("## 1. Issue (from signal)")
    lines.append(inc.get("issue") or "n/a")
    lines.append("")
    lines.append("## 2. Root-cause analysis (A4)")
    lines.append(inc.get("root_cause") or "n/a")
    lines.append("")
    lines.append("## 3. Correlation (A2)")
    lines.append(inc.get("correlation") or "n/a")
    lines.append("")
    lines.append("## 4. Priority / Severity (A3)")
    lines.append(f"{inc.get('severity')} — {inc.get('severity_rationale')}")
    lines.append("")
    lines.append("## 5. Remediation recommendation (A5)")
    for rem in inc.get("remediation", []) or ["(none proposed)"]:
        lines.append(f"- {rem}")
    lines.append("")
    lines.append("## 6. Business impact")
    lines.append(inc.get("business_impact") or "n/a")
    lines.append("")
    lines.append("## 7. Stakeholders to notify")
    for role, contact in (inc.get("stakeholders") or {}).items():
        lines.append(f"- {role}: {contact}")
    if not inc.get("stakeholders"):
        lines.append("- (none resolved; escalate to a human)")
    lines.append("")

    # --- the evidence section the operator asked for ---
    lines.append("## Knowledge referenced (RAG evidence)")
    lines.append("")
    krefs = inc.get("knowledge_references", [])
    if krefs:
        for k in krefs:
            lines.append(f"- {k}")
    else:
        lines.append("- (none)")
    lines.append("")

    if r.get("enabled") and r.get("hits"):
        lines.append("### Retrieved documents (with snippets)")
        lines.append("")
        lines.append(f"- embedder: `{r.get('embedder')}`  ·  "
                     f"query: `{r.get('query')}`  ·  best_score: `{r.get('best_score')}`")
        lines.append("")
        lines.append("| # | source | heading | score |")
        lines.append("|---|--------|---------|-------|")
        for i, h in enumerate(r["hits"], 1):
            lines.append(f"| {i} | `{h.get('source')}` | {h.get('heading')} | "
                         f"{round(float(h.get('score', 0.0)), 3)} |")
        lines.append("")
    else:
        lines.append("_Retrieval disabled or no documents matched._")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Advisory only; production actions require human approval. "
                 "Recipients resolved from the approved directory._")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Incident summary + knowledge evidence")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--query-file", dest="query_file", help="signal JSON file")
    g.add_argument("--query", help="inline signal JSON")
    p.add_argument("--out-prefix", default="incident_report",
                   help="artifact filename prefix (default incident_report)")
    args = p.parse_args(argv)

    if args.query_file:
        raw = Path(args.query_file).read_text(encoding="utf-8").strip()
    else:
        raw = args.query
    try:
        signal = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: input is not valid JSON: {exc}", file=sys.stderr)
        return 2

    report = build_report(signal)

    out_dir = _eval_dir()
    json_path = out_dir / f"{args.out_prefix}.json"
    md_path = out_dir / f"{args.out_prefix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    _write_md(report, md_path)

    inc = report["incident_summary"]
    print(f"[incident-report] {inc.get('incident_id')} severity={inc.get('severity')} "
          f"provider={report['provider']}")
    print(f"  entity: {report['entity']}  trace: {' -> '.join(report['trace'])}")
    print("  knowledge referenced:")
    for k in inc.get("knowledge_references", []) or ["(none)"]:
        print(f"    - {k}")
    print(f"\nWrote:\n  {json_path}\n  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
