"""Bridge from the agent package to the top-level retrieval package (Phase 4).

``retrieval/`` is a sibling package of ``agent/`` under capstone_agent/. This
thin bridge imports it and returns a ready Retriever only when a FAISS index
exists, so the multi-agent pipeline degrades gracefully (retrieval disabled)
when the index has not been built yet.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure the repo root (capstone_agent/) is importable so 'retrieval' resolves
# regardless of the caller's working directory.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def load_retriever() -> Any:
    """Return a Retriever if the FAISS index is present, else None."""
    from retrieval.retriever import Retriever

    if not Retriever.available():
        return None
    return Retriever()
