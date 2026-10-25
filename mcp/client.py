"""SentinelMCPClient (Phase 5b): connect to the MCP server and call tools.

The client:
  * performs the MCP handshake (initialize),
  * caches the advertised tool set from tools/list,
  * invokes tools via tools/call and unwraps the MCP result,
  * exposes a ToolRegistry-COMPATIBLE facade so the Phase 5 ToolAgent can dispatch
    through MCP with no code change (same names/get/validate/dispatch/schema_text).

Transport is abstracted behind `Transport.send(request_dict) -> response_dict`.
The default `InProcessTransport` hands the request straight to a SentinelMCPServer
in the same process (no sockets, no extra deps) so the demo runs offline. A stdio
or socket transport could be dropped in without touching the client.

Validation note: the server is the authority on validation and guardrails. The
client's facade reconstructs a LOCAL schema view from tools/list so the router
prompt (schema_text) and the agent's pre-dispatch validate() keep working; the
server re-validates on every call regardless.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from tools.tool_registry import Tool, ToolParam

from . import protocol as P
from .server import SentinelMCPServer


class Transport(Protocol):
    """A transport carries one JSON-RPC request and returns one response."""

    def send(self, request: dict[str, Any]) -> dict[str, Any]: ...


class InProcessTransport:
    """Transport that calls a SentinelMCPServer directly in-process.

    This still crosses the full protocol boundary: the client only ever hands the
    server a JSON-RPC request dict and reads back a JSON-RPC response dict. We even
    round-trip through JSON encode/decode to prove nothing but serializable wire
    data crosses the boundary.
    """

    def __init__(self, server: SentinelMCPServer | None = None) -> None:
        self.server = server or SentinelMCPServer()

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        import json

        wire = json.dumps(request)                 # client -> wire
        decoded = json.loads(wire)                 # server reads wire
        response = self.server.handle_message(decoded)
        return json.loads(json.dumps(response))    # server -> wire -> client


_JSON_TO_PARAM_TYPE = {"string": "string", "number": "number",
                       "integer": "number", "boolean": "boolean"}


@dataclass
class RemoteToolView:
    """A local, read-only mirror of a remotely-advertised MCP tool."""

    name: str
    description: str
    parameters: list[ToolParam]
    requires_approval: bool
    read_only: bool


class MCPClientError(Exception):
    pass


class SentinelMCPClient:
    """MCP client + ToolRegistry-compatible facade over a transport."""

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or InProcessTransport()
        self._req_id = 0
        self._tools: dict[str, RemoteToolView] = {}
        self.server_info: dict[str, Any] = {}
        self.protocol_version: str | None = None

    # -- low-level request ----------------------------------------------

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        req = P.make_request(self._next_id(), method, params)
        resp = self.transport.send(req)
        if P.is_error(resp):
            err = resp["error"]
            raise MCPClientError(f"MCP error {err.get('code')}: {err.get('message')}")
        return resp.get("result")

    # -- handshake + discovery ------------------------------------------

    def initialize(self) -> dict[str, Any]:
        result = self._call(P.METHOD_INITIALIZE, {
            "protocolVersion": P.PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "sentinel-tool-agent", "version": "0.1.0"},
        })
        self.server_info = result.get("serverInfo", {})
        self.protocol_version = result.get("protocolVersion")
        return result

    def list_tools(self) -> list[RemoteToolView]:
        result = self._call(P.METHOD_TOOLS_LIST, {})
        views: dict[str, RemoteToolView] = {}
        for spec in result.get("tools", []):
            views[spec["name"]] = self._spec_to_view(spec)
        self._tools = views
        return list(views.values())

    def connect(self) -> "SentinelMCPClient":
        """Handshake + discover tools in one call; returns self for chaining."""
        self.initialize()
        self.list_tools()
        return self

    @staticmethod
    def _spec_to_view(spec: dict[str, Any]) -> RemoteToolView:
        schema = spec.get("inputSchema", {}) or {}
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        params: list[ToolParam] = []
        for pname, pschema in props.items():
            jtype = (pschema or {}).get("type", "string")
            params.append(ToolParam(
                name=pname,
                type=_JSON_TO_PARAM_TYPE.get(jtype, "string"),
                required=pname in required,
                description=(pschema or {}).get("description", ""),
            ))
        ann = spec.get("annotations", {}) or {}
        return RemoteToolView(
            name=spec["name"],
            description=spec.get("description", ""),
            parameters=params,
            requires_approval=bool(ann.get("requiresApproval", False)),
            read_only=bool(ann.get("readOnlyHint", True)),
        )

    # -- tool invocation -------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool over MCP; return {'ok','result','error','isError'}."""
        result = self._call(P.METHOD_TOOLS_CALL, {"name": name, "arguments": arguments})
        is_err = bool(result.get("isError"))
        structured = result.get("structuredContent")
        if is_err:
            error = None
            if isinstance(structured, dict):
                error = structured.get("error")
            if not error:
                blocks = result.get("content", [])
                error = blocks[0].get("text") if blocks else "tool error"
            return {"ok": False, "result": None, "error": error, "isError": True}
        return {"ok": True, "result": structured, "error": None, "isError": False}

    # ================================================================
    # ToolRegistry-compatible facade (so ToolAgent uses MCP unchanged)
    # ================================================================

    def _ensure_tools(self) -> None:
        if not self._tools:
            self.connect()

    def names(self) -> list[str]:
        self._ensure_tools()
        return list(self._tools.keys())

    def get(self, name: str) -> RemoteToolView | None:
        self._ensure_tools()
        return self._tools.get(name)

    def schema_text(self) -> str:
        """Router-facing description, identical in shape to ToolRegistry.schema_text."""
        self._ensure_tools()
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

    def validate(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Local pre-dispatch validation mirroring ToolRegistry.validate.

        The server re-validates authoritatively; this local check lets the agent
        catch obvious errors (and drive its guardrails) before a round-trip.
        """
        self._ensure_tools()
        _PY_TYPES = {"string": str, "number": (int, float), "boolean": bool}
        tool = self._tools.get(name)
        if tool is None:
            return False, f"tool '{name}' is not in the allow-list (known: {self.names()})"
        if not isinstance(args, dict):
            return False, "arguments must be an object"
        for p in tool.parameters:
            if p.required and (p.name not in args or args[p.name] in (None, "")):
                return False, f"missing required argument '{p.name}' for tool '{name}'"
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
        """Dispatch over MCP; return a dict shaped like ToolRegistry.dispatch."""
        self._ensure_tools()
        ok, reason = self.validate(name, args)
        if not ok:
            return {"tool": name, "ok": False, "error": reason, "result": None}
        try:
            res = self.call_tool(name, args)
        except MCPClientError as exc:
            return {"tool": name, "ok": False, "error": str(exc), "result": None}
        return {"tool": name, "ok": res["ok"], "error": res["error"],
                "result": res["result"]}


def connect_in_process(registry: Any = None) -> SentinelMCPClient:
    """Build a client wired to an in-process server, handshake + discover tools."""
    server = SentinelMCPServer(registry=registry)
    client = SentinelMCPClient(InProcessTransport(server))
    return client.connect()
