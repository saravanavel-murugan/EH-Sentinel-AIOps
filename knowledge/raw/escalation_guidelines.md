# EventHub Ops — Escalation Guidelines

How and when to escalate, by severity. Channels/recipients are resolved from the approved
directory (see `events_stakeholder_summary.md`); values here are policy, not contacts.

---

## Severity → response & escalation

### P1 / Critical
- **When:** confirmed/strongly-suspected outage or severe degradation of a critical banking event
  flow (payments, cards, ATM, fraud, trades, ledger); event-loss risk; security/control-plane issue.
- **Escalation:** page platform on-call AND incident commander immediately; notify App Owner and
  Business Owner; frequent updates; human-led remediation.
- **Timers:** acknowledge within minutes; escalate further if unacknowledged.

### P2 / High
- **When:** major degradation of a critical service, rapidly increasing lag, multiple
  partitions/connectors affected, SLO breach likely.
- **Escalation:** urgent page to the owning team; engage platform + application teams; regular updates.

### P3 / Medium
- **When:** limited scope, workaround available, isolated connector/client issue, noncritical impact.
- **Escalation:** ticket + team notification; remediate within the agreed operational target.

### P4 / Low
- **When:** informational, transient, or low-impact with no current business impact.
- **Escalation:** dashboard/ticket or digest; trend and monitor.

---

## Escalation triggers (any one fires an escalation)
- Severity increases or blast radius widens.
- SLA/acknowledgement timer expires.
- Recovery not confirmed within the observation window; issue persists or worsens.
- Security relevance detected (auth/ACL/control-plane).

## Escalation rules
- Resolve recipients only from the approved on-call roster — never guess.
- Business Owners receive business-impact-framed updates; technical teams receive evidence-framed updates.
- Never claim a notification was delivered without a tool/delivery result.
- If telemetry is stale or contradictory, state the uncertainty and escalate to a human.
