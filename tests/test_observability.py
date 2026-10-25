"""Phase 8 tests — centralized observability: logging, tracing, redaction, and
graceful failure handling.

Runs on the deterministic offline fake provider (forced in conftest). Every log
and trace path is a pytest ``tmp_path`` so the real ``logs/`` is never touched.
These assert deployment-readiness BEHAVIOUR:

  * ``configure_logging`` is idempotent and honours ``SENTINEL_LOG_LEVEL``;
  * ``trace_run`` captures ``latency_ms`` + ``status`` and writes one JSON line;
  * ``redact`` / ``RedactingFilter`` provably keep planted secrets off disk;
  * ``safe_handle_turn`` degrades gracefully (never raises) for the three
    failure scenarios and preserves the advisory/read-only safety posture.

The A1-A8 node logic is reused unchanged.
"""

from __future__ import annotations

import json
import logging

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def actionable_signal() -> str:
    """Rising consumer lag on a known topic -> pipeline proceeds past A1."""
    return (
        '{"signal_id": "sig-p8", "source": "control_center", '
        '"entity": {"type": "topic", "id": "payments.settlement"}, '
        '"metric_or_event": "consumer_lag", "value": 60000, '
        '"unit": "messages", "environment": "prod"}'
    )


class SimulatedProviderOutage(BaseException):
    """A hard, non-recoverable provider failure.

    The A1-A8 nodes deliberately catch ``Exception`` and degrade to the
    deterministic rule fallback, so an ordinary LLM error never crashes the
    turn (that resilience is itself graceful handling). This models a
    catastrophic transport/runtime failure that the node layer does NOT swallow,
    so it reaches the runtime wrapper and exercises ``safe_handle_turn``'s own
    graceful degradation.
    """


def _raising_chat_model():
    """A deterministic fake chat model whose ``invoke`` raises a hard outage —
    simulates a provider/LLM failure offline. Subclasses the real fake so it is
    wired into the pipeline exactly like the normal offline model."""
    from agent.llm import DeterministicSentinelChatModel

    class _RaisingChatModel(DeterministicSentinelChatModel):
        def invoke(self, *args, **kwargs):
            raise SimulatedProviderOutage("simulated provider outage")

    return _RaisingChatModel()


class _RaisingSession:
    """A session stub whose handle_turn always raises — models an internal
    error on malformed input without depending on pipeline tolerance."""

    provider = "fake"

    def handle_turn(self, user_input):
        raise ValueError("malformed input: could not route turn")


def _read_lines(path):
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

def test_configure_logging_is_idempotent(tmp_path):
    import agent.observability as obs

    logger = obs.configure_logging(log_dir=tmp_path, level="INFO", force=True)
    n_handlers = len(logger.handlers)
    # A second (non-forced) call must not stack duplicate handlers.
    logger2 = obs.configure_logging(log_dir=tmp_path, level="INFO")
    assert logger2 is logger
    assert len(logger2.handlers) == n_handlers
    assert n_handlers >= 2  # rotating file + console


def test_configure_logging_honours_level_env(tmp_path, monkeypatch):
    import agent.observability as obs

    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "WARNING")
    logger = obs.configure_logging(log_dir=tmp_path, force=True)
    assert logger.level == logging.WARNING


# ---------------------------------------------------------------------------
# Tracing — latency + status + one JSON line per run
# ---------------------------------------------------------------------------

def test_trace_run_success_writes_latency_and_status(tmp_path):
    import agent.observability as obs

    obs.configure_logging(log_dir=tmp_path, force=True)
    with obs.trace_run("unit.test", provider="fake", log_dir=tmp_path) as tr:
        tr.extra["entity"] = "topic:payments.settlement"

    trace_path = tmp_path / obs.DEFAULT_TRACE_FILE
    lines = _read_lines(trace_path)
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["status"] == "ok"
    assert isinstance(rec["latency_ms"], int) and rec["latency_ms"] >= 0
    assert rec["entry_point"] == "unit.test"
    assert rec["run_id"].startswith("run-")


def test_trace_run_failure_records_error_and_reraises(tmp_path):
    import agent.observability as obs

    obs.configure_logging(log_dir=tmp_path, force=True)
    with pytest.raises(RuntimeError):
        with obs.trace_run("unit.test", provider="fake", log_dir=tmp_path):
            raise RuntimeError("boom")

    lines = _read_lines(tmp_path / obs.DEFAULT_TRACE_FILE)
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["status"] == "error"
    assert rec["error_type"] == "RuntimeError"
    assert isinstance(rec["latency_ms"], int)


# ---------------------------------------------------------------------------
# Redaction — planted secrets must never reach disk (HARD requirement)
# ---------------------------------------------------------------------------

def test_redact_scrubs_keys_and_patterns():
    import agent.observability as obs

    out = obs.redact({
        "note": "contact sk-ABC123DEF456 for access",
        "api_key": "sk-shouldbemasked",
        "env": "OPENAI_API_KEY=sk-zzz999",
        "nested": ["Bearer tok-abcdef", {"authorization": "Bearer xyz"}],
    })
    blob = json.dumps(out)
    assert "sk-ABC123DEF456" not in blob
    assert "sk-shouldbemasked" not in blob
    assert "sk-zzz999" not in blob
    assert obs.REDACTED in blob


def test_redacting_filter_strips_secret_from_log_and_trace(tmp_path):
    import agent.observability as obs

    logger = obs.configure_logging(log_dir=tmp_path, force=True)
    secret = "sk-SUPERSECRET123456"
    logger.info("planted secret %s and OPENAI_API_KEY=%s", secret, secret)

    with obs.trace_run("unit.leak", provider="fake", log_dir=tmp_path) as tr:
        tr.extra["note"] = f"do not leak {secret}"
        tr.extra["api_key"] = secret

    for handler in logger.handlers:
        handler.flush()

    log_text = (tmp_path / obs.DEFAULT_LOG_FILE).read_text(encoding="utf-8")
    trace_text = (tmp_path / obs.DEFAULT_TRACE_FILE).read_text(encoding="utf-8")
    assert secret not in log_text
    assert secret not in trace_text
    assert obs.REDACTED in trace_text


# ---------------------------------------------------------------------------
# PII masking (R2) — single source of truth composed WITH secret redaction
# ---------------------------------------------------------------------------

def test_mask_pii_maps_each_shape_to_placeholder():
    import agent.observability as obs

    assert obs.mask_pii("reach jane.doe@gmail.com") == "reach <EMAIL>"
    assert obs.mask_pii("card 4111 1111 1111 1111") == "card <CARD>"
    assert obs.mask_pii("iban GB82WEST12345698765432") == "iban <ID>"
    assert obs.mask_pii("aadhaar 1234 5678 9012") == "aadhaar <ID>"
    assert obs.mask_pii("ssn 123-45-6789") == "ssn <ID>"


def test_mask_pii_preserves_reserved_example_domains():
    import agent.observability as obs

    assert obs.mask_pii("alice@example.com") == "alice@example.com"
    assert obs.mask_pii("bob@example.org") == "bob@example.org"
    assert obs.mask_pii("carol@example.net") == "carol@example.net"
    # ...but a real external email IS masked.
    assert obs.mask_pii("jane.doe@gmail.com") == "<EMAIL>"


def test_mask_pii_is_idempotent():
    import agent.observability as obs

    x = "mail jane.doe@gmail.com phone +1 415 555 2671 card 4111 1111 1111 1111"
    once = obs.mask_pii(x)
    assert obs.mask_pii(once) == once


def test_mask_pii_preserves_dict_and_list_shape():
    import agent.observability as obs

    out = obs.mask_pii({
        "to": "jane.doe@gmail.com",
        "contacts": ["bob@gmail.com", "alice@example.com"],
        "pair": ("carol@yahoo.com", "ok"),
    })
    assert out == {
        "to": "<EMAIL>",
        "contacts": ["<EMAIL>", "alice@example.com"],
        "pair": ("<EMAIL>", "ok"),
    }
    assert isinstance(out["pair"], tuple)


@pytest.mark.parametrize("text", [
    "value 60000",
    "latency 2500 ms",
    "lag 1200 - 800",
    "5000 2671",
    "4155552671",
    "415 555 2671",
])
def test_mask_pii_does_not_mask_operational_numbers(text):
    import agent.observability as obs

    assert obs.mask_pii(text) == text


@pytest.mark.parametrize("text", [
    "+1 415 555 2671",
    "(415) 555-2671",
])
def test_mask_pii_masks_anchored_phone_numbers(text):
    import agent.observability as obs

    assert obs.mask_pii(text) == "<PHONE>"


def test_mask_pii_leaves_secret_shape_untouched():
    import agent.observability as obs

    # mask_pii does NO key-hint masking — that is redact's job.
    assert obs.mask_pii({"api_key": "sk-x"}) == {"api_key": "sk-x"}


def test_redact_and_mask_composition():
    import agent.observability as obs

    assert obs.redact_and_mask({
        "api_key": "sk-x",
        "to": "alice@example.com",
        "from": "j@gmail.com",
    }) == {
        "api_key": "<redacted>",
        "to": "alice@example.com",
        "from": "<EMAIL>",
    }


def test_redact_and_mask_is_idempotent():
    import agent.observability as obs

    x = {
        "note": "key OPENAI_API_KEY=sk-zzz999 and mail jane.doe@gmail.com",
        "phone": "+1 415 555 2671",
        "api_key": "sk-shouldmask",
    }
    once = obs.redact_and_mask(x)
    assert obs.redact_and_mask(once) == once


def test_redacting_filter_masks_pii_in_log(tmp_path):
    import agent.observability as obs

    logger = obs.configure_logging(log_dir=tmp_path, force=True)
    logger.info("operator left email jane.doe@gmail.com and phone +1 415 555 2671")
    for handler in logger.handlers:
        handler.flush()

    log_text = (tmp_path / obs.DEFAULT_LOG_FILE).read_text(encoding="utf-8")
    assert "jane.doe@gmail.com" not in log_text
    assert "<EMAIL>" in log_text
    assert "<PHONE>" in log_text


# ---------------------------------------------------------------------------
# Graceful failure — the three scenarios
# ---------------------------------------------------------------------------

def _assert_graceful_error(result, *, run_present=True):
    assert isinstance(result, dict)
    assert result.get("kind") == "error"
    assert result.get("ok") is False
    if run_present:
        assert result.get("run_id", "").startswith("run-")
    assert "error_type" in result
    # Safety posture preserved; no leaked stack trace / secret.
    assert "advisory" in result.get("safety", "").lower()
    assert "advisory" in result.get("response", "").lower()
    assert "Traceback" not in json.dumps(result)
    assert "sk-" not in json.dumps(result)
    # No weakening language.
    lowered = json.dumps(result).lower()
    assert "auto-approve" not in lowered
    assert "skip approval" not in lowered


def test_safe_handle_turn_malformed_input_returns_graceful_error(tmp_path):
    import agent.observability as obs

    obs.configure_logging(log_dir=tmp_path, force=True)
    result = obs.safe_handle_turn(_RaisingSession(), "???", log_dir=tmp_path)
    _assert_graceful_error(result)
    assert result["error_type"] == "ValueError"
    # One error trace line landed on disk.
    lines = _read_lines(tmp_path / obs.DEFAULT_TRACE_FILE)
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "error"


def test_safe_handle_turn_provider_failure_returns_graceful_error(
        tmp_path, actionable_signal):
    import agent.observability as obs
    from agent.session import SentinelSession

    session = SentinelSession(
        chat_model=_raising_chat_model(),
        use_retrieval=False,
        memory_path=tmp_path / "mem.json",
        feedback_path=tmp_path / "fb.json",
    )
    result = obs.safe_handle_turn(session, actionable_signal, log_dir=tmp_path)
    _assert_graceful_error(result)
    lines = _read_lines(tmp_path / obs.DEFAULT_TRACE_FILE)
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "error"


def test_safe_handle_turn_retrieval_disabled_completes(tmp_path, actionable_signal):
    import agent.observability as obs
    from agent.session import SentinelSession

    # Scenario #3: missing/disabled retrieval index must NOT crash — the turn
    # completes and safe_handle_turn returns a normal success dict.
    session = SentinelSession(
        use_retrieval=False,
        memory_path=tmp_path / "mem.json",
        feedback_path=tmp_path / "fb.json",
    )
    result = obs.safe_handle_turn(session, actionable_signal, log_dir=tmp_path)
    assert result.get("kind") == "signal"
    assert "run" not in result or result.get("ok") is not False
    # A success trace with latency landed on disk.
    lines = _read_lines(tmp_path / obs.DEFAULT_TRACE_FILE)
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["status"] == "ok"
    assert isinstance(rec["latency_ms"], int)


def test_safe_handle_turn_success_returns_unchanged_dict(tmp_path, actionable_signal):
    import agent.observability as obs
    from agent.session import SentinelSession

    session = SentinelSession(
        use_retrieval=False,
        memory_path=tmp_path / "mem.json",
        feedback_path=tmp_path / "fb.json",
    )
    direct = session.handle_turn(actionable_signal)
    # Fresh session to compare shape (keys) on the same input.
    session2 = SentinelSession(
        use_retrieval=False,
        memory_path=tmp_path / "mem2.json",
        feedback_path=tmp_path / "fb2.json",
    )
    wrapped = obs.safe_handle_turn(session2, actionable_signal, log_dir=tmp_path)
    assert wrapped.get("kind") == "signal"
    assert set(direct.keys()) == set(wrapped.keys())
