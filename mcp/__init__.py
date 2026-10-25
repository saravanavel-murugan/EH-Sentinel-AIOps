"""Sentinel MCP layer (Phase 5b): a Model Context Protocol boundary for tools.

Phase 5 built an *in-process* tool registry + custom router. This package adds a
real protocol boundary on top of the SAME tools:

    mcp.server  - SentinelMCPServer: speaks JSON-RPC (initialize / tools/list /
                  tools/call), wrapping the Phase 5 ToolRegistry.
    mcp.client  - SentinelMCPClient: connects over a transport, performs the MCP
                  handshake, lists tools, and calls them. It also exposes a
                  registry-compatible facade (names/validate/dispatch/schema_text)
                  so the existing ToolAgent can dispatch through MCP unchanged.

Transport is pluggable; the default InProcessTransport wires client<->server in
one process (no network, no extra deps) so the demo runs offline. The same
server/client would work over stdio or a socket in production.
"""

from .client import InProcessTransport, SentinelMCPClient, connect_in_process
from .server import SentinelMCPServer

__all__ = [
    "SentinelMCPServer",
    "SentinelMCPClient",
    "InProcessTransport",
    "connect_in_process",
]
