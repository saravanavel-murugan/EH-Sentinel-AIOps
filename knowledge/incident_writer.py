"""Write a resolved incident to the knowledge base for future reference.

On incident closure, the consolidated A6 record (the 7 sections) plus the
operator-supplied RESOLUTION and the ACTIONS ACTUALLY TAKEN are written as a
markdown document under knowledge/raw/incidents/. Re-running the ingest +
index-build scripts folds it into the FAISS index, so future similar incidents
retrieve "we've seen this before" context (the A8 governed-learning loop).
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INCIDENTS_DIR = _REPO_ROOT / "knowledge" / "raw" / "incidents"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "incident").lower()).strip("-")
    return s[:60] or "incident"


def build_resolved_incident_markdown(a6: dict[str, Any], *, actions_taken: list[str],
                                     resolution: str, final_root_cause: str = "",
                                     closed_by: str = "operator") -> str:
    """Render the resolved-incident knowledge document (markdown)."""
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    incident_id = a6.get("incident_id", "incident")
    stake = a6.get("stakeholders", {}) or {}
    stake_lines = "\n".join(f"  - {r}: {c}" for r, c in stake.items()) or "  - (none)"
    reco = "\n".join(f"  - {r}" for r in (a6.get("remediation", []) or [])) or "  - (none)"
    taken = "\n".join(f"  - {a}" for a in actions_taken) or "  - (none recorded)"

    return (
        f"# Resolved Incident: {incident_id}\n\n"
        f"- **Closed at:** {now}\n"
        f"- **Closed by:** {closed_by}\n"
        f"- **Status:** CLOSED\n\n"
        f"## 1. Issue (from signal)\n{a6.get('issue', 'n/a')}\n\n"
        f"## 2. Root-cause analysis (hypotheses at triage)\n{a6.get('root_cause', 'n/a')}\n\n"
        f"## 3. Correlation\n{a6.get('correlation', 'n/a')}\n\n"
        f"## 4. Priority / Severity\n{a6.get('severity', 'n/a')} - {a6.get('severity_rationale', '')}\n\n"
        f"## 5. Remediation recommended (A5)\n{reco}\n\n"
        f"## 6. Business impact\n{a6.get('business_impact', 'n/a')}\n\n"
        f"## 7. Stakeholders notified\n{stake_lines}\n\n"
        f"## Resolution (closure)\n"
        f"**Confirmed root cause:** {final_root_cause or 'see RCA hypotheses above'}\n\n"
        f"**Actions actually taken:**\n{taken}\n\n"
        f"**Outcome / resolution notes:**\n{resolution or '(none provided)'}\n"
    )


def write_resolved_incident(a6: dict[str, Any], *, actions_taken: list[str],
                            resolution: str, final_root_cause: str = "",
                            closed_by: str = "operator") -> Path:
    """Write the resolved incident markdown to knowledge/raw/incidents/ and return its path."""
    _INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    incident_id = a6.get("incident_id", "incident")
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = _INCIDENTS_DIR / f"{ts}-{_slug(incident_id)}.md"
    md = build_resolved_incident_markdown(
        a6, actions_taken=actions_taken, resolution=resolution,
        final_root_cause=final_root_cause, closed_by=closed_by,
    )
    path.write_text(md, encoding="utf-8")
    return path
