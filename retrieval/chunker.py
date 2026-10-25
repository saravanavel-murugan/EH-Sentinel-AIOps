"""Chunk knowledge documents into retrievable passages.

Markdown-aware chunking: split on headings (## / ###) so each chunk is a coherent
runbook/FAQ entry, then fall back to size-bounded splits for very long sections.
Each chunk keeps its source and a heading label for citation.
"""

from __future__ import annotations

import re
from typing import Any

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$", re.MULTILINE)
_MAX_CHARS = 1200


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) sections. Text before the first heading -> ('', body)."""
    sections: list[tuple[str, str]] = []
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())]
    # preamble before first heading
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            sections.append(("", pre))
    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((heading, body))
    return sections


def _size_bound(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    paras = re.split(r"\n\s*\n", text)
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                parts.append(buf)
            buf = p
    if buf:
        parts.append(buf)
    return parts


def chunk_documents(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn loaded docs into chunks: {chunk_id, source, heading, text}."""
    chunks: list[dict[str, Any]] = []
    cid = 0
    for doc in docs:
        for heading, body in _split_by_headings(doc["text"]):
            if not body:
                continue
            for piece in _size_bound(body):
                label = heading or doc["source"]
                text = f"{heading}\n{piece}".strip() if heading else piece
                chunks.append({
                    "chunk_id": cid,
                    "source": doc["source"],
                    "heading": label,
                    "text": text,
                })
                cid += 1
    return chunks
