# Phase 7 — Streamlit UI adaptive-behaviour evidence (before vs after)
# generated: 2026-10-24T20:21:21.669560+00:00
# provider: openai  retrieval: False

Reproduces the exact operator flow in `ui/streamlit_app.py`:
a signal turn, operator feedback via the sidebar form, then the same
entity's signal again. Panels below are what the Streamlit UI renders.

## UI panel — Adaptive behaviour (BEFORE feedback)
- No adaptation applied for topic:payments.settlement — identical to the pre-feedback baseline.
- adaptation flags: `{'entity': 'topic:payments.settlement', 'severity_nudge': False, 'concise': False, 'recurrence_emphasis': False, 'explanations': []}`

## UI sidebar — feedback submitted (non-sensitive)
- fb-1  severity_too_low  negative=True  (now 1 for entity)  note: operator felt severity understated the business risk
- fb-2  severity_too_low  negative=True  (now 2 for entity)  note: second operator agreed
- fb-3  too_verbose  negative=True  (now 3 for entity)  note: too long for triage
- fb-4  too_verbose  negative=True  (now 4 for entity)  note: prefer a concise summary

## UI panel — Adaptive behaviour (AFTER feedback)
- Adaptation applied (advisory) for topic:payments.settlement: 📊 Severity nudge · ✂️ Concise mode · 🔁 Recurrence emphasis
- badges: ['📊 Severity nudge', '✂️ Concise mode', '🔁 Recurrence emphasis']
- adaptation flags: `{'entity': 'topic:payments.settlement', 'severity_nudge': True, 'concise': True, 'recurrence_emphasis': True, 'explanations': ['severity_nudge: 2 operator(s) flagged severity_too_low on topic:payments.settlement — advisory recommendation to consider a higher severity (A3 output unchanged).', 'concise: 2 operator(s) flagged too_verbose on topic:payments.settlement — rendering a concise response (safety + escalation lines preserved).', 'recurrence_emphasis: 1 prior incident(s) and 4 negative operator feedback item(s) on topic:payments.settlement — surfacing a stronger recurrence banner.']}`

### Why these changes fired (feedback evidence shown in the UI expander)
- severity_nudge: 2 operator(s) flagged severity_too_low on topic:payments.settlement — advisory recommendation to consider a higher severity (A3 output unchanged).
- concise: 2 operator(s) flagged too_verbose on topic:payments.settlement — rendering a concise response (safety + escalation lines preserved).
- recurrence_emphasis: 1 prior incident(s) and 4 negative operator feedback item(s) on topic:payments.settlement — surfacing a stronger recurrence banner.

## UI sidebar — feedback summary
- count: 4
- category_counts: `{'severity_too_low': 2, 'too_verbose': 2}`

## Safety invariant
- The advisory safety NOTE is preserved in BOTH the before and after responses; adaptation changes presentation only and never alters A1–A8 decisions, approval requirements, or escalation.