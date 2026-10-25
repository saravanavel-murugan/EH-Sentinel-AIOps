"""R1 — deterministic domain-scope guardrail.

A pure, dependency-free module. No LLM, no network, no import-time side effects
beyond computing the effective allow set once. The SINGLE public scope contract
is :func:`classify_scope` — a 3-way classifier. There is deliberately NO
``is_in_scope`` boolean facade: every wiring site (``handle_turn``'s refusal
gate, the demo script, the UI live-check) needs the full 3-way value, and a
lossy wrapper would collapse ``needs_clarification`` into a false refusal.

Gate contract (enforced in ``SentinelSession.handle_turn``): refusal fires IF
AND ONLY IF ``classify_scope(text)[0] == SCOPE_OUT``. ``needs_clarification`` and
``in_scope`` both fall through to normal routing.

The classifier is deterministic (reproducible evidence), offline by
construction, zero-latency, and cannot itself be prompt-injected.
"""

from __future__ import annotations

import re

from .core_agent import BaselineAgent

SCOPE_IN = "in_scope"
SCOPE_OUT = "out_of_scope"
SCOPE_CLARIFY = "needs_clarification"

# Static, self-contained Kafka / ops vocabulary (source of truth for scope).
ALLOW_VOCAB: frozenset[str] = frozenset({
    "kafka", "broker", "partition", "partitions", "topic", "topics",
    "consumer", "producer", "consumer_lag", "lag", "zookeeper", "connector",
    "connect", "schema", "registry", "isr", "replication", "replica", "offset",
    "offsets", "cluster", "throughput", "confluent", "incident", "alert",
    "triage", "severity", "rca", "root cause", "escalation", "ticket",
    "runbook", "retention", "rebalance", "controller", "quorum",
    # multi-word phrases matched explicitly (see classify_scope)
    "schema registry", "consumer lag",
})

# Known multi-word phrases to match against the raw lowercase text.
_MULTI_WORD_PHRASES: tuple[str, ...] = (
    "schema registry", "consumer lag", "root cause",
)

# Bare greetings / acknowledgements that are too thin to classify.
_GREETINGS: frozenset[str] = frozenset({
    "hi", "hello", "hey", "thanks", "ok", "help",
})

_WORD_RE = re.compile(r"[a-z0-9_]+")
_MAX_CHARS = 20000


def _derive_dynamic_vocab() -> frozenset[str]:
    """Optionally widen ALLOW_VOCAB from the REAL baseline data (read-only).

    The ops vocabulary lives in ``agent/baseline_data.py`` (STATIC_THRESHOLDS,
    ENTITY_TABLE, INTENT_KEYWORDS), NOT in ``baseline_rules.py``. None of those
    constants are bare word tokens, so this extracts word-like fragments. Any
    import failure falls back silently to the static set. The dynamic set only
    WIDENS acceptance — it can never move a term from in-scope to out-of-scope.
    """
    try:
        from agent.baseline_data import (
            STATIC_THRESHOLDS, ENTITY_TABLE, INTENT_KEYWORDS,
        )
    except Exception:
        return frozenset()
    toks: set[str] = set()
    # metric names: split underscore phrases into their word parts
    for metric in STATIC_THRESHOLDS:                  # e.g. "consumer_lag"
        toks.update(metric.lower().split("_"))        # -> consumer, lag
    # entity "type:id" keys: split on ':' then '.' into word parts
    for key in ENTITY_TABLE:                          # e.g. "topic:payments.settlement"
        for frag in key.lower().replace(":", ".").split("."):
            if frag.isalpha():                        # keep word-like fragments only
                toks.add(frag)                        # -> topic, payments, settlement
    # intent keyword substrings: flatten and split on whitespace
    for kws in INTENT_KEYWORDS.values():              # e.g. ["root cause", "p1"]
        for kw in kws:
            toks.update(t for t in kw.lower().split() if t.isalpha())
    return frozenset(toks)


# Effective allow set — computed ONCE at import. If the dynamic import fails,
# the static ALLOW_VOCAB alone already covers the core Kafka/ops terms.
_EFFECTIVE_ALLOW: frozenset[str] = ALLOW_VOCAB | _derive_dynamic_vocab()


def classify_scope(text: str) -> tuple[str, str]:
    """Return ``(scope, reason)`` where scope is one of the SCOPE_* constants.

    Ordered, total algorithm (never raises):

    1. Signal JSON always passes -> (SCOPE_IN, "normalized signal JSON").
    2. Empty / bare greeting / fewer than 3 word tokens
       -> (SCOPE_CLARIFY, "greeting or too short to classify").
    3. Allow-vocabulary / known multi-word phrase hit
       -> (SCOPE_IN, "matched kafka/ops vocabulary: <term>").
    4. Otherwise -> (SCOPE_OUT, "no in-domain terms detected").

    This is the ONLY scope API. No ``is_in_scope`` facade.
    """
    raw = str(text or "").strip()[:_MAX_CHARS]

    # (1) Signal JSON is authoritative — never block the incident pipeline.
    if BaselineAgent._try_parse_signal(raw) is not None:
        return (SCOPE_IN, "normalized signal JSON")

    lowered = raw.lower()
    tokens = _WORD_RE.findall(lowered)

    # (2) Empty / greeting / too short to classify.
    if not raw or lowered in _GREETINGS or len(tokens) < 3:
        return (SCOPE_CLARIFY, "greeting or too short to classify")

    # (3) Multi-word phrases first (they span token boundaries), then singles.
    for phrase in _MULTI_WORD_PHRASES:
        if phrase in lowered:
            return (SCOPE_IN, f"matched kafka/ops vocabulary: {phrase}")
    for tok in tokens:
        if tok in _EFFECTIVE_ALLOW:
            return (SCOPE_IN, f"matched kafka/ops vocabulary: {tok}")

    # (4) No in-domain terms detected.
    return (SCOPE_OUT, "no in-domain terms detected")
