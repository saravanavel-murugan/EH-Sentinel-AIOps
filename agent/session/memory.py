"""Phase 6 — Memory handling for the Sentinel multi-agent workflow.

Two distinct memories, matching the Phase 6 requirement (short-term / long-term,
with reset vs. retention rules):

ConversationMemory (SHORT-TERM, in-process, per session)
    The running state of one operator conversation: an ordered list of turns
    (user input + agent summary) plus a small "working set" of facts the agent
    should keep in mind across turns (e.g. the entity currently in focus, the
    last incident id). Bounded by ``max_turns`` so context never grows without
    limit. Cleared by ``reset()`` when the operator starts a fresh conversation.

IncidentMemoryStore (LONG-TERM, persisted to JSON)
    Durable incident records that survive across sessions and process restarts.
    Used to (a) recall what happened last time for a given entity and
    (b) detect recurrence ("this is the 3rd lag incident on payments.settlement
    this week"). Retention is bounded by ``max_records`` (oldest pruned first)
    so the file cannot grow unbounded. ``reset()`` clears the store on disk —
    this is the deliberate, explicit "forget everything" control; normal
    operation RETAINS records.

Design notes
  * No secrets are ever stored: records hold incident metadata + knowledge
    citations, never credentials or the raw .env.
  * Long-term storage is plain JSON under ``logs/`` so it is inspectable and
    needs no database. The path is configurable for tests (temp dirs).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ==========================================================================
# Short-term conversation memory
# ==========================================================================

@dataclass
class Turn:
    """One exchange in a conversation (operator input -> agent summary)."""

    index: int
    role: str          # "user" | "agent" | "system"
    text: str
    ts: str = field(default_factory=_utc_now)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationMemory:
    """Bounded short-term memory for a single conversation.

    Holds the recent turns and a small key/value working set of facts the agent
    carries across turns within the SAME session. Resetting clears both.
    """

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self._turns: list[Turn] = []
        self._working_set: dict[str, Any] = {}
        self._counter = 0

    # -- turns -------------------------------------------------------------

    def add_turn(self, role: str, text: str, meta: Optional[dict[str, Any]] = None) -> Turn:
        self._counter += 1
        turn = Turn(index=self._counter, role=role, text=text, meta=meta or {})
        self._turns.append(turn)
        # Retention rule: keep only the most recent ``max_turns`` turns so the
        # short-term context stays bounded across a long conversation.
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns:]
        return turn

    @property
    def turns(self) -> list[Turn]:
        return list(self._turns)

    def recent(self, n: int = 5) -> list[Turn]:
        return self._turns[-n:]

    @property
    def turn_count(self) -> int:
        """Total turns observed this session (not capped by the window)."""
        return self._counter

    # -- working set (facts carried across turns) --------------------------

    def remember(self, key: str, value: Any) -> None:
        self._working_set[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        return self._working_set.get(key, default)

    @property
    def working_set(self) -> dict[str, Any]:
        return dict(self._working_set)

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        """Forget the current conversation (turns + working set). The turn
        counter restarts so a reset conversation begins at turn 1 again."""
        self._turns.clear()
        self._working_set.clear()
        self._counter = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_count": self._counter,
            "window": self.max_turns,
            "working_set": self._working_set,
            "turns": [t.to_dict() for t in self._turns],
        }


# ==========================================================================
# Long-term incident memory (persisted)
# ==========================================================================

@dataclass
class IncidentRecord:
    """A durable summary of one handled incident, keyed by entity."""

    incident_id: str
    entity: str
    metric: str
    classification: str
    severity: Optional[str]
    summary: str
    closure_recommendation: str
    knowledge_references: list[str] = field(default_factory=list)
    ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IncidentRecord":
        return cls(
            incident_id=d.get("incident_id", ""),
            entity=d.get("entity", ""),
            metric=d.get("metric", ""),
            classification=d.get("classification", ""),
            severity=d.get("severity"),
            summary=d.get("summary", ""),
            closure_recommendation=d.get("closure_recommendation", ""),
            knowledge_references=list(d.get("knowledge_references", []) or []),
            ts=d.get("ts", _utc_now()),
        )


class IncidentMemoryStore:
    """Durable, JSON-backed store of past incidents (long-term memory).

    RETENTION is the default: records persist across sessions and restarts,
    bounded by ``max_records`` (oldest pruned first). ``reset()`` is the explicit
    forget-all control. Reads are resilient: a missing or corrupt file yields an
    empty store rather than crashing.
    """

    def __init__(self, path: Path | str, max_records: int = 200):
        self.path = Path(path)
        self.max_records = max_records
        self._records: list[IncidentRecord] = []
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw.get("records", []) if isinstance(raw, dict) else raw
            self._records = [IncidentRecord.from_dict(d) for d in items if isinstance(d, dict)]
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

    def add(self, record: IncidentRecord) -> None:
        self._records.append(record)
        # Retention rule: bound total stored records (prune oldest first).
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]
        self._save()

    # -- reads -------------------------------------------------------------

    def all(self) -> list[IncidentRecord]:
        return list(self._records)

    def for_entity(self, entity: str) -> list[IncidentRecord]:
        """Return records for an entity, newest first."""
        hits = [r for r in self._records if r.entity == entity]
        return list(reversed(hits))

    def last_for_entity(self, entity: str) -> Optional[IncidentRecord]:
        hits = self.for_entity(entity)
        return hits[0] if hits else None

    def recurrence_count(self, entity: str, metric: Optional[str] = None) -> int:
        """How many prior incidents exist for this entity (optionally metric).

        Lets the agent say "this is a recurring issue" — a concrete benefit of
        long-term memory over the stateless baseline.
        """
        return sum(
            1 for r in self._records
            if r.entity == entity and (metric is None or r.metric == metric)
        )

    @property
    def count(self) -> int:
        return len(self._records)

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        """Explicitly forget all long-term records (and clear the file)."""
        self._records = []
        self._save()
