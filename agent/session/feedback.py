"""Phase 7 — Adaptive behaviour: operator feedback store + adaptation policy.

This is the Phase 7 layer that sits ON TOP OF the unchanged Phase 6 session and
the A1-A8 pipeline. It lets the system LEARN from operator feedback and adjust
how it PRESENTS its advice — never what it is allowed to do.

Two pieces, mirroring ``memory.py`` conventions exactly:

FeedbackRecord / FeedbackStore (LONG-TERM, persisted to JSON)
    Durable, non-sensitive operator feedback keyed by entity. Stores only
    incident metadata (entity key, metric, incident id) plus the feedback
    category/signal/rating and a free-text, non-sensitive note. NEVER stores
    secrets, credentials, or PII. Retention is bounded by ``max_records``
    (oldest pruned first); ``reset()`` is the explicit forget-all control;
    reads are resilient (missing/corrupt file -> empty store).

AdaptationPolicy / BehaviorProfile (STATELESS, deterministic)
    Reads accumulated feedback for an entity and derives a small set of SAFE,
    ADVISORY-ONLY presentation adjustments. The policy NEVER weakens the safety
    posture: it never auto-approves actions, never escalates privileges, never
    suppresses escalation, and never rewrites A1-A8 output. Every applied
    adjustment carries a structured, human-readable explanation
    ("applied X because N operator(s) gave feedback Y on entity Z").

Chosen adjustments (all advisory, deterministic, per-entity count driven):
  1. severity_nudge     — >= ADAPTATION_MIN_COUNT ``severity_too_low`` feedback
                           -> surface an advisory recommendation to CONSIDER a
                           higher severity (A3's value is shown, not changed).
  2. concise            — >= ADAPTATION_MIN_COUNT ``too_verbose`` feedback
                           -> render a trimmed response (safety/escalation
                           lines always preserved).
  3. recurrence_emphasis — >= 1 prior incident for the entity AND >= 1 negative
                           feedback of any category -> stronger recurrence banner.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# Trigger thresholds. Kept as named constants so they are easy to tune + test.
ADAPTATION_MIN_COUNT = 2

# Feedback categories that count as "negative" regardless of signal/rating.
NEGATIVE_CATEGORIES = {"severity_too_low", "too_verbose", "wrong_recipient"}


# ==========================================================================
# Feedback record + long-term store
# ==========================================================================

@dataclass
class FeedbackRecord:
    """One piece of operator feedback on a handled incident, keyed by entity.

    Holds only non-sensitive incident metadata + the feedback itself. No
    secrets, credentials, or PII are ever stored here.
    """

    feedback_id: str
    entity: str
    metric: str
    incident_id: str
    signal: str = "down"                 # "up"|"down"|"thumbs_up"|"thumbs_down"
    rating: Optional[int] = None         # optional 1-5 rating
    category: str = "other"              # severity_too_low|too_verbose|wrong_recipient|other
    note: str = ""                       # free text, non-sensitive
    ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeedbackRecord":
        return cls(
            feedback_id=d.get("feedback_id", ""),
            entity=d.get("entity", ""),
            metric=d.get("metric", ""),
            incident_id=d.get("incident_id", ""),
            signal=d.get("signal", "down"),
            rating=d.get("rating"),
            category=d.get("category", "other"),
            note=d.get("note", ""),
            ts=d.get("ts", _utc_now()),
        )

    def is_negative(self) -> bool:
        """True when this feedback expresses dissatisfaction.

        Negative when the signal is a thumbs-down, the rating is low (<= 2), or
        the category is one of the known negative tags.
        """
        if self.signal in {"down", "thumbs_down"}:
            return True
        if self.rating is not None and self.rating <= 2:
            return True
        return self.category in NEGATIVE_CATEGORIES


class FeedbackStore:
    """Durable, JSON-backed store of operator feedback (long-term).

    Mirrors ``IncidentMemoryStore``: RETENTION is the default (records persist
    across sessions + restarts, bounded by ``max_records`` with oldest pruned
    first); ``reset()`` is the explicit forget-all control; reads are resilient
    (missing/corrupt file -> empty store). Stores ONLY non-sensitive metadata +
    feedback categories/notes — never secrets or PII.
    """

    def __init__(self, path: Path | str, max_records: int = 500):
        self.path = Path(path)
        self.max_records = max_records
        self._records: list[FeedbackRecord] = []
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw.get("records", []) if isinstance(raw, dict) else raw
            self._records = [FeedbackRecord.from_dict(d) for d in items if isinstance(d, dict)]
        except (json.JSONDecodeError, OSError, TypeError):
            # Corrupt/unreadable store -> start empty rather than crash.
            self._records = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": _utc_now(),
                   "records": [r.to_dict() for r in self._records]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    # -- writes ------------------------------------------------------------

    def add(self, record: FeedbackRecord) -> None:
        self._records.append(record)
        # Retention rule: bound total stored records (prune oldest first).
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]
        self._save()

    # -- reads -------------------------------------------------------------

    def all(self) -> list[FeedbackRecord]:
        return list(self._records)

    def for_entity(self, entity: str) -> list[FeedbackRecord]:
        """Return feedback for an entity, newest first."""
        hits = [r for r in self._records if r.entity == entity]
        return list(reversed(hits))

    def category_counts(self, entity: Optional[str] = None) -> dict[str, int]:
        """Count feedback by category (optionally scoped to one entity)."""
        counts: dict[str, int] = {}
        for r in self._records:
            if entity is not None and r.entity != entity:
                continue
            counts[r.category] = counts.get(r.category, 0) + 1
        return counts

    def entity_counts(self) -> dict[str, int]:
        """Count feedback by entity."""
        counts: dict[str, int] = {}
        for r in self._records:
            counts[r.entity] = counts.get(r.entity, 0) + 1
        return counts

    def count_for_category(self, entity: str, category: str) -> int:
        """How many feedback records of ``category`` exist for ``entity``."""
        return sum(1 for r in self._records
                   if r.entity == entity and r.category == category)

    def negative_count(self, entity: str) -> int:
        """How many NEGATIVE feedback records exist for ``entity``."""
        return sum(1 for r in self._records
                   if r.entity == entity and r.is_negative())

    @property
    def count(self) -> int:
        return len(self._records)

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        """Explicitly forget all feedback (and clear the file)."""
        self._records = []
        self._save()


# ==========================================================================
# Behaviour profile + adaptation policy
# ==========================================================================

@dataclass
class BehaviorProfile:
    """The derived, advisory-only presentation adjustments for one entity.

    Each flag is a PRESENTATION change only. ``explanations`` carries one
    structured, human-readable line per applied adjustment so every change is
    explainable in-line.
    """

    entity: str = ""
    severity_nudge: bool = False
    concise: bool = False
    recurrence_emphasis: bool = False
    explanations: list[str] = field(default_factory=list)

    def any_applied(self) -> bool:
        return self.severity_nudge or self.concise or self.recurrence_emphasis

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptationPolicy:
    """Stateless, deterministic policy mapping feedback -> advisory adjustments.

    Reads the ``FeedbackStore`` for an entity and derives a ``BehaviorProfile``.
    When no trigger fires, the profile has every flag False and no explanations,
    so the session renders identically to Phase 6 (clean before/after).

    SAFETY: the policy only ever adjusts PRESENTATION. It never auto-approves an
    action, never escalates privileges, never suppresses escalation, and never
    rewrites A1-A8 output. It reads only counts/categories/entity key/notes —
    never a secret or PII.
    """

    def __init__(self, store: FeedbackStore, min_count: int = ADAPTATION_MIN_COUNT):
        self.store = store
        self.min_count = min_count

    def derive(self, entity: str, recurrence_count: int = 0) -> BehaviorProfile:
        profile = BehaviorProfile(entity=entity)
        if not entity:
            return profile

        severity_hits = self.store.count_for_category(entity, "severity_too_low")
        verbose_hits = self.store.count_for_category(entity, "too_verbose")
        negative_hits = self.store.negative_count(entity)

        # (1) Severity nudge — advisory recommendation only; A3 unchanged.
        if severity_hits >= self.min_count:
            profile.severity_nudge = True
            profile.explanations.append(
                f"severity_nudge: {severity_hits} operator(s) flagged "
                f"severity_too_low on {entity} — advisory recommendation to "
                f"consider a higher severity (A3 output unchanged)."
            )

        # (2) Concise mode — trim presentation; safety/escalation always kept.
        if verbose_hits >= self.min_count:
            profile.concise = True
            profile.explanations.append(
                f"concise: {verbose_hits} operator(s) flagged too_verbose on "
                f"{entity} — rendering a concise response (safety + escalation "
                f"lines preserved)."
            )

        # (3) Recurrence emphasis — stronger banner when the entity recurs AND
        #     has negative feedback history.
        if recurrence_count >= 1 and negative_hits >= 1:
            profile.recurrence_emphasis = True
            profile.explanations.append(
                f"recurrence_emphasis: {recurrence_count} prior incident(s) and "
                f"{negative_hits} negative operator feedback item(s) on {entity} "
                f"— surfacing a stronger recurrence banner."
            )

        return profile
