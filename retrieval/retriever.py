"""Retriever: semantic search over the FAISS knowledge index.

Loads the persisted FAISS store and embedder, embeds a query, returns the top-k
chunks above a minimum similarity. Explicitly reports when NO chunk clears the
threshold so callers can handle "no relevant information found" (Phase 4 task).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .embedder import embedder_name, get_embedder
from .faiss_store import FaissStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INDEX_DIR = _REPO_ROOT / "knowledge" / "faiss_index"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


class Retriever:
    def __init__(self, index_dir: str | Path | None = None):
        self.index_dir = Path(index_dir) if index_dir else _DEFAULT_INDEX_DIR
        self.store = FaissStore.load(self.index_dir)
        self.embedder = get_embedder()
        self.embedder_name = embedder_name()
        self.top_k = int(_env("SENTINEL_RETRIEVAL_TOP_K", "3"))
        self.min_score = float(_env("SENTINEL_RETRIEVAL_MIN_SCORE", "0.30"))
        # Guard: the query embedder must match the embedder the index was built
        # with (same dimension). A mismatch (e.g. fake query vs openai index)
        # would otherwise crash deep in FAISS. Detect it up front.
        self.index_embedder = self.store.meta.get("embedder", "unknown")
        self.index_dim = self.store.meta.get("dim")
        self.embedder_matches_index = (
            self.index_dim is None or self.index_dim == getattr(self.embedder, "dim", None)
        )

    @classmethod
    def available(cls, index_dir: str | Path | None = None) -> bool:
        d = Path(index_dir) if index_dir else _DEFAULT_INDEX_DIR
        return (d / "index.faiss").exists() and (d / "index.pkl").exists()

    def retrieve(self, query: str, top_k: int | None = None,
                 min_score: float | None = None) -> dict[str, Any]:
        """Return {query, hits[], found, best_score}. 'found' is False when no
        chunk clears the min_score threshold (no relevant info)."""
        k = top_k or self.top_k
        threshold = self.min_score if min_score is None else min_score
        if not self.embedder_matches_index:
            # Embedder/index dimension mismatch: degrade gracefully instead of
            # crashing. The caller sees found=False and a clear reason.
            return {
                "query": query,
                "embedder": self.embedder_name,
                "found": False,
                "best_score": None,
                "threshold": threshold,
                "hits": [],
                "error": (f"embedder '{self.embedder_name}' (dim {getattr(self.embedder, 'dim', '?')}) "
                          f"does not match index embedder '{self.index_embedder}' (dim {self.index_dim}); "
                          f"rebuild the index with: python scripts/build_faiss_index.py"),
            }
        qvec = self.embedder.embed_query(query)
        raw = self.store.search(qvec, top_k=k)
        hits = [h for h in raw if h["score"] >= threshold]
        return {
            "query": query,
            "embedder": self.embedder_name,
            "found": bool(hits),
            "best_score": raw[0]["score"] if raw else None,
            "threshold": threshold,
            "hits": hits,
        }

    @staticmethod
    def format_snippets(result: dict[str, Any], max_chars: int = 500) -> str:
        """Render retrieved hits as a citeable context block, or a 'no info' note."""
        if not result.get("found"):
            best = result.get("best_score")
            return ("NO_RELEVANT_KNOWLEDGE_FOUND "
                    f"(best similarity {best:.3f} < threshold {result['threshold']:.3f}); "
                    "proceed without retrieved runbook context.") if best is not None else \
                   "NO_RELEVANT_KNOWLEDGE_FOUND (empty index)."
        lines = []
        for h in result["hits"]:
            snippet = h["text"][:max_chars].replace("\n", " ").strip()
            lines.append(f"[{h['source']} :: {h['heading']} | score={h['score']:.3f}] {snippet}")
        return "\n".join(lines)
