# Phase 6 — Planning, Memory & Context

Phase 6 adds the three capabilities the earlier phases lacked: explicit
**multi-step planning**, **memory** (short-term + long-term), and genuine
**multi-turn** conversations — plus a rich Streamlit console that traces the
whole multi-agent workflow from raw signal to closure.

Everything is **additive**: the A1–A8 pipeline (Phase 3b), RAG (Phase 4), and
tools/MCP (Phase 5) are reused unchanged through their public facades
(`MultiAgentSentinel`, `ToolAgent`).

## New building blocks (`agent/session/`)

| Module | Responsibility |
|--------|----------------|
| `planner.py` | `IncidentPlan` — deterministic task decomposition of an incident into ordered, status-tracked steps (recall → A1…A8 → persist). |
| `memory.py`  | `ConversationMemory` (short-term, bounded window + working set) and `IncidentMemoryStore` (long-term, JSON-persisted, retention + reset rules). |
| `session.py` | `SentinelSession` — multi-turn orchestrator that builds a plan, runs the A1–A8 pipeline, reflects the trace onto the plan, recalls/persists memory, and answers free-text follow-ups via the Phase 5 tools. |

UI: `ui/streamlit_app.py` — operator console. CLI demo: `scripts/run_session_demo.py`.

## Multi-step reasoning (planning / task decomposition)

Each signal is decomposed into an explicit `IncidentPlan`. The plan mirrors the
orchestrator topology and its steps advance `pending → running → done | skipped |
failed` as the pipeline executes. If A1 gates the signal (noise / insufficient
evidence), the downstream steps and the persist step are marked **skipped** —
the plan always reflects what actually ran, so the reasoning is inspectable and
reproducible. Decomposition is deterministic; the *reasoning inside* each step is
still the A1–A8 LLM nodes.

## Memory handling

**Short-term (`ConversationMemory`)** — the running state of one conversation:
a bounded window of recent turns plus a small working set of carried facts
(current entity, current incident id). `reset()` clears it to start fresh.

**Long-term (`IncidentMemoryStore`)** — durable incident records persisted to
`logs/incident_memory.json`, surviving process restarts. Used to **recall** the
last incident for an entity and to detect **recurrence** ("this is the Nth lag
incident on `payments.settlement`").

### Reset vs. retention rules

| Action | Short-term | Long-term |
|--------|-----------|-----------|
| `reset` / "new incident" turn | **cleared** | **retained** (by design) |
| window overflow (`max_turns`) | oldest turns dropped | — |
| store overflow (`max_records`) | — | oldest records pruned |
| `clear_long_term_memory()` | — | **cleared** (explicit forget-all) |

Normal operation retains long-term memory; forgetting it is a deliberate,
explicit control. Corrupt/missing store files degrade to an empty store rather
than crashing. No secrets are ever persisted — records hold incident metadata
and knowledge citations only.

## Multi-turn conversations

A `SentinelSession` handles a sequence of turns:

- **Signal turn** (JSON) → plan + full A1–A8 pipeline + persist, with recurrence
  awareness surfaced from long-term memory.
- **Follow-up turn** (free text) → answered from memory + the Phase 5 `ToolAgent`
  (metric lookup / knowledge search / escalation), keeping the current entity in
  focus across turns.
- **Control turn** (`reset`) → clears short-term, retains long-term.

## Running it

```bash
# from capstone_agent/
streamlit run ui/streamlit_app.py            # rich UI: signal -> closure trace
python scripts/run_session_demo.py           # headless multi-turn demo (offline)
python scripts/run_session_demo.py --persist # use the real logs/incident_memory.json
python -m pytest tests/test_session_memory.py -q
```

The demo and tests run on the offline deterministic provider (no key); with
`SENTINEL_LLM=openai` in `.env` the same session runs live.

## Safety posture

Unchanged from earlier phases: advisory / read-only by default, human approval
for any production action, approved-directory-only recipients, retrieved text
treated as data not instructions, and no secrets sent to the model or persisted.
