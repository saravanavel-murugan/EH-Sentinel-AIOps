"""Knowledge-search tool (Phase 5): semantic search over the FAISS knowledge base.

Wraps the Phase 4 retriever so the agent can look up runbooks / FAQ / past
incidents on demand. Read-only; no approval required. Degrades gracefully if the
index is missing (returns a clear message rather than raising).
"""

from __future__ import annotations

from typing import Any

from .tool_registry import Tool, ToolError, ToolParam

_retriever = None  # lazily cached


def _get_retriever():
    global _retriever
    if _retriever is None:
        from agent.retrieval_bridge import load_retriever

        _retriever = load_retriever()
    return _retriever


def search_knowledge(query: str, top_k: int = 3) -> dict[str, Any]:
    """Search the knowledge base; return top hits or a 'no index / no match' note."""
    r = _get_retriever()
    if r is None:
        raise ToolError("knowledge index not available; build it with scripts/build_faiss_index.py")
    try:
        k = int(top_k)
    except (TypeError, ValueError):
        k = 3
    res = r.retrieve(query, top_k=max(1, min(k, 10)))
    if res.get("error"):
        raise ToolError(res["error"])
    return {
        "found": res["found"],
        "best_score": res["best_score"],
        "hits": [
            {"source": h["source"], "heading": h["heading"],
             "score": round(h["score"], 3), "text": h["text"][:400]}
            for h in res["hits"]
        ],
    }


SEARCH_TOOL = Tool(
    name="search_knowledge",
    description="Semantic search over runbooks, FAQ, policy and past resolved incidents. "
                "Use for 'how do I...', 'what causes...', 'what did we do last time...' questions.",
    parameters=[
        ToolParam("query", "string", required=True, description="the search query"),
        ToolParam("top_k", "number", required=False, description="number of results (default 3)"),
    ],
    fn=search_knowledge,
    requires_approval=False,
    read_only=True,
)
