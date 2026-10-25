# Phase 7 — Adaptive Behaviour

Phase 7 lets Sentinel **learn from operator feedback** and adjust how it
**presents** its advice — never what it is allowed to do. The system records
non-sensitive feedback on handled incidents and, on the next signal for the same
entity, applies a small set of **advisory-only** presentation adjustments, each
with a structured explanation.

Everything is **additive**. The A1–A8 pipeline (Phase 3b), RAG (Phase 4),
tools/MCP (Phase 5), and the Phase 6 session are reused unchanged through their
public facades. With **no feedback on record, behaviour is identical to
Phase 6** — a clean before/after.

## New building blocks (`agent/session/feedback.py`)

| Component | Responsibility |
|-----------|----------------|
| `FeedbackRecord` | One piece of operator feedback keyed by entity — `feedback_id`, `entity`, `metric`, `incident_id`, `signal`, optional `rating`, `category`, non-sensitive `note`, `ts`. `to_dict`/`from_dict` mirror `IncidentRecord`; `is_negative()` classifies dissatisfaction. |
| `FeedbackStore` | Durable, JSON-persisted long-term store (`logs/feedback.json`) mirroring `IncidentMemoryStore` exactly: bounded `max_records` (prune oldest), resilient load (missing/corrupt → empty), `add`, `all`, `for_entity`, `category_counts`, `entity_counts`, `count_for_category`, `negative_count`, `reset`. |
| `BehaviorProfile` | The derived, advisory-only adjustments for one entity: `severity_nudge`, `concise`, `recurrence_emphasis`, plus `explanations[]`. `any_applied()` / `to_dict()`. |
| `AdaptationPolicy` | Stateless, deterministic policy. `derive(entity, recurrence_count)` reads the store and returns a `BehaviorProfile`. No feedback ⇒ nothing applied. |
| session wiring | `SentinelSession` builds a `FeedbackStore` + `AdaptationPolicy`, adds `record_feedback(...)`, consults the policy before rendering a signal turn, surfaces an **ADAPTATION** section, extends `snapshot()`, and adds `clear_feedback()`. |

CLI demo: `scripts/run_phase7_feedback_demo.py`.

## How feedback is stored

Feedback is persisted as plain JSON at `logs/feedback.json` so it is inspectable
and needs no database. The store holds **only** non-sensitive incident metadata
(entity key, metric, incident id) plus the feedback itself (signal, optional
rating, category, a free-text non-sensitive note). **No secrets, credentials, or
PII are ever stored.** Reads are resilient: a missing or corrupt file degrades to
an empty store rather than crashing. Retention is bounded by `max_records`
(oldest pruned first).

A feedback item counts as **negative** when its `signal` is `down`/`thumbs_down`,
its `rating` is `<= 2`, or its `category` is one of the known negative tags
(`severity_too_low`, `too_verbose`, `wrong_recipient`).

## Adaptation logic — the three adjustments

All adjustments are **advisory**. They change presentation only; each is
triggered by a per-entity count reaching a threshold and carries a structured
explanation (`applied X because N operator(s) gave feedback Y on entity Z`).

| # | Adjustment | Trigger | Effect (advisory) |
|---|-----------|---------|-------------------|
| 1 | **Severity nudge** | `>= ADAPTATION_MIN_COUNT` (2) `severity_too_low` for the entity | Adds an ADAPTATION note that shows A3's severity (**unchanged**) and recommends the operator *consider* a higher severity, with the count. A3 output is never rewritten. |
| 2 | **Concise mode** | `>= ADAPTATION_MIN_COUNT` (2) `too_verbose` for the entity | Renders a trimmed body (A1/A3/A5/A7/A8 key lines). The safety `NOTE` and escalation info are **always** preserved. |
| 3 | **Recurrence emphasis** | `>= 1` prior incident for the entity **and** `>= 1` negative feedback item | Replaces the normal recurrence line with a stronger banner noting prior negative operator feedback. |

Thresholds are named constants in `feedback.py` (`ADAPTATION_MIN_COUNT = 2`;
recurrence uses `>= 1`) so they are easy to tune and test.

## Reset / retention rules

| Action | Short-term memory | Long-term incidents | Feedback |
|--------|------------------|---------------------|----------|
| `reset` / "new incident" turn | **cleared** | retained | **retained** (by design) |
| store overflow (`max_records`) | — | oldest pruned | oldest pruned |
| corrupt / missing store file | — | → empty store | → empty store |
| `clear_long_term_memory()` | — | **cleared** | — |
| `clear_feedback()` | — | — | **cleared** (explicit forget-all) |

Normal operation retains feedback; forgetting it is a deliberate, explicit
control via `clear_feedback()`.

## Before-vs-after narrative

The demo (`scripts/run_phase7_feedback_demo.py`) drives one entity through a
clean before/after on the offline fake provider:

1. **BEFORE** — a signal turn with no feedback on record. `out["adaptation"]`
   has every flag `False` and the render is the full Phase-6 pipeline block.
2. Four non-sensitive negative feedback items are recorded for the entity (two
   `severity_too_low`, two `too_verbose`).
3. **AFTER** — the same entity signal runs again. The response now carries an
   **ADAPTATION (advisory)** section, a concise body, the advisory severity
   nudge, and a stronger recurrence banner; `out["adaptation"]` flags are `True`
   with explanations.

Evidence is written to
`data/evaluation/phase7_feedback_transcript.{txt,json}`.

## In the Streamlit UI (`ui/streamlit_app.py`)

The operator console surfaces Phase 7 end to end, so an evaluator can see the
feedback → adaptation loop without the CLI:

- **Give feedback (sidebar form)** — a category selector (severity looked too
  low / too verbose / wrong recipient / other), a down/up signal, an optional
  1–5 rating, and a non-sensitive note. Submitting calls `record_feedback(...)`
  on the **in-focus** incident (entity/incident default to the session working
  set) and shows a confirmation.
- **Adaptive behaviour panel (on each signal turn)** — rendered from
  `result["adaptation"]`. With no feedback it shows a green *“no adaptation
  applied — identical to the pre-feedback baseline”* banner; once adjustments
  fire it shows the badges (📊 Severity nudge · ✂️ Concise mode · 🔁 Recurrence
  emphasis) and an expander with the per-adjustment feedback evidence.
- **Feedback summary (sidebar)** — live `count`, per-category counts, and an
  expander listing every stored feedback record (from `snapshot()["feedback"]`).
- **Forget operator feedback (sidebar)** — explicit `clear_feedback()` control,
  alongside the existing short-term reset and forget-long-term-memory controls.

The UI keeps the module's **headless import-safety**: every `st.*` call lives
inside `main()`/helpers, so `import ui.streamlit_app` stays side-effect-free.

A reproducible, no-browser evidence run of the exact UI flow (signal → sidebar
feedback → same-entity signal) is produced by
`scripts/ui_phase7_evidence.py`, which reuses the UI's own rendering helpers and
writes `data/evaluation/phase7_ui_evidence.{md,json}`.

## Running it

```bash
# from capstone_agent/
streamlit run ui/streamlit_app.py                           # rich UI (feedback form + ADAPTATION panel)
python scripts/ui_phase7_evidence.py --no-retrieval         # headless UI-flow evidence (offline)
python scripts/run_phase7_feedback_demo.py --no-retrieval   # offline before/after demo
python scripts/run_phase7_feedback_demo.py                  # with RAG (needs a FAISS index)
python scripts/run_phase7_feedback_demo.py --persist        # use the real logs/ stores
python -m pytest tests/test_feedback_adaptation.py -q
```

The demo and tests run on the offline deterministic provider (no key); with
`SENTINEL_LLM=openai` in `.env` the same session runs live.

## Safety posture

Adaptation is **advisory and never weakens the safety posture**. It:

- never changes A1–A8 output (A3 severity is shown, not rewritten);
- never auto-approves actions — A5 stays `read_only` with every action
  `requires_approval=True`;
- never escalates privileges and never suppresses A7 escalation;
- always renders the advisory safety `NOTE`, including in concise mode;
- stores only non-sensitive metadata + categories/notes — no secrets or PII.
