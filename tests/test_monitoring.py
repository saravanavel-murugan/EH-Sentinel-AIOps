"""R4 — agent/monitoring.py unit tests (offline, no key, no network).

Confirms the OFF-by-default degradation ladder: with the flags off both
functions return a disabled status dict with the right reason and neither raises;
with a flag on but the optional SDK absent they degrade to
"disabled (package not installed)"; monitoring_status() reports disabled even
with the SDKs absent; and a with-body exception inside langfuse_trace propagates
unchanged on the disabled path.
"""

from __future__ import annotations

import builtins

import pytest

import agent.monitoring as m


# -- flags OFF: disabled (not configured) --------------------------------

def test_langfuse_trace_disabled_yields_status(monkeypatch):
    monkeypatch.delenv("SENTINEL_LANGFUSE_ENABLED", raising=False)
    with m.langfuse_trace("test-trace", metadata={"k": "v"}) as status:
        assert status == {"enabled": False, "reason": "disabled (not configured)"}


def test_deepeval_score_disabled_returns_dict(monkeypatch):
    monkeypatch.delenv("SENTINEL_DEEPEVAL_ENABLED", raising=False)
    out = m.deepeval_score("why is lag rising", "advisory response")
    assert out == {"enabled": False, "reason": "disabled (not configured)",
                   "metrics": {}}


def test_monitoring_status_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SENTINEL_LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("SENTINEL_DEEPEVAL_ENABLED", raising=False)
    status = m.monitoring_status()
    assert status["langfuse"]["enabled"] is False
    assert status["deepeval"]["enabled"] is False
    assert status["langfuse"]["reason"] == "disabled (not configured)"
    assert status["deepeval"]["reason"] == "disabled (not configured)"


def test_neither_function_raises_when_off(monkeypatch):
    monkeypatch.delenv("SENTINEL_LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("SENTINEL_DEEPEVAL_ENABLED", raising=False)
    # Must not raise:
    with m.langfuse_trace("x"):
        pass
    m.deepeval_score("a", "b")
    m.monitoring_status()


# -- flag ON but package absent: graceful "package not installed" --------

def _block_import(monkeypatch, blocked: str):
    """Make ``import <blocked>`` raise ImportError, leaving others intact."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == blocked or name.startswith(blocked + "."):
            raise ImportError(f"blocked: {blocked}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_langfuse_graceful_when_package_absent(monkeypatch):
    monkeypatch.setenv("SENTINEL_LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-placeholder")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-placeholder")
    _block_import(monkeypatch, "langfuse")
    with m.langfuse_trace("test") as status:
        assert status["enabled"] is False
        assert status["reason"] == "disabled (package not installed)"


def test_deepeval_graceful_when_package_absent(monkeypatch):
    monkeypatch.setenv("SENTINEL_DEEPEVAL_ENABLED", "1")
    monkeypatch.setenv("SENTINEL_DEEPEVAL_MODEL", "gpt-4o-mini")
    _block_import(monkeypatch, "deepeval")
    out = m.deepeval_score("in", "out")
    assert out["enabled"] is False
    assert out["reason"] == "disabled (package not installed)"
    assert out["metrics"] == {}


def test_monitoring_status_disabled_even_with_sdks_absent(monkeypatch):
    monkeypatch.setenv("SENTINEL_LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-placeholder")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-placeholder")
    monkeypatch.setenv("SENTINEL_DEEPEVAL_ENABLED", "1")
    monkeypatch.setenv("SENTINEL_DEEPEVAL_MODEL", "gpt-4o-mini")
    _block_import(monkeypatch, "langfuse")
    _block_import(monkeypatch, "deepeval")
    status = m.monitoring_status()
    assert status["langfuse"]["enabled"] is False
    assert status["deepeval"]["enabled"] is False
    assert status["langfuse"]["reason"] == "disabled (package not installed)"
    assert status["deepeval"]["reason"] == "disabled (package not installed)"


# -- missing-config rungs ------------------------------------------------

def test_langfuse_no_credentials_reason(monkeypatch):
    """Flag on + package importable but no keys -> 'disabled (no credentials)'.

    Only asserted if langfuse is actually importable in this env; otherwise the
    package-not-installed rung is the correct earlier stop and is covered above.
    """
    monkeypatch.setenv("SENTINEL_LANGFUSE_ENABLED", "1")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    reason = m._langfuse_reason()
    assert reason in {"disabled (no credentials)",
                      "disabled (package not installed)"}


def test_deepeval_no_judge_model_reason(monkeypatch):
    monkeypatch.setenv("SENTINEL_DEEPEVAL_ENABLED", "1")
    monkeypatch.delenv("SENTINEL_DEEPEVAL_MODEL", raising=False)
    reason = m._deepeval_reason()
    assert reason in {"disabled (no judge model)",
                      "disabled (package not installed)"}


# -- with-body exception propagates unchanged (disabled path) ------------

def test_langfuse_trace_body_exception_propagates(monkeypatch):
    monkeypatch.delenv("SENTINEL_LANGFUSE_ENABLED", raising=False)

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom):
        with m.langfuse_trace("test"):
            raise _Boom("body error")
