"""Phase 6 — SentinelSession: planning + memory + multi-turn orchestration.

This is the Phase 6 layer that sits ON TOP OF the existing, unchanged pieces:

    * MultiAgentSentinel (A1-A8 LangGraph pipeline)   — Phase 3b, unchanged
    * ToolAgent (allow-listed tools over MCP/registry) — Phase 5, unchanged

What Phase 6 adds:

    1. PLANNING — every signal is decomposed into an explicit IncidentPlan whose
       steps are marked running/done/skipped as the A1-A8 pipeline executes, so
       the multi-step reasoning is inspectable end to end (signal -> closure).

    2. MEMORY — a short-term ConversationMemory (turns + working set within the
       session) and a long-term IncidentMemoryStore (incidents persisted across
       sessions). Before triaging, the session RECALLS prior incidents for the
       entity (recurrence awareness); after closing, it PERSISTS the record.

    3. MULTI-TURN — one session handles a sequence of turns. A turn may be a
       normalized-signal JSON (full incident pipeline) OR a free-text operator
       follow-up (answered from memory + the Phase 5 ToolAgent). Context carries
       across turns (the "current entity/incident in focus").

    4. ADAPTIVE BEHAVIOUR (Phase 7) — the session accepts non-sensitive operator
       feedback (FeedbackStore) and, before rendering a signal turn, consults a
       deterministic AdaptationPolicy for the entity. Derived adjustments change
       only how the response is PRESENTED (an advisory severity nudge, a concise
       render, a stronger recurrence banner) and are always explained in an
       ADAPTATION section. With NO feedback on record, behaviour is identical to
       Phase 6.

The session never performs real production actions: everything inherits the
read-only / human-approval guardrails of the underlying agents. Adaptation is
advisory only and NEVER weakens the safety posture.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Optional

from ..core_agent import BaselineAgent
from ..guardrails import SCOPE_OUT, classify_scope
from ..observability import mask_pii
from .feedback import AdaptationPolicy, BehaviorProfile, FeedbackRecord, FeedbackStore
from .memory import ConversationMemory, IncidentMemoryStore, IncidentRecord
from .planner import IncidentPlan

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MEMORY_PATH = _REPO_ROOT / "logs" / "incident_memory.json"
_DEFAULT_FEEDBACK_PATH = _REPO_ROOT / "logs" / "feedback.json"


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class SentinelSession:
    """A stateful, multi-turn conversation over the Sentinel multi-agent system.

    Construct once per operator conversation. Call ``handle_turn`` for each input;
    the session keeps short-term state and reads/writes long-term incident memory.
    """

    version = "phase7-session-0.1.0"

    def __init__(
        self,
        chat_model: Any = None,
        use_retrieval: bool = True,
        memory_path: Path | str | None = None,
        max_turns: int = 20,
        max_records: int = 200,
        multi_agent: Any = None,
        tool_agent: Any = None,
        feedback_path: Path | str | None = None,
    ):
        # Reuse the existing agents unchanged. Import lazily so Phase 2 stays
        # LLM-free and tests can inject fakes.
        from ..agents import MultiAgentSentinel
        from ..llm import provider_name
        from ..tool_agent import ToolAgent

        self.provider = provider_name()
        self._ma = multi_agent or MultiAgentSentinel(
            chat_model=chat_model, use_retrieval=use_retrieval
        )
        self._tools = tool_agent or ToolAgent(chat_model=chat_model)
        self.retrieval_enabled = getattr(self._ma, "retrieval_enabled", False)

        self.conversation = ConversationMemory(max_turns=max_turns)
        self.memory = IncidentMemoryStore(
            memory_path or _DEFAULT_MEMORY_PATH, max_records=max_records
        )
        # Phase 7 — feedback store + deterministic adaptation policy (advisory).
        self.feedback = FeedbackStore(feedback_path or _DEFAULT_FEEDBACK_PATH)
        self.adaptation = AdaptationPolicy(self.feedback)
        self.started_at = _utc_now()

    # ----------------------------------------------------------------------
    # Public entry point
    # ----------------------------------------------------------------------

    def handle_turn(self, user_input: str) -> dict[str, Any]:
        """Route one turn: signal JSON -> full pipeline; free text -> follow-up.

        Canonical sequence: reset is matched on the RAW text (the three reset
        phrases carry no PII and masking must not change reset detection). For
        every non-reset turn, ``text = mask_pii(raw)`` is the SINGLE value used
        downstream — stored, scope-classified, signal-parsed, and routed — so
        raw operator PII never reaches memory, the classifier, the pipeline, or
        the tools. An out_of_scope turn is refused and NEVER reaches the A1-A8
        pipeline or the ToolAgent; needs_clarification and in_scope fall through.
        """
        raw = (user_input or "").strip()

        if raw.lower() in {"reset", "/reset", "new incident"}:
            self.conversation.add_turn("user", raw)   # reset words carry no PII
            return self._handle_reset()

        # R2 — input masking is the single source of truth from here on.
        text = mask_pii(raw)
        self.conversation.add_turn("user", text)       # store MASKED user text only

        # R1 — domain-scope guardrail, on the masked text.
        scope, reason = classify_scope(text)
        if scope == SCOPE_OUT:
            return self._handle_out_of_scope(text, reason)

        signal = BaselineAgent._try_parse_signal(text)
        if signal is not None:
            return self._handle_signal_turn(signal)
        return self._handle_followup_turn(text)

    # ----------------------------------------------------------------------
    # Out-of-scope turn: refuse WITHOUT reaching the pipeline or tools
    # ----------------------------------------------------------------------

    def _handle_out_of_scope(self, text: str, reason: str) -> dict[str, Any]:
        """Refuse an out-of-scope turn with a friendly advisory.

        Returns the standard turn-dict shape (``kind`` + ``response`` keys) so
        the UI and ``safe_handle_turn`` treat it like any other turn. Does NOT
        construct an IncidentPlan, call ``self._ma.run_signal``, or touch
        ``self._tools`` — so A1-A8 and the ToolAgent are never reached.
        """
        advisory = (
            "I can only help with Confluent Kafka / cluster / infrastructure or "
            "business-impact incident questions (brokers, partitions, consumer "
            "lag, schema registry, connectors, severity/triage, escalation).\n"
            "Example in-scope request: \"why is consumer lag rising on "
            "topic:payments.settlement\".\n"
            "Please rephrase your question in those terms, or paste a normalized "
            "signal JSON to start an incident triage."
        )
        response = mask_pii(advisory)               # mask once, before both sinks
        self.conversation.add_turn("agent", response, meta={"kind": "refused"})
        return {
            "kind": "refused",
            "turn": self.conversation.turn_count,
            "provider": self.provider,
            "scope": "out_of_scope",
            "reason": reason,
            "response": response,
        }

    # ----------------------------------------------------------------------
    # Signal turn: plan + A1-A8 + memory, with full end-to-end trace
    # ----------------------------------------------------------------------

    def _handle_signal_turn(self, signal: dict[str, Any]) -> dict[str, Any]:
        plan = IncidentPlan.build_default(signal)
        entity = self._entity_key(signal)
        metric = signal.get("metric_or_event", "n/a")

        # --- STEP: recall prior context (long-term memory) ---
        plan.start("recall")
        prior = self.memory.for_entity(entity)
        recurrence = self.memory.recurrence_count(entity, metric)
        if prior:
            last = prior[0]
            plan.complete(
                "recall",
                f"{recurrence} prior incident(s) for {entity}; last was "
                f"{last.incident_id} ({last.severity}).",
            )
        else:
            plan.complete("recall", f"no prior incidents for {entity}.")

        # --- STEPS A1-A8: run the unchanged multi-agent pipeline ---
        # The pipeline runs as one bounded graph; we reflect its outcome onto the
        # plan steps (the orchestrator itself is not modified).
        for aid in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
            plan.start(aid)
        result = self._ma.run_signal(signal)
        trace = result.get("trace", []) or []
        agents = result.get("agents", {}) or {}
        gated = bool(result.get("stop_reason"))

        self._reflect_pipeline_on_plan(plan, trace, agents, gated,
                                       result.get("stop_reason"))

        # --- STEP: persist to long-term memory ---
        record: Optional[IncidentRecord] = None
        if not gated:
            record = self._persist_incident(result, entity, metric)
            plan.complete(
                "persist",
                f"stored {record.incident_id} (now {self.memory.recurrence_count(entity, metric)} "
                f"for {entity}/{metric}).",
            )
        else:
            plan.skip("persist", "gated at A1 (watch state) — nothing to persist.")

        # --- update short-term working set (carries across turns) ---
        self.conversation.remember("current_entity", entity)
        self.conversation.remember("current_metric", metric)
        if record is not None:
            self.conversation.remember("current_incident_id", record.incident_id)

        # --- Phase 7: derive advisory adaptation from accumulated feedback ---
        # With no feedback on record, the profile has nothing applied and the
        # render path is byte-for-byte identical to Phase 6.
        profile = self.adaptation.derive(entity, recurrence)

        # R2 — mask once, before BOTH sinks (stored turn + returned dict).
        response = mask_pii(self._render_signal_turn(result, plan, prior,
                                                     recurrence, profile))
        self.conversation.add_turn("agent", response,
                                   meta={"kind": "signal", "entity": entity,
                                         "trace": trace})

        return {
            "kind": "signal",
            "turn": self.conversation.turn_count,
            "provider": self.provider,
            "entity": entity,
            "entity_known": result.get("entity_known"),
            "recurrence_count": recurrence,
            "gated": gated,
            "stop_reason": result.get("stop_reason"),
            "trace": trace,
            "plan": plan.to_dict(),
            "retrieval": result.get("retrieval", {}),
            "agents": agents,
            "incident_id": record.incident_id if record else None,
            "pipeline_response": result.get("response", ""),
            "adaptation": profile.to_dict(),
            "response": response,
        }

    def _reflect_pipeline_on_plan(self, plan: IncidentPlan, trace: list[str],
                                  agents: dict[str, Any], gated: bool,
                                  stop_reason: Optional[str]) -> None:
        """Mark plan steps done/skipped from the pipeline's actual trace."""
        for aid in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
            if aid in trace:
                plan.complete(aid, self._agent_summary(aid, agents))
        if gated:
            # A1 ran and gated; the rest did not execute.
            plan.complete("A1", self._agent_summary("A1", agents))
            for aid in ("A2", "A3", "A4", "A5", "A6", "A7", "A8"):
                if aid not in trace:
                    plan.skip(aid, stop_reason or "skipped (A1 gate).")

    @staticmethod
    def _agent_summary(aid: str, agents: dict[str, Any]) -> str:
        a = agents.get(aid.lower(), {}) or {}
        if aid == "A1":
            return f"classification={a.get('classification')} score={a.get('anomaly_score')}"
        if aid == "A2":
            return f"candidate={a.get('incident_candidate_id')}"
        if aid == "A3":
            return f"severity={a.get('severity')}"
        if aid == "A4":
            return f"{len(a.get('hypotheses', []) or [])} hypothesis(es)"
        if aid == "A5":
            return f"{len(a.get('actions', []) or [])} action(s), read_only={a.get('read_only')}"
        if aid == "A6":
            return f"incident_id={a.get('incident_id')}"
        if aid == "A7":
            return f"channel={a.get('channel')} delivery={a.get('delivery_status')}"
        if aid == "A8":
            return f"recovery={a.get('recovery_status')} closure={a.get('closure_recommendation')}"
        return ""

    def _persist_incident(self, result: dict[str, Any], entity: str,
                          metric: str) -> IncidentRecord:
        agents = result.get("agents", {}) or {}
        a1 = agents.get("a1", {}) or {}
        a3 = agents.get("a3", {}) or {}
        a6 = agents.get("a6", {}) or {}
        a8 = agents.get("a8", {}) or {}
        record = IncidentRecord(
            incident_id=a6.get("incident_id") or f"inc-{entity}",
            entity=entity,
            metric=metric,
            classification=a1.get("classification", ""),
            severity=a6.get("severity") or a3.get("severity"),
            summary=a6.get("summary") or a6.get("issue", ""),
            closure_recommendation=a8.get("closure_recommendation", "continue_monitoring"),
            knowledge_references=a6.get("knowledge_references", []) or [],
        )
        self.memory.add(record)
        return record

    # ----------------------------------------------------------------------
    # Free-text follow-up turn: answer from memory + Phase 5 tools
    # ----------------------------------------------------------------------

    def _handle_followup_turn(self, text: str) -> dict[str, Any]:
        entity = self.conversation.recall("current_entity")
        incident_id = self.conversation.recall("current_incident_id")

        # Memory-grounded context about what we've already done this session.
        memory_note = self._memory_note(entity)

        # Let the Phase 5 ToolAgent handle the operator's follow-up (metric
        # lookup / knowledge search / escalation) with its own guardrails.
        tool_out = self._tools.handle(text)

        # R2 — mask once, before BOTH sinks (stored turn + returned dict).
        response = mask_pii(self._render_followup(text, memory_note, tool_out))
        self.conversation.add_turn("agent", response,
                                   meta={"kind": "followup",
                                         "entity": entity,
                                         "tools": tool_out.get("n_steps")})

        return {
            "kind": "followup",
            "turn": self.conversation.turn_count,
            "provider": self.provider,
            "focus_entity": entity,
            "focus_incident": incident_id,
            "memory_note": memory_note,
            "tool_transport": tool_out.get("transport"),
            "tool_steps": tool_out.get("steps", []),
            "tool_response": tool_out.get("response", ""),
            "response": response,
        }

    def _memory_note(self, entity: Optional[str]) -> str:
        if not entity:
            return "No incident is in focus yet this session. Paste a signal JSON to start."
        prior = self.memory.for_entity(entity)
        if not prior:
            return f"In focus: {entity}. No incidents recorded for it yet."
        last = prior[0]
        return (f"In focus: {entity}. {len(prior)} incident(s) on record; most "
                f"recent {last.incident_id} — {last.severity}, "
                f"closure: {last.closure_recommendation}.")

    # ----------------------------------------------------------------------
    # Reset: short-term only (long-term memory is retained by design)
    # ----------------------------------------------------------------------

    def _handle_reset(self) -> dict[str, Any]:
        kept = self.memory.count
        self.conversation.reset()
        response = (
            "Short-term conversation reset. Starting a fresh conversation.\n"
            f"Long-term incident memory RETAINED ({kept} record(s)); use "
            "clear_long_term_memory() to forget those too."
        )
        # Record the reset as the first turn of the new conversation.
        self.conversation.add_turn("system", response, meta={"kind": "reset"})
        return {
            "kind": "reset",
            "turn": self.conversation.turn_count,
            "long_term_retained": kept,
            "response": response,
        }

    def clear_long_term_memory(self) -> int:
        """Explicit forget-all for durable memory. Returns how many were cleared."""
        n = self.memory.count
        self.memory.reset()
        return n

    # ----------------------------------------------------------------------
    # Phase 7 — feedback intake + explicit forget-all
    # ----------------------------------------------------------------------

    def record_feedback(
        self,
        *,
        signal: str = "down",
        category: str = "other",
        rating: Optional[int] = None,
        note: str = "",
        entity: Optional[str] = None,
        incident_id: Optional[str] = None,
        metric: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit non-sensitive operator feedback for the in-focus incident.

        Defaults for entity/incident/metric come from the short-term working set
        (the incident currently in focus this session). Stores ONLY the
        non-sensitive fields below — never a secret or PII. Returns a small dict
        describing what was recorded.
        """
        entity = entity or self.conversation.recall("current_entity")
        incident_id = incident_id or self.conversation.recall("current_incident_id") or ""
        metric = metric or self.conversation.recall("current_metric") or "n/a"

        if not entity:
            msg = ("No incident is in focus yet this session — run a signal turn "
                   "first, or pass entity=... explicitly.")
            self.conversation.add_turn("system", msg, meta={"kind": "feedback_rejected"})
            return {"kind": "feedback", "recorded": False, "reason": msg}

        record = FeedbackRecord(
            feedback_id=f"fb-{self.feedback.count + 1}",
            entity=entity,
            metric=metric,
            incident_id=incident_id,
            signal=signal,
            rating=rating,
            category=category,
            note=note,
        )
        self.feedback.add(record)

        summary = (f"Feedback {record.feedback_id} recorded for {entity} "
                   f"(category={category}, negative={record.is_negative()}).")
        self.conversation.add_turn("system", summary, meta={"kind": "feedback"})
        return {
            "kind": "feedback",
            "recorded": True,
            "feedback_id": record.feedback_id,
            "entity": entity,
            "incident_id": incident_id,
            "category": category,
            "negative": record.is_negative(),
            "count_for_entity": len(self.feedback.for_entity(entity)),
        }

    def clear_feedback(self) -> int:
        """Explicit forget-all for operator feedback. Returns how many were cleared.

        Note: a ``reset`` turn clears SHORT-TERM state only and RETAINS feedback;
        this method is the deliberate, explicit control to forget feedback too.
        """
        n = self.feedback.count
        self.feedback.reset()
        return n

    # ----------------------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------------------

    def _render_signal_turn(self, result: dict[str, Any], plan: IncidentPlan,
                            prior: list[IncidentRecord], recurrence: int,
                            profile: Optional[BehaviorProfile] = None) -> str:
        """Render a signal turn.

        When ``profile`` is None or nothing is applied, rendering is IDENTICAL
        to Phase 6. When adjustments are applied they only change PRESENTATION:
        a stronger recurrence banner, a concise body, and/or an advisory
        severity nudge — always followed by an ADAPTATION (advisory) section
        that explains every change. The safety NOTE and escalation info are
        never removed.
        """
        applied = profile is not None and profile.any_applied()
        entity = result.get("entity")
        lines = ["=== SENTINEL SESSION — SIGNAL (end-to-end) ==="]
        lines.append(f"Turn   : {self.conversation.turn_count}  ·  provider: {self.provider}")
        lines.append(f"Entity : {entity} (known={result.get('entity_known')})")

        # --- Memory / recurrence banner (adjustment #3 may strengthen it) ---
        if recurrence:
            last = prior[0]
            if applied and profile.recurrence_emphasis:
                lines.append(f"Memory : (!) RECURRING + prior negative operator feedback — "
                             f"{recurrence} prior incident(s); last {last.incident_id} "
                             f"({last.severity}). Operators previously flagged this entity.")
            else:
                lines.append(f"Memory : RECURRING — {recurrence} prior incident(s); "
                             f"last {last.incident_id} ({last.severity}).")
        else:
            lines.append("Memory : first time this entity is seen (no prior incidents).")
        lines.append("")
        lines.append(plan.render())
        lines.append("")

        # --- Body: full pipeline output, or a concise summary (adjustment #2) ---
        if applied and profile.concise:
            lines.append("--- Multi-agent pipeline output (concise) ---")
            lines.extend(self._concise_pipeline_lines(result))
        else:
            lines.append("--- Multi-agent pipeline output ---")
            lines.append(result.get("response", ""))

        # --- ADAPTATION (advisory) section — explains every applied change ---
        if applied:
            lines.append("")
            lines.append("--- ADAPTATION (advisory) ---")
            if profile.severity_nudge:
                a3 = (result.get("agents", {}) or {}).get("a3", {}) or {}
                lines.append(
                    f"Severity nudge: A3 assessed severity={a3.get('severity')} "
                    f"(UNCHANGED). Feedback-informed recommendation: consider whether "
                    f"a higher severity is warranted."
                )
            for note in profile.explanations:
                lines.append(f"- {note}")
            lines.append("NOTE: adaptation is advisory only; it changes presentation "
                         "and never alters A1-A8 decisions, approval requirements, or "
                         "escalation.")
        return "\n".join(lines)

    @staticmethod
    def _concise_pipeline_lines(result: dict[str, Any]) -> list[str]:
        """A trimmed pipeline summary that ALWAYS preserves the safety/escalation
        lines. Used only when the concise adjustment is applied."""
        agents = result.get("agents", {}) or {}
        a1 = agents.get("a1", {}) or {}
        a3 = agents.get("a3", {}) or {}
        a5 = agents.get("a5", {}) or {}
        a7 = agents.get("a7", {}) or {}
        a8 = agents.get("a8", {}) or {}
        out: list[str] = []
        out.append(f"[A1] classification={a1.get('classification')}")
        out.append(f"[A3] severity={a3.get('severity')} "
                   f"review_required={a3.get('review_required')}")
        out.append(f"[A5] {len(a5.get('actions', []) or [])} action(s), "
                   f"read_only={a5.get('read_only')} "
                   f"(all require approval)")
        if a7:
            out.append(f"[A7] channel={a7.get('channel')} "
                       f"escalation_reason={a7.get('escalation_reason')} "
                       f"delivery={a7.get('delivery_status')}")
        out.append(f"[A8] closure={a8.get('closure_recommendation')}")
        # Safety line is always preserved, even in concise mode.
        out.append("NOTE: advisory only; production actions require human approval.")
        return out

    def _render_followup(self, text: str, memory_note: str,
                         tool_out: dict[str, Any]) -> str:
        lines = ["=== SENTINEL SESSION — FOLLOW-UP ==="]
        lines.append(f"Turn   : {self.conversation.turn_count}  ·  provider: {self.provider}")
        lines.append(f"Memory : {memory_note}")
        lines.append("")
        lines.append(tool_out.get("response", "(no tool output)"))
        return "\n".join(lines)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def _entity_key(signal: dict[str, Any]) -> str:
        entity = signal.get("entity", {}) or {}
        return f"{entity.get('type', 'n/a')}:{entity.get('id', 'n/a')}"

    def snapshot(self) -> dict[str, Any]:
        """A JSON-serializable view of the whole session (for UI/trace/debug)."""
        return {
            "version": self.version,
            "provider": self.provider,
            "started_at": self.started_at,
            "retrieval_enabled": self.retrieval_enabled,
            "conversation": self.conversation.to_dict(),
            "long_term_memory": {
                "count": self.memory.count,
                "records": [r.to_dict() for r in self.memory.all()],
            },
            "feedback": {
                "count": self.feedback.count,
                "category_counts": self.feedback.category_counts(),
                "records": [r.to_dict() for r in self.feedback.all()],
            },
        }
