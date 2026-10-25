"""Phase 8 — Deployment readiness: centralized observability.

This module adds the deployment-grade cross-cutting concerns the earlier phases
left ad-hoc, WITHOUT touching the A1-A8 pipeline, the ToolAgent, or the
SentinelSession public contract. It is the single import surface for:

    * ``configure_logging()`` — idempotent, stdlib-only logging setup that writes
      structured JSON lines to ``logs/sentinel.log`` (rotating) and a
      human-readable stream to the console. Both handlers carry a redacting
      filter so NOTHING reaches disk/console un-scrubbed.
    * ``redact()`` / ``RedactingFilter`` — a PII/secret-safe scrubber. API keys
      (``sk-...``, ``voc-...``), ``OPENAI_API_KEY=...`` assignments and bearer
      tokens are replaced with ``<redacted>``; dict values under secret-looking
      key names are masked. This is a HARD Scenario-1 requirement: no secrets or
      PII ever land in a log, trace, or evidence file.
    * ``RunTrace`` + ``trace_run()`` — per-run tracing that captures a short
      ``run_id``, start/end timestamps, ``latency_ms`` and the success/error
      outcome, writes ONE redacted JSON object per run to ``logs/traces.jsonl``,
      and emits one structured log record. Only metadata is recorded — never a
      raw payload.
    * ``safe_handle_turn()`` — a thin, well-tested graceful-failure wrapper
      around ``SentinelSession.handle_turn``. On success it returns the real
      result dict unchanged; on ANY exception it records an error trace and
      returns a structured, user-facing graceful error dict (no stack trace, no
      secret, advisory/read-only posture preserved). It NEVER raises.

Design notes
------------
* Stdlib only (``logging``, ``logging.handlers``, ``time``, ``uuid``, ``json``,
  ``dataclasses``, ``contextlib``, ``re``) — Phase 8 needs no new dependency.
* No import-time side effects: ``configure_logging()`` is NOT called on import,
  so importing this module is cheap and safe (keeps the headless UI import
  green).
* Everything is deterministic and offline-capable: the default provider comes
  from ``agent.llm.provider_name()`` which honours ``SENTINEL_LLM``.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import logging.handlers
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR: Path = _REPO_ROOT / "logs"
DEFAULT_LOG_FILE = "sentinel.log"
DEFAULT_TRACE_FILE = "traces.jsonl"

LOGGER_NAME = "sentinel"
REDACTED = "<redacted>"

# --------------------------------------------------------------------------
# Redaction — the single source of truth for secret patterns (HARD requirement)
# --------------------------------------------------------------------------

# Substrings that look like credentials/tokens are replaced wholesale. These are
# the exact shapes the tests plant and assert never reach disk.
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),                 # OpenAI-style keys
    re.compile(r"voc-[A-Za-z0-9_\-]{6,}"),                # Vocareum-style keys
    re.compile(r"(?i)OPENAI_API_KEY\s*[=:]\s*\S+"),       # explicit env assignment
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]+"),         # bearer tokens
]

# Dict keys whose NAME indicates the VALUE is sensitive — the value is masked
# regardless of its shape.
_SECRET_KEY_HINTS = ("api_key", "apikey", "secret", "token", "password",
                     "passwd", "authorization", "auth_token", "access_key")


def _scrub_text(text: str) -> str:
    """Replace any secret-looking substring in ``text`` with ``<redacted>``."""
    for pat in _SECRET_PATTERNS:
        text = pat.sub(REDACTED, text)
    return text


def redact(value: Any) -> Any:
    """Recursively scrub secrets/PII-looking content from ``value``.

    Pure and I/O-free. Strings have credential substrings replaced; dict values
    under secret-looking key names are masked; lists/tuples/dicts are walked.
    Non-string scalars are returned unchanged.
    """
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and any(h in k.lower() for h in _SECRET_KEY_HINTS):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        scrubbed = [redact(v) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    return value


# --------------------------------------------------------------------------
# PII masking (R2) — folded into the SAME source of truth as secret redaction.
# --------------------------------------------------------------------------

# Typed PII patterns -> placeholder. Ordered most-specific first so a credit
# card is not partially eaten by the phone pattern, etc. These compose WITH the
# secret machinery above (they do not replace it): secret scrubbing masks
# credentials, PII masking masks personal data. IP addresses are deliberately
# NOT masked — internal cluster/broker IPs are operational context the operator
# needs, and masking them would degrade incident usefulness.
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Email — the SINGLE shipped email pattern. Its @example.com negative
    # lookahead preserves reserved directory placeholders (alice@example.com /
    # @example.org / @example.net) while masking real PII (j@gmail.com).
    (re.compile(
        r"\b[A-Za-z0-9._%+\-]+@(?!example\.(?:com|org|net)\b)"
        r"[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ), "<EMAIL>"),
    (re.compile(r"\b(?:\d[ \-]?){13,16}\b"), "<CARD>"),          # credit-card / PAN
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "<ID>"),  # IBAN
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "<ID>"),          # Aadhaar-style 12-digit
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<ID>"),             # US SSN
    # Phone: REQUIRES a phone-like anchor (a leading +CC country code OR a
    # parenthesised area code) so ordinary operational numbers (60000,
    # 2500 ms, bare NNNN NNNN runs) are NOT masked. Non-word lookarounds stop
    # it matching inside a longer digit/word run.
    (re.compile(
        r"(?<![\w.])(?:"
        r"\+\d{1,3}[ \-]?(?:\(\d{1,4}\)[ \-]?)?\d{3,4}[ \-]?\d{3,4}(?:[ \-]?\d{2,4})?"  # +CC ...
        r"|\(\d{2,4}\)[ \-]?\d{3,4}[ \-]?\d{3,4}(?:[ \-]?\d{2,4})?"                       # (area) ...
        r")(?![\w.])"
    ), "<PHONE>"),
]


def mask_pii(value: Any) -> Any:
    """Recursively replace PII with typed placeholders, same SHAPE as ``redact``.

    Pure and I/O-free, never raises. Strings have each ``_PII_PATTERNS`` entry
    applied in order; dict VALUES are walked (keys untouched and NO
    secret-key-hint masking — that stays ``redact``'s responsibility);
    list/tuple are walked and rebuilt as the same type. Any other scalar is
    returned unchanged. Called alone on ``{"api_key": "sk-x"}`` it returns the
    value unchanged (``sk-`` has no PII shape); use :func:`redact_and_mask` to
    get both secret scrubbing and PII masking in one call. Idempotent — the
    emitted placeholders have no PII shape, so a second pass is a no-op.
    """
    if isinstance(value, str):
        text = value
        for pat, placeholder in _PII_PATTERNS:
            text = pat.sub(placeholder, text)
        return text
    if isinstance(value, dict):
        return {k: mask_pii(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        masked = [mask_pii(v) for v in value]
        return type(value)(masked) if isinstance(value, tuple) else masked
    return value


def redact_and_mask(value: Any) -> Any:
    """Scrub secrets THEN mask PII — the one-call composition for callers.

    Equivalent to ``mask_pii(redact(value))``: :func:`redact` runs first
    (secret-key-hint dict values -> ``<redacted>`` and ``sk-``/``voc-``/bearer
    patterns scrubbed), then :func:`mask_pii` masks PII shapes. The emitted
    placeholders (``<EMAIL>``, ``<PHONE>``, ``<CARD>``, ``<ID>``,
    ``<redacted>``) match NEITHER ``_SECRET_PATTERNS`` NOR ``_PII_PATTERNS``, so
    the composition is idempotent:
    ``redact_and_mask(redact_and_mask(x)) == redact_and_mask(x)``.
    """
    return mask_pii(redact(value))


class RedactingFilter(logging.Filter):
    """Scrub every log record BEFORE it reaches any handler.

    Guarantees that neither the formatted message nor the structured ``extra``
    fields can carry a secret OR PII to disk/console.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        if isinstance(record.msg, str):
            record.msg = mask_pii(_scrub_text(record.msg))
        elif record.msg is not None:
            record.msg = redact_and_mask(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_and_mask(record.args)
            else:
                record.args = tuple(redact_and_mask(a) for a in record.args)
        # Redact + mask any structured extras attached via extra={...}.
        extra = getattr(record, "extra_fields", None)
        if extra is not None:
            record.extra_fields = redact_and_mask(extra)
        return True


# --------------------------------------------------------------------------
# JSON-line formatter for the file handler
# --------------------------------------------------------------------------

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {
    "message", "asctime", "taskName",
}


class JsonLineFormatter(logging.Formatter):
    """Format each record as one compact JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _dt.datetime.fromtimestamp(
                record.created, _dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            # Only the exception type/line — never the full traceback text, so a
            # stack trace cannot leak into the structured log.
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(redact(payload), ensure_ascii=False)


# --------------------------------------------------------------------------
# Logging configuration (idempotent)
# --------------------------------------------------------------------------

_CONFIGURED = False


def _resolve_level(level: str | None) -> int:
    import os

    name = (level or os.environ.get("SENTINEL_LOG_LEVEL") or "INFO").strip().upper()
    return getattr(logging, name, logging.INFO)


def configure_logging(
    log_dir: Path | str | None = None,
    level: str | None = None,
    force: bool = False,
) -> logging.Logger:
    """Configure and return the ``sentinel`` logger.

    Idempotent: repeated calls do not stack duplicate handlers (guarded by a
    module-level flag unless ``force=True``). Attaches a rotating
    JSON-line file handler (``logs/sentinel.log``) and a human-readable console
    handler, both carrying a :class:`RedactingFilter`. Level comes from the
    argument, else ``SENTINEL_LOG_LEVEL``, else ``INFO``.
    """
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    resolved_level = _resolve_level(level)
    logger.setLevel(resolved_level)

    if _CONFIGURED and not force:
        return logger

    # Replace any handlers we previously attached (clean re-config on force).
    for h in list(logger.handlers):
        logger.removeHandler(h)

    directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / DEFAULT_LOG_FILE

    redactor = RedactingFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLineFormatter())
    file_handler.addFilter(redactor)
    file_handler.setLevel(resolved_level)

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    console.addFilter(redactor)
    console.setLevel(resolved_level)

    logger.addHandler(file_handler)
    logger.addHandler(console)
    # Do not propagate to the root logger (avoids double emission).
    logger.propagate = False

    _CONFIGURED = True
    return logger


def shutdown_logging() -> None:
    """Close and detach the sentinel logger's handlers.

    Needed on Windows before deleting a temp log directory: the rotating file
    handler holds the log file open, so it must be closed first. Resets the
    idempotency flag so a later ``configure_logging()`` reinstalls cleanly.
    """
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    for h in list(logger.handlers):
        try:
            h.close()
        finally:
            logger.removeHandler(h)
    _CONFIGURED = False


def get_logger() -> logging.Logger:
    """Return the sentinel logger, configuring it with defaults if needed."""
    if not _CONFIGURED:
        return configure_logging()
    return logging.getLogger(LOGGER_NAME)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def new_run_id() -> str:
    """A short, unique run identifier, e.g. ``run-1a2b3c4d``."""
    return "run-" + uuid.uuid4().hex[:8]


def latency_ms(start: float) -> int:
    """Elapsed milliseconds since ``start`` (a ``time.perf_counter()`` value)."""
    return round((time.perf_counter() - start) * 1000)


# --------------------------------------------------------------------------
# Run tracing
# --------------------------------------------------------------------------

@dataclass
class RunTrace:
    """One structured trace record per traced run (metadata only, redacted)."""

    run_id: str
    entry_point: str
    provider: str
    status: str = "ok"                 # "ok" | "error"
    latency_ms: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """A redacted, JSON-serializable view of the trace."""
        payload = {
            "run_id": self.run_id,
            "entry_point": self.entry_point,
            "provider": self.provider,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "extra": self.extra,
        }
        return redact(payload)


def _write_trace_line(trace: RunTrace, log_dir: Path | str | None,
                      trace_file: str | None) -> None:
    directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (trace_file or DEFAULT_TRACE_FILE)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(trace.to_dict(), ensure_ascii=False) + "\n")


@contextmanager
def trace_run(
    entry_point: str,
    provider: str | None = None,
    log_dir: Path | str | None = None,
    trace_file: str | None = None,
    **extra: Any,
) -> Iterator[RunTrace]:
    """Context manager that records latency + outcome for one run.

    Yields a :class:`RunTrace` so the caller may attach whitelisted metadata to
    ``.extra`` (never a raw payload). On exit — success OR exception — it sets
    ``latency_ms``, ``status`` and (on failure) ``error_type``/``error_message``,
    writes ONE redacted JSON line to ``logs/traces.jsonl`` and emits one
    structured log record. The exception is re-raised after recording so the
    caller decides recovery.
    """
    if provider is None:
        try:
            from .llm import provider_name

            provider = provider_name()
        except Exception:  # noqa: BLE001 - provider is best-effort metadata
            provider = "unknown"

    logger = get_logger()
    trace = RunTrace(
        run_id=new_run_id(),
        entry_point=entry_point,
        provider=provider,
        extra=dict(extra),
        started_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    start = time.perf_counter()
    try:
        yield trace
    except BaseException as exc:  # noqa: BLE001 - record then re-raise
        trace.status = "error"
        trace.error_type = type(exc).__name__
        trace.error_message = _scrub_text(str(exc))
        trace.latency_ms = latency_ms(start)
        trace.ended_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        _write_trace_line(trace, log_dir, trace_file)
        logger.error("run %s failed (%s)", trace.run_id, trace.error_type,
                     extra={"extra_fields": trace.to_dict()})
        raise
    else:
        if trace.status == "ok":
            trace.latency_ms = latency_ms(start)
            trace.ended_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        _write_trace_line(trace, log_dir, trace_file)
        logger.info("run %s ok (%sms)", trace.run_id, trace.latency_ms,
                    extra={"extra_fields": trace.to_dict()})


# --------------------------------------------------------------------------
# Graceful failure wrapper
# --------------------------------------------------------------------------

_SAFE_MESSAGE = (
    "Sentinel could not complete this turn due to an internal error. No "
    "production action was taken; the system remains advisory and read-only. "
    "Please retry, or check the service logs (by run id) for details."
)


def safe_handle_turn(
    session: Any,
    user_input: str,
    *,
    entry_point: str = "session.handle_turn",
    log_dir: Path | str | None = None,
    trace_file: str | None = None,
) -> dict[str, Any]:
    """Run ``session.handle_turn`` under a trace, degrading gracefully on error.

    On success returns the real result dict UNCHANGED (not mutated). On ANY
    exception, records an error trace and returns a structured graceful error
    dict — ``kind="error"``, ``ok=False``, the ``run_id``, a safe user-facing
    message, and an explicit note that the advisory/read-only posture is
    preserved. No stack trace or secret ever appears in the returned dict. This
    function NEVER raises.
    """
    provider = getattr(session, "provider", None)
    trace_cm = trace_run(
        entry_point,
        provider=provider,
        log_dir=log_dir,
        trace_file=trace_file,
    )
    trace = trace_cm.__enter__()
    try:
        result = session.handle_turn(user_input)
    except BaseException as exc:  # noqa: BLE001 - graceful degradation
        error_type = type(exc).__name__
        # Let trace_run record the error trace + log line, then swallow.
        try:
            trace_cm.__exit__(type(exc), exc, exc.__traceback__)
        except BaseException:  # noqa: BLE001 - the re-raised original; ignore
            pass
        return {
            "kind": "error",
            "ok": False,
            "run_id": trace.run_id,
            "provider": provider or "unknown",
            "error_type": error_type,
            "message": _SAFE_MESSAGE,
            "safety": "advisory/read-only preserved; no action taken",
            "response": _SAFE_MESSAGE,
        }
    else:
        trace_cm.__exit__(None, None, None)
        return result
