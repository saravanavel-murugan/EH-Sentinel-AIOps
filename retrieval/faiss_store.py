"""FAISS vector store for Phase 4 retrieval.

Builds an inner-product FAISS index over L2-normalized chunk embeddings (so the
score is cosine similarity in [-1, 1]). Persists the index (index.faiss) and the
chunk metadata (index.pkl) under knowledge/faiss_index/.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import faiss
import numpy as np


class FaissStore:
    def __init__(self, index: faiss.Index | None = None,
                 chunks: list[dict[str, Any]] | None = None,
                 meta: dict[str, Any] | None = None):
        self.index = index
        self.chunks = chunks or []
        self.meta = meta or {}

    # -- build / persist ---------------------------------------------------

    @classmethod
    def build(cls, chunks: list[dict[str, Any]], embeddings: list[list[float]],
              meta: dict[str, Any] | None = None) -> "FaissStore":
        if not embeddings:
            raise ValueError("No embeddings to index.")
        mat = np.asarray(embeddings, dtype="float32")
        dim = mat.shape[1]
        index = faiss.IndexFlatIP(dim)  # inner product on normalized vecs = cosine
        index.add(mat)
        m = {"dim": dim, "count": len(chunks)}
        if meta:
            m.update(meta)
        return cls(index=index, chunks=chunks, meta=m)

    def save(self, index_dir: str | Path) -> None:
        d = Path(index_dir)
        d.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(d / "index.faiss"))
        with (d / "index.pkl").open("wb") as fh:
            pickle.dump({"chunks": self.chunks, "meta": self.meta}, fh)

    @classmethod
    def load(cls, index_dir: str | Path) -> "FaissStore":
        d = Path(index_dir)
        index = faiss.read_index(str(d / "index.faiss"))
        with (d / "index.pkl").open("rb") as fh:
            payload = pickle.load(fh)
        return cls(index=index, chunks=payload["chunks"], meta=payload.get("meta", {}))

    # -- search ------------------------------------------------------------

    def search(self, query_vec: list[float], top_k: int = 3) -> list[dict[str, Any]]:
        q = np.asarray([query_vec], dtype="float32")
        scores, idxs = self.index.search(q, min(top_k, len(self.chunks)))
        results: list[dict[str, Any]] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            chunk = dict(self.chunks[idx])
            chunk["score"] = float(score)
            results.append(chunk)
        return results
