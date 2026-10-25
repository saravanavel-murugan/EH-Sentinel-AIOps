"""Typed output contracts for the A1-A8 multi-agent pipeline.

One Pydantic model per agent, mirroring requirements section 7 (Agent
specifications: Inputs / Responsibilities / Outputs / Guardrails). All fields are
optional with safe defaults so partial LLM output parses rather than crashes
(Phase 1 resilience principle). These are the typed contracts passed between
nodes in the LangGraph orchestrator.
"""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator


# A1 — Signal Validation / Anomaly Triage
class A1Output(BaseModel):
    classification: str = "insufficient_evidence"  # confirmed|likely|transient|noise|insufficient_evidence
    anomaly_score: float = 0.0
    evidence_refs: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    rationale: str = ""
    recommended_next_query: Optional[str] = None


# A2 — Correlation & Topology
class A2Output(BaseModel):
    incident_candidate_id: str = ""
    correlated_signal_ids: list[str] = Field(default_factory=list)
    dependency_path: list[str] = Field(default_factory=list)
    correlation_rationale: str = ""


# A3 — Severity & Business Impact
class A3Output(BaseModel):
    severity: Optional[str] = None  # P1|P2|P3|P4
    impact: Optional[str] = None
    affected_services: list[str] = Field(default_factory=list)
    confidence: str = ""
    rationale: str = ""
    escalation_deadline: Optional[str] = None
    review_required: bool = False

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Union[str, float, int, None]) -> str:
        return "" if v is None else str(v)


# A4 — Root-Cause Hypothesis
class Hypothesis(BaseModel):
    rank: int = 0
    cause: str = ""
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    # Models return confidence as "medium" OR 0.7; accept both, store as string.
    confidence: str = ""
    next_check: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Union[str, float, int, None]) -> str:
        return "" if v is None else str(v)


class A4Output(BaseModel):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    observed_facts: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    # Provenance: were the hypotheses grounded in retrieved runbooks/FAQ
    # ("knowledge_base") or inferred by the LLM from Kafka domain reasoning when
    # no relevant knowledge was found ("llm_inference")?
    analysis_source: str = "knowledge_base"


# A5 — Remediation Recommendation
class RemediationAction(BaseModel):
    action: str = ""
    purpose: str = ""
    expected_effect: str = ""
    risk: str = ""
    preconditions: list[str] = Field(default_factory=list)
    owner: str = ""
    verification: str = ""
    rollback: str = ""
    requires_approval: bool = True


class A5Output(BaseModel):
    actions: list[RemediationAction] = Field(default_factory=list)
    read_only: bool = True
    # Provenance: remediation drawn from an approved runbook ("knowledge_base")
    # or inferred by the LLM when no runbook matched ("llm_inference").
    analysis_source: str = "knowledge_base"


# A6 — Incident Summary & Ticket (consolidated 7-section record)
class A6Output(BaseModel):
    incident_id: str = ""
    idempotency_key: str = ""
    summary: str = ""
    # --- the 7 consolidated sections ---
    issue: str = ""                                     # 1. actual issue from the signal
    root_cause: str = ""                                # 2. RCA (from A4)
    correlation: str = ""                               # 3. correlation, if any (from A2)
    severity: Optional[str] = None                      # 4. priority/severity (from A3)
    severity_rationale: str = ""
    remediation: list[str] = Field(default_factory=list)  # 5. recommendation (from A5)
    business_impact: str = ""                            # 6. business impact (from A3/entity table)
    stakeholders: dict[str, str] = Field(default_factory=dict)  # 7. who to notify (entity table)
    # --- supporting ---
    timeline: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    # Knowledge-base documents (runbooks/FAQ/policy/past incidents) that grounded
    # the RCA/remediation, as "source :: heading (score)" citations (Phase 4 RAG).
    knowledge_references: list[str] = Field(default_factory=list)
    ticket_payload: dict = Field(default_factory=dict)
    # Full human-readable record used when the incident is closed to knowledge.
    closure_document: str = ""


# A7 — Stakeholder Communication & Escalation
class A7Output(BaseModel):
    recipients_by_role: dict[str, str] = Field(default_factory=dict)
    message: str = ""
    channel: str = ""
    escalation_reason: Optional[str] = None
    delivery_status: str = "not_sent"  # advisory; never claim delivered without a tool result


# A8 — Recovery Verification & Feedback
class A8Output(BaseModel):
    recovery_status: str = "monitoring"  # recovered|monitoring|not_recovered|worsening
    metrics_before_after: dict = Field(default_factory=dict)
    closure_recommendation: str = "continue_monitoring"  # close|continue_monitoring|escalate
    feedback_record: dict = Field(default_factory=dict)


# Convenience registry for parsing by agent id.
AGENT_OUTPUT_MODELS = {
    "A1": A1Output,
    "A2": A2Output,
    "A3": A3Output,
    "A4": A4Output,
    "A5": A5Output,
    "A6": A6Output,
    "A7": A7Output,
    "A8": A8Output,
}

AGENT_NAMES = {
    "A1": "Signal Validation / Anomaly Triage",
    "A2": "Correlation & Topology",
    "A3": "Severity & Business Impact",
    "A4": "Root-Cause Hypothesis",
    "A5": "Remediation Recommendation",
    "A6": "Incident Summary & Ticket",
    "A7": "Stakeholder Communication & Escalation",
    "A8": "Recovery Verification & Feedback",
}
