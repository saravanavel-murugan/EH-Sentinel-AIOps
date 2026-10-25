"""MCP wire protocol: JSON-RPC 2.0 envelopes + MCP method constants (Phase 5b).

This module defines the message shapes the Sentinel MCP server and client speak.
It follows the Model Context Protocol conventions:

  * Every message is a JSON-RPC 2.0 object.
  * A *request* has {"jsonrpc":"2.0","id":<n>,"method":<str>,"params":{...}}.
  * A *response* has {"jsonrpc":"2.0","id":<n>,"result":{...}}  OR  an "error".
  * A tool is advertised with an inputSchema in JSON-Schema form.
  * `tools/call` returns MCP "content" blocks ({"type":"text","text":...}).

We implement the small, tool-focused slice of MCP that Sentinel needs:
    initialize            - handshake, exchange protocol version + capabilities
    tools/list            - enumerate advertised tools with JSON-Schema
    tools/call            - invoke a tool by name with arguments

Keeping the envelope explicit (rather than importing an SDK) makes the protocol
boundary visible and keeps the project runnable offline with no extra deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The protocol version string this implementation negotiates.
PROTOCOL_VERSION = "2024-11-05"

# --- method names -------------------------------------------------------
METHOD_INITIALIZE = "initialize"
METHOD_TOOLS_LIST = "tools/list"
METHOD_TOOLS_CALL = "tools/call"

# --- JSON-RPC error codes (subset of the spec) --------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def make_request(req_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request object."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }


def make_result(req_id: int, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response object."""
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: int | None, code: int, message: str,
               data: Any = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response object."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def is_error(message: dict[str, Any]) -> bool:
    return isinstance(message, dict) and "error" in message


# --- MCP content helpers ------------------------------------------------

def text_content(text: str) -> dict[str, Any]:
    """An MCP content block of type 'text'."""
    return {"type": "text", "text": text}


def tool_call_result(content_blocks: list[dict[str, Any]],
                     structured: Any = None,
                     is_error_result: bool = False) -> dict[str, Any]:
    """Shape of a `tools/call` result: content blocks + optional structured data.

    `isError` lets the server report a tool-level failure (e.g. a validation or
    guardrail rejection) without turning it into a transport-level JSON-RPC error,
    which matches how MCP distinguishes tool errors from protocol errors.
    """
    result: dict[str, Any] = {"content": content_blocks, "isError": is_error_result}
    if structured is not None:
        result["structuredContent"] = structured
    return result


@dataclass
class ToolSpec:
    """An MCP-advertised tool: name, description, JSON-Schema input, annotations."""

    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": self.annotations,
        }


def param_type_to_json_schema(param_type: str) -> dict[str, Any]:
    """Map the registry's simple type names to JSON-Schema types."""
    mapping = {
        "string": {"type": "string"},
        "number": {"type": "number"},
        "boolean": {"type": "boolean"},
    }
    return mapping.get(param_type, {"type": "string"})
