# Cross-Tier Comparison - Baseline vs LLM Prompts vs Multi-Agent

Provider: `fake`  |  cases: 6 (4 actionable, 2 correctly gated)  |  10 capabilities per case

## Headline: capability coverage on ACTIONABLE incidents

Scored only on the 4 actionable cases (non-actionable signals are correctly gated to a watch state, so incident-workflow capabilities should NOT fire there). This is the fair quality measure.

| Tier | Aggregate (max 40) | Avg capabilities/case |
|------|--------------------|------------------------|
| Phase 2 baseline (rules/templates, no LLM) | 16 | 4.00 |
| Phase 3 LLM - prompt v1 (minimal) | 11 | 2.75 |
| Phase 3 LLM - prompt v2 (structured) | 20 | 5.00 |
| Phase 3 LLM - prompt v3 (few-shot/CoT/safety) | 32 | 8.00 |
| Phase 3b multi-agent A1-A8 | 36 | 9.00 |

## All-cases aggregate (includes gated cases, for reference)

| Tier | Aggregate (max 60) |
|------|--------------------|
| Phase 2 baseline (rules/templates, no LLM) | 21 |
| Phase 3 LLM - prompt v1 (minimal) | 15 |
| Phase 3 LLM - prompt v2 (structured) | 27 |
| Phase 3 LLM - prompt v3 (few-shot/CoT/safety) | 41 |
| Phase 3b multi-agent A1-A8 | 37 |

## Capability coverage matrix (cases covered / 6)

| Capability | baseline | llm_v1 | llm_v2 | llm_v3 | multiagent |
|---|---|---|---|---|---|
| C1 classification | 5 | 5 | 5 | 5 | 5 |
| C2 severity | 4 | 4 | 4 | 4 | 3 |
| C3 business impact | 4 | 0 | 4 | 4 | 3 |
| C4 affected services | 4 | 0 | 4 | 4 | 3 |
| C5 ranked hypotheses | 0 | 0 | 0 | 4 | 4 |
| C6 next diagnostic check | 0 | 0 | 0 | 4 | 4 |
| C7 stakeholder recipients | 4 | 0 | 4 | 4 | 3 |
| C8 remediation actions | 0 | 0 | 0 | 0 | 4 |
| C9 approval-gated (safety) | 0 | 6 | 6 | 6 | 4 |
| C10 recovery/uncertainty | 0 | 0 | 0 | 6 | 4 |

## Per-case capability score (out of 10)

| Case | actionable | baseline | llm_v1 | llm_v2 | llm_v3 | multiagent |
|---|---|---|---|---|---|---|
| tc-01-payments-lag-critical | yes | 5 | 3 | 6 | 9 | 10 |
| tc-02-fraud-lag | yes | 5 | 3 | 6 | 9 | 10 |
| tc-03-cards-produce-errors | yes | 5 | 3 | 6 | 9 | 10 |
| tc-04-unknown-entity | yes | 1 | 2 | 2 | 5 | 6 |
| tc-05-unknown-metric | gated | 0 | 1 | 1 | 2 | 0 |
| tc-06-trades-low-lag-noise | gated | 5 | 3 | 6 | 7 | 1 |

> On actionable incidents the ordering is baseline < v1 < v2 < v3 <= multi-agent, with multi-agent uniquely adding remediation actions (C8). On gated cases a LOW score is CORRECT: the A1 gate stops noise/insufficient-evidence signals before the incident workflow runs.