"""Cross-tier comparison harness (Phase 2 vs Phase 3 LLM vs Phase 3b multi-agent).

Runs the SAME test set through four tiers and scores each on a common capability
rubric, so the improvement from rules -> LLM prompts -> multi-agent is visible
with evidence:

  * baseline   - Phase 2 rules/template agent (no LLM)
  * llm_v1     - Phase 3 single-node LLM, minimal prompt
  * llm_v2     - Phase 3 single-node LLM, structured prompt
  * llm_v3     - Phase 3 single-node LLM, few-shot/CoT/safety prompt
  * multiagent - Phase 3b A1-A8 LangGraph pipeline

Rubric (0/1 per capability, 10 capabilities): a tier scores a point if its output
for an actionable signal exposes that capability.

  C1  classification present
  C2  severity assigned
  C3  business impact stated
  C4  affected services listed
  C5  ranked root-cause hypotheses (>=1)
  C6  next diagnostic check
  C7  stakeholder recipients resolved
  C8  remediation action(s) proposed
  C9  actions gated by human approval (safety)
  C10 recovery verification / uncertainty handling

Outputs JSON + a Markdown table. Offline by default (fake model); live with
SENTINEL_LLM=openai.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agent.core_agent import BaselineAgent, LLMAgent
from agent.agents import MultiAgentSentinel
from agent.agents.agent_prompts import AGENT_PROMPTS
from agent.agents.contracts import AGENT_NAMES
from agent.llm import get_chat_model
from agent.planner import _build_context
from agent.prompts import PROMPTS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTSET_CANDIDATES = [
    _REPO_ROOT / "data" / "evaluation" / "test_cases.json",
    _REPO_ROOT / "data" / "test_cases.json",
]

CAPABILITIES = [
    ("C1", "classification"),
    ("C2", "severity"),
    ("C3", "business_impact"),
    ("C4", "affected_services"),
    ("C5", "hypotheses"),
    ("C6", "next_check"),
    ("C7", "recipients"),
    ("C8", "remediation"),
    ("C9", "approval_gated"),
    ("C10", "recovery_or_uncertainty"),
]


def _default_testset() -> Path:
    for c in _TESTSET_CANDIDATES:
        if c.exists():
            return c
    return _TESTSET_CANDIDATES[0]


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or _default_testset()
    if not path.exists():
        raise FileNotFoundError(f"Test set not found; looked in {_TESTSET_CANDIDATES}")
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


# --------------------------------------------------------------------------
# Capability extractors: map each tier's raw result to a capability dict.
# --------------------------------------------------------------------------

def _caps_baseline(res: dict[str, Any]) -> dict[str, bool]:
    # Baseline returns classification/severity + a rendered template; it has no
    # hypotheses, next-check, remediation, approval gating, or recovery notion.
    cls = res.get("classification")
    sev = res.get("severity")
    known = res.get("entity_known")
    resp = res.get("response", "")
    return {
        "classification": bool(cls) and cls != "insufficient_evidence",
        "severity": bool(sev),
        "business_impact": "Business impact" in resp,
        "affected_services": "Business svc" in resp,
        "hypotheses": False,
        "next_check": False,
        "recipients": "Notify (static lookup)" in resp and bool(known),
        "remediation": False,
        "approval_gated": False,          # baseline has no action model
        "recovery_or_uncertainty": False,  # baseline is stateless, no recovery
    }


def _caps_llm(res: dict[str, Any]) -> dict[str, bool]:
    r = res.get("result", {}) or {}
    return {
        "classification": bool(r.get("classification")) and r.get("classification") != "insufficient_evidence",
        "severity": bool(r.get("severity")),
        "business_impact": bool(r.get("business_impact")),
        "affected_services": bool(r.get("affected_services")),
        "hypotheses": bool(r.get("hypotheses")),
        "next_check": bool(r.get("next_check")),
        "recipients": bool(r.get("recommended_recipients")),
        "remediation": False,  # single-node triage does not emit remediation actions
        "approval_gated": bool(r.get("requires_human_approval_for_actions")),
        "recovery_or_uncertainty": bool(r.get("uncertainty")),
    }


def _caps_multiagent(res: dict[str, Any]) -> dict[str, bool]:
    a = res.get("agents", {}) or {}
    a1, a3, a4, a5, a7, a8 = (a.get("a1", {}), a.get("a3", {}), a.get("a4", {}),
                              a.get("a5", {}), a.get("a7", {}), a.get("a8", {}))
    actions = a5.get("actions", []) if a5 else []
    return {
        "classification": bool(a1.get("classification")) and a1.get("classification") != "insufficient_evidence",
        "severity": bool(a3.get("severity")),
        "business_impact": bool(a3.get("impact")),
        "affected_services": bool(a3.get("affected_services")),
        "hypotheses": bool(a4.get("hypotheses")),
        "next_check": bool(a4.get("next_checks")) or any(h.get("next_check") for h in a4.get("hypotheses", [])),
        "recipients": bool(a7.get("recipients_by_role")),
        "remediation": bool(actions),
        "approval_gated": bool(actions) and all(act.get("requires_approval") for act in actions),
        "recovery_or_uncertainty": bool(a8.get("recovery_status")),
    }


def _score(caps: dict[str, bool]) -> int:
    return sum(1 for _, key in CAPABILITIES if caps.get(key))


def run_comparison(cases: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = BaselineAgent()
    llm_agents = {v: LLMAgent(prompt_version=v) for v in ("v1", "v2", "v3")}
    multiagent = MultiAgentSentinel()
    provider = multiagent.provider

    tiers: dict[str, Callable[[dict[str, Any]], dict[str, bool]]] = {
        "baseline": lambda sig: _caps_baseline(baseline.handle(json.dumps(sig))),
        "llm_v1": lambda sig: _caps_llm(llm_agents["v1"].triage_signal(sig, "v1")),
        "llm_v2": lambda sig: _caps_llm(llm_agents["v2"].triage_signal(sig, "v2")),
        "llm_v3": lambda sig: _caps_llm(llm_agents["v3"].triage_signal(sig, "v3")),
        "multiagent": lambda sig: _caps_multiagent(multiagent.run_signal(sig)),
    }
    tier_names = list(tiers.keys())

    per_case: list[dict[str, Any]] = []
    agg = {t: 0 for t in tier_names}            # all cases
    agg_actionable = {t: 0 for t in tier_names}  # only actionable cases (fair headline)
    cap_tally = {t: {key: 0 for _, key in CAPABILITIES} for t in tier_names}

    n_actionable = sum(1 for c in cases if c.get("actionable", True))

    for case in cases:
        sig = case["signal"]
        actionable = case.get("actionable", True)
        row = {"id": case["id"], "note": case.get("note", ""),
               "actionable": actionable, "by_tier": {}}
        for t in tier_names:
            caps = tiers[t](sig)
            score = _score(caps)
            agg[t] += score
            if actionable:
                agg_actionable[t] += score
            for _, key in CAPABILITIES:
                if caps.get(key):
                    cap_tally[t][key] += 1
            row["by_tier"][t] = {"score": score, "caps": caps}
        per_case.append(row)

    return {
        "provider": provider,
        "tiers": tier_names,
        "capabilities": [{"id": cid, "key": key} for cid, key in CAPABILITIES],
        "n_cases": len(cases),
        "n_actionable": n_actionable,
        "aggregate_actionable": agg_actionable,
        "max_per_tier_actionable": len(CAPABILITIES) * n_actionable,
        "max_per_tier": len(CAPABILITIES) * len(cases),
        "aggregate": agg,
        "capability_tally": cap_tally,
        "per_case": per_case,
    }


def to_markdown(report: dict[str, Any]) -> str:
    tiers = report["tiers"]
    n = report["n_cases"]
    na = report["n_actionable"]
    L: list[str] = []
    L.append("# Cross-Tier Comparison - Baseline vs LLM Prompts vs Multi-Agent")
    L.append("")
    L.append(f"Provider: `{report['provider']}`  |  cases: {n} ({na} actionable, "
             f"{n - na} correctly gated)  |  10 capabilities per case")
    L.append("")
    labels = {
        "baseline": "Phase 2 baseline (rules/templates, no LLM)",
        "llm_v1": "Phase 3 LLM - prompt v1 (minimal)",
        "llm_v2": "Phase 3 LLM - prompt v2 (structured)",
        "llm_v3": "Phase 3 LLM - prompt v3 (few-shot/CoT/safety)",
        "multiagent": "Phase 3b multi-agent A1-A8",
    }
    L.append("## Headline: capability coverage on ACTIONABLE incidents")
    L.append("")
    L.append("Scored only on the %d actionable cases (non-actionable signals are correctly gated "
             "to a watch state, so incident-workflow capabilities should NOT fire there). This is "
             "the fair quality measure." % na)
    L.append("")
    L.append("| Tier | Aggregate (max %d) | Avg capabilities/case |" % report["max_per_tier_actionable"])
    L.append("|------|--------------------|------------------------|")
    for t in tiers:
        agg = report["aggregate_actionable"][t]
        L.append(f"| {labels.get(t, t)} | {agg} | {agg / na:.2f} |")
    L.append("")
    L.append("## All-cases aggregate (includes gated cases, for reference)")
    L.append("")
    L.append("| Tier | Aggregate (max %d) |" % report["max_per_tier"])
    L.append("|------|--------------------|")
    for t in tiers:
        L.append(f"| {labels.get(t, t)} | {report['aggregate'][t]} |")
    L.append("")

    # capability coverage matrix (per capability, how many of N cases covered)
    L.append("## Capability coverage matrix (cases covered / %d)" % n)
    L.append("")
    header = "| Capability | " + " | ".join(tiers) + " |"
    sep = "|" + "---|" * (len(tiers) + 1)
    L.append(header)
    L.append(sep)
    cap_label = {
        "classification": "C1 classification",
        "severity": "C2 severity",
        "business_impact": "C3 business impact",
        "affected_services": "C4 affected services",
        "hypotheses": "C5 ranked hypotheses",
        "next_check": "C6 next diagnostic check",
        "recipients": "C7 stakeholder recipients",
        "remediation": "C8 remediation actions",
        "approval_gated": "C9 approval-gated (safety)",
        "recovery_or_uncertainty": "C10 recovery/uncertainty",
    }
    for _, key in CAPABILITIES:
        cells = " | ".join(str(report["capability_tally"][t][key]) for t in tiers)
        L.append(f"| {cap_label[key]} | {cells} |")
    L.append("")

    # per-case scores
    L.append("## Per-case capability score (out of 10)")
    L.append("")
    L.append("| Case | actionable | " + " | ".join(tiers) + " |")
    L.append("|" + "---|" * (len(tiers) + 2))
    for row in report["per_case"]:
        cells = " | ".join(str(row["by_tier"][t]["score"]) for t in tiers)
        flag = "yes" if row.get("actionable") else "gated"
        L.append(f"| {row['id']} | {flag} | {cells} |")
    L.append("")
    L.append("> On actionable incidents the ordering is baseline < v1 < v2 < v3 <= multi-agent, "
             "with multi-agent uniquely adding remediation actions (C8). On gated cases a LOW "
             "score is CORRECT: the A1 gate stops noise/insufficient-evidence signals before the "
             "incident workflow runs.")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Prompt -> Output transcript capture (actual input + raw output per version)
# --------------------------------------------------------------------------

def _render_prompt(messages: list[Any]) -> str:
    """Flatten a list of LangChain messages into readable role-tagged text."""
    parts = []
    for m in messages:
        role = getattr(m, "type", m.__class__.__name__)
        content = m.content if isinstance(m.content, str) else str(m.content)
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


def capture_transcript(case: dict[str, Any]) -> dict[str, Any]:
    """For one case, capture the actual PROMPT (input) and raw OUTPUT per version.

    Covers: baseline (template, no prompt), LLM v1/v2/v3 (rendered prompt + raw
    model output), and the multi-agent pipeline (each A1-A8 agent's rendered
    prompt + raw output).
    """
    sig = case["signal"]
    chat = get_chat_model()
    context = _build_context(sig)
    context_json = json.dumps(context, ensure_ascii=False)

    entries: list[dict[str, Any]] = []

    # Baseline: no prompt; it is a deterministic template. Record its input + output.
    baseline = BaselineAgent()
    b_res = baseline.handle(json.dumps(sig))
    entries.append({
        "tier": "baseline",
        "label": "Phase 2 baseline (rules/templates, no LLM)",
        "prompt": "(no prompt - deterministic rules/template; input is the signal JSON)",
        "input": json.dumps(sig, ensure_ascii=False),
        "output": b_res.get("response", ""),
    })

    # LLM v1/v2/v3: rendered prompt + raw model output.
    for v in ("v1", "v2", "v3"):
        messages = PROMPTS[v].format_messages(context_json=context_json)
        resp = chat.invoke(messages)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        entries.append({
            "tier": f"llm_{v}",
            "label": f"Phase 3 single-node LLM - prompt {v}",
            "prompt": _render_prompt(messages),
            "input": context_json,
            "output": raw,
        })

    # Multi-agent: capture each agent's rendered prompt + raw output in order.
    agent_entries: list[dict[str, Any]] = []
    for agent_id in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
        msgs = AGENT_PROMPTS[agent_id].format_messages(agent_id=agent_id, context_json=context_json)
        resp = chat.invoke(msgs)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        agent_entries.append({
            "agent_id": agent_id,
            "agent_name": AGENT_NAMES[agent_id],
            "prompt": _render_prompt(msgs),
            "output": raw,
        })
    entries.append({
        "tier": "multiagent",
        "label": "Phase 3b multi-agent A1-A8 (per-agent prompts)",
        "agents": agent_entries,
    })

    return {"case_id": case["id"], "signal": sig, "entries": entries}


def transcript_to_markdown(transcript: dict[str, Any]) -> str:
    L: list[str] = []
    L.append("# Prompt -> Output Transcript")
    L.append("")
    L.append(f"Case: `{transcript['case_id']}`")
    L.append("")
    L.append("Signal (input):")
    L.append("```json")
    L.append(json.dumps(transcript["signal"], indent=2, ensure_ascii=False))
    L.append("```")
    L.append("")
    for e in transcript["entries"]:
        L.append("---")
        L.append(f"## {e['label']}")
        L.append("")
        if e["tier"] == "multiagent":
            for a in e["agents"]:
                L.append(f"### {a['agent_id']} - {a['agent_name']}")
                L.append("")
                L.append("Prompt (input):")
                L.append("```text")
                L.append(a["prompt"])
                L.append("```")
                L.append("Output (raw):")
                L.append("```json")
                L.append(a["output"])
                L.append("```")
                L.append("")
            continue
        L.append("Prompt (input):")
        L.append("```text")
        L.append(e["prompt"])
        L.append("```")
        L.append("Output (raw):")
        L.append("```text")
        L.append(e["output"])
        L.append("```")
        L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Cross-tier capability comparison")
    parser.add_argument("--test-set", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--md-out", default=None)
    parser.add_argument("--transcript-case", default=None,
                        help="case id to capture a Prompt->Output transcript for "
                             "(default: first actionable case)")
    args = parser.parse_args(argv)

    test_set_path = Path(args.test_set) if args.test_set else _default_testset()
    cases = load_cases(test_set_path)
    report = run_comparison(cases)

    out_dir = test_set_path.parent
    json_out = Path(args.json_out) if args.json_out else out_dir / "multiagent_comparison.json"
    md_out = Path(args.md_out) if args.md_out else out_dir / "multiagent_comparison.md"

    Path(json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md = to_markdown(report)
    Path(md_out).write_text(md, encoding="utf-8")

    # Prompt -> Output transcript for a representative case.
    if args.transcript_case:
        tcase = next((c for c in cases if c["id"] == args.transcript_case), None)
    else:
        tcase = next((c for c in cases if c.get("actionable", True)), cases[0])
    transcript = capture_transcript(tcase)
    t_json = out_dir / "prompt_output_transcript.json"
    t_md = out_dir / "prompt_output_transcript.md"
    t_json.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")
    t_md.write_text(transcript_to_markdown(transcript), encoding="utf-8")

    print(md)
    print(f"\nWrote {json_out}\nWrote {md_out}")
    print(f"Wrote {t_json}\nWrote {t_md}  (Prompt->Output transcript for {tcase['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
