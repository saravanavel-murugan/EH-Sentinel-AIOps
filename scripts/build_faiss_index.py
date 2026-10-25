"""Build the FAISS index from chunks.json (Phase 4).

Embeds each chunk with the configured embedder (SENTINEL_EMBEDDINGS: openai|fake)
and writes knowledge/faiss_index/{index.faiss,index.pkl}.

Usage (from capstone_agent/):
    # offline (no key)
    python scripts/build_faiss_index.py
    # live OpenAI embeddings
    #   set SENTINEL_EMBEDDINGS=openai + OPENAI_API_KEY in .env, then run

Run ingest_documents.py first to produce chunks.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.env_config import load_env  # noqa: E402

load_env()  # .env is authoritative (override=True)

from retrieval.embedder import embedder_name, get_embedder  # noqa: E402
from retrieval.faiss_store import FaissStore  # noqa: E402

_PROCESSED = _REPO_ROOT / "knowledge" / "processed" / "chunks.json"
_INDEX_DIR = _REPO_ROOT / "knowledge" / "faiss_index"


def main() -> int:
    if not _PROCESSED.exists():
        print(f"ERROR: {_PROCESSED} not found. Run scripts/ingest_documents.py first.",
              file=sys.stderr)
        return 2
    payload = json.loads(_PROCESSED.read_text(encoding="utf-8"))
    chunks = payload["chunks"]
    if not chunks:
        print("ERROR: no chunks to index.", file=sys.stderr)
        return 2

    embedder = get_embedder()
    name = embedder_name()
    print(f"Embedding {len(chunks)} chunk(s) with provider '{name}' (dim={embedder.dim})...")
    vectors = embedder.embed_documents([c["text"] for c in chunks])

    store = FaissStore.build(chunks, vectors, meta={"embedder": name, "dim": embedder.dim})
    store.save(_INDEX_DIR)
    print(f"Wrote index.faiss + index.pkl to {_INDEX_DIR} ({len(chunks)} vectors, dim {embedder.dim})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
