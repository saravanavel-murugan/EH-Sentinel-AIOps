"""Template-based response rendering for the Phase 2 baseline agent.

Responses are built from fixed string templates. There is no natural-language
generation; the agent only fills slots. This keeps the baseline transparent and
makes its limitations obvious (rigid phrasing, no nuance, no synthesis).
"""

from __future__ import annotations

from typing import Any

UNKNOWN_INTENT = (
    "I could not match your question to a known baseline intent.\n"
    "Baseline supports only: triage a signal, ask severity, ask root cause, "
    "ask stakeholders, ask recovery.\n"
    "Try rephrasing with explicit keywords (e.g., 'severity', 'who to notify')."
)

UNKNOWN_ENTITY = (
    "Entity '{key}' is not in the baseline lookup table.\n"
    "Baseline cannot determine business impact or stakeholders for it.\n"
    "(A real system would resolve this against the CMDB / service catalogue.)"
)

RCA_TEMPLATE = (
    "Baseline root-cause support is not available.\n"
    "This version has no evidence retrieval or hypothesis reasoning.\n"
    "Suggested manual next step: inspect metrics/logs for '{metric}' on "
    "'{entity}' and correlate with recent deployments."
)


def render_signal_triage(signal: dict[str, Any], classification: dict[str, Any],
                         entity_info: dict[str, Any] | None,
                         severity: dict[str, Any] | None,
                         entity_key_str: str | None) -> str:
    """Render the full triage summary for a normalized signal."""
    lines: list[str] = []
    lines.append("=== BASELINE TRIAGE (rules/template only) ===")
    lines.append(f"Entity        : {entity_key_str or 'unknown'}")
    lines.append(f"Metric/Event  : {signal.get('metric_or_event', 'n/a')}")
    lines.append(f"Value         : {signal.get('value', 'n/a')} {signal.get('unit', '')}".rstrip())
    lines.append(f"Environment   : {signal.get('environment', 'n/a')}")
    lines.append("")
    lines.append(f"Classification: {classification['classification']}")
    lines.append(f"  reason      : {classification['reason']}")

    if entity_info is None:
        lines.append("")
        lines.append(UNKNOWN_ENTITY.format(key=entity_key_str or "n/a"))
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Severity      : {severity['severity']}")
    lines.append(f"  rationale   : {severity['rationale']}")
    lines.append(f"  confidence  : {severity['confidence']}")
    lines.append("")
    lines.append(f"Business svc  : {', '.join(entity_info['business_services'])}")
    lines.append(f"Business impact: {entity_info['business_impact']}")
    lines.append(f"Criticality   : Tier {entity_info['criticality_tier']}")
    lines.append("")
    lines.append("Notify (static lookup):")
    for role, contact in entity_info["stakeholders"].items():
        lines.append(f"  - {role:13s}: {contact}")
    lines.append("")
    lines.append("NOTE: advisory only. Baseline cannot act, correlate, or verify recovery.")
    return "\n".join(lines)


def render_text_answer(intent: str, text: str) -> str:
    """Render a response to a free-text question based on matched intent."""
    if intent == "unknown":
        return UNKNOWN_INTENT
    if intent == "triage_signal":
        return (
            "To triage a signal, pass a normalized-signal JSON (see docs/inputs.md).\n"
            "Baseline free-text mode cannot infer the signal values from prose."
        )
    if intent == "ask_severity":
        return (
            "Baseline severity needs a signal's entity + metric + value as JSON.\n"
            "It then applies a static criticality x classification matrix."
        )
    if intent == "ask_rca":
        return RCA_TEMPLATE.format(metric="<metric>", entity="<entity>")
    if intent == "ask_stakeholders":
        return (
            "Baseline resolves stakeholders only from a small static table keyed by "
            "'type:id' (e.g., 'topic:payments.settlement'). Provide the exact entity."
        )
    if intent == "ask_recovery":
        return (
            "Baseline has no recovery verification. It cannot tell whether an incident "
            "actually recovered; it only sees one input at a time."
        )
    return UNKNOWN_INTENT
