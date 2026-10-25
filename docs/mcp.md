# MCP Layer — Model Context Protocol boundary for tools (Phase 5b)

Phase 5 built tool calling as an **in-process** registry + custom router. The MCP
layer adds a real **protocol boundary** on top of the *same* three tools, so tool
calling can happen over the Model Context Protocol (MCP) instead of a direct
Python call. Nothing about the tools changes; only *how the agent reaches them*
changes.

## Why

- **Decoupling.** The agent (MCP client) and the tools (MCP server) talk only
  through serialisable JSON-RPC messages. The tools could move to another process
  or host without touching the agent.
- **Standard discovery.** Tools are advertised with a JSON-Schema `inputSchema`
  and safety annotations, the shape MCP-aware clients expect.
- **Same guardrails.** The server reuses the Phase 5 `ToolRegistry` for the
  allow-list, schema validation, and safe dispatch. A rejected call becomes an
  MCP *tool-level* error, not a crash.

## Components

```
mcp/
  protocol.py   JSON-RPC 2.0 envelopes + MCP method constants + ToolSpec
  server.py     SentinelMCPServer  — wraps the ToolRegistry, answers MCP methods
  client.py     SentinelMCPClient  — handshake, discovery, tool calls + registry facade
  __init__.py   exports + connect_in_process()
```

### Protocol (`protocol.py`)

Every message is a JSON-RPC 2.0 object. We implement the tool-focused slice of MCP:

| Method        | Purpose                                                   |
|---------------|-----------------------------------------------------------|
| `initialize`  | Handshake: exchange `protocolVersion` + capabilities/info |
| `tools/list`  | Enumerate tools with `inputSchema` (JSON-Schema) + annotations |
| `tools/call`  | Invoke a tool by name; return MCP `content` blocks + `structuredContent` |

Protocol version negotiated: `2024-11-05`. Tool errors are returned inside a
successful `tools/call` result with `isError: true` (distinct from transport-level
JSON-RPC errors like `METHOD_NOT_FOUND`).

### Server (`server.py`)

`SentinelMCPServer` is a thin adapter over `ToolRegistry`:

- `tools/list` translates each registry `Tool` into an MCP tool spec. The simple
  registry types (`string|number|boolean`) become a JSON-Schema `object` with
  `properties` + `required`. Safety flags map to MCP annotations:
  `readOnlyHint`, `requiresApproval`, `destructiveHint`.
- `tools/call` delegates to `registry.dispatch(...)`, which enforces the
  allow-list and schema. The result is wrapped in MCP content blocks.
- `handle_message(request) -> response` routes one decoded JSON-RPC request and
  never raises. `initialize` must be called before other methods.

The **registry stays the single source of truth** for the tool set and guardrails;
the server does not reimplement them.

### Client (`client.py`)

`SentinelMCPClient` performs the handshake, caches the advertised tools, and calls
them. Its key property: it also exposes a **`ToolRegistry`-compatible facade**
(`names`, `get`, `schema_text`, `validate`, `dispatch`) so the existing Phase 5
`ToolAgent` can dispatch over MCP **with no change to the agent loop**.

- Local `validate()` mirrors the registry so the agent's pre-dispatch guardrails
  and the router prompt (`schema_text`) keep working. The **server re-validates
  authoritatively** on every call.
- `dispatch()` performs a `tools/call` and reshapes the MCP result back into the
  `{tool, ok, error, result}` dict the agent expects.

### Transport

Transport is abstracted behind `Transport.send(request) -> response`. The default
`InProcessTransport` hands the request straight to a server in the same process —
and round-trips through `json.dumps`/`json.loads` so only serialisable wire data
crosses the boundary. This keeps the demo **offline with no extra dependencies**.
A stdio or socket transport could be dropped in without touching client or server.

## Using MCP from the agent

```python
from agent.tool_agent import ToolAgent

agent = ToolAgent(use_mcp=True)        # tools dispatched over MCP
out = agent.handle("who should I notify for a P1 on topic:payments.settlement")
print(out["transport"])                # "mcp"
```

`ToolAgent(use_mcp=False)` (default) keeps the original in-process path. Passing an
explicit `registry=` still works (`transport="custom"`).

## Demo

Run from `capstone_agent/`:

```bash
python scripts/run_mcp_demo.py             # protocol trace + guardrails + agent-over-MCP
python scripts/run_mcp_demo.py --protocol  # just the raw JSON-RPC trace
python scripts/run_mcp_demo.py --agent     # just the ToolAgent running over MCP
```

Runs offline with `SENTINEL_LLM=fake`; uses OpenAI when `.env` selects it. Events
are appended to `logs/mcp_events.log`.

### What the demo shows

1. **Protocol trace** — `initialize`, `tools/list`, and two `tools/call` messages
   printed as raw JSON-RPC in both directions.
2. **Guardrails over MCP** — a disallowed tool (`restart_broker`), a missing
   required argument, and an unknown argument all return `ok=False` with a clear
   reason (MCP tool-level errors), never a crash.
3. **ToolAgent over MCP** — the agent selects the correct tool per request and
   dispatches it through the client/server; output reports `Transport: mcp` and
   the `escalate_incident` approval gate still fires (dry-run plan only).

## Relationship to Phase 5

| Aspect            | Phase 5 (in-process)        | Phase 5b (MCP)                      |
|-------------------|-----------------------------|-------------------------------------|
| Tool definitions  | `tools/` registry           | same registry (unchanged)           |
| Reaching a tool   | direct Python call          | JSON-RPC over a transport           |
| Discovery         | `registry.schema_text()`    | `tools/list` with JSON-Schema       |
| Validation        | `registry.validate`         | client pre-check **+** server re-validate |
| Agent loop        | `ToolAgent`                 | same `ToolAgent`, `use_mcp=True`    |

MCP is an **additional boundary**, not a rewrite. The custom router ([2]=b) and the
in-process path both still work.
