"""EventHub Ops Sentinel — agent package.

Phase 2 exposes the baseline rules/template agent. Later phases add LLM,
retrieval, tools, memory, and adaptation on top of this package.
"""

from .core_agent import BaselineAgent, LLMAgent

__all__ = ["BaselineAgent", "LLMAgent"]
