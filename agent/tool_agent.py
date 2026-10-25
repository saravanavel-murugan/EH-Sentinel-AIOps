"""Phase 5 ToolAgent: agent-selected tool calling with guardrails + loop prevention.

Flow per request:
    loop (bounded):
        route (LLM picks tool + args)  ->  guardrails  ->  validate  ->  dispatch
        stop when the router returns tool='none' or a stop condition fires.

Guardrails:
  * allow-list      - only registered tools may run (registry.validate).
  * schema validation - required args present, basic types, no unknown args.
  * approval gate   - a requires_approval tool returns a PLAN only (never 'acts').
  * loop prevention - MAX_ITERATIONS hard cap + repeated-identical-call detection.
  * error handling  - dispatch never raises; failures are recorded and the loop
                      does not retry the same failing call.

Provider-agnostic: uses the configured chat model (OpenAI or offline fake).
"""

from __future__ import annotations

import json
from typing import Any

from tools.router import route
from tools.tool_registry import build_default_registry

MAX_ITERATIONS = 4  # loop-prevention hard cap


class ToolAgent:
    version = "phase5-toolagent-0.1.0"

    def __init__(self, chat_model: Any = None, registry: Any = None,
                 max_iterations: int = MAX_ITERATIONS, use_mcp: bool = False):
        from .llm import get_chat_model, provider_name

        self.provider = provider_name()
        self._chat = chat_model or get_chat_model()
        # `registry` is used only through the registry facade
        # (names/get/validate/dispatch/schema_text). An MCP client exposes the
        # same facade, so the loop below is identical whether tools are called
        # in-process or over the MCP protocol boundary.
        if registry is not None:
            self.registry = registry
            self.transport = "custom"
        elif use_mcp:
            from mcp import connect_in_process

            self.registry = connect_in_process()
            self.transport = "mcp"
        else:
            self.registry = build_default_registry()
            self.transport = "in-process"
        self.max_iterations = max_iterations

    def handle(self, request: str) -> dict[str, Any]:
        """Run the bounded route->validate->dispatch loop for one request."""
        history: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        seen_calls: set[str] = set()
        stop_reason = "completed"

        for i in range(1, self.max_iterations + 1):
            decision = route(self._chat, self.registry, request, history)
            tool = decision.get("tool", "none")
            args = decision.get("args", {}) or {}
            reason = decision.get("reason", "")

            if tool in ("none", "", None):
                stop_reason = "router chose no tool (done)"
                steps.append({"iteration": i, "tool": "none", "reason": reason})
                break

            # --- loop prevention: repeated identical call ---
            call_sig = f"{tool}:{json.dumps(args, sort_keys=True)}"
            if call_sig in seen_calls:
                stop_reason = f"loop prevented: repeated call {call_sig}"
                steps.append({"iteration": i, "tool": tool, "args": args,
                              "guardrail": "repeated_call_blocked", "reason": reason})
                break
            seen_calls.add(call_sig)

            # --- allow-list + schema validation (registry) ---
            ok, why = self.registry.validate(tool, args)
            if not ok:
                steps.append({"iteration": i, "tool": tool, "args": args,
                              "ok": False, "guardrail": "validation_failed",
                              "error": why, "reason": reason})
                history.append({"tool": tool, "ok": False, "error": why})
                # Do not retry the same bad call; let the router try something else,
                # but the repeated-call guard will stop an identical retry.
                continue

            # --- approval gate (requires_approval tools return a plan only) ---
            tool_obj = self.registry.get(tool)
            approval_note = None
            if tool_obj and tool_obj.requires_approval:
                approval_note = ("approval-gated: output is a PLAN; a human must approve "
                                 "before any real action.")

            # --- dispatch (never raises) ---
            result = self.registry.dispatch(tool, args)
            step = {"iteration": i, "tool": tool, "args": args,
                    "ok": result["ok"], "error": result.get("error"),
                    "result": result.get("result"), "reason": reason}
            if approval_note:
                step["approval"] = approval_note
            steps.append(step)
            history.append({"tool": tool, "ok": result["ok"],
                            "summary": _short(result.get("result"))})

            # One successful tool call answers most operator requests; stop to
            # avoid needless iteration (and keep behaviour predictable).
            if result["ok"]:
                stop_reason = "tool call succeeded"
                break
        else:
            stop_reason = f"max_iterations ({self.max_iterations}) reached"

        return {
            "request": request,
            "provider": self.provider,
            "transport": self.transport,
            "stop_reason": stop_reason,
            "n_steps": len(steps),
            "steps": steps,
            "response": self._render(request, steps, stop_reason, self.transport),
        }

    @staticmethod
    def _render(request: str, steps: list[dict[str, Any]], stop_reason: str,
                transport: str = "in-process") -> str:
        lines = ["=== TOOL AGENT (Phase 5) ==="]
        lines.append(f"Request : {request}")
        lines.append(f"Transport: {transport}")
        for s in steps:
            tool = s.get("tool")
            if tool == "none":
                lines.append(f"  [{s['iteration']}] no tool selected - {s.get('reason')}")
                continue
            head = f"  [{s['iteration']}] tool={tool} args={s.get('args')}"
            lines.append(head)
            if s.get("guardrail"):
                lines.append(f"       GUARDRAIL: {s['guardrail']} - {s.get('error', '')}")
            elif s.get("ok"):
                if s.get("approval"):
                    lines.append(f"       {s['approval']}")
                lines.append(f"       OK -> {_short(s.get('result'))}")
            else:
                lines.append(f"       FAILED -> {s.get('error')}")
        lines.append(f"Stop    : {stop_reason}")
        return "\n".join(lines)


def _short(obj: Any, limit: int = 220) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s[:limit] + ("..." if len(s) > limit else "")
