"""SentinelMCPServer (Phase 5b): expose the Phase 5 tools over MCP (JSON-RPC).

The server wraps the Phase 5 ToolRegistry and answers three MCP methods:

    initialize  -> protocol version + server capabilities/info
    tools/list  -> each tool as {name, description, inputSchema, annotations}
    tools/call  -> validate + dispatch the tool, return MCP content blocks

Design choices:
  * The registry remains the single source of truth for the tool set, schemas,
    validation and dispatch. The server is a thin protocol adapter; it does NOT
    reimplement guardrails. A validation/allow-list failure from the registry
    becomes an MCP tool-level error (result.isError = true), while a malformed
    protocol message becomes a JSON-RPC error (the error member).
  * `handle_message` takes a decoded JSON-RPC request dict and returns a decoded
    response dict. The transport layer owns encode/decode, so the same server
    works over an in-process queue, stdio, or a socket.
  * ToolParam -> JSON-Schema translation is done here so clients see a standard
    MCP inputSchema (type: object, properties, required).
"""

from __future__ import annotations

import json
from typing import Any

from tools.tool_registry import ToolRegistry, build_default_registry

from . import protocol as P

SERVER_NAME = "eventhub-sentinel-mcp"
SERVER_VERSION = "0.1.0"


class SentinelMCPServer:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or build_default_registry()
        self._initialized = False

    # -- tool advertisement ----------------------------------------------

    def _input_schema(self, tool: Any) -> dict[str, Any]:
        """Build a JSON-Schema object for a registry Tool's parameters."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in tool.parameters:
            prop = P.param_type_to_json_schema(p.type)
            if p.description:
                prop = {**prop, "description": p.description}
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        return schema

    def _tool_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for name in self.registry.names():
            tool = self.registry.get(name)
            annotations = {
                # MCP annotation hints mirror the registry's safety flags.
                "readOnlyHint": bool(tool.read_only),
                "requiresApproval": bool(tool.requires_approval),
                "destructiveHint": not bool(tool.read_only),
            }
            specs.append(
                P.ToolSpec(
                    name=tool.name,
                    description=tool.description,
                    input_schema=self._input_schema(tool),
                    annotations=annotations,
                ).to_wire()
            )
        return specs

    # -- method handlers -------------------------------------------------

    def _handle_initialize(self, req_id: int, params: dict[str, Any]) -> dict[str, Any]:
        self._initialized = True
        client_version = params.get("protocolVersion", P.PROTOCOL_VERSION)
        return P.make_result(req_id, {
            "protocolVersion": P.PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            # Echo what the client asked for; a real server might negotiate down.
            "negotiatedWith": client_version,
        })

    def _handle_tools_list(self, req_id: int, params: dict[str, Any]) -> dict[str, Any]:
        return P.make_result(req_id, {"tools": self._tool_specs()})

    def _handle_tools_call(self, req_id: int, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            return P.make_error(req_id, P.INVALID_PARAMS,
                                "tools/call requires a string 'name'")
        if not isinstance(args, dict):
            return P.make_error(req_id, P.INVALID_PARAMS,
                                "tools/call 'arguments' must be an object")

        # The registry enforces allow-list + schema validation + safe dispatch.
        dispatched = self.registry.dispatch(name, args)
        ok = dispatched["ok"]
        payload = dispatched["result"] if ok else {"error": dispatched["error"]}

        content = [P.text_content(json.dumps(payload, ensure_ascii=False, indent=2))]
        result = P.tool_call_result(
            content_blocks=content,
            structured=payload,
            is_error_result=not ok,
        )
        return P.make_result(req_id, result)

    # -- dispatch --------------------------------------------------------

    _HANDLERS = {
        P.METHOD_INITIALIZE: "_handle_initialize",
        P.METHOD_TOOLS_LIST: "_handle_tools_list",
        P.METHOD_TOOLS_CALL: "_handle_tools_call",
    }

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Route one decoded JSON-RPC request to its handler; never raises."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return P.make_error(message.get("id") if isinstance(message, dict) else None,
                                P.INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        req_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {}) or {}
        if not isinstance(params, dict):
            return P.make_error(req_id, P.INVALID_PARAMS, "'params' must be an object")

        # Require initialize first (except for the initialize call itself).
        if method != P.METHOD_INITIALIZE and not self._initialized:
            return P.make_error(req_id, P.INVALID_REQUEST,
                                "server not initialized; call 'initialize' first")

        handler_name = self._HANDLERS.get(method)
        if handler_name is None:
            return P.make_error(req_id, P.METHOD_NOT_FOUND, f"unknown method '{method}'")
        try:
            return getattr(self, handler_name)(req_id, params)
        except Exception as exc:  # noqa: BLE001 - protocol boundary must not crash
            return P.make_error(req_id, P.INTERNAL_ERROR,
                                f"{type(exc).__name__}: {exc}")
