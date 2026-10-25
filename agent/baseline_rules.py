"""Baseline deterministic rules for the Phase 2 agent.

Pure rules/thresholds — NO LLM, NO retrieval, NO statistics. Every decision is a
simple comparison or substring match. This is intentionally naive so that Phase 2
can demonstrate the limitations that later phases fix.
"""

from __future__ import annotations

from typing import Any

from .baseline_data import (
    ENTITY_TABLE,
    INTENT_KEYWORDS,
    STATIC_THRESHOLDS,
)


def classify_intent(text: str) -> str:
    """Map a free-text question to an intent via substring keyword matching.

    Returns 'unknown' when no keyword matches (a deliberate baseline limitation).
    """
    lowered = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return intent
    return "unknown"


def entity_key(signal: dict[str, Any]) -> str | None:
    """Build the 'type:id' lookup key from a normalized signal's entity block."""
    entity = signal.get("entity") or {}
    etype = entity.get("type")
    eid = entity.get("id")
    if etype and eid:
        return f"{etype}:{eid}"
    return None


def lookup_entity(signal: dict[str, Any]) -> dict[str, Any] | None:
    """Naive exact-match lookup against the hard-coded ENTITY_TABLE.

    LIMITATION BY DESIGN: exact key match only. No fuzzy match, no topology,
    no resolution of parent cluster/broker. Unknown entity -> None.
    """
    key = entity_key(signal)
    if key is None:
        return None
    return ENTITY_TABLE.get(key)


def classify_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Classify a signal as confirmed/likely/transient/noise using a flat threshold.

    LIMITATION BY DESIGN: single global threshold per metric; no baseline
    deviation, no duration, no corroboration, no time-series.
    """
    metric = signal.get("metric_or_event", "")
    value = signal.get("value")
    threshold_cfg = STATIC_THRESHOLDS.get(metric)

    if threshold_cfg is None or not isinstance(value, (int, float)):
        return {
            "classification": "insufficient_evidence",
            "reason": f"No baseline rule for metric '{metric}' or non-numeric value.",
            "threshold_used": threshold_cfg,
        }

    threshold = float(threshold_cfg["value"])
    if value >= threshold * 2:
        classification = "confirmed"
    elif value >= threshold:
        classification = "likely"
    elif value >= threshold * 0.5:
        classification = "transient"
    else:
        classification = "noise"

    return {
        "classification": classification,
        "reason": f"value {value} vs static threshold {threshold} ({metric}).",
        "threshold_used": threshold,
    }


def estimate_severity(signal: dict[str, Any], entity_info: dict[str, Any] | None,
                      classification: str) -> dict[str, Any]:
    """Guess a P1-P4 severity from criticality tier + classification.

    LIMITATION BY DESIGN: a lookup-table cross of two coarse dimensions. No blast
    radius, no SLO breach, no duration, no confidence, no security weighting.
    """
    tier = entity_info["criticality_tier"] if entity_info else 3

    # Coarse matrix: tier (1-3) x classification.
    matrix = {
        ("confirmed", 1): "P1",
        ("confirmed", 2): "P2",
        ("confirmed", 3): "P3",
        ("likely", 1): "P2",
        ("likely", 2): "P3",
        ("likely", 3): "P3",
        ("transient", 1): "P3",
        ("transient", 2): "P4",
        ("transient", 3): "P4",
        ("noise", 1): "P4",
        ("noise", 2): "P4",
        ("noise", 3): "P4",
    }
    severity = matrix.get((classification, tier), "P4")
    return {
        "severity": severity,
        "rationale": f"criticality_tier={tier} x classification={classification} (static matrix).",
        "confidence": "n/a (baseline has no confidence model)",
    }
