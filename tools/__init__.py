"""EventHub Ops Sentinel - tools package (Phase 5: agent-selected tool calling).

Exposes the tool registry + the three tools (search_knowledge, lookup_metric,
escalate_incident). The ToolAgent (agent/tool_agent.py) routes to these with
guardrails and loop prevention.
"""

from .tool_registry import Tool, ToolParam, ToolRegistry, build_default_registry

__all__ = ["Tool", "ToolParam", "ToolRegistry", "build_default_registry"]
