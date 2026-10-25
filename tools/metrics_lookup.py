"""Metrics-lookup tool (Phase 5): sandboxed time-series for a Kafka entity.

Returns a canned/sandbox metric series so the agent can "check a metric" without
a live cluster. Read-only, no approval. In production this would wrap an approved,
allow-listed Prometheus/Control-Center query with time-range + row limits.
"""

from __future__ import annotations

from typing import Any

from .tool_registry import Tool, ToolError, ToolParam

# Sandbox fixtures keyed by metric; deterministic so demos are reproducible.
_SANDBOX: dict[str, dict[str, Any]] = {
    "consumer_lag": {"unit": "messages", "series": [40000, 55000, 80000, 110000, 125000],
                     "trend": "rising"},
    "produce_error_rate": {"unit": "errors/s", "series": [2, 5, 18, 30, 35], "trend": "rising"},
    "under_replicated_partitions": {"unit": "count", "series": [0, 0, 1, 2, 3], "trend": "rising"},
    "broker_cpu": {"unit": "percent", "series": [40, 42, 45, 44, 43], "trend": "flat"},
}


def lookup_metric(entity_id: str, metric: str, window_points: int = 5) -> dict[str, Any]:
    """Return a sandbox time-series for (entity, metric)."""
    fixture = _SANDBOX.get(metric)
    if fixture is None:
        raise ToolError(f"no sandbox series for metric '{metric}' "
                        f"(known: {sorted(_SANDBOX.keys())})")
    try:
        n = max(1, min(int(window_points), len(fixture["series"])))
    except (TypeError, ValueError):
        n = len(fixture["series"])
    series = fixture["series"][-n:]
    return {
        "entity_id": entity_id,
        "metric": metric,
        "unit": fixture["unit"],
        "series": series,
        "latest": series[-1],
        "trend": fixture["trend"],
        "source": "sandbox",
    }


METRICS_TOOL = Tool(
    name="lookup_metric",
    description="Fetch a recent (sandbox) time-series for a metric on an entity. "
                "Use for 'what is the current/recent value of <metric> on <entity>' questions.",
    parameters=[
        ToolParam("entity_id", "string", required=True, description="e.g. topic:payments.settlement"),
        ToolParam("metric", "string", required=True, description="e.g. consumer_lag"),
        ToolParam("window_points", "number", required=False, description="how many recent points (default 5)"),
    ],
    fn=lookup_metric,
    requires_approval=False,
    read_only=True,
)
