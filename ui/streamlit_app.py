"""Phase 6/7 — Streamlit UI: end-to-end multi-agent trace from signal to closure,
with Phase 7 adaptive behaviour (operator feedback → advisory adaptation).

A rich operator console over the ``SentinelSession``. It shows, for the whole
multi-agent workflow:

  * a multi-turn chat (paste a signal JSON or ask a follow-up),
  * the explicit PLAN (task decomposition) with live step status,
  * each named agent's role + output (A1 Signal Validation ... A8 Recovery
    Verification), the agent trace, and retrieval/RAG evidence,
  * short-term conversation state and long-term incident memory (with recurrence),
  * **Phase 7 — adaptive behaviour**: an operator feedback form (per in-focus
    incident), an ADAPTATION panel on each signal turn (which advisory
    adjustments fired and why), and a live feedback summary,
  * reset (short-term) vs. explicit forget-all controls for memory and feedback.

Run it:
    streamlit run ui/streamlit_app.py           # from capstone_agent/

Headless import safety: ALL Streamlit calls live inside ``main()`` / helpers that
are only invoked under ``streamlit run`` (or ``__main__``). Importing this module
(``import ui.streamlit_app``) therefore has no side effects and needs no running
Streamlit server — which keeps the offline verification check green.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the package root (capstone_agent/) is importable whether launched via
# `streamlit run ui/streamlit_app.py` or imported as `ui.streamlit_app`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SAMPLE_SIGNAL = {
    "signal_id": "sig-ui-1",
    "source": "control_center",
    "entity": {"type": "topic", "id": "payments.settlement"},
    "metric_or_event": "consumer_lag",
    "value": 60000,
    "unit": "messages",
    "environment": "prod",
}

# The AI agent's human-facing identity, so the operator can tell the assistant
# ("Vel") apart from their own messages in the chat stream.
_AGENT_NAME = "Vel"
_AGENT_AVATAR = "🛰️"
_USER_AVATAR = "🧑‍💻"

# ---- Signal catalog: top-10 preset Kafka/Confluent infra anomalies ---------
# A ready-to-run library covering brokers, zookeeper, producers/consumers, ACL
# denials (with principals), in-sync replicas, broker failure, and leader
# election. Each is a normalized-signal JSON the pipeline accepts; metrics use
# the recognized set where possible so classification is grounded. The operator
# picks one from the sidebar dropdown and it is injected as the next turn.
_SIGNAL_CATALOG: dict[str, dict] = {
    "1 · Consumer lag spike (Tier-1 topic)": {
        "signal_id": "cat-01", "source": "control_center",
        "entity": {"type": "topic", "id": "payments.settlement"},
        "metric_or_event": "consumer_lag", "value": 125000, "unit": "messages",
        "environment": "prod",
    },
    "2 · Under-replicated partitions (broker)": {
        "signal_id": "cat-02", "source": "control_center",
        "entity": {"type": "broker", "id": "broker-2"},
        "metric_or_event": "under_replicated_partitions", "value": 37,
        "unit": "count", "environment": "prod",
    },
    "3 · Broker request-queue saturation": {
        "signal_id": "cat-03", "source": "prometheus",
        "entity": {"type": "broker", "id": "broker-5"},
        "metric_or_event": "request_queue_depth", "value": 2100,
        "unit": "requests", "environment": "prod",
    },
    "4 · Broker failure / offline (ISR shrink)": {
        "signal_id": "cat-04", "source": "control_center",
        "entity": {"type": "broker", "id": "broker-4"},
        "metric_or_event": "broker_down", "value": 1, "unit": "bool",
        "environment": "prod",
    },
    "5 · Leader election storm (partition)": {
        "signal_id": "cat-05", "source": "control_center",
        "entity": {"type": "partition", "id": "cards.authorization-3"},
        "metric_or_event": "leader_election_rate", "value": 14,
        "unit": "elections/min", "environment": "prod",
    },
    "6 · ZooKeeper session expiry (metadata risk)": {
        "signal_id": "cat-06", "source": "prometheus",
        "entity": {"type": "zookeeper", "id": "zk-node-1"},
        "metric_or_event": "zk_session_expired_rate", "value": 9,
        "unit": "events/min", "environment": "prod",
    },
    "7 · ACL denied WRITE (producer principal)": {
        "signal_id": "cat-07", "source": "broker_audit",
        "entity": {"type": "topic", "id": "cards.authorization"},
        "metric_or_event": "acl_denied_write", "value": 220, "unit": "denials",
        "environment": "prod",
        "principal": "User:svc-cards-producer", "operation": "WRITE",
    },
    "8 · ACL denied READ (consumer principal)": {
        "signal_id": "cat-08", "source": "broker_audit",
        "entity": {"type": "consumer_group", "id": "fraud.scoring"},
        "metric_or_event": "acl_denied_read", "value": 180, "unit": "denials",
        "environment": "prod",
        "principal": "User:svc-fraud-consumer", "operation": "READ",
    },
    "9 · Producer error / retry surge": {
        "signal_id": "cat-09", "source": "control_center",
        "entity": {"type": "topic", "id": "trades.execution"},
        "metric_or_event": "produce_error_rate", "value": 48, "unit": "errors/s",
        "environment": "prod",
    },
    "10 · ISR shrink during maintenance (lower severity)": {
        "signal_id": "cat-10", "source": "control_center",
        "entity": {"type": "broker", "id": "broker-3"},
        "metric_or_event": "under_replicated_partitions", "value": 2,
        "unit": "count", "environment": "prod",
    },
}

_STATUS_GLYPH = {
    "pending": "⬜", "running": "🔄", "done": "✅",
    "skipped": "⏭️", "failed": "❌",
}

# Phase 7 — operator feedback categories offered in the UI form. The two
# threshold-gated categories (severity_too_low, too_verbose) drive the advisory
# adaptations; wrong_recipient and other are also stored (and count as negative
# where noted). Labels are plain-language for operators.
_FEEDBACK_CATEGORIES = {
    "severity_too_low": "Severity looked too low",
    "too_verbose": "Response was too verbose",
    "wrong_recipient": "Wrong recipient / routing",
    "other": "Other (free note)",
}

# Phase 7 — the three advisory adjustments the AdaptationPolicy can apply, with
# a human label + what the operator sees when each fires.
_ADAPTATION_META = {
    "severity_nudge": ("📊 Severity nudge",
                       "Advisory recommendation to consider a higher severity "
                       "(A3's assessment is shown UNCHANGED)."),
    "concise": ("✂️ Concise mode",
                "Trimmed response body (safety + escalation lines preserved)."),
    "recurrence_emphasis": ("🔁 Recurrence emphasis",
                            "Stronger recurrence banner for an entity with prior "
                            "incidents AND negative feedback history."),
}


# ==========================================================================
# Phase 8 — observability readers (logs / traces). Pure functions: no Streamlit
# imports, resilient to missing/partial files, and secret-safe because the
# source files are already written through the redacting filter/redactor.
# ==========================================================================

def _observability_paths():
    """Return (log_path, trace_path) from the observability module's defaults."""
    from agent.observability import DEFAULT_LOG_DIR, DEFAULT_LOG_FILE, DEFAULT_TRACE_FILE
    return (DEFAULT_LOG_DIR / DEFAULT_LOG_FILE,
            DEFAULT_LOG_DIR / DEFAULT_TRACE_FILE)


def read_jsonl(path, limit: int = 500) -> list:
    """Read a .jsonl file into a list of dicts (newest-last). Resilient: a
    missing file yields []; malformed lines are skipped. Reads at most the last
    ``limit`` lines so a large file never blocks the UI."""
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"_raw": line})
    return out


def read_log_tail(path, limit: int = 500) -> list:
    """Read the structured JSON-line log (``sentinel.log``) as a list of dicts,
    newest-last. Same resilience as :func:`read_jsonl`."""
    return read_jsonl(path, limit=limit)


def latency_stats(traces: list) -> dict:
    """Compute simple latency aggregates from trace dicts (pure helper)."""
    vals = [int(t["latency_ms"]) for t in traces
            if isinstance(t, dict) and isinstance(t.get("latency_ms"), (int, float))]
    if not vals:
        return {"count": 0, "min": None, "max": None, "avg": None, "p95": None,
                "values": []}
    ordered = sorted(vals)
    p95_idx = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return {
        "count": len(vals),
        "min": ordered[0],
        "max": ordered[-1],
        "avg": round(sum(vals) / len(vals), 1),
        "p95": ordered[p95_idx],
        "values": vals,
    }


def split_traces(traces: list):
    """Partition trace dicts into (ok, error) by status (pure helper)."""
    ok = [t for t in traces if isinstance(t, dict) and t.get("status") == "ok"]
    err = [t for t in traces if isinstance(t, dict) and t.get("status") == "error"]
    return ok, err


# ==========================================================================
# Phase 9 — evaluation-report readers. The evaluation harness writes JSON/MD
# artefacts under data/evaluation/; the tab reads them read-only (no re-run).
# ==========================================================================

def _eval_artifact_dir():
    """Return the data/evaluation directory (where phase9_* artefacts live)."""
    return _REPO_ROOT / "data" / "evaluation"


def read_json_artifact(path) -> dict:
    """Read a JSON artefact into a dict. Resilient: missing/corrupt -> {}."""
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}


# Human labels + the metric field that carries each quality dimension's score.
_QUALITY_DIMS = {
    "anomaly": ("Anomaly validation", "precision"),
    "severity": ("Severity accuracy", "present_rate"),
    "correlation": ("Correlation quality", "candidate_rate"),
    "rca": ("Root-cause quality", "hypothesis_rate"),
    "recommendation": ("Recommendation usefulness", "actions_present_rate"),
}

# Human-facing agent metadata: name, icon, one-line purpose, and the key output.
# Keyed by the lowercase state id (a1..a8). Names mirror contracts.AGENT_NAMES.
_AGENT_META = {
    "a1": {"icon": "🔎", "name": "Signal Validation / Anomaly Triage",
           "purpose": "Decides whether a signal is a real anomaly vs transient/noise, "
                      "detects duplicates, and asks for more evidence if needed.",
           "produces": "classification, anomaly score, missing data"},
    "a2": {"icon": "🔗", "name": "Correlation & Topology",
           "purpose": "Groups related symptoms into one incident candidate and maps "
                      "the impacted dependency path.",
           "produces": "incident candidate, correlated signals, dependency path"},
    "a3": {"icon": "📊", "name": "Severity & Business Impact",
           "purpose": "Assigns P1–P4 priority and the business impact, using the "
                      "entity's criticality tier.",
           "produces": "severity, business impact, affected services"},
    "a4": {"icon": "🧩", "name": "Root-Cause Hypothesis",
           "purpose": "Produces ranked root-cause hypotheses with evidence for/against "
                      "and the next diagnostic check — grounded in runbooks when "
                      "available, else LLM-inferred.",
           "produces": "ranked hypotheses, observed facts, next checks"},
    "a5": {"icon": "🛠️", "name": "Remediation Recommendation",
           "purpose": "Enumerates safe, reversible, approval-gated actions (diagnostics "
                      "first). Read-only by default; never acts automatically.",
           "produces": "recommended actions (all require approval)"},
    "a6": {"icon": "📝", "name": "Incident Summary & Ticket",
           "purpose": "Consolidates everything into one 7-section incident record with "
                      "a narrative summary and the knowledge-reference trail.",
           "produces": "incident record, closure document, ticket payload"},
    "a7": {"icon": "📣", "name": "Stakeholder Communication & Escalation",
           "purpose": "Resolves recipients ONLY from the approved directory and drafts "
                      "an audience-appropriate message. Never auto-sends.",
           "produces": "recipients by role, message, channel (not sent)"},
    "a8": {"icon": "✅", "name": "Recovery Verification & Feedback",
           "purpose": "Verifies recovery against explicit metric criteria and records "
                      "feedback. Alert disappearance alone is not proof of recovery.",
           "produces": "recovery status, closure recommendation"},
}

_AGENT_ORDER = ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"]


def agent_label(aid: str) -> str:
    """Human label for an agent id, e.g. 'A4 · Root-Cause Hypothesis' (pure helper)."""
    meta = _AGENT_META.get(aid.lower())
    if not meta:
        return aid.upper()
    return f"{aid.upper()} · {meta['name']}"


def trace_labels(trace: list) -> str:
    """Render a trace like ['A1','A2'] as readable agent names (pure helper)."""
    return "  →  ".join(agent_label(a) for a in trace) if trace else "—"

# ==========================================================================
# Themes. Each palette is the SAME set of role keys so a single CSS template
# ("_build_theme_css") renders any of them. Four selectable themes:
#   * slate_teal     — the original deep slate-navy + teal ops dashboard (default)
#   * midnight_purple — midnight purple canvas with a violet/magenta accent
#   * dark           — neutral near-black dark theme with a blue accent
#   * light          — clean light theme with a blue accent on white panels
# Keys: accent (primary), accent_bright (hover), accent2 (headings/links),
#       warn, bg (canvas), panel, panel2 (stripes/hover), line (borders),
#       text, muted (captions), ink (text on filled buttons).
# ==========================================================================

_THEMES: dict[str, dict[str, str]] = {
    "slate_teal": {
        "label": "🟦 Slate + Teal (default)",
        "accent": "#2DD4BF", "accent_bright": "#5EEAD4", "accent2": "#38BDF8",
        "warn": "#FBBF24", "bg": "#0B1220", "panel": "#141D2E",
        "panel2": "#1C2740", "line": "#263247", "text": "#E5E7EB",
        "muted": "#94A3B8", "ink": "#06111F",
    },
    "midnight_purple": {
        "label": "🟣 Midnight Purple",
        "accent": "#A78BFA", "accent_bright": "#C4B5FD", "accent2": "#E879F9",
        "warn": "#FBBF24", "bg": "#140B22", "panel": "#1E1233",
        "panel2": "#2A1A47", "line": "#3B2A5C", "text": "#EDE9FE",
        "muted": "#B3A3D4", "ink": "#140B22",
    },
    "dark": {
        "label": "⬛ Dark",
        "accent": "#3B82F6", "accent_bright": "#60A5FA", "accent2": "#60A5FA",
        "warn": "#F59E0B", "bg": "#0A0A0A", "panel": "#161616",
        "panel2": "#222222", "line": "#333333", "text": "#EAEAEA",
        "muted": "#9CA3AF", "ink": "#0A0A0A",
    },
    "light": {
        "label": "⬜ Light",
        "accent": "#2563EB", "accent_bright": "#1D4ED8", "accent2": "#1D4ED8",
        "warn": "#B45309", "bg": "#FFFFFF", "panel": "#F3F4F6",
        "panel2": "#E5E7EB", "line": "#D1D5DB", "text": "#111827",
        "muted": "#4B5563", "ink": "#FFFFFF",
    },
}

_DEFAULT_THEME = "slate_teal"


def _build_theme_css(palette: dict[str, str]) -> str:
    """Render the app CSS for a given palette. The same selectors as the original
    slate+teal theme, parameterised by the palette's role colours so every theme
    is consistent across canvas, sidebar, buttons, tables, inputs, and alerts."""
    p = palette
    accent, accent_bright, accent2 = p["accent"], p["accent_bright"], p["accent2"]
    bg, panel, panel2, line = p["bg"], p["panel"], p["panel2"], p["line"]
    text, muted, ink = p["text"], p["muted"], p["ink"]
    return f"""
<style>
  /* canvas */
  .stApp {{ background-color: {bg}; color: {text}; }}
  .main .block-container {{ background-color: {bg}; }}

  /* headings in the secondary accent; body text; muted captions */
  h1, h2, h3, h4, h5 {{ color: {accent2} !important; letter-spacing: 0.2px; }}
  .stApp a {{ color: {accent}; }}
  .stApp, .stMarkdown, p, span, label {{ color: {text}; }}
  .stCaption, [data-testid="stCaptionContainer"] {{ color: {muted} !important; }}

  /* sidebar with an accent edge. Widen the allowed range and let the user drag
     it far wider than Streamlit's default cap (the preview/JSON panels need the
     room); content wraps instead of being clipped. */
  section[data-testid="stSidebar"] {{
      background-color: {panel};
      border-right: 1px solid {line};
      min-width: 300px !important;
      max-width: 42vw !important;
  }}
  section[data-testid="stSidebar"] > div {{ width: 100% !important; }}
  section[data-testid="stSidebar"] .stJson, 
  section[data-testid="stSidebar"] pre,
  section[data-testid="stSidebar"] code {{
      white-space: pre-wrap !important;
      word-break: break-word !important;
      overflow-wrap: anywhere !important;
  }}
  section[data-testid="stSidebar"] h1,
  section[data-testid="stSidebar"] h2,
  section[data-testid="stSidebar"] h3 {{ color: {accent} !important; }}
  section[data-testid="stSidebar"] * {{ color: {text}; }}

  /* buttons: accent fill, ink text, subtle lift on hover */
  .stButton > button {{
      background-color: {accent};
      color: {ink};
      border: 0;
      border-radius: 8px;
      font-weight: 700;
      transition: background-color 120ms ease, transform 80ms ease;
  }}
  .stButton > button:hover {{ background-color: {accent_bright}; color: {ink};
      transform: translateY(-1px); }}

  /* progress bar fill */
  .stProgress > div > div > div > div {{ background-color: {accent}; }}

  /* tabs: active tab underlined in the accent */
  button[data-baseweb="tab"] {{ color: {muted}; }}
  button[data-baseweb="tab"][aria-selected="true"] {{ color: {accent2}; }}
  div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {{
      background-color: {accent}; }}

  /* chat bubbles: panel with an accent left border */
  div[data-testid="stChatMessage"] {{
      background-color: {panel};
      border: 1px solid {line};
      border-left: 4px solid {accent};
      border-radius: 12px;
      padding: 0.6rem 0.85rem;
  }}

  /* expanders + status panels */
  div[data-testid="stExpander"] {{
      border: 1px solid {line};
      border-radius: 12px;
      background-color: {panel};
  }}
  div[data-testid="stExpander"] summary {{ color: {accent2}; }}

  /* metrics */
  div[data-testid="stMetric"] {{
      background-color: {panel};
      border: 1px solid {line};
      border-radius: 10px;
      padding: 0.4rem 0.6rem;
  }}

  /* tables: accent header, striped rows */
  table {{ color: {text}; border-collapse: collapse; }}
  table thead tr th {{
      background-color: {panel2};
      color: {accent2} !important;
      border-bottom: 2px solid {accent};
  }}
  table tbody tr {{ background-color: {panel}; }}
  table tbody tr:nth-child(even) {{ background-color: {panel2}; }}

  /* inputs */
  div[data-testid="stChatInput"] textarea {{
      border-color: {line};
      background-color: {panel};
      color: {text};
  }}
  div[data-testid="stChatInput"] textarea:focus {{ border-color: {accent}; }}

  /* code / json blocks: panel with an accent edge */
  .stCode, pre, code {{
      background-color: {panel} !important;
      border-left: 3px solid {accent2};
      color: {text};
  }}

  /* alerts */
  div[data-testid="stAlert"] {{ border-radius: 10px; }}
</style>
"""


# ==========================================================================
# Session plumbing (no Streamlit imports at module scope)
# ==========================================================================

def _get_session(st):
    """Return the SentinelSession stored in st.session_state, creating it once."""
    from agent.env_config import load_env
    from agent.session import SentinelSession

    if "sentinel_session" not in st.session_state:
        load_env(verbose=False)
        # Retrieval is optional; disable gracefully if no FAISS index is present.
        try:
            st.session_state.sentinel_session = SentinelSession(use_retrieval=True)
        except Exception:  # noqa: BLE001
            st.session_state.sentinel_session = SentinelSession(use_retrieval=False)
        st.session_state.history = []  # list of {role, text, result}
    return st.session_state.sentinel_session


# ==========================================================================
# Rendering helpers (take `st` so the module imports without streamlit)
# ==========================================================================

def _render_plan(st, plan: dict) -> None:
    st.markdown(f"**Plan objective:** {plan.get('objective', '')}")
    steps = plan.get("steps", [])
    done = sum(1 for s in steps if s.get("status") == "done")
    total = len(steps) or 1
    st.progress(done / total, text=plan.get("progress", f"{done}/{total}"))
    for i, s in enumerate(steps, 1):
        glyph = _STATUS_GLYPH.get(s.get("status"), "⬜")
        summary = f" — {s['result_summary']}" if s.get("result_summary") else ""
        st.markdown(f"{glyph} **{i}. {s['title']}** `({s['owner']})`{summary}")


def _render_agents(st, agents: dict) -> None:
    for aid in _AGENT_ORDER:
        a = agents.get(aid)
        if not a:
            continue
        meta = _AGENT_META.get(aid, {})
        icon = meta.get("icon", "•")
        name = meta.get("name", aid.upper())
        with st.expander(f"{icon}  {aid.upper()} · {name}", expanded=(aid == "a6")):
            if meta.get("purpose"):
                st.caption(f"**Purpose:** {meta['purpose']}")
                st.caption(f"**Produces:** {meta.get('produces', '')}")
            st.json(a)


def _render_about_agents(st) -> None:
    """A reference panel describing what each of the 8 agents does."""
    st.markdown(
        "The pipeline is **8 cooperating agents** (LangGraph nodes, each driven by a "
        "LangChain chat model). A signal flows through them in order; A1 can gate the "
        "flow to a watch state for noise/insufficient evidence."
    )
    for aid in _AGENT_ORDER:
        m = _AGENT_META[aid]
        st.markdown(
            f"**{m['icon']} {aid.upper()} · {m['name']}**  \n"
            f"{m['purpose']}  \n"
            f"<span style='color:#94A3B8'>Produces: {m['produces']}</span>",
            unsafe_allow_html=True,
        )


def analysis_source_of(agents: dict) -> str:
    """Return 'knowledge_base' or 'llm_inference' from the A4 output (pure helper)."""
    a4 = agents.get("a4") or {}
    return a4.get("analysis_source", "knowledge_base")


def _render_analysis_source(st, agents: dict) -> None:
    """Prominent badge showing whether this incident was runbook-grounded or
    LLM-inferred (signal not covered by the knowledge base)."""
    src = analysis_source_of(agents)
    if src == "llm_inference":
        st.warning(
            "🧠 **Analysis source: LLM inference** — this signal is **not covered "
            "by the knowledge base**. Root cause & remediation were derived by the "
            "LLM from domain reasoning and must be human-validated before any action."
        )
    else:
        st.success(
            "📚 **Analysis source: knowledge base** — root cause & remediation are "
            "grounded in retrieved runbooks/FAQ (see Retrieval evidence below)."
        )


def _render_retrieval(st, retrieval: dict) -> None:
    if not retrieval.get("enabled"):
        st.info("Retrieval (RAG) disabled — no FAISS index wired for this run.")
        return
    if not retrieval.get("found"):
        st.warning(f"No relevant knowledge matched (best score "
                   f"{retrieval.get('best_score')}).")
        return
    st.caption(f"embedder `{retrieval.get('embedder')}` · query "
               f"`{retrieval.get('query')}`")
    hits = retrieval.get("hits", [])
    if hits:
        st.table([
            {"source": h.get("source"), "heading": h.get("heading"),
             "score": round(float(h.get("score", 0.0)), 3)}
            for h in hits
        ])


def adaptation_applied(adaptation: dict) -> bool:
    """True when any advisory adjustment fired for this turn (pure helper)."""
    if not adaptation:
        return False
    return bool(adaptation.get("severity_nudge")
                or adaptation.get("concise")
                or adaptation.get("recurrence_emphasis"))


def _render_adaptation(st, adaptation: dict) -> None:
    """Phase 7 — show which advisory adjustments fired (and why), or that none
    did. When nothing is applied the turn is identical to Phase 6, which we state
    explicitly so the before/after contrast is clear in the UI."""
    entity = (adaptation or {}).get("entity") or "—"
    if not adaptation_applied(adaptation):
        st.success(
            f"🟢 **No adaptation applied** for `{entity}` — behaviour is identical "
            "to the pre-feedback baseline. Submit feedback (sidebar) and re-run "
            "the same entity's signal to see the advisory adaptation."
        )
        return

    flags = [k for k in ("severity_nudge", "concise", "recurrence_emphasis")
             if adaptation.get(k)]
    badges = " · ".join(_ADAPTATION_META[k][0] for k in flags)
    st.warning(f"🧭 **Adaptation applied (advisory) for `{entity}`:** {badges}")
    for k in flags:
        label, desc = _ADAPTATION_META[k]
        st.markdown(f"- **{label}** — {desc}")
    explanations = adaptation.get("explanations", [])
    if explanations:
        with st.expander("Why these changes fired (feedback evidence)", expanded=True):
            for note in explanations:
                st.markdown(f"- {note}")
    st.caption("Adaptation is advisory only: it changes presentation and never "
               "alters A1–A8 decisions, approval requirements, or escalation.")


def _render_feedback_summary(st, session) -> None:
    """Phase 7 — live feedback store summary (counts by category + records)."""
    snap = session.snapshot()
    fb = snap.get("feedback", {}) or {}
    st.subheader("Operator feedback (Phase 7)")
    st.caption(f"{fb.get('count', 0)} feedback item(s) on record "
               "(persisted, non-sensitive)")
    cat_counts = fb.get("category_counts", {}) or {}
    if cat_counts:
        st.table([{"category": c, "count": n} for c, n in cat_counts.items()])
    else:
        st.write("_no feedback recorded yet_")
    records = fb.get("records", []) or []
    if records:
        with st.expander(f"All {len(records)} feedback record(s)", expanded=False):
            st.table([
                {"id": r.get("feedback_id"), "entity": r.get("entity"),
                 "category": r.get("category"), "signal": r.get("signal"),
                 "rating": r.get("rating")}
                for r in records
            ])


def _render_feedback_form(st, session) -> None:
    """Phase 7 — sidebar form to submit operator feedback on the in-focus
    incident. Entity/incident default to the session working set."""
    in_focus = session.conversation.recall("current_entity")
    st.subheader("Give feedback")
    if in_focus:
        st.caption(f"In focus: `{in_focus}`")
    else:
        st.caption("Run a signal turn first to put an incident in focus.")

    with st.form("feedback_form", clear_on_submit=True):
        cat_key = st.selectbox(
            "Category",
            options=list(_FEEDBACK_CATEGORIES.keys()),
            format_func=lambda k: _FEEDBACK_CATEGORIES[k],
        )
        signal = st.radio("Signal", options=["down", "up"],
                          horizontal=True, index=0)
        rating = st.slider("Rating (optional)", min_value=0, max_value=5, value=0,
                           help="0 = no rating; 1–2 counts as negative")
        note = st.text_input("Note (optional, non-sensitive)", value="")
        submitted = st.form_submit_button("Submit feedback")

    if submitted:
        res = session.record_feedback(
            signal=signal,
            category=cat_key,
            rating=(rating or None),
            note=note,
        )
        if res.get("recorded"):
            st.success(
                f"Recorded {res['feedback_id']} for `{res['entity']}` "
                f"(category={res['category']}, negative={res['negative']}, "
                f"now {res['count_for_entity']} for this entity)."
            )
            st.session_state.history.append({
                "role": "assistant",
                "text": f"📝 Feedback {res['feedback_id']} recorded "
                        f"({res['category']}).",
                "result": {"kind": "feedback", "response": ""},
            })
            st.rerun()
        else:
            st.error(res.get("reason", "Feedback not recorded."))


def _render_memory(st, session) -> None:
    snap = session.snapshot()
    conv = snap["conversation"]
    ltm = snap["long_term_memory"]

    st.subheader("Short-term (this conversation)")
    st.caption(f"{conv['turn_count']} turn(s); window={conv['window']}")
    if conv["working_set"]:
        st.json(conv["working_set"])
    else:
        st.write("_working set empty_")

    st.subheader("Long-term (persisted incidents)")
    st.caption(f"{ltm['count']} record(s) retained across sessions")
    if ltm["records"]:
        st.table([
            {"incident": r["incident_id"], "entity": r["entity"],
             "metric": r["metric"], "severity": r["severity"],
             "class": r["classification"]}
            for r in ltm["records"]
        ])
    else:
        st.write("_no incidents recorded yet_")


def _render_turn_result(st, result: dict) -> None:
    """Render one agent turn result (signal or follow-up) in the chat stream."""
    kind = result.get("kind")
    if kind == "signal":
        if result.get("recurrence_count"):
            st.warning(f"🔁 Recurring: {result['recurrence_count']} prior "
                       f"incident(s) for {result.get('entity')}.")
        if result.get("gated"):
            st.info(f"Gated at **{agent_label('a1')}**: {result.get('stop_reason')}")
        # Provenance badge: was the analysis grounded in the knowledge base or
        # inferred by the LLM for a signal the knowledge base does not cover?
        _render_analysis_source(st, result.get("agents", {}))
        # Phase 7 — advisory adaptation derived from accumulated operator feedback.
        st.markdown("##### Adaptive behaviour (Phase 7)")
        _render_adaptation(st, result.get("adaptation", {}))
        st.markdown("##### Plan (task decomposition)")
        _render_plan(st, result.get("plan", {}))
        st.markdown(f"**Agent trace:** {trace_labels(result.get('trace', []))}")
        st.markdown("##### Retrieval evidence (RAG)")
        _render_retrieval(st, result.get("retrieval", {}))
        st.markdown("##### Agent reasoning — each agent's role & output")
        _render_agents(st, result.get("agents", {}))
        with st.expander("Raw pipeline text", expanded=False):
            st.code(result.get("pipeline_response", ""), language="text")
    elif kind == "followup":
        st.caption(result.get("memory_note", ""))
        st.code(result.get("tool_response", ""), language="text")
    elif kind == "feedback":
        # Feedback acknowledgements carry their text in the history headline;
        # nothing further to render inline.
        pass
    else:  # reset / other
        resp = result.get("response", "")
        if resp:
            st.code(resp, language="text")


# ==========================================================================
# Phase 8 — observability tab renderers (logs / traces / latency / errors)
# ==========================================================================

def _render_observability_header(st) -> None:
    log_path, trace_path = _observability_paths()
    st.caption(
        "Phase 8 — deployment observability. Structured logs, per-run traces, "
        "latency, and graceful-failure handling. All records pass through the "
        "redacting filter, so **no secrets or PII are ever shown**."
    )
    c1, c2 = st.columns(2)
    c1.caption(f"log file: `{log_path}`")
    c2.caption(f"trace file: `{trace_path}`")


def _render_logs_tab(st) -> None:
    """Structured application log (logs/sentinel.log, JSON lines)."""
    st.subheader("📜 Structured logs")
    _render_observability_header(st)
    log_path, _ = _observability_paths()
    records = read_log_tail(log_path)
    if not records:
        st.info(
            "No log records yet. Logs are written once a run is traced — run a "
            "signal turn in the **Console** tab, or `python scripts/"
            "run_phase8_deploy_check.py`, then reload."
        )
        return

    levels = sorted({str(r.get("level", "?")) for r in records if isinstance(r, dict)})
    chosen = st.multiselect("Levels", options=levels, default=levels)
    show = [r for r in records
            if not isinstance(r, dict) or str(r.get("level", "?")) in chosen]
    st.caption(f"Showing {len(show)} of {len(records)} most-recent record(s), "
               "newest last.")
    st.table([
        {"ts": r.get("ts", ""), "level": r.get("level", ""),
         "logger": r.get("logger", ""),
         "message": (str(r.get("msg", r.get("_raw", "")))[:120])}
        for r in show if isinstance(r, dict)
    ])
    with st.expander("Raw log records (JSON)", expanded=False):
        st.json(show[-50:])


def _render_traces_tab(st) -> None:
    """Per-run traces (logs/traces.jsonl) — run_id, provider, status, latency."""
    st.subheader("🧵 Run traces")
    _render_observability_header(st)
    _, trace_path = _observability_paths()
    traces = read_jsonl(trace_path)
    if not traces:
        st.info(
            "No traces yet. Each traced run appends one record. Run a signal "
            "turn in the **Console** tab or the Phase 8 deploy-check script, "
            "then reload."
        )
        return

    ok, err = split_traces(traces)
    m1, m2, m3 = st.columns(3)
    m1.metric("Total runs", len(traces))
    m2.metric("OK", len(ok))
    m3.metric("Errors", len(err))
    st.caption(f"Showing {len(traces)} most-recent trace(s), newest last.")
    st.table([
        {"run_id": t.get("run_id", ""), "entry_point": t.get("entry_point", ""),
         "provider": t.get("provider", ""), "status": t.get("status", ""),
         "latency_ms": t.get("latency_ms", ""),
         "error_type": t.get("error_type") or ""}
        for t in traces if isinstance(t, dict)
    ])
    with st.expander("Raw trace records (JSON)", expanded=False):
        st.json(traces[-50:])


def _render_latency_tab(st) -> None:
    """Latency aggregates + a per-run chart from the traces."""
    st.subheader("⏱️ Latency")
    _render_observability_header(st)
    _, trace_path = _observability_paths()
    traces = read_jsonl(trace_path)
    stats = latency_stats(traces)
    if not stats["count"]:
        st.info("No latency samples yet — run a traced turn, then reload.")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Samples", stats["count"])
    c2.metric("min (ms)", stats["min"])
    c3.metric("avg (ms)", stats["avg"])
    c4.metric("p95 (ms)", stats["p95"])
    c5.metric("max (ms)", stats["max"])

    # Per-run latency over time (index = run order). st.bar_chart needs no extra
    # dependency and renders newest-last.
    series = [t.get("latency_ms") for t in traces
              if isinstance(t, dict) and isinstance(t.get("latency_ms"), (int, float))]
    st.markdown("**Per-run latency (ms), in run order**")
    st.bar_chart(series)
    st.caption("Latency is wall-clock per run (`perf_counter`). On the offline "
               "fake provider it reflects pipeline overhead only; the live "
               "OpenAI path adds model round-trip time.")


def _render_error_handling_tab(st) -> None:
    """Graceful-failure evidence: error traces + the three handled scenarios."""
    st.subheader("🛡️ Graceful failure handling")
    _render_observability_header(st)
    _, trace_path = _observability_paths()
    traces = read_jsonl(trace_path)
    _, err = split_traces(traces)

    st.markdown(
        "Every turn in the Console runs through `safe_handle_turn`, a wrapper "
        "that catches any internal error, records an **error trace**, and "
        "returns a structured advisory response instead of crashing — the "
        "safety posture (advisory / read-only, no auto-action) is preserved."
    )
    st.markdown("**Handled failure scenarios (Phase 8 deploy-check):**")
    st.table([
        {"scenario": "Malformed / invalid input",
         "outcome": "graceful error", "crash?": "no"},
        {"scenario": "Provider / LLM outage (injected)",
         "outcome": "graceful error", "crash?": "no"},
        {"scenario": "Missing / disabled retrieval index",
         "outcome": "completes (degraded)", "crash?": "no"},
    ])

    st.markdown("**Error traces captured on disk**")
    if not err:
        st.success("No error traces recorded — no failures captured yet. "
                   "(Run the deploy-check or trigger a bad input to see one.)")
    else:
        st.caption(f"{len(err)} error trace(s), newest last.")
        st.table([
            {"run_id": t.get("run_id", ""), "entry_point": t.get("entry_point", ""),
             "error_type": t.get("error_type", ""),
             "latency_ms": t.get("latency_ms", ""),
             "message": (str(t.get("error_message") or "")[:100])}
            for t in err if isinstance(t, dict)
        ])
    st.caption("Error messages shown here are already redacted — no stack trace "
               "or secret is ever persisted or surfaced.")


def _render_evaluation_tab(st) -> None:
    """Phase 9 — surface the evaluation report: go/no-go headline, quality
    scorecards vs gates, gating confusion matrix, consistency, safety/ethics
    review, and the debugged-failure before/after. Read-only from the harness
    artefacts under data/evaluation/."""
    st.subheader("📈 Evaluation & engineering review")
    eval_dir = _eval_artifact_dir()
    report = read_json_artifact(eval_dir / "phase9_evaluation.json")
    failure = read_json_artifact(eval_dir / "phase9_failure_analysis.json")

    if not report:
        st.info(
            "No evaluation report yet. Generate it with "
            "`python scripts/run_phase9_eval.py --no-retrieval`, then reload. "
            "The tab reads `data/evaluation/phase9_evaluation.json` and "
            "`phase9_failure_analysis.json`."
        )
        return

    st.caption(
        f"generated `{report.get('generated_at', '?')}` · provider "
        f"`{report.get('provider', '?')}` · {report.get('n_cases', '?')} cases "
        f"({report.get('n_actionable', '?')} actionable) · read-only view of the "
        "harness output."
    )

    # ---- go / no-go headline ----
    go = bool(report.get("go"))
    if go and report.get("safety_passed") and report.get("quality_passed"):
        st.success("✅ **GO** — all quality gates met and the safety scorecard "
                   "passed (zero violations).")
    elif not report.get("safety_passed", True):
        st.error("⛔ **NO-GO** — a safety gate failed. Safety violations are hard "
                 "release blockers and are never averaged away.")
    else:
        st.warning("⚠️ **NO-GO** — one or more quality gates did not meet their "
                   "acceptance threshold.")
    for reason in report.get("reasons", []):
        st.caption(f"· {reason}")

    # ---- quality scorecards vs gates ----
    st.markdown("##### Quality metrics vs acceptance gates")
    quality = report.get("quality", {}) or {}
    rows = []
    for key, (label, field) in _QUALITY_DIMS.items():
        sc = quality.get(key, {}) or {}
        if not sc:
            continue
        score = sc.get(field)
        rows.append({
            "dimension": label,
            "metric": f"{field} = {score}",
            "gate": f"≥ {sc.get('gate')}",
            "result": "✅ pass" if sc.get("passed") else "❌ fail",
        })
    # severity's critical-downgrade guard is a distinct hard check worth surfacing
    sev = quality.get("severity", {}) or {}
    if sev:
        rows.append({
            "dimension": "Severity — unreviewed critical downgrades",
            "metric": str(sev.get("unreviewed_critical_downgrades", "?")),
            "gate": "= 0 (hard)",
            "result": "✅ pass" if sev.get("unreviewed_critical_downgrades", 1) == 0
                      else "❌ fail",
        })
    if rows:
        st.table(rows)

    # ---- gating confusion matrix ----
    gating = report.get("gating", {}) or {}
    if gating:
        st.markdown("##### Gating correctness (open incident vs watch-state)")
        conf = gating.get("confusion", {}) or {}
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("accuracy", gating.get("accuracy"))
        c2.metric("TP", conf.get("tp"))
        c3.metric("FP", conf.get("fp"))
        c4.metric("FN", conf.get("fn"))
        c5.metric("TN", conf.get("tn"))
        if gating.get("mismatch_count"):
            st.warning(f"{gating['mismatch_count']} mismatch(es): "
                       f"{gating.get('mismatches')}")
        else:
            st.caption("No mismatches — every case gated/opened as labelled.")
        with st.expander("Per-case gating detail", expanded=False):
            st.table([
                {"id": r.get("id"), "actionable": r.get("actionable"),
                 "gated": r.get("gated"), "classification": r.get("classification"),
                 "correct": "✅" if r.get("correct") else "❌"}
                for r in gating.get("rows", []) if isinstance(r, dict)
            ])

    # ---- consistency ----
    cons = report.get("consistency", {}) or {}
    if cons:
        st.markdown("##### Consistency / reliability")
        if cons.get("all_stable"):
            st.success(f"🔁 Stable across K={cons.get('k')} repeats "
                       f"({cons.get('stable')} case(s) identical, "
                       f"{cons.get('unstable')} unstable).")
        else:
            st.warning(f"Unstable cases: {cons.get('unstable_ids')}")
        if cons.get("why"):
            st.caption(cons["why"])

    # ---- safety / ethics review ----
    st.markdown("##### Safety & ethics review (zero-violation is a hard blocker)")
    safety = report.get("safety_scorecard", []) or []
    if safety:
        st.table([
            {"check": s.get("check"), "gate": s.get("gate"),
             "result": "✅ pass" if s.get("passed") else "❌ FAIL",
             "evidence": (str(s.get("evidence", ""))[:90])}
            for s in safety if isinstance(s, dict)
        ])

    # ---- debugged failure: before / after ----
    if failure:
        st.markdown("##### Root-cause analysis — debugged failure (before/after)")
        st.caption(f"case `{failure.get('case_id', '?')}` · "
                   f"resolved = {failure.get('resolved')}")
        st.markdown(f"**Symptom:** {failure.get('symptom', '')}")
        st.markdown(f"**Root cause:** {failure.get('root_cause', '')}")
        fix = failure.get("fix", {}) or {}
        st.markdown(f"**Fix:** {fix.get('what_changed', '')} "
                    f"_(A1–A8 node logic touched: {fix.get('node_logic_touched')})_")
        before, after = failure.get("before", {}) or {}, failure.get("after", {}) or {}
        st.table([
            {"state": "BEFORE", "label": before.get("label"),
             "mismatches": before.get("mismatch_count"),
             "gating_accuracy": before.get("gating_accuracy")},
            {"state": "AFTER", "label": after.get("label"),
             "mismatches": after.get("mismatch_count"),
             "gating_accuracy": after.get("gating_accuracy")},
        ])

    # ---- full report doc + raw JSON ----
    report_md = _REPO_ROOT / "docs" / "evaluation_report.md"
    if report_md.exists():
        with st.expander("📄 Full evaluation report (docs/evaluation_report.md)",
                         expanded=False):
            try:
                st.markdown(report_md.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                st.caption("(could not read the report file)")
    with st.expander("Raw evaluation JSON", expanded=False):
        st.json(report)


def _render_governance_tab(st) -> None:
    """Governance & monitoring surface (R1 scope, R2 PII, R3 guardrails,
    R4 Langfuse/DeepEval). Read-only, import-safe headless: every Streamlit call
    lives inside this function, guardrail/monitoring logic is imported lazily,
    and each section degrades to an info note when its artifact is absent."""
    from agent.guardrails import classify_scope
    from agent.observability import mask_pii

    st.subheader("🛡️ Governance & monitoring")
    st.caption(
        "Domain-scope + PII guardrails, the guardrails evidence table, and the "
        "optional Langfuse/DeepEval status — all offline, no key, no network."
    )
    eval_dir = _eval_artifact_dir()

    # ---- (1) Domain-scope live check (R1) --------------------------------
    st.markdown("##### 1 · Domain scope (R1)")
    st.caption(
        "Sentinel refuses a turn IFF `classify_scope(text)[0] == out_of_scope`. "
        "`needs_clarification` and `in_scope` fall through to normal routing."
    )
    scope_text = st.text_input(
        "Try a message", value="why is consumer lag rising on the broker",
        key="gov_scope_input",
    )
    if scope_text:
        scope, reason = classify_scope(scope_text)
        label = {"in_scope": "✅ in_scope", "out_of_scope": "⛔ out_of_scope",
                 "needs_clarification": "❓ needs_clarification"}.get(scope, scope)
        if scope == "out_of_scope":
            st.error(f"**{label}** — {reason}")
        elif scope == "in_scope":
            st.success(f"**{label}** — {reason}")
        else:
            st.info(f"**{label}** — {reason}")
    examples = [
        ('{"entity":{"type":"topic","id":"payments.settlement"},'
         '"metric_or_event":"consumer_lag","value":60000}', "signal JSON"),
        ("why is consumer lag rising on the broker", "in-vocab question"),
        ("hi", "greeting"),
        ("what is the weather today", "out-of-scope question"),
    ]
    rows = []
    for text, note in examples:
        scope, reason = classify_scope(text)
        rows.append({"example": note, "input": text[:50],
                     "scope": scope, "reason": reason})
    st.table(rows)

    # ---- (2) PII before -> after (R2) ------------------------------------
    st.markdown("##### 2 · PII masking (R2)")
    st.caption(
        "The single masking source of truth (`agent/observability.py mask_pii`) "
        "runs on both the input (before storage/model/tools) and the response "
        "(before both sinks). Reserved `@example.com` placeholders are preserved."
    )
    st.markdown("**Input-masking boundary (live)**")
    pii_in = st.text_area(
        "Paste a message with PII to see it masked",
        value="broker lag — reach me at jane.doe@gmail.com / +1 415 555 2671",
        key="gov_pii_input", height=80,
    )
    c1, c2 = st.columns(2)
    with c1:
        st.caption("before")
        st.code(pii_in or "", language="text")
    with c2:
        st.caption("after mask_pii(...)")
        st.code(mask_pii(pii_in or ""), language="text")

    st.markdown("**Output-masking boundary (fixed illustration)**")
    st.caption(
        "A fixed in-tab constant (not an artifact, not the live pipeline) showing "
        "the handler output-masking hook: a real contact is masked while the "
        "reserved directory placeholder is preserved."
    )
    _out_demo = ("Paging on-call: j.doe@gmail.com; "
                 "directory owner alice@example.com")
    o1, o2 = st.columns(2)
    with o1:
        st.caption("before (simulated tool/directory echo)")
        st.code(_out_demo, language="text")
    with o2:
        st.caption("after mask_pii(...)")
        st.code(mask_pii(_out_demo), language="text")

    # ---- (3) Guardrails evidence table (R3) ------------------------------
    st.markdown("##### 3 · Guardrails evidence (R3)")
    guard = read_json_artifact(eval_dir / "guardrails_evidence.json")
    if not guard:
        st.info(
            "No guardrails evidence yet. Generate it with "
            "`python scripts/run_guardrails_demo.py`, then reload. The tab reads "
            "`data/evaluation/guardrails_evidence.json`."
        )
    else:
        st.caption(
            f"generated `{guard.get('generated_at', '?')}` · provider "
            f"`{guard.get('provider', '?')}` · result "
            f"**{guard.get('result', '?')}**"
        )
        st.table([
            {"guardrail": r.get("guardrail"),
             "fired": "✅" if r.get("fired") else "❌",
             "input": str(r.get("input_summary", ""))[:60],
             "evidence": str(r.get("evidence", ""))[:90]}
            for r in guard.get("guardrails", []) if isinstance(r, dict)
        ])
    guardrails_md = _REPO_ROOT / "docs" / "guardrails.md"
    if guardrails_md.exists():
        with st.expander("📄 Guardrails narrative (docs/guardrails.md)",
                         expanded=False):
            try:
                st.markdown(guardrails_md.read_text(encoding="utf-8",
                                                    errors="replace"))
            except OSError:
                st.caption("(could not read the guardrails doc)")

    # ---- (4) Langfuse + DeepEval status (R4) -----------------------------
    st.markdown("##### 4 · LLM monitoring — Langfuse + DeepEval (R4)")
    mon = read_json_artifact(eval_dir / "monitoring_evidence.json")
    if not mon:
        st.info(
            "No monitoring evidence yet. Generate it with "
            "`python scripts/run_monitoring_demo.py`, then reload. The tab reads "
            "`data/evaluation/monitoring_evidence.json`."
        )
    else:
        for name, key in (("Langfuse", "langfuse"), ("DeepEval", "deepeval")):
            section = mon.get(key, {}) or {}
            enabled = section.get("enabled")
            reason = section.get("reason")
            if enabled:
                st.success(f"**{name}** — enabled ({reason})")
            else:
                shown = (reason if reason and reason != "disabled (not configured)"
                         else "disabled (offline / not configured)")
                st.info(f"**{name}** — {shown}")
    st.caption(
        "Optional and OFF by default. To enable: uncomment the exact-pinned "
        "deepeval/langfuse block in `requirements.txt`, install, then set the "
        "OFF-by-default keys in `.env` (see `.env.example`). No key value is "
        "ever displayed."
    )


# ==========================================================================
# Main app (only called under `streamlit run` / __main__)
# ==========================================================================

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="EventHub Ops Sentinel — Phase 9",
                       page_icon="🛰️", layout="wide")
    # Apply the selected theme (chosen in the sidebar; persisted in session_state).
    theme_key = st.session_state.get("theme_key", _DEFAULT_THEME)
    if theme_key not in _THEMES:
        theme_key = _DEFAULT_THEME
    st.markdown(_build_theme_css(_THEMES[theme_key]), unsafe_allow_html=True)
    session = _get_session(st)

    st.title(f"{_AGENT_AVATAR} Vel — EventHub Ops Sentinel")
    st.caption(
        f"You are chatting with **{_AGENT_NAME}**, the AI operations agent "
        f"(you = 🧑‍💻 operator). Phase 9 · planning + memory + adaptive behaviour "
        f"+ deployment observability + evaluation · provider `{session.provider}` "
        f"· retrieval `{session.retrieval_enabled}` · advisory only — production "
        "actions require human approval."
    )

    # ---- sidebar: controls + live memory -----------------------------
    with st.sidebar:
        st.header("Appearance")
        # The selectbox binds to session_state["theme_key"]; changing it reruns
        # the app, and the new palette is applied at the top of main().
        _theme_keys = list(_THEMES.keys())
        st.selectbox(
            "Theme",
            options=_theme_keys,
            index=_theme_keys.index(theme_key),
            format_func=lambda k: _THEMES[k]["label"],
            key="theme_key",
            help="Switch between Slate+Teal, Midnight Purple, Dark, and Light.",
        )
        st.divider()

        st.header("Session")

        # Top-10 signal catalog: pick a preset Kafka/Confluent anomaly and load
        # it as the next turn (brokers, zookeeper, producer/consumer, ACL
        # denials with principals, ISR, broker failure, leader election, …).
        st.subheader("Test signals")
        _catalog_labels = list(_SIGNAL_CATALOG.keys())
        chosen_signal = st.selectbox(
            "Pick a preset anomaly",
            options=_catalog_labels,
            key="signal_catalog_choice",
            help="Top-10 Confluent Kafka infra/app anomalies, ready to triage.",
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("Load selected", use_container_width=True):
                st.session_state.pending_input = json.dumps(
                    _SIGNAL_CATALOG[chosen_signal])
        with cc2:
            if st.button("Load sample", use_container_width=True):
                st.session_state.pending_input = json.dumps(_SAMPLE_SIGNAL)
        with st.expander("Preview selected signal JSON", expanded=False):
            st.json(_SIGNAL_CATALOG[chosen_signal])
        st.divider()

        if st.button("Reset conversation (short-term)"):
            res = session.handle_turn("reset")
            st.session_state.history.append(
                {"role": "assistant", "text": res["response"], "result": res})
            st.rerun()
        if st.button("Forget long-term memory"):
            n = session.clear_long_term_memory()
            st.session_state.history.append(
                {"role": "assistant",
                 "text": f"Cleared {n} long-term incident record(s).",
                 "result": {"kind": "reset", "response": ""}})
            st.rerun()
        if st.button("Forget operator feedback"):
            n = session.clear_feedback()
            st.session_state.history.append(
                {"role": "assistant",
                 "text": f"Cleared {n} operator feedback record(s).",
                 "result": {"kind": "feedback", "response": ""}})
            st.rerun()
        st.divider()

        # Phase 7 — submit operator feedback on the in-focus incident.
        _render_feedback_form(st, session)
        st.divider()
        _render_feedback_summary(st, session)
        st.divider()
        _render_memory(st, session)

    # ---- input (chat box or injected sample) -------------------------
    # st.chat_input renders a fixed bar at the page bottom, so it lives at the
    # top level (not inside a tab). It still drives the Console tab below.
    injected = st.session_state.pop("pending_input", None)
    typed = st.chat_input("Paste a signal JSON, ask a follow-up, or type 'reset'…")
    user_input = injected or typed

    # ---- tabs: operator Console + Phase 8 observability --------------
    (tab_console, tab_logs, tab_traces, tab_latency, tab_errors,
     tab_eval, tab_gov) = st.tabs([
        "💬 Console", "📜 Logs", "🧵 Traces", "⏱️ Latency", "🛡️ Error handling",
        "📈 Evaluation", "🛡️ Governance",
    ])

    with tab_console:
        with st.expander("ℹ️ About the 8 agents — what each one does",
                         expanded=False):
            _render_about_agents(st)

        # replay chat history. The AI agent ("Vel") and the human operator get
        # distinct avatars + name labels so the two speakers are never confused.
        for msg in st.session_state.history:
            if msg["role"] == "user":
                with st.chat_message("user", avatar=_USER_AVATAR):
                    st.caption("You · operator")
                    st.code(msg["text"], language="json"
                            if msg["text"].strip().startswith("{") else "text")
            else:
                with st.chat_message("assistant", avatar=_AGENT_AVATAR):
                    st.caption(f"{_AGENT_NAME} · AI agent")
                    st.markdown(msg["text"].splitlines()[0] if msg["text"] else "")
                    if msg.get("result"):
                        _render_turn_result(st, msg["result"])

        if user_input:
            st.session_state.history.append({"role": "user", "text": user_input})
            with st.chat_message("user", avatar=_USER_AVATAR):
                st.caption("You · operator")
                st.code(user_input, language="json"
                        if user_input.strip().startswith("{") else "text")
            with st.chat_message("assistant", avatar=_AGENT_AVATAR):
                st.caption(f"{_AGENT_NAME} · AI agent")
                with st.status(f"{_AGENT_NAME} is running the multi-agent workflow…",
                               expanded=True) as status:
                    # Phase 8 — transparent graceful-failure wrapper. On success
                    # the result dict is identical to session.handle_turn(...);
                    # on an internal error it returns a structured advisory error
                    # dict instead of crashing the UI.
                    from agent.observability import safe_handle_turn

                    result = safe_handle_turn(session, user_input)
                    status.update(label=f"Done · turn {result.get('turn')}",
                                  state="complete")
                headline = (result.get("response") or "").splitlines()
                st.markdown(headline[0] if headline else "")
                _render_turn_result(st, result)
            st.session_state.history.append(
                {"role": "assistant",
                 "text": (result.get("response") or "").splitlines()[0]
                 if result.get("response") else "",
                 "result": result})
            st.rerun()

    with tab_logs:
        _render_logs_tab(st)
    with tab_traces:
        _render_traces_tab(st)
    with tab_latency:
        _render_latency_tab(st)
    with tab_errors:
        _render_error_handling_tab(st)
    with tab_eval:
        _render_evaluation_tab(st)
    with tab_gov:
        _render_governance_tab(st)


if __name__ == "__main__":
    main()
