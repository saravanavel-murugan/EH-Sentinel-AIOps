# Tool Usage — Phase 5

**Project:** EventHub Ops – Sentinel
**Phase 5 artifact** — agent-selected tool calling with schemas, routing, guardrails, error
handling, and loop prevention.

> **Reproduce (from `capstone_agent/`):**
> ```bash
> python scripts/run_tool_agent.py --demo
> python scripts/run_tool_agent.py --request "who should I notify for a P1 on topic:payments.settlement"
> ```
> Provider from `.env` (`SENTINEL_LLM`). Offline fake router runs without a key.

---

## 1. The tools (≥2 required; 3 provided)

Each tool has a schema (name, description, typed parameters) in `tools/` and is registered in the
allow-list (`tool_registry.py`).

| Tool | Purpose | Args | Safety |
|------|---------|------|--------|
| `search_knowledge` | semantic search over runbooks/FAQ/policy/past incidents (FAISS) | `query:string`, `top_k:number?` | read-only |
| `lookup_metric` | recent (sandbox) time-series for a metric on an entity | `entity_id:string`, `metric:string`, `window_points:number?` | read-only |
| `escalate_incident` | approval-gated, **dry-run** stakeholder notification plan | `entity_id:string`, `severity:string`, `message:string` | **requires_approval**, write, never sends |

---

## 2. Tool-calling logic (custom router + bounded loop)

Per-request flow in `ToolAgent` (`agent/tool_agent.py`):

```
loop (max 4 iterations):
    route   -> LLM picks ONE tool + args from the schemas (tools/router.py)
    guard   -> repeated-call check; allow-list + schema validation
    approve -> requires_approval tools return a PLAN only
    dispatch-> run the tool (never raises); record result
    stop    -> on success / 'none' / loop / max-iterations
```

The router (`tools/router.py`) is **custom** (provider-agnostic): it prompts the model to return
`{"tool","args","reason"}` JSON and parses it defensively. The offline fake model has a
deterministic keyword router so the flow runs without a key.

---

## 3. Correct tool selection — evidence

From `python scripts/run_tool_agent.py --demo` (live OpenAI run; full log in
`data/evaluation/phase5_tool_demo.txt`):

| Request | Tool chosen | Result |
|---------|-------------|--------|
| "who should I notify for a P1 on topic:payments.settlement" | `escalate_incident` | approval-gated plan with all 5 recipients resolved from the directory |
| "what is the recent consumer_lag value on topic:payments.settlement" | `lookup_metric` | series `[40000…125000]`, latest 125000, trend rising |
| "how do I handle rising consumer lag on a topic" | `search_knowledge` | RB-01 — Consumer lag rising (score 0.57) |

Each request routed to the *right* tool for its intent (notify → escalate, value → metric,
how-to → knowledge).

---

## 4. Incorrect / failed tool calls — evidence (all 3 modes)

| # | Attempt | Guardrail | Outcome |
|---|---------|-----------|---------|
| 1 | `lookup_metric` missing required `metric` | schema validation | blocked: "missing required argument 'metric'" |
| 2 | `restart_broker` (not registered) | allow-list | blocked: "not in the allow-list (known: search_knowledge, lookup_metric, escalate_incident)" |
| 3 | `search_knowledge` with extra `bad_field` | schema validation | blocked: "unknown argument 'bad_field'" |
| 4 | same `lookup_metric` call issued twice | loop prevention | blocked at iteration 2: "loop prevented: repeated call …" |

All failures return a structured error (dispatch never raises), so the agent degrades safely
rather than crashing.

---

## 5. Safeguards (against misuse and loops)

- **Allow-list:** only registered tools run; an unknown/disallowed tool (e.g. `restart_broker`)
  is rejected before any call.
- **Schema validation:** required args enforced, basic types checked, unknown args rejected.
- **Approval gate:** `escalate_incident` is `requires_approval` and **dry-run** — it returns a
  notification *plan* with `delivery_status="not_sent"`; it never actually notifies.
- **Recipients never guessed:** escalate resolves recipients only from the approved entity table;
  an unknown entity yields "escalate to a human", not a fabricated address.
- **Loop prevention:** a hard `MAX_ITERATIONS=4` cap plus repeated-identical-call detection stop
  runaway tool loops.
- **Error handling:** `registry.dispatch` catches every exception and returns a structured
  failure; one successful call ends the loop (predictable behaviour).

---

## 6. Files

- Registry + schemas + validation/dispatch: `tools/tool_registry.py`
- Tools: `tools/tool_search.py`, `tools/metrics_lookup.py`, `tools/tool_escalate.py`
- Router: `tools/router.py` (+ offline router in `agent/llm.py` `_route_tool`)
- Agent: `agent/tool_agent.py` (`ToolAgent`)
- CLI + demo: `scripts/run_tool_agent.py`
- Evidence: `data/evaluation/phase5_tool_demo.txt`

> Relationship to the A1–A8 pipeline: the ToolAgent is a standalone demonstrator of
> agent-selected tool calling (Phase 5). The A1–A8 incident pipeline remains unchanged; the same
> tools (knowledge search, escalation) mirror capabilities A4/A5/A7 use internally.
