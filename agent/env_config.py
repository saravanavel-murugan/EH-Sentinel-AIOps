"""Shared .env loader + provider reporting for all Sentinel entrypoints.

Loads capstone_agent/.env with override=True so the .env file is AUTHORITATIVE:
values in the file take precedence over any stale shell variables (a common
source of "why is it still using fake?" confusion). Call load_env() at the top
of every script.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env(verbose: bool = True) -> None:
    """Load .env with override=True (file wins over shell), then optionally print
    the active providers so the selection is never a mystery."""
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env", override=True)
    except Exception:  # noqa: BLE001 - dotenv is optional
        pass

    if verbose:
        llm = os.environ.get("SENTINEL_LLM", "fake").strip() or "fake"
        emb = os.environ.get("SENTINEL_EMBEDDINGS", "fake").strip() or "fake"
        has_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
        key_note = "key set" if has_key else "NO key"
        print(f"[sentinel] providers: LLM={llm}, EMBEDDINGS={emb} ({key_note})")
        if (llm == "openai" or emb == "openai") and not has_key:
            print("[sentinel] WARNING: a provider is set to 'openai' but OPENAI_API_KEY is empty.")
