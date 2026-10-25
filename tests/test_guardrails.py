"""R1 unit tests — deterministic domain-scope guardrail (agent/guardrails.py).

Pure-function tests on classify_scope: the 3-way label is correct for signal
JSON, greetings/short text, in-vocabulary text, and out-of-domain text, and the
classifier never raises on None / non-string / oversized input.
"""

from __future__ import annotations

import json

from agent.guardrails import (
    SCOPE_CLARIFY,
    SCOPE_IN,
    SCOPE_OUT,
    classify_scope,
)


def test_signal_json_is_in_scope():
    signal = {
        "signal_id": "sig-1",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "consumer_lag",
        "value": 60000,
    }
    scope, reason = classify_scope(json.dumps(signal))
    assert scope == SCOPE_IN
    assert reason == "normalized signal JSON"


def test_bare_greeting_needs_clarification():
    for greeting in ("hi", "thanks", "hello", "ok", "help"):
        scope, reason = classify_scope(greeting)
        assert scope == SCOPE_CLARIFY, greeting
        assert "short" in reason or "greeting" in reason


def test_two_word_text_needs_clarification():
    scope, reason = classify_scope("broker down")   # 2 tokens -> too short
    assert scope == SCOPE_CLARIFY


def test_kafka_vocabulary_is_in_scope_with_matched_term():
    scope, reason = classify_scope("why is consumer lag rising on the broker")
    assert scope == SCOPE_IN
    assert "consumer lag" in reason or "broker" in reason or "lag" in reason


def test_schema_registry_phrase_is_in_scope():
    scope, reason = classify_scope("schema registry down and failing")
    assert scope == SCOPE_IN
    assert "schema registry" in reason


def test_out_of_domain_is_out_of_scope():
    scope, reason = classify_scope("what is the weather today")
    assert scope == SCOPE_OUT
    assert reason == "no in-domain terms detected"


def test_none_and_non_string_never_raise():
    for bad in (None, 123, 4.5, object()):
        scope, reason = classify_scope(bad)  # type: ignore[arg-type]
        assert scope in {SCOPE_IN, SCOPE_OUT, SCOPE_CLARIFY}
        assert isinstance(reason, str)


def test_oversized_input_never_raises():
    scope, reason = classify_scope("x" * 20001)
    assert scope in {SCOPE_IN, SCOPE_OUT, SCOPE_CLARIFY}
    assert isinstance(reason, str)


def test_returns_two_tuple_of_strings():
    out = classify_scope("broker partition lag rising")
    assert isinstance(out, tuple) and len(out) == 2
    assert all(isinstance(x, str) for x in out)
