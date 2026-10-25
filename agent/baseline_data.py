"""Baseline sample data for the Phase 2 rules/template agent.

This is a deliberately SMALL, HARD-CODED lookup table derived from
``docs/events_stakeholder_summary.md``. It exists only so the baseline agent can
produce a plausible triage response without any LLM, retrieval, or live CMDB.

LIMITATION BY DESIGN: anything not present in this table falls through to a
generic "unknown entity" response. Later phases replace this with retrieval over
the source-of-truth catalogue.

All names/contacts are PII-safe placeholders (``@example.com``).
"""

from __future__ import annotations

# Static thresholds per metric. Baseline uses a single flat threshold with no
# dynamic baselines, no per-topic tuning, and no time-series context.
# LIMITATION BY DESIGN: one global number per metric.
STATIC_THRESHOLDS: dict[str, dict[str, float | str]] = {
    "consumer_lag": {"value": 50000, "unit": "messages"},
    "under_replicated_partitions": {"value": 1, "unit": "count"},
    "produce_error_rate": {"value": 10, "unit": "errors/s"},
    "sink_error_rate": {"value": 10, "unit": "errors/s"},
    "source_error_rate": {"value": 10, "unit": "errors/s"},
    "request_queue_depth": {"value": 500, "unit": "requests"},
}

# Entity -> business impact + stakeholders. Keyed by "type:id".
# Mirrors docs/events_stakeholder_summary.md (placeholder data).
ENTITY_TABLE: dict[str, dict] = {
    "topic:payments.settlement": {
        "business_services": ["Payments Settlement"],
        "business_impact": "Payments delayed or failed; settlement backlog; SLA/regulatory risk",
        "criticality_tier": 1,
        "stakeholders": {
            "app_owner": "payments-app-owner@example.com",
            "business_owner": "payments-biz-owner@example.com",
            "prod_support": "prodsupport-payments@example.com",
            "sre": "sre-streaming@example.com",
            "on_call": "pager:payments-oncall / #inc-payments",
        },
    },
    "topic:cards.authorization": {
        "business_services": ["Card Authorization"],
        "business_impact": "Card authorization failures; declined transactions at POS/ecom",
        "criticality_tier": 1,
        "stakeholders": {
            "app_owner": "cards-app-owner@example.com",
            "business_owner": "cards-biz-owner@example.com",
            "prod_support": "prodsupport-cards@example.com",
            "sre": "sre-streaming@example.com",
            "on_call": "pager:cards-oncall / #inc-cards",
        },
    },
    "topic:atm.withdrawals": {
        "business_services": ["ATM Services"],
        "business_impact": "Withdrawal retractions/reversals; customer cash disputes",
        "criticality_tier": 1,
        "stakeholders": {
            "app_owner": "atm-app-owner@example.com",
            "business_owner": "atm-biz-owner@example.com",
            "prod_support": "prodsupport-atm@example.com",
            "sre": "sre-streaming@example.com",
            "on_call": "pager:atm-oncall / #inc-atm",
        },
    },
    "consumer_group:fraud.scoring": {
        "business_services": ["Fraud Detection"],
        "business_impact": "Fraud scoring delayed; potential unscored fraud exposure in ATM/card transactions",
        "criticality_tier": 1,
        "stakeholders": {
            "app_owner": "fraud-app-owner@example.com",
            "business_owner": "fraud-biz-owner@example.com",
            "prod_support": "prodsupport-fraud@example.com",
            "sre": "sre-ml@example.com",
            "on_call": "pager:fraud-oncall / #inc-fraud",
        },
    },
    "topic:trades.execution": {
        "business_services": ["Trading / Markets"],
        "business_impact": "Trade transactions delayed; order capture gaps; market risk",
        "criticality_tier": 1,
        "stakeholders": {
            "app_owner": "trades-app-owner@example.com",
            "business_owner": "trades-biz-owner@example.com",
            "prod_support": "prodsupport-trades@example.com",
            "sre": "sre-streaming@example.com",
            "on_call": "pager:trades-oncall / #inc-trades",
        },
    },
    "connector:crm.sink": {
        "business_services": ["Customer Notifications"],
        "business_impact": "Customer notifications delayed; reduced service quality",
        "criticality_tier": 2,
        "stakeholders": {
            "app_owner": "crm-app-owner@example.com",
            "business_owner": "crm-biz-owner@example.com",
            "prod_support": "prodsupport-crm@example.com",
            "sre": "sre-integration@example.com",
            "on_call": "#inc-notifications",
        },
    },
}

# Keyword -> intent, for free-text questions. Pure substring matching.
# LIMITATION BY DESIGN: brittle. "lag" matches, "falling behind" does not.
INTENT_KEYWORDS: dict[str, list[str]] = {
    "triage_signal": ["lag", "noise", "real incident", "anomaly", "actionable"],
    "ask_severity": ["severity", "how bad", "p1", "p2", "priority", "impact"],
    "ask_rca": ["root cause", "why", "cause", "rca", "diagnose"],
    "ask_stakeholders": ["who", "notify", "contact", "stakeholder", "page", "alert"],
    "ask_recovery": ["recovered", "resolved", "closed", "back to normal", "recovery"],
}
