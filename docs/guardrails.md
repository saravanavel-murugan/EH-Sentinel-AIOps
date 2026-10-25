# Guardrails — governance narrative

EventHub Ops Sentinel is an **advisory, read-only** AIOps assistant for a
Confluent Kafka platform. A layered set of guardrails keeps it on-topic, safe,
and leak-free. Each guardrail below states **what it defends against**, **where
it is enforced** (file + function), and **how to see it fire**. Every control is
deterministic and runs fully offline on the fake provider — no key, no network.

Regenerate the live evidence any time with:

```powershell
$env:SENTINEL_LLM='fake'; $env:SENTINEL_EMBEDDINGS='fake'
python scripts/run_guardrails_demo.py       # -> data/evaluation/guardrails_evidence.{json,md}
python scripts/run_monitoring_demo.py       # -> data/evaluation/monitoring_evidence.{json,md}
```

The Streamlit **Governance** tab renders both artifacts plus this document.

## Guardrail summary

| Guardrail | Defends against | Enforced at |
| --- | --- | --- |
| Allow-list tools | arbitrary / unsafe tool calls | `agent/tool_agent.py` `ToolAgent.handle` → `tools/tool_registry.py` `ToolRegistry.validate` |
| Schema validation | malformed / unknown args | `tools/tool_registry.py` `ToolRegistry.validate` |
| Approval gate | autonomous production action | `agent/tool_agent.py` (`requires_approval` → PLAN only, never acts) |
| Loop prevention | runaway / repeated calls | `agent/tool_agent.py` `MAX_ITERATIONS` + `seen_calls` |
| Secret redaction | key / token leakage to logs | `agent/observability.py` `_SECRET_PATTERNS` / `RedactingFilter` |
| Injection-as-data | prompt injection via signal content | A1–A8 treat the payload as data (reference; not re-designed) |
| No guessed recipients | mis-escalation | A7 resolves recipients only from the approved directory |
| **R1 domain scope** | off-topic / abuse | `agent/guardrails.py` `classify_scope` + `agent/session/session.py` `handle_turn` |
| **R2 PII masking** | PII leakage in and out | `agent/observability.py` `mask_pii` + session input/output hooks |

## Existing guardrails

### Allow-list tools
**Defends:** an agent (or a prompt-injected request) calling an arbitrary or
unsafe tool. **Enforced at:** `ToolAgent.handle` routes every decision through
`ToolRegistry.validate`, which rejects any tool name not registered in the
allow-list. **See it fire:** ask for an unregistered tool (e.g. `restart_broker`)
— the step carries `guardrail == "validation_failed"` with an "allow-list"
message and the tool is never dispatched.

### Schema validation
**Defends:** malformed calls — missing required args, wrong types, or unknown
arguments. **Enforced at:** `ToolRegistry.validate` checks required fields, basic
types, and rejects unknown args before dispatch. **See it fire:** call a known
tool with a bogus argument — the step carries `guardrail == "validation_failed"`.

### Approval gate
**Defends:** the system taking an autonomous production action. **Enforced at:**
`ToolAgent.handle` marks any tool with `requires_approval=True` (e.g.
`escalate_incident`) as producing a **PLAN only**; it attaches an `approval` note
and the tool returns `delivery_status="not_sent"`. **See it fire:** ask who to
notify for a P1 — the escalate step carries an `approval` note and never sends.

### Loop prevention
**Defends:** a runaway agent repeating the same call forever. **Enforced at:**
`ToolAgent.handle` with a hard `MAX_ITERATIONS` cap and a `seen_calls` set that
blocks an identical repeated call. **See it fire:** a degenerate router that
keeps asking for the same failing call trips `guardrail ==
"repeated_call_blocked"` (or the loop stops at `max_iterations`).

### Secret redaction
**Defends:** API keys / tokens reaching logs, traces, or evidence. **Enforced
at:** `agent/observability.py` — `_SECRET_PATTERNS` scrub `sk-…`, `voc-…`,
`OPENAI_API_KEY=…` assignments and bearer tokens to `<redacted>`, and
`RedactingFilter` scrubs every log record at the logging boundary. **See it
fire:** `redact("OPENAI_API_KEY=sk-…")` returns a string containing `<redacted>`
and no `sk-` substring.

### Injection-as-data
**Defends:** prompt injection carried inside signal payloads. **Enforced at:**
the A1–A8 pipeline treats the signal payload as **data**, not instructions (the
deterministic nodes never execute payload text). Referenced here for
completeness; the pipeline is not re-designed by this feature.

### No guessed recipients
**Defends:** escalating to the wrong person. **Enforced at:** A7 (and the
`escalate_incident` tool) resolve recipients **only** from the approved entity
directory; an unknown entity yields no recipients and an advisory to escalate to
a human, never a guessed address.

## New guardrails (this feature)

### R1 — Domain scope
**Defends:** off-topic or abusive input reaching the incident pipeline or the
ToolAgent. **Enforced at:** `agent/guardrails.py` `classify_scope` — a pure,
deterministic 3-way classifier (`in_scope` / `needs_clarification` /
`out_of_scope`) wired into `SentinelSession.handle_turn`. The gate rule is a hard
contract: a turn is refused **if and only if** `classify_scope(text)[0] ==
"out_of_scope"`. A refused turn returns `kind == "refused"` with a friendly
advisory and **never** constructs an `IncidentPlan`, calls `run_signal`, or
touches the ToolAgent. Signal JSON always passes; greetings and short messages
fall through as `needs_clarification` to the normal follow-up path. **See it
fire:** `classify_scope("what's the weather")` → `out_of_scope`, and a session
turn on that input returns `kind == "refused"`.

Why keyword/rule over an LLM classifier: it is deterministic (reproducible
evidence), offline by construction, zero-latency, and cannot itself be
prompt-injected.

### R2 — PII masking
**Defends:** personal data (emails, phones, cards, IBAN, Aadhaar, SSN) leaking
into memory, logs, traces, the pipeline, tools, or the operator response.
**Enforced at:** `agent/observability.py` `mask_pii` is the single masking source
of truth, composed with secret redaction via `redact_and_mask`. Two session
hooks apply it:

* **Input masking** — `handle_turn` computes `text = mask_pii(raw)` once; the
  masked value is what gets stored, classified, parsed, and routed. Raw PII never
  reaches memory, `run_signal`, the ToolAgent, or any log/trace.
* **Output masking** — each handler masks its rendered response exactly once,
  before `add_turn("agent", …)`, so both the stored turn and the returned dict
  carry placeholders (even if a tool echoed a directory contact).

Reserved placeholders like `alice@example.com` (`@example.com` / `.org` / `.net`)
are preserved by a negative lookahead so fixtures and the recipient directory are
unaffected. Internal cluster/broker IPs are **deliberately not** masked — they
are operational context the operator needs. **See it fire:**
`mask_pii("reach me at jane.doe@gmail.com / +1 415 555 2671")` →
`"reach me at <EMAIL> / <PHONE>"`, while `alice@example.com` stays verbatim.

## Optional LLM monitoring (R4)

Langfuse (tracing) and DeepEval (evaluation) are **optional and OFF by default**.
`agent/monitoring.py` guards every optional import lazily, reads config from the
environment (defaults OFF), and routes every outbound string through
`redact_and_mask`. Offline it is a pure no-op that returns structured disabled
status dicts and never touches the network. See
`data/evaluation/monitoring_evidence.{json,md}` and the Governance tab for the
live disabled status, and `.env.example` for the OFF-by-default keys.
