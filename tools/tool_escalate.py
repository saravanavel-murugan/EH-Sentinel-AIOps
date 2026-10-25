"""Escalation/notify tool (Phase 5): approval-gated, dry-run stakeholder notify.

Resolves recipients ONLY from the approved entity table (same source A7 uses) and
produces a notification PLAN. It never actually sends: it is a dry-run that always
returns delivery_status='not_sent' and requires_approval=True. This models the
Phase 1 safety posture (recipients never guessed; no action without approval).
"""

from __future__ import annotations

from typing import Any

from .tool_registry import Tool, ToolError, ToolParam


def escalate(entity_id: str, severity: str, message: str) -> dict[str, Any]:
    """Build an approval-gated, dry-run notification plan for an entity's stakeholders."""
    from agent.baseline_data import ENTITY_TABLE

    info = ENTITY_TABLE.get(entity_id)
    if info is None:
        # Tolerate a missing 'type:' prefix by matching on the id suffix.
        for key, val in ENTITY_TABLE.items():
            if key.split(":", 1)[-1] == entity_id:
                info, entity_id = val, key
                break
    if info is None:
        # Never guess recipients; escalate to a human instead.
        return {
            "entity_id": entity_id,
            "recipients": {},
            "channel": None,
            "delivery_status": "not_sent",
            "requires_approval": True,
            "escalation_reason": f"entity '{entity_id}' not in approved directory; "
                                 f"no recipients resolved - escalate to a human.",
        }

    sev = (severity or "").upper()
    channel = "page" if sev in ("P1", "P2") else "ticket"
    return {
        "entity_id": entity_id,
        "recipients": info["stakeholders"],
        "channel": channel,
        "message": message,
        "delivery_status": "not_sent",      # dry-run: never actually delivered
        "requires_approval": True,          # human approval required before any send
        "note": "DRY-RUN notification plan; no message was sent.",
    }


ESCALATE_TOOL = Tool(
    name="escalate_incident",
    description="Build an approval-gated, DRY-RUN notification plan for an entity's stakeholders "
                "(resolved from the approved directory). Use when the operator asks who to notify "
                "or to escalate. Never actually sends.",
    parameters=[
        ToolParam("entity_id", "string", required=True, description="e.g. topic:payments.settlement"),
        ToolParam("severity", "string", required=True, description="P1|P2|P3|P4"),
        ToolParam("message", "string", required=True, description="short incident message"),
    ],
    fn=escalate,
    requires_approval=True,   # guardrail: this tool's output must be human-approved to act on
    read_only=False,
)
