"""Custom tool router (Phase 5, [2]=b): the LLM picks a tool + args from a prompt.

Provider-agnostic: works with the real ChatOpenAI model OR the offline fake chat
model. The router asks the model to return a JSON object:
    {"tool": "<name|none>", "args": {...}, "reason": "..."}
and parses it defensively. The offline fake model has a deterministic router
(keyword-based) so the whole flow runs without a key.

Routing is a SINGLE decision per step; the ToolAgent owns the multi-step loop and
its guardrails (max iterations, repeated-call detection).
"""

from __future__ import annotations

import json
import re
from typing import Any

from .tool_registry import ToolRegistry

_ROUTER_SYSTEM = (
    "You are a tool router for the EventHub Ops Sentinel operator assistant. "
    "Given the user request and the available tools, choose EXACTLY ONE tool to call next, "
    "or 'none' if no tool is appropriate or the task is complete. "
    "Return ONLY a JSON object: {{\"tool\": \"<tool name or none>\", \"args\": {{...}}, "
    "\"reason\": \"<one line>\"}}. "
    "Use only tools from the list and only their defined arguments. Never invent a tool."
)

_ROUTER_HUMAN = (
    "ROUTER_REQUEST\n"
    "Available tools:\n{tools}\n\n"
    "User request: {request}\n"
    "Prior tool results this turn (may be empty): {history}\n"
    "Return the JSON tool decision."
)


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[:-3]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


def route(chat_model: Any, registry: ToolRegistry, request: str,
          history: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a routing decision {tool, args, reason} using the chat model."""
    prompt = (_ROUTER_SYSTEM + "\n\n" + _ROUTER_HUMAN).format(
        tools=registry.schema_text(),
        request=request,
        history=json.dumps(history)[:800],
    )
    from langchain_core.messages import HumanMessage

    try:
        resp = chat_model.invoke([HumanMessage(content=prompt)])
        content = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:  # noqa: BLE001
        return {"tool": "none", "args": {}, "reason": f"router error: {exc}"}

    try:
        obj = json.loads(_strip_fence(content))
        if isinstance(obj, dict):
            return {
                "tool": str(obj.get("tool", "none")),
                "args": obj.get("args", {}) if isinstance(obj.get("args"), dict) else {},
                "reason": str(obj.get("reason", "")),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    # last-resort: try to spot a tool name in free text
    for name in registry.names():
        if re.search(rf"\b{re.escape(name)}\b", content):
            return {"tool": name, "args": {}, "reason": "parsed from free text"}
    return {"tool": "none", "args": {}, "reason": "router returned no parseable decision"}
