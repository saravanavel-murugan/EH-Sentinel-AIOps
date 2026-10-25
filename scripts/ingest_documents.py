"""Ingest knowledge docs -> chunks.json (Phase 4).

Loads knowledge/raw/*.md, chunks them (markdown heading-aware), and writes
knowledge/processed/chunks.json. No embeddings here (that's build_faiss_index.py),
so this step needs no API key.

Usage (from capstone_agent/):
    python scripts/ingest_documents.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from retrieval.chunker import chunk_documents  # noqa: E402
from retrieval.document_loader import load_documents  # noqa: E402

_RAW_DIR = _REPO_ROOT / "knowledge" / "raw"
_PROCESSED = _REPO_ROOT / "knowledge" / "processed" / "chunks.json"


def main() -> int:
    docs = load_documents(_RAW_DIR)
    if not docs:
        print(f"ERROR: no documents found in {_RAW_DIR}", file=sys.stderr)
        return 2
    chunks = chunk_documents(docs)
    _PROCESSED.parent.mkdir(parents=True, exist_ok=True)
    _PROCESSED.write_text(
        json.dumps({"n_docs": len(docs), "n_chunks": len(chunks), "chunks": chunks},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Loaded {len(docs)} doc(s); wrote {len(chunks)} chunk(s) to {_PROCESSED}")
    for d in docs:
        n = sum(1 for c in chunks if c["source"] == d["source"])
        print(f"  - {d['source']}: {n} chunk(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
