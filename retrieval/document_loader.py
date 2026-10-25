"""Load raw knowledge documents for embedding.

Reads text/markdown files from knowledge/raw/. (PDF support can be added later;
Phase 4 uses .md source docs per the project decision.) Each returned document
carries its source filename for citations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_SUPPORTED = {".md", ".txt"}


def load_documents(raw_dir: str | Path) -> list[dict[str, Any]]:
    """Return a list of {source, path, text} for each supported file under raw_dir.

    Walks SUBDIRECTORIES too (e.g. knowledge/raw/incidents/) so resolved-incident
    documents written at closure are picked up on the next ingest. The ``source``
    is the path relative to raw_dir (e.g. 'incidents/20261019-...-incident.md').
    """
    raw = Path(raw_dir)
    docs: list[dict[str, Any]] = []
    if not raw.exists():
        return docs
    for path in sorted(raw.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SUPPORTED:
            continue
        text = path.read_text(encoding="utf-8")
        source = path.relative_to(raw).as_posix()
        docs.append({"source": source, "path": str(path), "text": text})
    return docs
