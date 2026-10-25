"""Configurable embeddings for Phase 4 retrieval.

Selects the embedding backend from ``SENTINEL_EMBEDDINGS``:

* ``openai`` -> OpenAI embeddings via ``langchain_openai.OpenAIEmbeddings``
  (model from ``SENTINEL_OPENAI_EMBED_MODEL``, default text-embedding-3-small;
  requires ``OPENAI_API_KEY``). This is the real/evaluation path.
* ``fake``   -> an offline, deterministic hashing embedder (no network, no key)
  so the FAISS index can be built and retrieval verified without a key.

Both return L2-normalized vectors so inner-product search == cosine similarity.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


# --------------------------------------------------------------------------
# Offline deterministic hashing embedder
# --------------------------------------------------------------------------

class FakeHashingEmbedder:
    """Deterministic bag-of-words hashing embedder.

    Each token is hashed to a bucket in a fixed-dim vector; counts are summed and
    the vector is L2-normalized. Not semantically strong, but deterministic and
    good enough to demonstrate the retrieval pipeline offline (lexically-similar
    text lands near its source chunks).
    """

    def __init__(self, dim: int | None = None):
        self.dim = dim or int(_env("SENTINEL_EMBED_DIM", "256"))

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


# --------------------------------------------------------------------------
# OpenAI embedder wrapper (normalized)
# --------------------------------------------------------------------------

class OpenAIEmbedderWrapper:
    """Wraps langchain_openai.OpenAIEmbeddings and L2-normalizes outputs."""

    def __init__(self):
        from langchain_openai import OpenAIEmbeddings

        api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SENTINEL_EMBEDDINGS=openai but OPENAI_API_KEY is not set. "
                "Set it in .env or switch SENTINEL_EMBEDDINGS=fake for offline runs."
            )
        model = _env("SENTINEL_OPENAI_EMBED_MODEL", "text-embedding-3-small")
        # Optional custom base URL for OpenAI-compatible gateways/proxies
        # (e.g. Vocareum "voc-" keys -> https://api.vocareum.com/v1).
        base_url = _env("SENTINEL_OPENAI_BASE_URL")
        kwargs: dict = {"model": model, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._emb = OpenAIEmbeddings(**kwargs)
        # text-embedding-3-small = 1536 dims; recorded for index metadata.
        self.dim = 1536

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._normalize(v) for v in self._emb.embed_documents(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self._normalize(self._emb.embed_query(text))


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_embedder() -> Embedder:
    provider = _env("SENTINEL_EMBEDDINGS", "fake").lower()
    if provider == "openai":
        return OpenAIEmbedderWrapper()
    if provider == "fake":
        return FakeHashingEmbedder()
    raise RuntimeError(f"Unknown SENTINEL_EMBEDDINGS provider: {provider!r} (use 'openai' or 'fake').")


def embedder_name() -> str:
    return _env("SENTINEL_EMBEDDINGS", "fake").lower()
