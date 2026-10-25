"""Typed output contracts for the Phase 3 LLM triage agent.

These Pydantic models validate the LLM's JSON output. Invalid or partial output
is tolerated with safe defaults rather than crashing (Phase 1 resilience: degrade
gracefully, state uncertainty). The schema mirrors the agent output fields in
``docs/outputs.md`` (A1-A7 flavour) but condensed for the single-signal triage.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Hypothesis(BaseModel):
    cause: str = ""
    evidence_for: str = ""
    evidence_against: str = ""
    confidence: str = ""
    next_check: str = ""


class TriageResult(BaseModel):
    """Validated triage output. All fields optional so partial LLM output parses."""

    classification: str = "insufficient_evidence"
    severity: Optional[str] = None
    severity_rationale: Optional[str] = None
    affected_services: list[str] = Field(default_factory=list)
    business_impact: Optional[str] = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    next_check: Optional[str] = None
    recommended_recipients: dict[str, str] = Field(default_factory=dict)
    uncertainty: str = ""
    summary: str = ""
    requires_human_approval_for_actions: bool = True

    def completeness_score(self) -> int:
        """Count populated high-value fields (0-6). Used by the comparison harness
        as a coarse proxy for response quality: more grounded detail = higher."""
        score = 0
        if self.classification and self.classification != "insufficient_evidence":
            score += 1
        if self.severity:
            score += 1
        if self.business_impact:
            score += 1
        if self.hypotheses:
            score += 1
        if self.next_check:
            score += 1
        if self.uncertainty:
            score += 1
        return score
