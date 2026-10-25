# EventHub Ops – Sentinel

A governed, observable **multi-agent AIOps** system for a business-critical banking
Confluent Kafka platform. Sentinel ingests alerts/logs/metrics, validates and correlates
signals, assesses severity and business impact, forms evidence-backed root-cause hypotheses,
recommends safe remediation, notifies the right stakeholders, verifies recovery, and keeps a
full audit trail — **advisory and read-only by default**, with human approval for any
production action.

> **This directory (`capstone_agent/`) is the canonical project — run everything from here.**
> The `../phases/phase*/` folders are per-phase submission-evidence mirrors (snapshots), not the
> place to run day-to-day.

---

## Quick start

```bash
# from capstone_agent/
pip install -r requirements.txt

# copy the env template; offline fake model is the default (no API key needed)
# (Windows PowerShell)  Copy-Item .env.example .env
# (bash)                cp .env.example .env
```

### Run the agents

```bash
# Phase 2 — baseline rules/template agent (no LLM)
python scripts/run_agent.py --batch data/evaluation/phase2_demo_inputs.txt

# Phase 3 — single-node LLM triage agent (LangChain + LangGraph)
python scripts/run_llm_agent.py --query-file data/evaluation/sample_signal.json
python scripts/run_llm_agent.py --query-file data/evaluation/sample_signal.json --prompt-version v1

# Phase 3 — prompt-strategy comparison (v1/v2/v3) -> data/evaluation/phase3_comparison.{json,md}
python -m evaluation.prompt_compare

# Phase 3b — multi-agent A1-A8 pipeline (requirements section 7)
python scripts/run_multiagent.py --query-file data/evaluation/sample_signal.json
python scripts/run_multiagent.py --batch data/evaluation/phase2_demo_inputs.txt

# Phase 5 — tool-using agent (in-process registry + custom router)
python scripts/run_tool_agent.py --demo

# Phase 5b — MCP layer: tools exposed over a JSON-RPC protocol boundary
python scripts/run_mcp_demo.py             # protocol trace + guardrails + agent-over-MCP
python scripts/run_mcp_demo.py --protocol  # just the raw JSON-RPC trace

# Phase 6/7 — planning, memory, adaptive behaviour (rich UI: feedback form + ADAPTATION panel)
streamlit run ui/streamlit_app.py          # operator console: signal -> closure + Phase 7 feedback/adaptation
python scripts/run_session_demo.py         # headless multi-turn demo (offline-capable)

# Phase 7 — adaptive behaviour: feedback-driven advisory adjustments (before/after)
python scripts/run_phase7_feedback_demo.py # headless before-vs-after demo (offline-capable)
python scripts/ui_phase7_evidence.py       # reproduce the UI feedback->adaptation flow headless (evidence)

# Phase 8 — deployment readiness: logging/tracing, latency+error capture, graceful failure
python scripts/run_phase8_deploy_check.py --no-retrieval   # offline evidence: latency + 3 graceful failures
docker build -t eventhub-sentinel .                        # package the Streamlit app (offline-first image)
docker run --rm -p 8501:8501 eventhub-sentinel             # run the container (no key needed)

# Phase 9 — evaluation & engineering review: scorecards, gating, consistency, safety, go/no-go
python scripts/run_phase9_eval.py --no-retrieval           # full offline evaluation -> data/evaluation/phase9_*.{json,md}; prints PASS/FAIL
```

### Test everything

```bash
# full regression suite (deterministic, offline, no key) — 33 tests
python -m pytest tests/ -q

# one-shot smoke test with a PASS/FAIL summary (no pytest needed)
python scripts/test_all.py

# MCP tool-call EVIDENCE: which documents the search_knowledge tool cited
# (writes data/evaluation/mcp_evidence.{json,md})
python scripts/eval_mcp_evidence.py

# INCIDENT SUMMARY with knowledge-reference evidence (A1-A8 + RAG citations)
# (writes data/evaluation/incident_report.{json,md})
python scripts/incident_report.py --query-file data/evaluation/sample_signal.json
```

The suite forces the offline fake providers, so it runs without a key regardless
of `.env`. It covers three layers: (1) the MCP protocol/server/client/tools,
(2) the `ToolAgent` with in-process vs MCP **parity**, and (3) the Phase 2/3/3b
agents end-to-end.

### Live OpenAI (optional) — one switch flips ALL agents + retrieval

The default providers are offline/deterministic so everything runs without a key. To run the
**whole system** (Phase 3 single-node LLM agent, Phase 3b A1–A8 multi-agent pipeline, and Phase 4
retrieval embeddings) on OpenAI, set these in `.env`:

```
SENTINEL_LLM=openai              # all LLM agents -> ChatOpenAI
SENTINEL_EMBEDDINGS=openai       # retrieval -> OpenAI embeddings (text-embedding-3-small)
OPENAI_API_KEY=sk-...            # one key used by both
SENTINEL_OPENAI_MODEL=gpt-4o-mini
SENTINEL_OPENAI_EMBED_MODEL=text-embedding-3-small
```

Then rebuild the index with OpenAI embeddings and run the agents:

```bash
python scripts/ingest_documents.py        # (no key needed; produces chunks.json)
python scripts/build_faiss_index.py        # embeds with OpenAI when SENTINEL_EMBEDDINGS=openai
python scripts/run_multiagent.py --query-file data/evaluation/sample_signal.json
```

Provider selection is centralized: `agent/llm.py` (`SENTINEL_LLM`) for all chat agents and
`retrieval/embedder.py` (`SENTINEL_EMBEDDINGS`) for embeddings. The baseline agent is pure rules
(no LLM) by design.

> **Windows PowerShell note:** pass signal JSON with `--query-file` or `--batch`; an inline
> `--query '{...}'` loses its double quotes to the shell.

---

## What's built so far

| Phase | What | Entry point |
|-------|------|-------------|
| 1 | Problem framing, personas, I/O, success criteria, edge cases, evaluation plan | `docs/*.md` |
| 2 | Baseline rules/template agent (no LLM) + limitations | `scripts/run_agent.py`, `agent/core_agent.py:BaselineAgent` |
| 3 | LLM triage agent (LangChain + LangGraph), 3 prompt strategies, comparison (default v3) | `scripts/run_llm_agent.py`, `evaluation/prompt_compare.py` |
| 3b | Multi-agent **A1–A8** pipeline per requirements §7 + architecture/data-flow diagrams | `scripts/run_multiagent.py`, `agent/agents/` |
| 4 | RAG: FAISS knowledge base (runbooks/FAQ/policy/past incidents), wired into A4/A5 | `scripts/build_faiss_index.py`, `retrieval/`, `evaluation/retrieval_eval.py` |
| 5 | Tool-using agent: allow-listed registry + custom router + guardrails | `scripts/run_tool_agent.py`, `tools/`, `agent/tool_agent.py` |
| 5b | **MCP layer**: same tools exposed over a JSON-RPC (Model Context Protocol) boundary | `scripts/run_mcp_demo.py`, `mcp/` |
| 6 | **Planning, memory & context**: task decomposition, short/long-term memory (reset vs retention), multi-turn sessions + rich Streamlit UI (signal→closure trace) | `ui/streamlit_app.py`, `scripts/run_session_demo.py`, `agent/session/` |
| 7 | **Adaptive behaviour**: operator feedback store + deterministic adaptation policy (advisory severity nudge, concise mode, recurrence emphasis) — advisory only, never weakens safety. Surfaced in the Streamlit UI (feedback form + ADAPTATION panel + feedback summary) | `scripts/run_phase7_feedback_demo.py`, `agent/session/feedback.py`, `ui/streamlit_app.py` |
| 8 | **Deployment readiness**: packaging (Dockerfile + pyproject), centralized structured logging + per-run tracing, latency & error capture, graceful-failure runtime wrapper (`safe_handle_turn`) — additive, offline, secrets never logged | `scripts/run_phase8_deploy_check.py`, `agent/observability.py`, `Dockerfile` |
| 9 | **Evaluation & engineering review**: per-dimension quality scorecards vs gates, gating-correctness, consistency (K=3), safety scorecard (zero-violation hard blocker), root-cause analysis with before/after, prompt comparison + go/no-go — additive, offline | `scripts/run_phase9_eval.py`, `evaluation/evaluation_harness.py`, report `docs/evaluation_report.md` |

The eight agents (A1 Signal Validation, A2 Correlation & Topology, A3 Severity & Business
Impact, A4 Root-Cause Hypothesis, A5 Remediation Recommendation, A6 Incident Summary & Ticket,
A7 Stakeholder Communication, A8 Recovery Verification) run as a bounded LangGraph pipeline.
Deterministic rules ground and constrain the LLM so it cannot invent metrics, recipients, or
authorization.

---

## Repository layout (key parts)

```
capstone_agent/
├── README.md                 (this file)
├── requirements.txt          (pinned deps)
├── pyproject.toml            installable packaging (same pinned deps) (Phase 8)
├── Dockerfile                offline-first Streamlit image (Phase 8)
├── .dockerignore             excludes .env/caches/logs from the image (Phase 8)
├── .env.example              (config template; no secrets)
├── agent/
│   ├── core_agent.py         BaselineAgent (Phase 2) + LLMAgent (Phase 3)
│   ├── baseline_*.py         deterministic rules / templates / sample data
│   ├── llm.py                provider factory (ChatOpenAI | offline fake)
│   ├── prompts.py            v1/v2/v3 prompt strategies
│   ├── planner.py            Phase 3 single-node LangGraph
│   ├── schemas.py            Pydantic triage contract
│   ├── observability.py      logging/tracing + redaction + safe_handle_turn (Phase 8)
│   ├── agents/               A1-A8 multi-agent pipeline (Phase 3b)
│   ├── session/              planning + memory + multi-turn session (Phase 6)
│   └── tool_agent.py         ToolAgent (Phase 5); use_mcp=True dispatches over MCP
├── ui/                       Streamlit console: signal->closure trace (Phase 6)
├── tools/                    tool registry + 3 tools + custom router (Phase 5)
├── retrieval/                embedder, FAISS store, retriever (Phase 4)
├── mcp/                       MCP server + client over JSON-RPC (Phase 5b)
├── evaluation/
│   ├── prompt_compare.py     prompt-strategy comparison harness
│   ├── evaluation_harness.py Phase 9 scorecards + gating + consistency + safety + go/no-go
│   └── failure_analysis.py   Phase 9 tc-05 root-cause analysis (before/after)
├── scripts/                  run_agent.py | run_llm_agent.py | run_multiagent.py | run_tool_agent.py | run_mcp_demo.py | run_phase9_eval.py | test_all.py
├── tests/                    pytest suite (MCP, ToolAgent parity, A1-A8 agents, Phase 9 eval harness)
├── data/evaluation/          test_cases.json, sample_signal.json, demo inputs, results,
│                             phase9_evaluation.{json,md}, phase9_failure_analysis.{json,md} (Phase 9)
├── docs/                     problem framing, inputs/outputs, architecture + diagrams, etc.
└── logs/                     interactions.log, mcp_events.log, incident_memory.json, feedback.json,
                              sentinel.log (structured JSON), traces.jsonl (per-run latency/errors) (Phase 8)
```

---

## Documentation

- Problem & success: `docs/problem_framing.md`, `docs/success_criteria.md`, `docs/evaluation_plan.md`
- I/O & stakeholders: `docs/inputs.md`, `docs/outputs.md`, `docs/events_stakeholder_summary.md`
- Personas & edge cases: `docs/personas.md`, `docs/edge_cases.md`
- Phase 2 limitations: `docs/baseline_limitations.md`
- Phase 3 prompt comparison: `docs/prompt_comparison_table.md`
- Architecture + data-flow diagrams: `docs/architecture.md`, `docs/diagrams/*.svg`
- Retrieval / RAG (Phase 4): `docs/retrieval.md`
- Tool usage (Phase 5): `docs/tools.md`
- MCP layer (Phase 5b): `docs/mcp.md`
- Novel-signal LLM fallback (not-in-knowledge-base): `docs/novel_signal_llm_fallback.md`
- Planning, memory & context (Phase 6): `docs/planning_memory.md`
- Adaptive behaviour (Phase 7): `docs/adaptive_behaviour.md`
- Deployment readiness (Phase 8): `docs/deployment.md`
- Evaluation & engineering review (Phase 9): `docs/evaluation_report.md`
- Forced demo script (3–5 interactions): `docs/demo_script.md`
- Engineering & product justification: `docs/engineering_justification.md`

---

## Safety posture

Read-only/advisory by default; production actions require human approval. No secrets or customer
payloads are sent to the model. Retrieved text (logs, tickets, topic names) is treated as data,
not instructions. All placeholder names/contacts use `@example.com`.
