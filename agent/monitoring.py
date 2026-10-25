"""R4 — optional LLM monitoring (Langfuse) + evaluation (DeepEval).

Both integrations are OPTIONAL and OFF by default. This module guards every
optional import: ``deepeval`` and ``langfuse`` are imported lazily INSIDE the
functions under ``try/except ImportError`` — there is no import-time import of
either package, so importing this module is cheap and safe offline with no key
and no network.

Configuration is read directly from ``os.environ`` (defaults OFF); ``.env`` is
never read, printed, or modified here (``env_config.load_env`` already loads it
elsewhere). Every outbound string is routed through
:func:`agent.observability.redact_and_mask` before anything could be sent, so no
secret or PII can leak to a monitoring backend.

Degradation ladder (each rung yields a disabled dict with a precise reason):
    1. Flag off                         -> "disabled (not configured)"
    2. Flag on, package not importable  -> "disabled (package not installed)"
    3. Flag on, package present, config missing:
         Langfuse missing keys          -> "disabled (no credentials)"
         DeepEval missing judge model    -> "disabled (no judge model)"
    4. All present -> enabled; any runtime error in the enabled path is caught
       and returned as "error: <type>" (type name only — no secret, no stack).

Monitoring's OWN enter/exit logic never raises. A genuine exception raised by a
caller's ``with``-body IS re-raised unchanged (see :func:`langfuse_trace`).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from .observability import get_logger, redact_and_mask

# --------------------------------------------------------------------------
# Config contract — read from os.environ, defaults OFF. .env is NOT touched.
# --------------------------------------------------------------------------

_LANGFUSE_FLAG = "SENTINEL_LANGFUSE_ENABLED"
_LANGFUSE_PUBLIC = "LANGFUSE_PUBLIC_KEY"
_LANGFUSE_SECRET = "LANGFUSE_SECRET_KEY"
_LANGFUSE_HOST = "LANGFUSE_HOST"

_DEEPEVAL_FLAG = "SENTINEL_DEEPEVAL_ENABLED"
_DEEPEVAL_MODEL = "SENTINEL_DEEPEVAL_MODEL"

_REASON_OFF = "disabled (not configured)"
_REASON_NO_PKG = "disabled (package not installed)"
_REASON_NO_CREDS = "disabled (no credentials)"
_REASON_NO_JUDGE = "disabled (no judge model)"


def _flag_on(name: str) -> bool:
    """A monitoring flag is ON only for an explicit truthy value."""
    return os.environ.get(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _langfuse_reason() -> str | None:
    """Return None if Langfuse is fully configured+importable, else a reason."""
    if not _flag_on(_LANGFUSE_FLAG):
        return _REASON_OFF
    try:  # lazy, guarded — never imported at module load
        import langfuse  # noqa: F401
    except ImportError:
        return _REASON_NO_PKG
    if not (os.environ.get(_LANGFUSE_PUBLIC, "").strip()
            and os.environ.get(_LANGFUSE_SECRET, "").strip()):
        return _REASON_NO_CREDS
    return None


def _deepeval_reason() -> str | None:
    """Return None if DeepEval is fully configured+importable, else a reason."""
    if not _flag_on(_DEEPEVAL_FLAG):
        return _REASON_OFF
    try:  # lazy, guarded — never imported at module load
        import deepeval  # noqa: F401
    except ImportError:
        return _REASON_NO_PKG
    if not os.environ.get(_DEEPEVAL_MODEL, "").strip():
        return _REASON_NO_JUDGE
    return None


# --------------------------------------------------------------------------
# Langfuse tracing (context manager)
# --------------------------------------------------------------------------

@contextmanager
def langfuse_trace(name: str, *, metadata: dict | None = None) -> Iterator[dict]:
    """Yield a status dict for a Langfuse trace, degrading gracefully.

    If Langfuse is disabled/absent/unconfigured, yield
    ``{'enabled': False, 'reason': <reason>}`` and do nothing (no network). If
    enabled AND importable AND keys present, open a trace and yield
    ``{'enabled': True, 'trace_id': ...}``. All ``metadata`` is passed through
    :func:`redact_and_mask` first.

    Context-manager contract:
      * ``__enter__`` creates/opens the trace and yields the status dict.
      * ``__exit__`` ALWAYS finalizes/flushes the trace inside a ``try/except``
        that swallows any client/network error (teardown can never raise); a
        failed flush logs WARNING via the sentinel logger and is otherwise
        ignored.
      * If the with-body raises, the exception type name (masked) is recorded on
        the open trace best-effort, then the body's exception is RE-RAISED after
        cleanup. "Never raises" applies to monitoring's own enter/exit logic,
        not to a genuine caller with-body exception.

    On the disabled path ``__exit__`` is a no-op and a body exception propagates
    unchanged.
    """
    reason = _langfuse_reason()
    safe_meta = redact_and_mask(dict(metadata)) if metadata else {}
    safe_name = redact_and_mask(str(name))

    if reason is not None:
        # Disabled path: yield status, do nothing, let any body error propagate.
        yield {"enabled": False, "reason": reason}
        return

    # Enabled path — all imports lazy and guarded.
    client = None
    trace = None
    status: dict[str, Any] = {"enabled": True, "reason": "enabled"}
    try:
        from langfuse import Langfuse  # type: ignore

        client = Langfuse(
            public_key=os.environ.get(_LANGFUSE_PUBLIC, "").strip(),
            secret_key=os.environ.get(_LANGFUSE_SECRET, "").strip(),
            host=os.environ.get(_LANGFUSE_HOST, "").strip() or None,
        )
        trace = client.trace(name=safe_name, metadata=safe_meta)
        status["trace_id"] = getattr(trace, "id", None)
    except Exception as exc:  # noqa: BLE001 - monitoring must never crash a turn
        get_logger().warning(
            "langfuse trace open failed (%s); continuing disabled",
            type(exc).__name__,
        )
        yield {"enabled": False, "reason": f"error: {type(exc).__name__}"}
        return

    body_exc: BaseException | None = None
    try:
        yield status
    except BaseException as exc:  # noqa: BLE001 - caller's body; record + re-raise
        body_exc = exc
        try:  # best-effort: record masked type name on the open trace
            if trace is not None and hasattr(trace, "update"):
                trace.update(metadata={"error_type": type(exc).__name__})
        except Exception:  # noqa: BLE001 - monitoring teardown never raises
            pass
    finally:
        # ALWAYS flush, swallowing any client/network error.
        try:
            if client is not None and hasattr(client, "flush"):
                client.flush()
        except Exception as exc:  # noqa: BLE001 - best-effort flush
            get_logger().warning("langfuse flush failed (%s)", type(exc).__name__)

    if body_exc is not None:
        raise body_exc


# --------------------------------------------------------------------------
# DeepEval scoring
# --------------------------------------------------------------------------

def deepeval_score(input_text: str, output_text: str,
                   *, metrics: Any = None) -> dict:
    """Score an input/output pair with DeepEval, degrading gracefully.

    Returns ``{'enabled': bool, 'reason': str, 'metrics': {...}}``. The disabled
    path returns ``{'enabled': False, 'reason': <reason>, 'metrics': {}}`` and
    never raises or touches the network. The enabled path runs the configured
    metrics on MASKED input/output.

    When ``metrics is None`` the default is a single
    ``AnswerRelevancyMetric(threshold=0.5, model=<SENTINEL_DEEPEVAL_MODEL>)``.
    DeepEval metrics require an LLM judge (network/keys), so if no judge model is
    configured while enabled, this degrades to
    ``reason="disabled (no judge model)"`` WITHOUT any network call. The default
    offline path never reaches the enabled code.
    """
    reason = _deepeval_reason()
    if reason is not None:
        return {"enabled": False, "reason": reason, "metrics": {}}

    # Enabled path — all imports lazy and guarded. Mask BEFORE anything is used.
    safe_in = redact_and_mask(str(input_text))
    safe_out = redact_and_mask(str(output_text))
    try:
        from deepeval import evaluate  # type: ignore
        from deepeval.metrics import AnswerRelevancyMetric  # type: ignore
        from deepeval.test_case import LLMTestCase  # type: ignore

        judge = os.environ.get(_DEEPEVAL_MODEL, "").strip()
        active = metrics or [AnswerRelevancyMetric(threshold=0.5, model=judge)]
        case = LLMTestCase(input=safe_in, actual_output=safe_out)
        evaluate([case], active)
        scores = {
            getattr(m, "__name__", type(m).__name__): getattr(m, "score", None)
            for m in active
        }
        return {"enabled": True, "reason": "enabled", "metrics": scores}
    except Exception as exc:  # noqa: BLE001 - never raise; report type only
        get_logger().warning("deepeval score failed (%s)", type(exc).__name__)
        return {"enabled": False, "reason": f"error: {type(exc).__name__}",
                "metrics": {}}


# --------------------------------------------------------------------------
# Status summary
# --------------------------------------------------------------------------

def monitoring_status() -> dict:
    """Summarise Langfuse + DeepEval enabled/reason. Never raises.

    Reports disabled even when the optional SDKs are absent. Enabled only when
    the flag is on AND the package imports AND the required config is present.
    """
    lf_reason = _langfuse_reason()
    de_reason = _deepeval_reason()
    return {
        "langfuse": {
            "enabled": lf_reason is None,
            "reason": lf_reason or "enabled",
        },
        "deepeval": {
            "enabled": de_reason is None,
            "reason": de_reason or "enabled",
        },
    }
