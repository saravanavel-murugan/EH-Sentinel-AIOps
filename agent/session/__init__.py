"""EventHub Ops Sentinel — Phase 6/7 planning, memory, context & adaptation.

Adds an explicit planning/task-decomposition layer, short-term conversation
memory, long-term persisted incident memory (with reset/retention rules), a
multi-turn session that orchestrates the existing (unchanged) A1-A8 pipeline and
Phase 5 tools into one end-to-end, inspectable workflow, and (Phase 7) a
feedback-driven adaptive-behaviour layer that adjusts PRESENTATION only —
advisory, deterministic, and never weakening the safety posture.

Public surface:
    SentinelSession      - multi-turn orchestrator (planning + memory + agents)
    IncidentPlan         - deterministic task decomposition with step status
    ConversationMemory   - bounded short-term conversation state
    IncidentMemoryStore  - durable long-term incident memory (JSON)
    IncidentRecord       - one stored incident
    FeedbackRecord       - one piece of operator feedback (Phase 7)
    FeedbackStore        - durable long-term feedback store, JSON (Phase 7)
    AdaptationPolicy     - deterministic feedback -> advisory adjustments (Phase 7)
    BehaviorProfile      - the derived, advisory-only adjustments (Phase 7)
"""

from __future__ import annotations

from .feedback import AdaptationPolicy, BehaviorProfile, FeedbackRecord, FeedbackStore
from .memory import ConversationMemory, IncidentMemoryStore, IncidentRecord, Turn
from .planner import IncidentPlan, PlanStep
from .session import SentinelSession

__all__ = [
    "SentinelSession",
    "IncidentPlan",
    "PlanStep",
    "ConversationMemory",
    "IncidentMemoryStore",
    "IncidentRecord",
    "Turn",
    "FeedbackRecord",
    "FeedbackStore",
    "AdaptationPolicy",
    "BehaviorProfile",
]
