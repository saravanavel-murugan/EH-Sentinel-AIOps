"""LLM provider factory for Phase 3.

Selects the chat model based on the ``SENTINEL_LLM`` environment variable:

* ``openai`` -> production path via ``langchain_openai.ChatOpenAI`` (needs
  ``OPENAI_API_KEY``). This is the real provider used in deployment.
* ``fake``   -> an offline, deterministic chat model used for verification and
  demos without any network access or API key. It returns schema-valid JSON so
  the full LangGraph graph, output parsing, and comparison harness can run and
  be validated end-to-end.

The fake model is NOT a substitute for real LLM reasoning — it exists so the
plumbing (prompt rendering, graph transitions, JSON parsing, error handling) is
provably correct before a live key is supplied. It intentionally varies its
output quality by prompt version so the comparison harness shows a realistic
spread (v1 worst, v3 best), mirroring how prompt quality affects a real model.

Security: no secrets are ever logged. Redaction and "data-not-instructions"
handling live in the graph/prompt layer, not here.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.language_models.chat_models import SimpleChatModel
from langchain_core.messages import BaseMessage


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --------------------------------------------------------------------------
# Offline deterministic fake chat model
# --------------------------------------------------------------------------

class DeterministicSentinelChatModel(SimpleChatModel):
    """A fake chat model that produces structured triage JSON from the prompt.

    It reads the serialized signal/context embedded in the human prompt and the
    prompt-version marker, then emits JSON whose completeness depends on the
    version. This lets the offline harness demonstrate prompt-quality effects
    deterministically (no randomness, no network).

    Subclasses ``SimpleChatModel`` so our ``_call`` drives every response.
    """

    @property
    def _llm_type(self) -> str:
        return "deterministic-sentinel-fake"

    def _call(self, messages: list[BaseMessage], stop: list[str] | None = None,
              run_manager: Any = None, **kwargs: Any) -> str:
        prompt_text = "\n".join(
            m.content if isinstance(m.content, str) else str(m.content)
            for m in messages
        )
        # Phase 5 tool router prompts are tagged ROUTER_REQUEST.
        if "ROUTER_REQUEST" in prompt_text:
            return json.dumps(self._route_tool(prompt_text))
        ctx = self._extract_context(prompt_text)
        # Multi-agent pipeline tags each prompt with AGENT_ID: An.
        agent_id = self._detect_agent_id(prompt_text)
        if agent_id:
            return json.dumps(self._build_agent_response(agent_id, ctx))
        # Single-node Phase 3 agent uses PROMPT_VERSION: vN.
        version = self._detect_version(prompt_text)
        return json.dumps(self._build_response(version, ctx))

    @staticmethod
    def _route_tool(prompt_text: str) -> dict[str, Any]:
        """Deterministic offline tool router: pick a tool from the user request by
        keyword. Mirrors how a real model would route, so demos run without a key."""
        # Extract the user request line.
        m = re.search(r"User request:\s*(.+)", prompt_text)
        req = (m.group(1) if m else prompt_text).lower()

        def _entity() -> str:
            # Keep the full 'type:id' key (e.g. topic:payments.settlement) so the
            # entity-table lookup in escalate/metrics tools resolves correctly.
            em = re.search(r"(topic|consumer_group|connector|broker):[a-z0-9._-]+", req)
            return em.group(0) if em else "topic:payments.settlement"

        def _metric() -> str:
            for mt in ("consumer_lag", "produce_error_rate",
                       "under_replicated_partitions", "broker_cpu"):
                if mt.replace("_", " ") in req or mt in req:
                    return mt
            return "consumer_lag"

        # notify / escalate intent
        if any(w in req for w in ("notify", "escalate", "page", "who to", "stakeholder")):
            sev = "P1" if "p1" in req else "P2" if "p2" in req else "P3"
            return {"tool": "escalate_incident",
                    "args": {"entity_id": _entity(), "severity": sev,
                             "message": "Operator-requested escalation."},
                    "reason": "request asks to notify/escalate"}
        # metric lookup intent
        if any(w in req for w in ("metric", "value", "lag value", "current", "recent", "trend", "how high")):
            return {"tool": "lookup_metric",
                    "args": {"entity_id": _entity(), "metric": _metric()},
                    "reason": "request asks for a metric value"}
        # knowledge search intent
        if any(w in req for w in ("how", "what causes", "runbook", "why", "last time", "resolve", "fix", "cause")):
            return {"tool": "search_knowledge",
                    "args": {"query": req[:120]},
                    "reason": "request is a how-to/knowledge question"}
        return {"tool": "none", "args": {}, "reason": "no tool matched the request"}

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _detect_version(text: str) -> str:
        m = re.search(r"PROMPT_VERSION\s*[:=]\s*(v[123])", text)
        return m.group(1) if m else "v1"

    @staticmethod
    def _detect_agent_id(text: str) -> str | None:
        m = re.search(r"AGENT_ID\s*[:=]\s*(A[1-8])", text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_context(text: str) -> dict[str, Any]:
        """Pull the JSON context block the prompt embeds after 'CONTEXT_JSON:'.

        Uses the LAST occurrence of the marker: the v3 system prompt contains a
        few-shot example with its own decoy 'CONTEXT_JSON:', while the real,
        grounded context is always appended in the final human turn.
        """
        marker = "CONTEXT_JSON:"
        idx = text.rfind(marker)
        if idx == -1:
            return {}
        tail = text[idx + len(marker):].strip()
        # Context is a single-line JSON object emitted by the graph.
        brace = tail.find("{")
        if brace == -1:
            return {}
        depth = 0
        for i, ch in enumerate(tail[brace:], start=brace):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(tail[brace:i + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}

    # -- multi-agent (A1-A8) deterministic responses ----------------------

    def _build_agent_response(self, agent_id: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Return a deterministic, schema-shaped response for one A1-A8 agent.

        Grounded in the deterministic context so the pipeline is verifiable
        offline. A real LLM would produce richer prose; the shapes match the
        typed contracts in agent/agents/contracts.py.
        """
        cls = ctx.get("rule_classification", "insufficient_evidence")
        sev = ctx.get("rule_severity")
        entity = ctx.get("entity_key", "unknown")
        metric = ctx.get("metric_or_event", "n/a")
        impact = ctx.get("business_impact")
        services = ctx.get("business_services", [])
        stakeholders = ctx.get("stakeholders", {})
        known = ctx.get("entity_known", False)

        if agent_id == "A1":
            score = {"confirmed": 0.9, "likely": 0.7, "transient": 0.4,
                     "noise": 0.1, "insufficient_evidence": 0.2}.get(cls, 0.2)
            return {
                "classification": cls,
                "anomaly_score": score,
                "evidence_refs": [f"metric:{metric}"],
                "missing_data": [] if known else ["entity not in catalogue"],
                "rationale": ctx.get("rule_classification_reason", ""),
                "recommended_next_query": None if known else f"resolve {entity} in CMDB",
            }
        if agent_id == "A2":
            return {
                "incident_candidate_id": f"inc-{entity}",
                "correlated_signal_ids": [],
                "dependency_path": [entity] + ([f"service:{services[0]}"] if services else []),
                "correlation_rationale": "Grouped by shared entity and time window.",
            }
        if agent_id == "A3":
            return {
                "severity": sev,
                "impact": impact,
                "affected_services": services,
                "confidence": "medium",
                "rationale": ctx.get("rule_severity_rationale", ""),
                "escalation_deadline": None,
                "review_required": ctx.get("criticality_tier") == 1,
            }
        if agent_id == "A4":
            # A novel metric is actionable even though the deterministic rule left
            # it 'insufficient_evidence' (no threshold): the pipeline routes it to
            # LLM reasoning, so produce hypotheses. This holds for unknown entities
            # too (the symptom is still analyzable; only recipients are unresolved).
            novel_actionable = bool(ctx.get("novel_metric"))
            if cls in ("noise", "insufficient_evidence") and not novel_actionable:
                return {"hypotheses": [], "observed_facts": [], "next_checks": [],
                        "analysis_source": "knowledge_base"}
            if novel_actionable and cls in ("noise", "insufficient_evidence"):
                cls = "likely"  # mirror the A1-node override for hypothesis gen
            grounded = bool(ctx.get("knowledge_grounded"))
            citation = self._retrieval_citation(ctx)
            hyp = self._hypotheses(metric, cls)
            hyps = []
            for i, h in enumerate(hyp):
                evidence_for = [h["evidence_for"]]
                if grounded and citation:
                    evidence_for.append(f"runbook: {citation}")
                else:
                    evidence_for.append("LLM domain inference (no runbook match)")
                hyps.append({
                    "rank": i + 1, "cause": h["cause"],
                    "evidence_for": evidence_for,
                    "evidence_against": [h["evidence_against"]],
                    "confidence": h["confidence"], "next_check": h["next_check"],
                })
            observed = [f"{metric}={ctx.get('value')}"]
            if grounded and citation:
                observed.append(f"grounded in {citation}")
            else:
                observed.insert(0, "No matching runbook/FAQ found; hypotheses "
                                   "inferred by LLM (validate before acting).")
            return {
                "hypotheses": hyps,
                "observed_facts": observed,
                "next_checks": [hyp[0]["next_check"]] if hyp else [],
                "analysis_source": "knowledge_base" if grounded else "llm_inference",
            }
        if agent_id == "A5":
            grounded = bool(ctx.get("knowledge_grounded"))
            citation = self._retrieval_citation(ctx)
            owner = stakeholders.get("prod_support", "prod_support")
            if grounded and citation:
                actions = [{
                    "action": f"Follow runbook step for {metric} (per {citation})",
                    "purpose": f"Apply approved runbook procedure from {citation}",
                    "expected_effect": "Narrow / resolve root cause per runbook",
                    "risk": "low (read-only)",
                    "preconditions": ["read access to metrics", "runbook retrieved"],
                    "owner": owner,
                    "verification": f"{metric} trend reviewed against runbook exit criteria",
                    "rollback": "n/a (read-only)",
                    "requires_approval": True,
                }]
            else:
                # NEW signal not covered by the KB: LLM proposes safe, reversible
                # diagnostics from first principles, tied to the A4 hypotheses.
                note = "no runbook found - LLM-inferred, human-validate before acting"
                actions = [
                    {
                        "action": f"Collect recent {metric} time-series and compare to baseline",
                        "purpose": "Establish magnitude/trend before any change",
                        "expected_effect": "Quantify the anomaly",
                        "risk": "low (read-only)",
                        "preconditions": ["read access to metrics", note],
                        "owner": owner,
                        "verification": f"{metric} trend captured",
                        "rollback": "n/a (read-only)",
                        "requires_approval": True,
                    },
                    {
                        "action": f"Inspect logs/health of the entity emitting {metric}",
                        "purpose": "Identify correlated errors or capacity limits",
                        "expected_effect": "Narrow likely root cause",
                        "risk": "low (read-only)",
                        "preconditions": ["read access to logs", note],
                        "owner": owner,
                        "verification": "relevant error signatures reviewed",
                        "rollback": "n/a (read-only)",
                        "requires_approval": True,
                    },
                    {
                        "action": "Escalate to a human SME for a novel/unclassified signal",
                        "purpose": "No approved runbook exists for this metric",
                        "expected_effect": "Expert confirms or writes a runbook",
                        "risk": "low",
                        "preconditions": [note],
                        "owner": owner,
                        "verification": "SME acknowledges the incident",
                        "rollback": "n/a",
                        "requires_approval": True,
                    },
                ]
            return {
                "read_only": True,
                "actions": actions,
                "analysis_source": "knowledge_base" if grounded else "llm_inference",
            }
        if agent_id == "A6":
            # The node fills the 7 structured sections deterministically; the model
            # only provides the narrative summary.
            return {
                "summary": (
                    f"{entity}: {metric} classified {cls} at severity {sev}. "
                    f"Business impact: {impact or 'unknown'}. "
                    f"Root cause and remediation consolidated from upstream agents; "
                    f"production actions require human approval."
                ),
            }
        if agent_id == "A7":
            return {
                "recipients_by_role": stakeholders,
                "message": f"{entity}: {cls} / {sev}. Impact: {impact or 'unknown'}.",
                "channel": "page" if sev in ("P1", "P2") else "ticket",
                "escalation_reason": None if known else "entity unknown; escalate to human",
                "delivery_status": "not_sent",
            }
        if agent_id == "A8":
            return {
                "recovery_status": "monitoring",
                "metrics_before_after": {},
                "closure_recommendation": "continue_monitoring",
                "feedback_record": {},
            }
        return {}

    @staticmethod
    def _retrieval_citation(ctx: dict[str, Any]) -> str | None:
        """Extract a short 'source :: heading' citation from retrieved_knowledge,
        or None when retrieval is disabled / found nothing."""
        rk = ctx.get("retrieved_knowledge", "")
        if not rk or rk.startswith("RETRIEVAL_DISABLED") or rk.startswith("NO_RELEVANT_KNOWLEDGE_FOUND"):
            return None
        # First snippet is formatted "[source :: heading | score=...] text".
        first = rk.split("\n", 1)[0]
        if first.startswith("[") and "]" in first:
            inside = first[1:first.index("]")]
            return inside.split("|")[0].strip()
        return None

    def _build_response(self, version: str, ctx: dict[str, Any]) -> dict[str, Any]:
        classification = ctx.get("rule_classification", "insufficient_evidence")
        severity = ctx.get("rule_severity")
        entity = ctx.get("entity_key", "unknown")
        metric = ctx.get("metric_or_event", "n/a")
        impact = ctx.get("business_impact")
        services = ctx.get("business_services", [])
        stakeholders = ctx.get("stakeholders", {})

        # v1 — minimal prompt: model returns a bare, often incomplete answer.
        if version == "v1":
            return {
                "classification": classification,
                "severity": severity,
                "summary": f"{entity}: {metric} looks {classification}.",
                # v1 omits evidence, hypotheses, recipients, uncertainty.
            }

        # v2 — structured prompt with schema: fuller, but shallow reasoning.
        if version == "v2":
            return {
                "classification": classification,
                "severity": severity,
                "affected_services": services,
                "business_impact": impact,
                "summary": (
                    f"{entity}: {metric} classified {classification}; "
                    f"severity {severity}. Impact: {impact or 'unknown'}."
                ),
                "recommended_recipients": stakeholders,
                # v2 still omits ranked hypotheses + evidence + uncertainty + next_check.
            }

        # v3 — few-shot + CoT + evidence/uncertainty: full, grounded output.
        hypotheses = self._hypotheses(metric, classification)
        return {
            "classification": classification,
            "severity": severity,
            "severity_rationale": ctx.get("rule_severity_rationale"),
            "affected_services": services,
            "business_impact": impact,
            "hypotheses": hypotheses,
            "next_check": hypotheses[0]["next_check"] if hypotheses else None,
            "recommended_recipients": stakeholders,
            "uncertainty": self._uncertainty(ctx),
            "summary": (
                f"{entity}: {metric} classified {classification} (severity {severity}). "
                f"Impact: {impact or 'unknown'}. "
                f"Top hypothesis: {hypotheses[0]['cause'] if hypotheses else 'n/a'}."
            ),
            "requires_human_approval_for_actions": True,
        }

    @staticmethod
    def _hypotheses(metric: str, classification: str) -> list[dict[str, Any]]:
        if classification in ("noise", "insufficient_evidence"):
            return []
        table = {
            "consumer_lag": [
                {"cause": "Downstream consumer slow / under-capacity",
                 "evidence_for": "lag rising vs baseline", "evidence_against": "no broker alerts",
                 "confidence": "medium", "next_check": "compare consumer throughput vs input rate"},
                {"cause": "Hot partition / skew",
                 "evidence_for": "single-partition lag", "evidence_against": "even distribution seen",
                 "confidence": "low", "next_check": "inspect per-partition lag"},
            ],
            "produce_error_rate": [
                {"cause": "Quota/throttling or ACL rejection",
                 "evidence_for": "error surge on produce", "evidence_against": "broker healthy",
                 "confidence": "medium", "next_check": "check quota + ACL denials for client"},
            ],
        }
        # Novel / unclassified metric (not in the small demo table and, typically,
        # not in the knowledge base): return a generic-but-reasonable set of
        # LLM-inference-style hypotheses so the offline path still demonstrates
        # first-principles reasoning for a NEW signal.
        return table.get(metric, [
            {"cause": f"Capacity / resource saturation driving {metric}",
             "evidence_for": f"{metric} exceeded its threshold",
             "evidence_against": "no corroborating capacity alert yet",
             "confidence": "medium",
             "next_check": f"compare {metric} against resource utilization (CPU/mem/IO) on the entity"},
            {"cause": f"Upstream/downstream dependency degradation affecting {metric}",
             "evidence_for": "metric anomalies often propagate across the dependency path",
             "evidence_against": "no correlated signals confirmed yet",
             "confidence": "low",
             "next_check": "check health + error rates of adjacent services/topics"},
            {"cause": f"Recent config/deploy change impacting {metric}",
             "evidence_for": "change is a common trigger for new anomalies",
             "evidence_against": "no change record correlated yet",
             "confidence": "low",
             "next_check": "review recent deploys/config changes for this entity in the change log"},
        ])

    @staticmethod
    def _uncertainty(ctx: dict[str, Any]) -> str:
        if not ctx.get("entity_known", False):
            return "Entity not found in catalogue; business impact/recipients unresolved - escalate to a human."
        if ctx.get("rule_classification") == "insufficient_evidence":
            return "No baseline rule for this metric; evidence insufficient — recommend gathering more telemetry."
        return "Grounded in deterministic rules; confidence qualified per hypothesis."


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_chat_model() -> Any:
    """Return a chat model per SENTINEL_LLM. Defaults to the offline fake model."""
    provider = _env("SENTINEL_LLM", "fake").lower()

    if provider == "openai":
        # Imported lazily so the offline path needs no openai package/key.
        from langchain_openai import ChatOpenAI

        api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SENTINEL_LLM=openai but OPENAI_API_KEY is not set. "
                "Set it in .env or switch SENTINEL_LLM=fake for offline runs."
            )
        model = _env("SENTINEL_OPENAI_MODEL", "gpt-4o-mini")
        try:
            temperature = float(_env("SENTINEL_LLM_TEMPERATURE", "0"))
        except ValueError:
            temperature = 0.0
        # Optional custom base URL for OpenAI-compatible gateways/proxies
        # (e.g. Vocareum "voc-" keys -> https://api.vocareum.com/v1).
        base_url = _env("SENTINEL_OPENAI_BASE_URL")
        kwargs: dict[str, Any] = {"model": model, "temperature": temperature, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    if provider == "fake":
        return DeterministicSentinelChatModel()

    raise RuntimeError(f"Unknown SENTINEL_LLM provider: {provider!r} (use 'openai' or 'fake').")


def provider_name() -> str:
    return _env("SENTINEL_LLM", "fake").lower()
