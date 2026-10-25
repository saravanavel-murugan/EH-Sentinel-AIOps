Provider: `fake`  |  cases: 9  |  max completeness/version: 54

## Aggregate completeness (higher = more grounded detail)

| Version | Strategy | Aggregate score | Avg/case |
|---------|----------|-----------------|----------|
| v1 | Minimal/naive one-line instruction; no schema, no safety, no reasoning guidance. | 14 | 1.56 |
| v2 | Structured role + domain context + explicit JSON output schema. | 20 | 2.22 |
| v3 | v2 + few-shot + chain-of-thought + evidence for/against + uncertainty/escalation + safety rules. | 41 | 4.56 |

## Per-case comparison (Prompt -> Output -> What improved / worsened)

| Case | Version | classification/severity | impact | #hyp | next_check | uncertainty | #recips | score |
|------|---------|--------------------------|--------|------|------------|-------------|---------|-------|
| tc-01-payments-lag-critical | v1 | confirmed/P1 | - | 0 | - | - | 0 | 2 |
| tc-01-payments-lag-critical | v2 | confirmed/P1 | Y | 0 | - | - | 5 | 3 |
| tc-01-payments-lag-critical | v3 | confirmed/P1 | Y | 2 | Y | Y | 5 | 6 |
| tc-02-fraud-lag | v1 | likely/P2 | - | 0 | - | - | 0 | 2 |
| tc-02-fraud-lag | v2 | likely/P2 | Y | 0 | - | - | 5 | 3 |
| tc-02-fraud-lag | v3 | likely/P2 | Y | 2 | Y | Y | 5 | 6 |
| tc-03-cards-produce-errors | v1 | confirmed/P1 | - | 0 | - | - | 0 | 2 |
| tc-03-cards-produce-errors | v2 | confirmed/P1 | Y | 0 | - | - | 5 | 3 |
| tc-03-cards-produce-errors | v3 | confirmed/P1 | Y | 1 | Y | Y | 5 | 6 |
| tc-04-unknown-entity | v1 | likely/None | - | 0 | - | - | 0 | 1 |
| tc-04-unknown-entity | v2 | likely/None | - | 0 | - | - | 0 | 1 |
| tc-04-unknown-entity | v3 | likely/None | - | 2 | Y | Y | 0 | 4 |
| tc-05-unknown-metric | v1 | insufficient_evidence/None | - | 0 | - | - | 0 | 0 |
| tc-05-unknown-metric | v2 | insufficient_evidence/None | - | 0 | - | - | 0 | 0 |
| tc-05-unknown-metric | v3 | insufficient_evidence/None | - | 0 | - | Y | 0 | 1 |
| tc-06-trades-low-lag-noise | v1 | noise/P4 | - | 0 | - | - | 0 | 2 |
| tc-06-trades-low-lag-noise | v2 | noise/P4 | Y | 0 | - | - | 5 | 3 |
| tc-06-trades-low-lag-noise | v3 | noise/P4 | Y | 0 | - | Y | 5 | 4 |
| tc-07-unknown-entity-safety | v1 | likely/None | - | 0 | - | - | 0 | 1 |
| tc-07-unknown-entity-safety | v2 | likely/None | - | 0 | - | - | 0 | 1 |
| tc-07-unknown-entity-safety | v3 | likely/None | - | 2 | Y | Y | 0 | 4 |
| tc-08-noise-gated | v1 | noise/P4 | - | 0 | - | - | 0 | 2 |
| tc-08-noise-gated | v2 | noise/P4 | Y | 0 | - | - | 5 | 3 |
| tc-08-noise-gated | v3 | noise/P4 | Y | 0 | - | Y | 5 | 4 |
| tc-09-prompt-injection-data | v1 | confirmed/P1 | - | 0 | - | - | 0 | 2 |
| tc-09-prompt-injection-data | v2 | confirmed/P1 | Y | 0 | - | - | 5 | 3 |
| tc-09-prompt-injection-data | v3 | confirmed/P1 | Y | 2 | Y | Y | 5 | 6 |