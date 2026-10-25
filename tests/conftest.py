"""Shared pytest fixtures + deterministic offline setup for the Sentinel suite.

The whole suite runs on the OFFLINE FAKE providers so it is deterministic and
needs no API key or network — regardless of what .env says. We set the provider
env vars BEFORE any agent module is imported, and we do NOT call agent.env_config
(which would override from .env). This keeps CI/grading reproducible.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 1. Force offline deterministic providers before any import reads them.
os.environ["SENTINEL_LLM"] = "fake"
os.environ["SENTINEL_EMBEDDINGS"] = "fake"
os.environ.pop("OPENAI_API_KEY", None)

# 2. Put the canonical package root (capstone_agent/) on sys.path so
#    `import agent`, `import tools`, `import mcp` resolve.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402


@pytest.fixture()
def sample_signal() -> dict:
    """A representative normalized signal (rising consumer lag on a known topic)."""
    return {
        "signal_id": "sig-test",
        "source": "control_center",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "consumer_lag",
        "value": 60000,
        "unit": "messages",
        "environment": "prod",
    }


@pytest.fixture()
def fake_chat():
    """A fresh deterministic fake chat model (no network, no key)."""
    from agent.llm import DeterministicSentinelChatModel

    return DeterministicSentinelChatModel()


@pytest.fixture()
def mcp_client():
    """An in-process MCP client already handshaken + tool-discovered."""
    from mcp import connect_in_process

    return connect_in_process()
