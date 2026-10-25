"""Tool registry, schemas, allow-list, validation and dispatch (Phase 5).

A Tool pairs a JSON-ish schema (name, description, parameters) with a Python
callable. The registry enforces:
  * an allow-list (only registered tools may run),
  * argument validation against the schema (required fields, basic types),
  * safe dispatch with structured error handling (never raises to the agent).

This is the deterministic "controls enforce" layer around agent tool-calling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """Raised internally for a tool failure; dispatch converts it to a result dict."""


@dataclass
class ToolParam:
    name: str
    type: str                  # "string" | "number" | "boolean"
    required: bool = True
    description: str = ""


@dataclass
class Tool:
    name: str
    description: str
    parameters: list[ToolParam]
    fn: Callable[..., Any]
    # Safety flags surfaced to the agent/guardrails.
    requires_approval: bool = False
    read_only: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "requires_approval": self.requires_approval,
            "read_only": self.read_only,
            "parameters": [
                {"name": p.name, "type": p.type, "required": p.required,
                 "description": p.description}
                for p in self.parameters
            ],
        }


_PY_TYPES = {"string": str, "number": (int, float), "boolean": bool}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def schema_text(self) -> str:
        """Human/LLM-readable description of all tools, for the router prompt."""
        lines = []
        for t in self._tools.values():
            params = ", ".join(
                f"{p.name}:{p.type}{'' if p.required else '?'}" for p in t.parameters
            )
            flags = []
            if t.requires_approval:
                flags.append("requires_approval")
            if not t.read_only:
                flags.append("write")
            flag_s = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {t.name}({params}): {t.description}{flag_s}")
        return "\n".join(lines)

    # -- validation + dispatch -------------------------------------------

    def validate(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Return (ok, reason). Checks allow-list, required args, and basic types."""
        tool = self._tools.get(name)
        if tool is None:
            return False, f"tool '{name}' is not in the allow-list (known: {self.names()})"
        if not isinstance(args, dict):
            return False, "arguments must be an object"
        # required present
        for p in tool.parameters:
            if p.required and (p.name not in args or args[p.name] in (None, "")):
                return False, f"missing required argument '{p.name}' for tool '{name}'"
        # basic type check + reject unknown args
        allowed = {p.name: p for p in tool.parameters}
        for key, val in args.items():
            if key not in allowed:
                return False, f"unknown argument '{key}' for tool '{name}'"
            expected = _PY_TYPES.get(allowed[key].type, str)
            if val is not None and not isinstance(val, expected):
                return False, (f"argument '{key}' should be {allowed[key].type}, "
                               f"got {type(val).__name__}")
        return True, "ok"

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Validate then call the tool. Always returns a structured result dict;
        never raises to the caller (error handling requirement)."""
        ok, reason = self.validate(name, args)
        if not ok:
            return {"tool": name, "ok": False, "error": reason, "result": None}
        tool = self._tools[name]
        try:
            result = tool.fn(**args)
            return {"tool": name, "ok": True, "error": None, "result": result}
        except ToolError as exc:
            return {"tool": name, "ok": False, "error": str(exc), "result": None}
        except Exception as exc:  # noqa: BLE001 - never crash the agent on a tool bug
            return {"tool": name, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}", "result": None}


def build_default_registry() -> ToolRegistry:
    """Build the registry with the Phase 5 tools. Imported lazily to avoid
    heavy deps (FAISS) when the registry is only introspected."""
    from .metrics_lookup import METRICS_TOOL
    from .tool_escalate import ESCALATE_TOOL
    from .tool_search import SEARCH_TOOL

    reg = ToolRegistry()
    reg.register(SEARCH_TOOL)
    reg.register(METRICS_TOOL)
    reg.register(ESCALATE_TOOL)
    return reg
