"""Dependency-free safety policy shared by the server and verification CLI."""
from __future__ import annotations

MINIMUM_LATENCY_SAFETY_SAMPLES = 20
ALWAYS_HARD_BLOCKERS = frozenset({
    "unauthorized_graph_traffic", "duplicate_effects_detected",
    "duplicate_transition_observations_detected", "observation_write_failure",
    "observation_latency_incomplete",
})


def operational_safety_blockers(aggregate: dict) -> list[str]:
    hard = set(ALWAYS_HARD_BLOCKERS)
    graph_count = int(aggregate.get("assigned_graph_count") or 0)
    if graph_count > 0:
        hard.update({"comparator_not_exact", "fallback_rate_above_one_percent"})
    # Preserve the existing p95 safety floor, independently of release sample size.
    if graph_count >= MINIMUM_LATENCY_SAFETY_SAMPLES:
        hard.add("active_latency_regression")
    return sorted(hard.intersection(str(item) for item in aggregate.get("blockers") or []))
