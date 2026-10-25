# Baseline Agent Limitations (Phase 2)

**Project:** EventHub Ops – Sentinel
**Phase 2 artifact** — documents the baseline rules/template agent, demonstrates its
limitations with real run evidence, and explains why it is insufficient for real users.

> The baseline is **intentionally naive**. Its job is to establish a working end-to-end
> skeleton and make the gaps obvious, so later phases (3 LLM, 4 retrieval, 5 tools,
> 6 memory/planning, 7 adaptation) each close a specific gap with evidence.

---

## 1. What the baseline does

A stateless Python agent (`agent/core_agent.py`) that accepts either:

- a **normalized-signal JSON** (schema in `inputs.md`), or
- a **free-text operator question**,

and produces a templated triage response using only deterministic logic:

- `classify_signal` — flat static threshold per metric → confirmed / likely / transient / noise.
- `lookup_entity` — exact-match lookup in a small hard-coded table (from `events_stakeholder_summary.md`).
- `estimate_severity` — coarse `criticality_tier × classification` matrix → P1–P4.
- `classify_intent` — substring keyword match for free-text questions.
- Template rendering — fixed string templates, no natural-language generation.

No LLM, no retrieval, no memory, no tools, no correlation. Every interaction is logged as a
JSON line to `logs/interactions.log`.

**Run commands:**

```bash
# forced demo batch (primary evidence)
python scripts/run_agent.py --batch data/evaluation/phase2_demo_inputs.txt

# single signal from a file (robust on Windows PowerShell)
python scripts/run_agent.py --query-file data/evaluation/sample_signal.json

# interactive
python scripts/run_agent.py
```

---

## 2. Demonstrated limitations (with run evidence)

The forced demo (`data/evaluation/phase2_demo_inputs.txt`, 11 interactions) was run and logged.
The limitations below are reproduced directly from that run.

### Limitation 1 — Brittle keyword/intent matching (no language understanding)

Free-text questions are matched by raw substring keywords. A natural paraphrase with no keyword
falls through to a generic failure.

- **Input (interaction 3):** `Is this topic falling behind and should I be worried?`
- **Baseline output:** `I could not match your question to a known baseline intent...`
- **Why it fails:** "falling behind" is exactly consumer lag, but no keyword matched. A real
  operator phrases things many ways; the baseline only understands a fixed vocabulary.

Even when a keyword *does* match, the baseline cannot use the prose:

- **Input (interaction 4):** `Who do I notify for payments?`
- **Baseline output:** "...Provide the exact entity." (it matched `ask_stakeholders` but cannot
  extract `topic:payments.settlement` from the sentence).

### Limitation 2 — No correlation, no deduplication, no memory (stateless)

Each input is handled in isolation. An alert storm of near-identical signals produces N separate
full responses instead of one deduplicated incident.

- **Input (interactions 6–8):** three near-duplicate `produce_error_rate` alerts on
  `topic:cards.authorization` (values 35, 36, 34 errors/s).
- **Baseline output:** **three** identical P1 triage blocks — one per alert.
- **Why it fails:** real on-call would be paged three times for one issue. The baseline has no
  state to remember it already saw this fingerprint, so it cannot collapse duplicates or
  correlate related symptoms into a single incident.

### Limitation 3 — No real reasoning or knowledge (hard-coded tables only)

Severity is a two-dimensional lookup, entity knowledge is a tiny static table, and there is no
root-cause reasoning or recovery verification.

- **Unknown entity (interaction 5):** `topic:loans.disbursement` → "not in the baseline lookup
  table ... cannot determine business impact or stakeholders." Any entity outside the table is
  invisible to the baseline.
- **Unknown metric (interaction 9):** `disk_usage` on `broker-3` → `insufficient_evidence` with
  no rule, and the broker entity is also unknown — so a real disk-pressure signal produces nothing
  useful.
- **No nuance (interaction 10):** `consumer_lag=1000` on Tier-1 `topic:trades.execution` →
  classified `noise`/P4 purely on the flat threshold, with no notion of trend, duration, or
  whether 1000 is abnormal *for that topic*.
- **No recovery (interaction 11):** `Has the payments incident recovered yet?` → "Baseline has no
  recovery verification ... it only sees one input at a time."

---

## 3. Why this version is insufficient for real users

The primary persona (Platform Ops on-call operator, see `personas.md`) needs fast, trustworthy
triage under pressure. The baseline fails that bar because:

- **It breaks on real language.** Operators do not speak in keywords; brittle matching produces
  dead-ends exactly when speed matters.
- **It amplifies alert fatigue instead of reducing it.** With no dedup/correlation, an alert storm
  becomes a response storm — the opposite of the stated goal (reduce noise and time-to-triage).
- **It cannot reason or explain.** No ranked root-cause hypotheses, no evidence for/against, no
  next diagnostic check — the operator still has to do the hard thinking alone.
- **Its knowledge is frozen and tiny.** A hard-coded table cannot keep up with a real platform's
  entities, ownership changes, or new metrics; unknown entities/metrics simply disappear.
- **It cannot close the loop.** No recovery verification and no feedback means it can neither
  confirm resolution nor improve over time.

In short, the baseline is a transparent skeleton, not a usable assistant.

---

## 4. What later phases fix (traceability forward)

| Baseline limitation | Fixed in | How |
|---------------------|----------|-----|
| Brittle keyword matching / no language understanding | Phase 3 (LLM) | Natural-language understanding + prompt strategies |
| Frozen, tiny knowledge table; unknown entities/metrics | Phase 4 (Retrieval) | Embeddings + semantic search over the knowledge base/catalogue |
| No tool use (cannot fetch evidence or act safely) | Phase 5 (Tools) | Tool/function calling with guardrails |
| Stateless; no correlation/dedup/memory | Phase 6 (Planning & Memory) | Multi-step reasoning + short/long-term memory |
| Cannot learn from operators | Phase 7 (Adaptive behaviour) | Feedback capture + behaviour adjustment |
| No evaluation of quality | Phase 9 (Evaluation) | Test harness, metrics, root-cause analysis |

---

## 5. Evidence artifacts

- Code: `agent/core_agent.py`, `agent/baseline_rules.py`, `agent/baseline_templates.py`, `agent/baseline_data.py`
- CLI: `scripts/run_agent.py`
- Forced inputs: `data/evaluation/phase2_demo_inputs.txt`
- Sample log: `logs/interactions.log` (11 JSON-line records from the demo run)
- Demo walkthrough: `phases/phase2/demo_script.md`
