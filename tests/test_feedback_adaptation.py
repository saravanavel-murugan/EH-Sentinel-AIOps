"""Phase 7 tests — operator feedback store + deterministic adaptation policy.

Runs on the offline fake provider (forced in conftest). Feedback + memory are
written to pytest ``tmp_path`` so tests never touch logs/. These assert
BEHAVIOUR (persistence, retention/reset, policy thresholds, before-vs-after,
and the safety invariants) — adaptation is advisory-only and must never weaken
the safety posture. A1-A8 node logic is reused unchanged.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def actionable_signal() -> dict:
    return {
        "signal_id": "sig-p7",
        "source": "control_center",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "consumer_lag",
        "value": 60000, "unit": "messages", "environment": "prod",
    }


@pytest.fixture()
def session(tmp_path, fake_chat):
    from agent.session import SentinelSession

    return SentinelSession(
        chat_model=fake_chat,
        use_retrieval=False,
        memory_path=tmp_path / "mem.json",
        feedback_path=tmp_path / "fb.json",
    )


def _submit(session, signal, category, n):
    """Run the signal turn then record ``n`` feedback of ``category``."""
    out = session.handle_turn(json.dumps(signal))
    for _ in range(n):
        session.record_feedback(category=category)
    return out


# ---------------------------------------------------------------------------
# FeedbackStore — persistence, retention, reset, resilience
# ---------------------------------------------------------------------------

def test_feedback_persists_and_reloads(tmp_path):
    from agent.session.feedback import FeedbackRecord, FeedbackStore

    path = tmp_path / "fb.json"
    store = FeedbackStore(path)
    store.add(FeedbackRecord(
        feedback_id="fb-1", entity="topic:payments.settlement",
        metric="consumer_lag", incident_id="inc-1",
        category="severity_too_low", signal="down",
    ))
    assert path.exists()

    reloaded = FeedbackStore(path)
    assert reloaded.count == 1
    assert reloaded.for_entity("topic:payments.settlement")[0].feedback_id == "fb-1"
    assert reloaded.count_for_category("topic:payments.settlement", "severity_too_low") == 1


def test_feedback_retention_prunes_oldest(tmp_path):
    from agent.session.feedback import FeedbackRecord, FeedbackStore

    store = FeedbackStore(tmp_path / "fb.json", max_records=2)
    for i in range(4):
        store.add(FeedbackRecord(
            feedback_id=f"fb-{i}", entity="topic:x", metric="m",
            incident_id="inc", category="too_verbose",
        ))
    assert store.count == 2
    ids = [r.feedback_id for r in store.all()]
    assert ids == ["fb-2", "fb-3"]        # oldest pruned first


def test_feedback_reset_forgets_all(tmp_path):
    from agent.session.feedback import FeedbackRecord, FeedbackStore

    store = FeedbackStore(tmp_path / "fb.json")
    store.add(FeedbackRecord(
        feedback_id="fb-1", entity="topic:x", metric="m",
        incident_id="inc", category="severity_too_low",
    ))
    store.reset()
    assert store.count == 0
    assert FeedbackStore(tmp_path / "fb.json").count == 0


def test_corrupt_feedback_file_degrades_to_empty(tmp_path):
    from agent.session.feedback import FeedbackStore

    path = tmp_path / "fb.json"
    path.write_text("not valid json {", encoding="utf-8")
    store = FeedbackStore(path)            # must not raise
    assert store.count == 0


def test_missing_feedback_file_is_empty(tmp_path):
    from agent.session.feedback import FeedbackStore

    store = FeedbackStore(tmp_path / "does_not_exist.json")
    assert store.count == 0


def test_feedback_is_negative_classification():
    from agent.session.feedback import FeedbackRecord

    down = FeedbackRecord("f", "e", "m", "i", signal="down", category="other")
    low_rating = FeedbackRecord("f", "e", "m", "i", signal="up", rating=1, category="other")
    tag = FeedbackRecord("f", "e", "m", "i", signal="up", category="too_verbose")
    positive = FeedbackRecord("f", "e", "m", "i", signal="up", rating=5, category="other")
    assert down.is_negative()
    assert low_rating.is_negative()
    assert tag.is_negative()
    assert not positive.is_negative()


# ---------------------------------------------------------------------------
# AdaptationPolicy — thresholds
# ---------------------------------------------------------------------------

def test_policy_requires_threshold_for_severity_nudge(tmp_path):
    from agent.session.feedback import (AdaptationPolicy, FeedbackRecord,
                                        FeedbackStore)

    store = FeedbackStore(tmp_path / "fb.json")
    policy = AdaptationPolicy(store)
    ent = "topic:x"

    store.add(FeedbackRecord("fb-1", ent, "m", "i", category="severity_too_low"))
    assert policy.derive(ent).severity_nudge is False    # 1 < threshold

    store.add(FeedbackRecord("fb-2", ent, "m", "i", category="severity_too_low"))
    prof = policy.derive(ent)
    assert prof.severity_nudge is True                   # 2 >= threshold
    assert any("severity_nudge" in e for e in prof.explanations)


def test_policy_concise_threshold_and_recurrence(tmp_path):
    from agent.session.feedback import (AdaptationPolicy, FeedbackRecord,
                                        FeedbackStore)

    store = FeedbackStore(tmp_path / "fb.json")
    policy = AdaptationPolicy(store)
    ent = "topic:x"

    store.add(FeedbackRecord("fb-1", ent, "m", "i", category="too_verbose"))
    assert policy.derive(ent).concise is False
    store.add(FeedbackRecord("fb-2", ent, "m", "i", category="too_verbose"))
    assert policy.derive(ent).concise is True

    # recurrence emphasis needs a prior incident AND a negative feedback item
    assert policy.derive(ent, recurrence_count=0).recurrence_emphasis is False
    assert policy.derive(ent, recurrence_count=1).recurrence_emphasis is True


def test_policy_no_feedback_no_adjustments(tmp_path):
    from agent.session.feedback import AdaptationPolicy, FeedbackStore

    policy = AdaptationPolicy(FeedbackStore(tmp_path / "fb.json"))
    prof = policy.derive("topic:x", recurrence_count=3)
    assert prof.any_applied() is False
    assert prof.explanations == []


# ---------------------------------------------------------------------------
# Session: record_feedback + snapshot + reset/retention
# ---------------------------------------------------------------------------

def test_record_feedback_uses_working_set(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    res = session.record_feedback(category="severity_too_low")
    assert res["recorded"] is True
    assert res["entity"] == "topic:payments.settlement"
    assert res["negative"] is True
    assert session.feedback.count == 1


def test_record_feedback_without_focus_is_rejected(session):
    res = session.record_feedback(category="severity_too_low")
    assert res["recorded"] is False
    assert session.feedback.count == 0


def test_snapshot_includes_feedback(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    session.record_feedback(category="too_verbose")
    snap = session.snapshot()
    assert "feedback" in snap
    assert snap["feedback"]["count"] == 1
    assert snap["feedback"]["category_counts"].get("too_verbose") == 1


def test_reset_retains_feedback_but_clear_feedback_forgets(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    session.record_feedback(category="severity_too_low")
    assert session.feedback.count == 1

    # a reset turn clears short-term only; feedback is RETAINED
    session.handle_turn("reset")
    assert session.feedback.count == 1

    # clear_feedback() is the explicit forget-all
    cleared = session.clear_feedback()
    assert cleared == 1
    assert session.feedback.count == 0
    # on-disk store is empty too
    from agent.session.feedback import FeedbackStore
    assert FeedbackStore(session.feedback.path).count == 0


# ---------------------------------------------------------------------------
# Before-vs-after behaviour
# ---------------------------------------------------------------------------

def test_no_feedback_matches_phase6_shape(session, actionable_signal):
    out = session.handle_turn(json.dumps(actionable_signal))
    assert out["adaptation"]["severity_nudge"] is False
    assert out["adaptation"]["concise"] is False
    assert out["adaptation"]["recurrence_emphasis"] is False
    # Phase-6 render: full pipeline block present, no ADAPTATION section.
    assert "--- Multi-agent pipeline output ---" in out["response"]
    assert "ADAPTATION" not in out["response"]


def test_after_feedback_behaviour_differs(session, actionable_signal):
    before = session.handle_turn(json.dumps(actionable_signal))
    for _ in range(2):
        session.record_feedback(category="severity_too_low")
    for _ in range(2):
        session.record_feedback(category="too_verbose")

    after = session.handle_turn(json.dumps(dict(actionable_signal,
                                                signal_id="sig-p7-2", value=72000)))
    # flags flipped on
    assert after["adaptation"]["severity_nudge"] is True
    assert after["adaptation"]["concise"] is True
    assert after["adaptation"]["recurrence_emphasis"] is True
    # rendered output differs and carries the ADAPTATION section + concise body
    assert before["response"] != after["response"]
    assert "ADAPTATION (advisory)" in after["response"]
    assert "concise" in after["response"]
    assert after["adaptation"]["explanations"]


# ---------------------------------------------------------------------------
# Safety invariants — adaptation never weakens the safety posture
# ---------------------------------------------------------------------------

def test_adaptation_preserves_safety_note_and_approval(session, actionable_signal):
    before = session.handle_turn(json.dumps(actionable_signal))
    for _ in range(2):
        session.record_feedback(category="severity_too_low")
    for _ in range(2):
        session.record_feedback(category="too_verbose")
    after = session.handle_turn(json.dumps(dict(actionable_signal,
                                                signal_id="sig-p7-3", value=72000)))

    text = after["response"]
    # advisory safety note is ALWAYS present, even in concise mode
    assert "advisory only" in text
    # adaptation never introduces auto-approve / escalation-suppression language
    lowered = text.lower()
    for forbidden in ("auto-approve", "auto approve", "skip approval",
                      "no approval", "suppress escalation"):
        assert forbidden not in lowered

    # A5 guardrails untouched vs the pre-adaptation run
    a5_before = before["agents"]["a5"]
    a5_after = after["agents"]["a5"]
    assert a5_before["read_only"] is True and a5_after["read_only"] is True
    for a in a5_after.get("actions", []):
        assert a.get("requires_approval") is True

    # A3 severity value is NOT rewritten by the nudge (same pipeline value)
    assert after["agents"]["a3"]["severity"] == before["agents"]["a3"]["severity"]


def test_severity_nudge_shows_a3_unchanged(session, actionable_signal):
    session.handle_turn(json.dumps(actionable_signal))
    for _ in range(2):
        session.record_feedback(category="severity_too_low")
    after = session.handle_turn(json.dumps(dict(actionable_signal,
                                                signal_id="sig-p7-4", value=72000)))
    sev = after["agents"]["a3"]["severity"]
    # the nudge presents the A3 value and recommends CONSIDERING higher — advisory
    assert "UNCHANGED" in after["response"]
    assert str(sev) in after["response"]


# ---------------------------------------------------------------------------
# No PII / secrets persisted
# ---------------------------------------------------------------------------

def test_no_secret_persisted_in_feedback(session, actionable_signal, tmp_path):
    session.handle_turn(json.dumps(actionable_signal))
    # a note that happens to mention a secret-like token must still only be
    # stored as the plain note text the operator typed — we assert the store
    # holds exactly the expected keys and never an env/secret key.
    session.record_feedback(category="too_verbose", note="response too long")

    raw = json.loads(session.feedback.path.read_text(encoding="utf-8"))
    assert set(raw.keys()) == {"updated_at", "records"}
    expected_keys = {"feedback_id", "entity", "metric", "incident_id",
                     "signal", "rating", "category", "note", "ts"}
    for rec in raw["records"]:
        assert set(rec.keys()) == expected_keys
        # no secret/credential-looking keys leaked into the record
        for k in rec:
            assert "api_key" not in k.lower()
            assert "secret" not in k.lower()
            assert "token" not in k.lower()
    # the planted text must not contain a fake key pattern we never store
    text = session.feedback.path.read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "OPENAI_API_KEY" not in text
