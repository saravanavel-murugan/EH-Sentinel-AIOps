"""Shared incident state passed between the A1-A8 LangGraph nodes.

The state carries the original signal, the deterministic grounded context, each
agent's typed output (as a plain dict for LangGraph serialization), a running
list of errors, and control flags (e.g. whether A1 gated the pipeline to stop
early for noise/insufficient-evidence).
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class IncidentState(TypedDict, total=False):
    # inputs
    signal: dict[str, Any]
    prompt_version: str  # reserved; per-agent prompts are fixed in this pipeline
    # deterministic grounding (built once, shared by all agents)
    context: dict[str, Any]
    # per-agent outputs (dicts for serialization); keys: a1..a8
    a1: dict[str, Any]
    a2: dict[str, Any]
    a3: dict[str, Any]
    a4: dict[str, Any]
    a5: dict[str, Any]
    a6: dict[str, Any]
    a7: dict[str, Any]
    a8: dict[str, Any]
    # retrieval (Phase 4 RAG) — diagnostics about what was retrieved
    retrieval: dict[str, Any]
    # control / diagnostics
    stop_reason: Optional[str]
    errors: list[str]
    trace: list[str]  # ordered list of agent ids that executed
