# R4 — LLM monitoring evidence (Langfuse + DeepEval)
# generated: 2026-10-25T20:07:03.419435+00:00
# result: PASS  offline: True

Optional LLM monitoring is OFF by default. This evidence proves both
integrations degrade gracefully offline (no key, no network, no crash).

## Status

| Integration | enabled | reason |
| --- | --- | --- |
| Langfuse | False | disabled (not configured) |
| DeepEval | False | disabled (not configured) |

## Live calls (disabled offline path)
```
langfuse_trace(...) yielded: {'enabled': False, 'reason': 'disabled (not configured)'}
deepeval_score(...) returned: {'enabled': False, 'reason': 'disabled (not configured)', 'metrics': {}}
```

## How to enable
Uncomment the exact-pinned optional block in `requirements.txt`, install,
then set the OFF-by-default keys in `.env` (see `.env.example`):
`SENTINEL_LANGFUSE_ENABLED=1`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_HOST`, `SENTINEL_DEEPEVAL_ENABLED=1`, `SENTINEL_DEEPEVAL_MODEL`.
No key value is ever displayed or logged.