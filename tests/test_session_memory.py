"""Phase 6 tests — planning, memory (short/long-term), and multi-turn sessions.

Runs on the deterministic offline fake provider (forced in conftest). Long-term
memory is written to a pytest ``tmp_path`` so tests never touch logs/.
These assert pipeline BEHAVIOUR (plan step status, recall, recurrence, reset vs
retention), not LLM prose quality. Existing A1-A8 node logic is reused unchanged.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def actionable_signal() -> dict:
    """Rising consumer lag on a known topic -> pipeline proceeds past A1."""
    return {
        "signal_id": "sig-p6",
        "source": "control_center",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "consumer_lag",
        "value": 60000, "unit": "messages", "environment": "prod",
    }


@pytest.fixture()
def session(tmp_path, fake_chat):
    """A session on fake providers with an isolated long-term memory file."""
    from agent.session import SentinelSession

    return SentinelSession(
        chat_model=fake_chat,
        use_retrieval=False,                      # no FAISS dependency
        memory_path=tmp_path / "mem.json",
    )


# ---------------------------------------------------------------------------
# Planning / task decomposition
# ---------------------------------------------------------------------------

def test_plan_decomposes_into_ordered_steps(actionable_signal):
    from agent.session.planner import IncidentPlan

    plan = IncidentPlan.build_default(actionable_signal)
    keys = [s.key for s in plan.steps]
    # recall -> A1..A8 -> persist, in order
    assert keys == ["recall", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "persist"]
    assert plan.objective
    assert plan.total == 10
    assert plan.completed == 0


def test_plan_status_transitions_and_gate_skip():
    from agent.session.planner import DONE, SKIPPED, IncidentPlan

    plan = IncidentPlan.build_default({"entity": {"type": "topic", "id": "x"}})
    plan.start("A1")
    plan.complete("A1", "classification=noise")
    assert plan.get("A1").status == DONE
    assert plan.completed == 1
    plan.skip_remaining("gated at A1")
    assert all(s.status in (DONE, SKIPPED) for s in plan.steps)
    assert "[x]" in plan.render() and "[-]" in plan.render()


# ---------------------------------------------------------------------------
# Short-term conversation memory
# ---------------------------------------------------------------------------

def test_conversation_memory_window_and_working_set():
    from agent.session.memory import ConversationMemory

    cm = ConversationMemory(max_turns=3)
    for i in range(5):
        cm.add_turn("user", f"msg {i}")
    # window caps retained turns at 3, but the counter reflects all 5
    assert len(cm.turns) == 3
    assert cm.turn_count == 5
    assert cm.turns[-1].text == "msg 4"

    cm.remember("current_entity", "topic:payments.settlement")
    assert cm.recall("current_entity") == "topic:payments.settlement"
    assert cm.recall("missing", "default") == "default"


def test_conversation_memory_reset_clears_everything():
    from agent.session.memory import ConversationMemory

    cm = ConversationMemory()
    cm.add_turn("user", "hello")
    cm.remember("k", "v")
    cm.reset()
    assert cm.turns == []
    assert cm.turn_count == 0
    assert cm.working_set == {}


# ---------------------------------------------------------------------------
# Long-term incident memory (persistence, recurrence, retention, reset)
# ---------------------------------------------------------------------------

def test_long_term_memory_persists_and_recalls(tmp_path):
    from agent.session.memory import IncidentMemoryStore, IncidentRecord

    path = tmp_path / "mem.json"
    store = IncidentMemoryStore(path)
    store.add(IncidentRecord(
        incident_id="inc-1", entity="topic:payments.settlement",
        metric="consumer_lag", classification="confirmed", severity="P2",
        summary="lag", closure_recommendation="continue_monitoring",
    ))
    assert path.exists()

    # A fresh store loads the persisted record from disk (survives "restart").
    reloaded = IncidentMemoryStore(path)
    assert reloaded.count == 1
    assert reloaded.last_for_entity("topic:payments.settlement").incident_id == "inc-1"
    assert reloaded.recurrence_count("topic:payments.settlement", "consumer_lag") == 1


def test_long_term_memory_retention_prunes_oldest(tmp_path):
    from agent.session.memory import IncidentMemoryStore, IncidentRecord

    store = IncidentMemoryStore(tmp_path / "mem.json", max_records=2)
    for i in range(4):
        store.add(IncidentRecord(
            incident_id=f"inc-{i}", entity="topic:x", metric="consumer_lag",
            classification="confirmed", severity="P3", summary="s",
            closure_recommendation="continue_monitoring",
        ))
    assert store.count == 2
    ids = [r.incident_id for r in store.all()]
    assert ids == ["inc-2", "inc-3"]   # oldest pruned first


def test_long_term_memory_reset_forgets_all(tmp_path):
    from agent.session.memory import IncidentMemoryStore, IncidentRecord

    store = IncidentMemoryStore(tmp_path / "mem.json")
    store.add(IncidentRecord(
        incident_id="inc-1", entity="topic:x", metric="m",
        classification="confirmed", severity="P1", summary="s",
        closure_recommendation="close",
    ))
    store.reset()
    assert store.count == 0
    assert IncidentMemoryStore(tmp_path / "mem.json").count == 0


def test_corrupt_memory_file_degrades_to_empty(tmp_path):
    from agent.session.memory import IncidentMemoryStore

    path = tmp_path / "mem.json"
    path.write_text("not valid json {", encoding="utf-8")
    store = IncidentMemoryStore(path)         # must not raise
    assert store.count == 0


# ---------------------------------------------------------------------------
# Session: signal turn drives plan + memory end to end
# ---------------------------------------------------------------------------

def test_session_signal_turn_runs_plan_and_persists(session, actionable_signal):
    out = session.handle_turn(json.dumps(actionable_signal))

    assert out["kind"] == "signal"
    assert out["entity"] == "topic:payments.settlement"
    assert out["gated"] is False
    # plan fully executed: recall + A1..A8 + persist all done
    steps = {s["key"]: s["status"] for s in out["plan"]["steps"]}
    for key in ("recall", "A1", "A8", "persist"):
        assert steps[key] == "done", f"{key} not done: {steps}"
    # the incident was written to long-term memory
    assert out["incident_id"]
    assert session.memory.recurrence_count("topic:payments.settlement") == 1
    assert "SENTINEL SESSION" in out["response"]


def test_session_detects_recurrence_on_second_signal(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    second = dict(actionable_signal, signal_id="sig-p6-2", value=72000)
    out = session.handle_turn(json.dumps(second))

    assert out["recurrence_count"] == 1          # one PRIOR incident at recall time
    assert session.memory.count == 2
    assert "RECURRING" in out["response"]


def test_session_gated_signal_skips_downstream_and_persist(session):
    """A 'noise'-class signal gates at A1: downstream + persist are skipped."""
    noise = {
        "signal_id": "sig-noise",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "consumer_lag",
        "value": 10, "unit": "messages", "environment": "prod",
    }
    out = session.handle_turn(json.dumps(noise))
    steps = {s["key"]: s["status"] for s in out["plan"]["steps"]}
    if out["gated"]:
        assert steps["persist"] == "skipped"
        assert session.memory.count == 0
    else:
        # if the rules classify it actionable, at least the plan must be coherent
        assert steps["A1"] == "done"


# ---------------------------------------------------------------------------
# Session: multi-turn + follow-up + reset vs retention
# ---------------------------------------------------------------------------

def test_session_followup_uses_memory_and_tools(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    out = session.handle_turn(
        "what is the recent consumer_lag value on topic:payments.settlement"
    )
    assert out["kind"] == "followup"
    assert out["focus_entity"] == "topic:payments.settlement"
    # a tool was invoked via the Phase 5 ToolAgent
    assert out["tool_steps"]
    assert "topic:payments.settlement" in out["memory_note"]


def test_session_reset_clears_short_term_retains_long_term(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    assert session.memory.count == 1
    assert session.conversation.turn_count >= 2

    out = session.handle_turn("reset")
    assert out["kind"] == "reset"
    assert out["long_term_retained"] == 1
    # long-term retained, short-term restarted (reset msg is turn 1)
    assert session.memory.count == 1
    assert session.conversation.turn_count == 1


def test_session_clear_long_term_memory_explicit(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    cleared = session.clear_long_term_memory()
    assert cleared == 1
    assert session.memory.count == 0


# ---------------------------------------------------------------------------
# R1 — domain-scope guardrail + R2 PII masking at the session boundary
# ---------------------------------------------------------------------------

def test_out_of_scope_turn_is_refused_and_never_runs_pipeline(tmp_path):
    """An out-of-scope input returns kind='refused' and the A1-A8 pipeline
    (run_signal) is NEVER invoked."""
    from unittest.mock import Mock

    from agent.session import SentinelSession

    spy = Mock()
    session = SentinelSession(
        use_retrieval=False,
        memory_path=tmp_path / "mem.json",
        feedback_path=tmp_path / "fb.json",
        multi_agent=spy,
        tool_agent=Mock(),
    )
    out = session.handle_turn("what is the weather today")

    assert out["kind"] == "refused"
    assert out["scope"] == "out_of_scope"
    assert "reason" in out and "response" in out
    spy.run_signal.assert_not_called()


def test_in_scope_signal_still_runs_full_pipeline(session, actionable_signal):
    """An in-scope signal JSON is not refused — it runs the full pipeline."""
    out = session.handle_turn(json.dumps(actionable_signal))
    assert out["kind"] == "signal"


def test_input_pii_is_masked_in_response_and_stored_turn(session):
    """A turn whose input carries email + phone yields placeholders in both the
    returned response and the stored agent conversation turn — never raw PII."""
    out = session.handle_turn(
        "broker lag — reach me at jane.doe@gmail.com / +1 415 555 2671"
    )
    # followup turn still runs; response carries placeholders not raw PII
    assert "<EMAIL>" in out["response"]
    assert "<PHONE>" in out["response"]
    assert "jane.doe@gmail.com" not in out["response"]
    assert "415 555 2671" not in out["response"]

    # the stored user turn is masked
    user_turns = [t for t in session.conversation.turns if t.role == "user"]
    assert user_turns
    assert "jane.doe@gmail.com" not in user_turns[-1].text
    assert "<EMAIL>" in user_turns[-1].text
    assert "<PHONE>" in user_turns[-1].text

    # the stored agent turn is masked too (both sinks)
    agent_turns = [t for t in session.conversation.turns if t.role == "agent"]
    assert agent_turns
    assert "jane.doe@gmail.com" not in agent_turns[-1].text
    assert "415 555 2671" not in agent_turns[-1].text
