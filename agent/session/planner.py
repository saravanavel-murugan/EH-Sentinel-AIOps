"""Phase 6 — Planning / task decomposition for the Sentinel incident workflow.

Phases 1-5 wired the *mechanics* (rules, LLM, RAG, tools, MCP, A1-A8). What was
missing was an explicit, inspectable PLAN: the agent decomposing an incident into
ordered steps, tracking each step's status as it executes, and exposing that plan
so a human can follow the multi-step reasoning end to end.

This module is deliberately deterministic. The *reasoning inside* each step is
done by the A1-A8 LLM nodes (unchanged); the plan is the scaffolding around them.
Keeping decomposition deterministic means the end-to-end trace is reproducible
offline and the plan can never "hallucinate" a step that the pipeline does not
actually run.

A plan is a list of ``PlanStep``s. Each step maps to a stage of the incident
lifecycle (triage -> correlate -> ... -> closure) and carries:
  * a stable ``key`` (used to update status by name),
  * a human ``title`` and ``detail``,
  * the owning agent id (A1..A8) or ``tool`` / ``memory`` for non-agent steps,
  * a ``status`` that advances pending -> running -> done | skipped | failed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Lifecycle status values a step can hold.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"

_TERMINAL = {DONE, SKIPPED, FAILED}


@dataclass
class PlanStep:
    """One decomposed task in the incident plan."""

    key: str
    title: str
    detail: str
    owner: str  # agent id (A1..A8) | "tool" | "memory" | "gate"
    status: str = PENDING
    result_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IncidentPlan:
    """An ordered, status-tracked decomposition of one incident's handling.

    The plan is built once (``build_default``) from the signal, then mutated as
    the session executes each stage (``start`` / ``complete`` / ``skip`` /
    ``fail``). It is a plain object (no LLM) so the trace is deterministic.
    """

    def __init__(self, steps: list[PlanStep], objective: str = ""):
        self.objective = objective
        self.steps = steps
        self._by_key = {s.key: s for s in steps}

    # -- construction ------------------------------------------------------

    @classmethod
    def build_default(cls, signal: dict[str, Any]) -> "IncidentPlan":
        """Decompose a normalized signal into the standard A1-A8 + closure plan.

        The decomposition mirrors the orchestrator topology: validate (A1) gates
        the rest; if A1 keeps the signal, correlate/severity/RCA/remediation/
        record/notify/verify follow, then the incident is persisted to memory.
        """
        entity = signal.get("entity", {}) or {}
        ekey = f"{entity.get('type', 'n/a')}:{entity.get('id', 'n/a')}"
        metric = signal.get("metric_or_event", "n/a")
        objective = (
            f"Triage and (if actionable) drive {ekey} / {metric} from raw signal "
            f"to a consolidated, evidence-backed incident record and closure "
            f"recommendation — advisory only, human approval for any action."
        )
        steps = [
            PlanStep("recall", "Recall prior context",
                     "Check short-term conversation state and long-term incident "
                     "memory for this entity before triaging.", owner="memory"),
            PlanStep("A1", "Validate signal / triage anomaly",
                     "Classify the signal; gate out noise / insufficient evidence.",
                     owner="A1"),
            PlanStep("A2", "Correlate & map topology",
                     "Group with related signals; identify dependency path.",
                     owner="A2"),
            PlanStep("A3", "Assess severity & business impact",
                     "Assign P1-P4 and affected services from the grounded table.",
                     owner="A3"),
            PlanStep("A4", "Form root-cause hypotheses",
                     "Rank evidence-backed hypotheses (RAG-grounded when available).",
                     owner="A4"),
            PlanStep("A5", "Recommend remediation",
                     "Propose approval-gated, read-only remediation steps.",
                     owner="A5"),
            PlanStep("A6", "Consolidate incident record",
                     "Build the 7-section record + knowledge references.",
                     owner="A6"),
            PlanStep("A7", "Notify stakeholders",
                     "Resolve approved recipients; prepare communication.",
                     owner="A7"),
            PlanStep("A8", "Verify recovery",
                     "Assess recovery status and closure recommendation.",
                     owner="A8"),
            PlanStep("persist", "Persist incident to memory",
                     "Write the closure record to long-term memory for future "
                     "recall and recurrence detection.", owner="memory"),
        ]
        return cls(steps, objective=objective)

    # -- status transitions ------------------------------------------------

    def get(self, key: str) -> Optional[PlanStep]:
        return self._by_key.get(key)

    def start(self, key: str) -> None:
        step = self._by_key.get(key)
        if step and step.status not in _TERMINAL:
            step.status = RUNNING

    def complete(self, key: str, summary: str = "") -> None:
        self._set(key, DONE, summary)

    def skip(self, key: str, summary: str = "") -> None:
        self._set(key, SKIPPED, summary)

    def fail(self, key: str, summary: str = "") -> None:
        self._set(key, FAILED, summary)

    def skip_remaining(self, summary: str = "") -> None:
        """Mark every still-pending/running step as skipped (used when the A1
        gate stops the pipeline early)."""
        for step in self.steps:
            if step.status not in _TERMINAL:
                step.status = SKIPPED
                if summary:
                    step.result_summary = summary

    def _set(self, key: str, status: str, summary: str) -> None:
        step = self._by_key.get(key)
        if step is not None:
            step.status = status
            if summary:
                step.result_summary = summary

    # -- views -------------------------------------------------------------

    @property
    def completed(self) -> int:
        return sum(1 for s in self.steps if s.status == DONE)

    @property
    def total(self) -> int:
        return len(self.steps)

    def progress(self) -> str:
        return f"{self.completed}/{self.total} steps complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "progress": self.progress(),
            "steps": [s.to_dict() for s in self.steps],
        }

    def render(self) -> str:
        """Human-readable checklist with status glyphs for the trace/UI/CLI."""
        glyph = {PENDING: "[ ]", RUNNING: "[~]", DONE: "[x]",
                 SKIPPED: "[-]", FAILED: "[!]"}
        lines = [f"PLAN: {self.objective}", f"  ({self.progress()})"]
        for i, s in enumerate(self.steps, 1):
            line = f"  {glyph.get(s.status, '[ ]')} {i}. {s.title} ({s.owner})"
            if s.result_summary:
                line += f" — {s.result_summary}"
            lines.append(line)
        return "\n".join(lines)
