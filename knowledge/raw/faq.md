# EventHub Ops — Operator FAQ

Common questions for the on-call Platform Operations operator using Sentinel.

---

**Q: Is a short-lived lag spike always an incident?**
No. A brief `consumer_lag` spike that self-resolves within the observation window is usually
transient/noise. Sentinel classifies it accordingly and keeps it in a watch state rather than
paging. Sustained or growing lag on a critical topic is an incident.

**Q: How is severity decided?**
Severity (P1–P4) combines technical evidence (classification, scope, duration) with business
criticality from the service catalogue. A critical-tier service (payments, cards, ATM, fraud,
trades, ledger) is never downgraded just because model confidence is low.

**Q: What does "insufficient evidence" mean?**
There is no baseline rule for the metric, or the data is incomplete/stale. Sentinel does not
guess — it states the uncertainty and keeps the signal in a watch state or escalates.

**Q: Will Sentinel restart a broker or connector automatically?**
No. Sentinel is read-only/advisory by default. Any production action (restart, config/ACL/topic
change, offset change) requires explicit human approval and a change record.

**Q: Why did I get one incident for many alerts?**
Correlation and deduplication group related/duplicate alerts into a single incident candidate,
preserving links to all original signals. This reduces alert fatigue.

**Q: Who gets notified for an incident?**
Recipients are resolved only from the approved directory (CMDB / service catalogue / on-call
roster), mapped per entity to App Owner, Business Owner, Prod Support, SRE, and on-call. Sentinel
never guesses a recipient.

**Q: How do I know an incident actually recovered?**
Recovery is verified against explicit metric criteria over an observation window. Alert
disappearance alone is not proof of recovery; closure follows deterministic policy.

**Q: What if the entity isn't in the catalogue?**
Sentinel flags the missing mapping and escalates to a human rather than fabricating business
impact or recipients.
