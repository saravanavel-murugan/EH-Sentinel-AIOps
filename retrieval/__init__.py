"""EventHub Ops Sentinel — retrieval (RAG) package (Phase 4).

Pipeline: document_loader -> chunker -> embedder -> faiss_store -> retriever.
Embeddings are configurable (OpenAI | offline fake) via SENTINEL_EMBEDDINGS.
"""

from .retriever import Retriever

__all__ = ["Retriever"]
