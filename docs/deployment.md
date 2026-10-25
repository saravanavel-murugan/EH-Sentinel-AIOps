# Phase 8 — Deployment Readiness

Phase 8 makes Sentinel **runnable as a packaged app** and adds the
deployment-grade cross-cutting concerns the earlier phases left ad-hoc:
centralized structured logging, per-run tracing with latency and error capture,
and a graceful-failure runtime wrapper. Everything is **additive** — the A1–A8
pipeline (Phase 3b), RAG (Phase 4), tools/MCP (Phase 5), the Phase 6 session, and
Phase 7 adaptation are reused unchanged through their public facades. On the
happy path, behaviour is byte-for-byte identical; the traced/safe wrappers are
opt-in or transparent.

Everything runs **offline** on the deterministic fake provider with **no API key
and no network**. A redacting filter guarantees **no secret or PII** ever reaches
a log, trace, or evidence file (a hard Scenario-1 requirement).

## New building blocks (`agent/observability.py`)

| Component | Responsibility |
|-----------|----------------|
| `configure_logging()` | Idempotent, stdlib-only setup. Attaches a `RotatingFileHandler` writing JSON lines to `logs/sentinel.log` plus a human-readable console handler. Both carry a `RedactingFilter`. Level from `SENTINEL_LOG_LEVEL` (default `INFO`). |
| `redact()` / `RedactingFilter` | PII/secret-safe scrubber. Replaces `sk-…`, `voc-…`, `OPENAI_API_KEY=…`, and `Bearer …` with `<redacted>`, and masks dict values under secret-looking key names (`api_key`/`secret`/`token`/`password`/`authorization`). Single source of truth for both logging and the trace file. |
| `RunTrace` + `trace_run()` | A context manager that assigns a short `run_id`, times the run, sets `latency_ms` + `status`, and (on failure) `error_type`/`error_message`. Writes one redacted JSON object per run to `logs/traces.jsonl` and emits one structured log record. Re-raises after recording. |
| `safe_handle_turn()` | Thin graceful-failure wrapper around `SentinelSession.handle_turn`. On success returns the real dict unchanged; on ANY exception returns a structured `kind="error"` response (no stack trace, no secret, advisory posture preserved). Never raises. |
| `new_run_id()` / `latency_ms()` / `shutdown_logging()` | Small helpers; `shutdown_logging()` closes handlers so a temp log dir can be removed cleanly on Windows. |

CLI evidence: `scripts/run_phase8_deploy_check.py`.

## Packaging & reproducibility

- **`pyproject.toml`** makes the project installable (`pip install .`) with the
  **same pinned dependency set** as `requirements.txt` (LangChain 0.3.27,
  langchain-core 0.3.78, langgraph 0.6.11, langchain-openai 0.3.35, pydantic
  2.9.2, python-dotenv 1.0.1, faiss-cpu 1.9.0, numpy 1.26.4, streamlit 1.39.0;
  pytest in the `test` extra). `requires-python = ">=3.11"`. The `python
  scripts/...` invocation style is unchanged.
- **`Dockerfile`** builds a minimal `python:3.11-slim` image: install pinned deps
  first (cached layer), copy the source, and default `CMD` to the Streamlit UI on
  `0.0.0.0:${PORT}` headless. It is offline-first — `SENTINEL_LLM=fake` by
  default — so the container runs with no key and no network.
- **`.dockerignore`** keeps `.env`, `__pycache__/`, `.pytest_cache/`, `logs/*.log`,
  `logs/*.jsonl`, `.worktrees/`, `.agents/`, and `phases/` out of the image.

## Environment management

| Variable | Purpose | Default |
|----------|---------|---------|
| `SENTINEL_LLM` | Chat provider: `fake` (offline) or `openai` (live). | `fake` |
| `SENTINEL_EMBEDDINGS` | Embeddings provider for RAG. | `fake` |
| `SENTINEL_LOG_LEVEL` | Logging level for `logs/sentinel.log` + console. | `INFO` |
| `OPENAI_API_KEY` | Required only when a provider is `openai`. | (unset) |

`.env` is loaded by `agent/env_config.load_env()` with `override=True`, so the
file is authoritative over stale shell variables. **Secrets are injected at
runtime via environment variables and are NEVER baked into the image or into
code, tests, docs, or evidence.** The container does not copy `.env`.

## Logging & tracing design

- **`logs/sentinel.log`** — rotating, structured **JSON lines** (one object per
  record: `ts`, `level`, `logger`, `msg`, plus whitelisted `extra` fields). The
  console handler is human-readable for interactive use.
- **`logs/traces.jsonl`** — one **clean JSON object per run** for latency/error
  capture: `run_id`, `entry_point`, `provider`, `status`, `latency_ms`,
  `started_at`/`ended_at`, and on failure `error_type`/`error_message`.
- **Redaction runs before any write.** The same `redact()` rules apply to log
  records (via `RedactingFilter` on every handler) and to the trace file, so a
  planted `sk-…` / `OPENAI_API_KEY=…` can never land on disk. The structured log
  records an exception's **type** only — never the full traceback text.

Only **metadata** is logged (entry point, provider, status, latency, error type,
and whitelisted extra keys such as the entity key). Raw signal payloads, notes,
and business data are never written.

## Latency & error capture

Every traced run records `latency_ms` (rounded from `time.perf_counter()`), a
`status` of `ok` or `error`, and — on failure — the exception `error_type` and a
redacted `error_message`. Both success and failure traces are appended to
`logs/traces.jsonl`, so operators can measure per-run latency and review error
history directly from disk. `scripts/run_phase8_deploy_check.py` tails this file
as proof the capture landed.

## Graceful failure handling

`safe_handle_turn(session, user_input)` wraps the turn inside `trace_run`. On
success it returns the real result dict unchanged; on ANY exception it records an
error trace and returns a structured degraded response:

```json
{
  "kind": "error",
  "ok": false,
  "run_id": "run-1a2b3c4d",
  "provider": "fake",
  "error_type": "ValueError",
  "message": "Sentinel could not complete this turn due to an internal error. No production action was taken; the system remains advisory and read-only. ...",
  "safety": "advisory/read-only preserved; no action taken",
  "response": "<the same safe message, rendered for the UI/console>"
}
```

No stack trace or secret ever appears in the returned dict. The three required
scenarios, all exercised offline by the evidence script:

| # | Scenario | How it is exercised | Outcome |
|---|----------|---------------------|---------|
| 1 | **Malformed / invalid input** | A turn path that raises an internal error on bad input. | `kind="error"` graceful dict; no crash. |
| 2 | **Provider / LLM outage** | A fake chat model whose `invoke` raises a hard, non-recoverable outage. (Ordinary LLM errors are already caught *inside* the A1–A8 nodes, which degrade to the deterministic rule fallback — that resilience is itself graceful handling; this scenario models the catastrophic case that reaches the runtime wrapper.) | `kind="error"` graceful dict; no crash. |
| 3 | **Missing / disabled retrieval index** | `use_retrieval=False` (or no FAISS index): `MultiAgentSentinel` degrades retrieval to disabled. | The turn **completes** with a normal `kind="signal"` dict — the system does not crash when the index is absent. |

In every degraded case the **advisory / read-only safety posture is preserved**:
no production action is taken, no approval is skipped, and no escalation is
suppressed.

## Local deploy steps

```bash
# from capstone_agent/

# 1) Run the operator console directly (offline fake provider)
streamlit run ui/streamlit_app.py

# 2) Offline deployment-readiness evidence (latency + 3 graceful failures)
python scripts/run_phase8_deploy_check.py --no-retrieval

# 3) Build + run the container (offline-first; no key needed)
docker build -t eventhub-sentinel .
docker run --rm -p 8501:8501 eventhub-sentinel

# 4) Live OpenAI path — key injected at runtime, never baked in
docker run --rm -p 8501:8501 \
  -e SENTINEL_LLM=openai -e SENTINEL_EMBEDDINGS=openai \
  -e OPENAI_API_KEY=... eventhub-sentinel
```

## Deployment assumptions and limitations

- **Offline by default.** The fake provider is deterministic and needs no key or
  network; the live OpenAI path is opt-in via `SENTINEL_LLM=openai` + a runtime
  `OPENAI_API_KEY`.
- **Single-process app.** The Streamlit console and session hold in-process
  state; there is no multi-worker/horizontal-scaling story. Concurrency is a
  single operator conversation per session.
- **JSON-file persistence, not a database.** Long-term incident memory
  (`logs/incident_memory.json`), feedback (`logs/feedback.json`), and traces
  (`logs/traces.jsonl`) are plain files — inspectable and portable, but not a
  concurrent datastore.
- **Advisory / read-only.** The system never performs production actions; all
  remediation requires human approval. Graceful degradation never weakens this.
- **Latency depends on the provider.** Offline latency is small and
  deterministic; live latency depends on the OpenAI endpoint and network.
- **The Dockerfile is a packaging artefact.** It is validated **structurally**
  (correct base image, pinned install, no secret baked in, sensible `CMD`); a
  real `docker build`/cloud push is out of scope for this phase and not required
  for the offline verification.
- **No real cloud push or outbound network** is performed by any Phase 8 script.
- **Log rotation** caps `logs/sentinel.log` at ~1 MB × 3 backups; adjust for your
  retention needs in a real deployment.
