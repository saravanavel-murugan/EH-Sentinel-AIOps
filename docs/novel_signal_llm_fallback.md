# Novel-signal handling — LLM fallback when a signal is not in the knowledge base

When a new signal arrives that the knowledge base does **not** cover, the A1–A8
pipeline no longer stops or returns an empty root cause. Instead A4 (root-cause)
and A5 (remediation) fall back to **LLM reasoning from first principles**, and the
incident record is clearly tagged so an operator knows the analysis is model-
inferred and must be validated before any action.

## What "not in the knowledge base" means

Two distinct cases are handled:

1. **Known metric, no matching runbook.** Retrieval (Phase 4 FAISS) runs but finds
   no relevant document (`found = false`).
2. **Novel metric, no deterministic rule.** The metric has no entry in
   `STATIC_THRESHOLDS`, so the deterministic classifier returns
   `insufficient_evidence`. Previously A1 gated the pipeline off for these. Now, if
   the **entity is known** and the value is numeric, the signal is treated as
   actionable (`likely`) and routed through the full pipeline.

Both cases set `context["knowledge_grounded"] = false`.

## How the decision flows

```
enrich: retrieval runs -> context["knowledge_grounded"] = (retrieval found a doc?)
                          context["novel_metric"]      = (no threshold rule + numeric value)

A1: if novel_metric AND entity_known AND rule=insufficient_evidence
        -> classification promoted to "likely" (not gated off)

A4: knowledge_grounded == true  -> ground hypotheses in runbook, cite source,
                                    analysis_source = "knowledge_base"
    knowledge_grounded == false -> LLM infers ranked hypotheses from Kafka domain
                                    reasoning, analysis_source = "llm_inference"

A5: same split -> runbook steps (knowledge_base) OR LLM-proposed safe, reversible,
                  approval-gated diagnostics (llm_inference)

A6: root_cause prefixed "[source: runbook-grounded | LLM-inferred ...]";
    knowledge_references note that no KB doc matched;
    closure document carries an "Analysis source:" line.
```

## Provenance fields

| Field | Where | Values |
|-------|-------|--------|
| `A4Output.analysis_source` | A4 output | `knowledge_base` \| `llm_inference` |
| `A5Output.analysis_source` | A5 output | `knowledge_base` \| `llm_inference` |
| `A6.root_cause` prefix | incident record | `[source: runbook-grounded]` or `[source: LLM-inferred …]` |
| `A6.knowledge_references` | incident record | citations, or an explicit "LLM-inferred" note |
| closure document `Analysis source:` | closure markdown | one-line provenance statement |

The knowledge base remains the **source of truth on coverage**: the node forces
`analysis_source` to match whether retrieval actually grounded the signal, so the
LLM cannot claim runbook grounding that does not exist.

## Safety is preserved

LLM-inferred remediation is held to the same guardrails as runbook-backed
remediation: `read_only = true`, every action `requires_approval = true`, recipients
resolved only from the approved directory, and the record states the analysis is
model-inferred and must be human-validated. The LLM widens *coverage*; it does not
widen *authority*.

## Try it

```bash
# from capstone_agent/ — a metric with no KB coverage (live OpenAI recommended)
python scripts/incident_report.py --query-file - <<'JSON'
{"signal_id":"sig-novel","source":"control_center",
 "entity":{"type":"topic","id":"payments.settlement"},
 "metric_or_event":"tls_cert_expiry_days","value":2,"unit":"days","environment":"prod"}
JSON
```

(Or point `--query-file` at a JSON file.) Offline (`SENTINEL_LLM=fake`) also
demonstrates the path with deterministic LLM-style hypotheses.

**Verified live (OpenAI):** `tls_cert_expiry_days=2` on `topic:payments.settlement`
ran the full A1→A8 pipeline, severity P1, with an LLM-inferred root cause (certificate
nearing expiry + missing expiry monitoring) and three approval-gated remediation
actions — `analysis_source = llm_inference`, knowledge references flagged as
LLM-inferred. Evidence: `data/evaluation/incident_report_novel.md`.

Note: a semantically related metric (e.g. `schema_registry_timeout_rate`) DOES match
a runbook (RB-05) under the live embedder and is correctly handled as
`knowledge_base` — the fallback only triggers when there is genuinely no coverage.
