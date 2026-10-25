"""Evidence harness: which knowledge DOCUMENTS are referenced after MCP tool calls.

For a set of operator queries, this calls the `search_knowledge` tool OVER THE
MCP boundary (client -> JSON-RPC -> server -> Phase 4 FAISS retriever) and records,
per query, the documents that were cited: source file, section heading, relevance
score, and a snippet. It writes two artifacts:

    data/evaluation/mcp_evidence.json   machine-readable evidence
    data/evaluation/mcp_evidence.md     human-readable evidence table

This is the auditable proof that tool calls made over MCP are grounded in the
knowledge base, with traceable citations back to source documents.

Usage (from capstone_agent/):
    python scripts/eval_mcp_evidence.py
    python scripts/eval_mcp_evidence.py --top-k 5

Provider from .env. For real embeddings set SENTINEL_EMBEDDINGS=openai and build
the index first (scripts/ingest_documents.py + scripts/build_faiss_index.py).
The fake embedder also works offline (lower scores).
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

from mcp import connect_in_process  # noqa: E402

# Representative operator knowledge queries (how-to / what-causes / past-incident).
QUERIES = [
    "how do I handle rising consumer lag on a topic",
    "what causes under-replicated partitions and how to recover",
    "producer error rate surge - quota or ACL rejection runbook",
    "how do I escalate a P2 incident and who do I page",
    "kafka connect connector task failed what to check",
]


def _eval_dir() -> Path:
    """Prefer data/evaluation/ (canonical), fall back to data/."""
    cand = _REPO_ROOT / "data" / "evaluation"
    if cand.exists():
        return cand
    alt = _REPO_ROOT / "data"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


def run(top_k: int) -> dict:
    client = connect_in_process()
    records = []
    for q in QUERIES:
        res = client.call_tool("search_knowledge", {"query": q, "top_k": top_k})
        hits = []
        if res["ok"] and res["result"]:
            for h in res["result"].get("hits", []):
                hits.append({
                    "source": h.get("source"),
                    "heading": h.get("heading"),
                    "score": h.get("score"),
                    "snippet": (h.get("text") or "")[:240],
                })
        records.append({
            "query": q,
            "ok": res["ok"],
            "found": bool(res["result"] and res["result"].get("found")),
            "best_score": (res["result"] or {}).get("best_score"),
            "documents_referenced": hits,
        })

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "transport": "mcp",
        "server": client.server_info,
        "protocol_version": client.protocol_version,
        "tool": "search_knowledge",
        "top_k": top_k,
        "n_queries": len(QUERIES),
        "queries": records,
    }


def _write_md(report: dict, path: Path) -> None:
    lines = [
        "# MCP Tool-Call Evidence — documents referenced via `search_knowledge`",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Transport: **{report['transport']}** (JSON-RPC over MCP)",
        f"- Server: `{report['server'].get('name')}` "
        f"(protocol `{report['protocol_version']}`)",
        f"- Tool: `{report['tool']}`  ·  top_k = {report['top_k']}  ·  "
        f"{report['n_queries']} queries",
        "",
        "Each query below was sent as an MCP `tools/call`; the rows are the source "
        "documents the tool cited (with relevance score), proving the call was "
        "grounded in the knowledge base.",
        "",
    ]
    for i, rec in enumerate(report["queries"], 1):
        lines.append(f"## {i}. {rec['query']}")
        lines.append("")
        lines.append(f"- found: **{rec['found']}**  ·  best_score: "
                     f"`{rec['best_score']}`")
        if rec["documents_referenced"]:
            lines.append("")
            lines.append("| # | source | heading | score |")
            lines.append("|---|--------|---------|-------|")
            for j, h in enumerate(rec["documents_referenced"], 1):
                lines.append(f"| {j} | `{h['source']}` | {h['heading']} | {h['score']} |")
            lines.append("")
            top = rec["documents_referenced"][0]
            lines.append(f"> top snippet ({top['source']} :: {top['heading']}):")
            lines.append(f"> {top['snippet']}")
        else:
            lines.append("- (no documents referenced)")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MCP tool-call document-evidence harness")
    p.add_argument("--top-k", type=int, default=3, help="results per query (default 3)")
    args = p.parse_args(argv)

    report = run(args.top_k)

    out_dir = _eval_dir()
    json_path = out_dir / "mcp_evidence.json"
    md_path = out_dir / "mcp_evidence.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    _write_md(report, md_path)

    # Console summary.
    print(f"[mcp-evidence] transport={report['transport']} "
          f"server={report['server'].get('name')} "
          f"proto={report['protocol_version']}")
    for rec in report["queries"]:
        cites = ", ".join(f"{h['source']}::{h['heading']}({h['score']})"
                          for h in rec["documents_referenced"]) or "(none)"
        print(f"  - {rec['query']}")
        print(f"      found={rec['found']} best={rec['best_score']} -> {cites}")
    print(f"\nWrote:\n  {json_path}\n  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
