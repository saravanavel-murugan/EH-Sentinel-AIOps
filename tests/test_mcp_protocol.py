"""MCP layer tests: protocol handshake, discovery, tool calls, and guardrails.

These exercise the server + client + the 3 Phase 5 tools directly over the
in-process JSON-RPC transport. No LLM is involved here.
"""

from __future__ import annotations

from mcp import protocol as P
from mcp.client import InProcessTransport, SentinelMCPClient
from mcp.server import SentinelMCPServer

EXPECTED_TOOLS = {"search_knowledge", "lookup_metric", "escalate_incident"}


# -- handshake -----------------------------------------------------------

def test_initialize_handshake():
    client = SentinelMCPClient()
    result = client.initialize()
    assert result["protocolVersion"] == P.PROTOCOL_VERSION
    assert client.protocol_version == P.PROTOCOL_VERSION
    assert client.server_info["name"] == "eventhub-sentinel-mcp"
    assert "version" in client.server_info


def test_initialize_required_first():
    """Any method before initialize is a protocol error."""
    server = SentinelMCPServer()
    req = P.make_request(1, P.METHOD_TOOLS_LIST, {})
    resp = server.handle_message(req)
    assert P.is_error(resp)
    assert resp["error"]["code"] == P.INVALID_REQUEST


# -- discovery -----------------------------------------------------------

def test_tools_list_advertises_all_tools(mcp_client):
    names = set(mcp_client.names())
    assert names == EXPECTED_TOOLS


def test_tool_specs_have_json_schema_and_annotations():
    server = SentinelMCPServer()
    server.handle_message(P.make_request(1, P.METHOD_INITIALIZE, {}))
    resp = server.handle_message(P.make_request(2, P.METHOD_TOOLS_LIST, {}))
    tools = {t["name"]: t for t in resp["result"]["tools"]}
    assert set(tools) == EXPECTED_TOOLS

    for spec in tools.values():
        schema = spec["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert schema["additionalProperties"] is False
        assert "readOnlyHint" in spec["annotations"]

    # escalate_incident is the write/approval tool -> annotations must reflect it.
    esc = tools["escalate_incident"]["annotations"]
    assert esc["requiresApproval"] is True
    assert esc["readOnlyHint"] is False
    assert esc["destructiveHint"] is True

    # required args surfaced in JSON-Schema
    lm = tools["lookup_metric"]["inputSchema"]
    assert set(lm["required"]) == {"entity_id", "metric"}


# -- tools/call (happy path) ---------------------------------------------

def test_call_lookup_metric(mcp_client):
    res = mcp_client.call_tool(
        "lookup_metric",
        {"entity_id": "topic:payments.settlement", "metric": "consumer_lag"},
    )
    assert res["ok"] is True
    assert res["isError"] is False
    assert res["result"]["latest"] == 125000
    assert res["result"]["trend"] == "rising"


def test_call_escalate_is_dry_run(mcp_client):
    res = mcp_client.call_tool(
        "escalate_incident",
        {"entity_id": "topic:payments.settlement", "severity": "P1",
         "message": "lag rising"},
    )
    assert res["ok"] is True
    data = res["result"]
    assert data["delivery_status"] == "not_sent"   # never actually sends
    assert data["requires_approval"] is True
    assert data["recipients"]                        # resolved from directory


def test_tools_call_returns_mcp_content_blocks():
    """Raw server result carries MCP 'content' blocks + structuredContent."""
    server = SentinelMCPServer()
    server.handle_message(P.make_request(1, P.METHOD_INITIALIZE, {}))
    resp = server.handle_message(P.make_request(2, P.METHOD_TOOLS_CALL, {
        "name": "lookup_metric",
        "arguments": {"entity_id": "topic:payments.settlement", "metric": "consumer_lag"},
    }))
    result = resp["result"]
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert result["structuredContent"]["metric"] == "consumer_lag"


# -- guardrails become tool-level errors (not crashes) -------------------

def test_disallowed_tool_rejected(mcp_client):
    res = mcp_client.dispatch("restart_broker", {"broker": "b3"})
    assert res["ok"] is False
    assert "allow-list" in res["error"]


def test_missing_required_arg_rejected(mcp_client):
    res = mcp_client.dispatch("lookup_metric", {"entity_id": "topic:payments.settlement"})
    assert res["ok"] is False
    assert "missing required argument" in res["error"]


def test_unknown_arg_rejected(mcp_client):
    res = mcp_client.dispatch("search_knowledge", {"query": "lag", "bad_field": 1})
    assert res["ok"] is False
    assert "unknown argument" in res["error"]


def test_unknown_method_is_protocol_error():
    server = SentinelMCPServer()
    server.handle_message(P.make_request(1, P.METHOD_INITIALIZE, {}))
    resp = server.handle_message(P.make_request(2, "tools/nope", {}))
    assert P.is_error(resp)
    assert resp["error"]["code"] == P.METHOD_NOT_FOUND


# -- transport integrity -------------------------------------------------

def test_transport_only_carries_serializable_wire():
    """The in-process transport round-trips JSON, proving only wire data crosses."""
    import json

    sent = {}

    class Spy(InProcessTransport):
        def send(self, request):
            # request must be JSON-serializable (a real wire message)
            sent["req"] = json.loads(json.dumps(request))
            return super().send(request)

    client = SentinelMCPClient(Spy()).connect()
    client.call_tool("lookup_metric",
                     {"entity_id": "topic:payments.settlement", "metric": "consumer_lag"})
    assert sent["req"]["jsonrpc"] == "2.0"
    assert sent["req"]["method"] in {P.METHOD_INITIALIZE, P.METHOD_TOOLS_LIST,
                                     P.METHOD_TOOLS_CALL}
