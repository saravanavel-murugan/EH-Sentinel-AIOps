# R3 — guardrails evidence
# generated: 2026-10-25T20:06:48.979090+00:00
# provider: fake  result: PASS

Each governance control was forced to fire offline on the deterministic
fake provider. No secret or PII appears in this evidence.

## Guardrails

| Guardrail | Fired | Input | Evidence |
| --- | --- | --- | --- |
| domain_scope | True | off-topic question ('what is the weather today') | classify_scope -> out_of_scope (no in-domain terms detected); session turn kind=refused |
| pii_masking | True | operator message carrying a real email + phone | masked -> 'reach me at <EMAIL> / <PHONE>'; reserved placeholder preserved -> 'directory owner alice@example.com' |
| secret_redaction | True | an environment assignment leaking an API key | redact(...) -> '<redacted>' |
| allow_list | True | router asks for an unregistered tool ('restart_broker') | step guardrail=validation_failed; error=tool 'restart_broker' is not in the allow-list (known: ['search_knowledge', 'loo |
| schema_validation | True | known tool called with an unknown argument | step guardrail=validation_failed; error=missing required argument 'entity_id' for tool 'lookup_metric' |
| approval_gate | True | operator asks who to notify (approval-gated tool) | approval note present=True; delivery_status=not_sent |
| loop_prevention | True | a degenerate router that repeats the identical call | stop_reason=loop prevented: repeated call restart_broker:{"id": "b1"}; repeated_call step=True |

See `docs/guardrails.md` for the full governance narrative and enforcement locations.