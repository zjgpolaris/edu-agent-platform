from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from security.audit_log import list_audit_events
from student_profile import list_learning_events
from trace_store import get_trace_store


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top(counter: Counter[str], limit: int = 8) -> dict[str, int]:
    return dict(counter.most_common(limit))


def _trace_id(event: dict[str, Any]) -> str | None:
    metadata = event.get("metadata") or {}
    trace_id = metadata.get("trace_id")
    return trace_id if isinstance(trace_id, str) and trace_id else None


def _event_time(event: dict[str, Any]) -> str:
    return str(event.get("created_at") or "")


def _tool_name(event: dict[str, Any]) -> str | None:
    value = (event.get("metadata") or {}).get("tool_name")
    return value if isinstance(value, str) and value else None


def _compact_recent(events: list[dict[str, Any]], *, fields: list[str], limit: int = 10) -> list[dict[str, Any]]:
    recent = []
    for event in events[:limit]:
        item = {field: event.get(field) for field in fields if field in event}
        metadata = event.get("metadata") or {}
        trace_id = metadata.get("trace_id")
        if trace_id:
            item["trace_id"] = trace_id
        recent.append(item)
    return recent


def _build_trace_groups(audit_events: list[dict[str, Any]], learning_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trace_id": "",
            "audit_count": 0,
            "learning_count": 0,
            "failure_count": 0,
            "actions": set(),
            "features": set(),
            "tools": set(),
            "errors": [],
            "latest_at": "",
        }
    )

    for event in audit_events:
        trace_id = _trace_id(event)
        if not trace_id:
            continue
        group = groups[trace_id]
        group["trace_id"] = trace_id
        group["audit_count"] += 1
        if event.get("action"):
            group["actions"].add(event["action"])
        if event.get("success") is False:
            group["failure_count"] += 1
            group["errors"].append(str(event.get("action") or "audit_failed"))
        group["latest_at"] = max(group["latest_at"], _event_time(event))

    for event in learning_events:
        trace_id = _trace_id(event)
        if not trace_id:
            continue
        group = groups[trace_id]
        group["trace_id"] = trace_id
        group["learning_count"] += 1
        if event.get("feature"):
            group["features"].add(event["feature"])
        tool_name = (event.get("metadata") or {}).get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            group["tools"].add(tool_name)
        if event.get("success") is False:
            group["failure_count"] += 1
            error_code = (event.get("metadata") or {}).get("error_code") or event.get("event_type") or "learning_failed"
            group["errors"].append(str(error_code))
        group["latest_at"] = max(group["latest_at"], _event_time(event))

    normalized = []
    for group in groups.values():
        normalized.append(
            {
                "trace_id": group["trace_id"],
                "audit_count": group["audit_count"],
                "learning_count": group["learning_count"],
                "status": "failed" if group["failure_count"] else "ok",
                "failure_count": group["failure_count"],
                "error_summary": "; ".join(group["errors"][:3]),
                "actions": sorted(group["actions"]),
                "features": sorted(group["features"]),
                "tools": sorted(group["tools"]),
                "latest_at": group["latest_at"],
            }
        )
    return sorted(normalized, key=lambda item: item["latest_at"], reverse=True)[:20]


def _status(total_events: int, coverage_rate: float) -> str:
    if total_events == 0:
        return "no_events"
    if coverage_rate < 0.5:
        return "partial_trace_coverage"
    return "ok"


def _rate(success: int, total: int) -> float:
    return round(success / total, 3) if total else 0.0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def _metadata_number(metadata: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _build_production_summary(trace_limit: int = 20) -> dict[str, Any]:
    recent_traces = get_trace_store().list_recent_traces(limit=trace_limit)
    step_latencies: list[float] = []
    llm_latencies: list[float] = []
    llm_costs: list[float] = []
    model_counts: Counter[str] = Counter()
    rag_diagnosis_counts: Counter[str] = Counter()
    rag_failure_stage_counts: Counter[str] = Counter()
    fallback_count = 0
    llm_error_count = 0
    total_steps = 0
    llm_calls = 0

    for trace in recent_traces:
        for event in trace.get("events") or []:
            total_steps += 1
            metadata = event.get("metadata") or {}
            latency = event.get("latency_ms")
            if isinstance(latency, (int, float)):
                step_latencies.append(float(latency))
            rag_inspector = metadata.get("rag_inspector")
            if isinstance(rag_inspector, dict):
                diagnosis_code = _metadata_text(rag_inspector, "diagnosis_code")
                failure_stage = _metadata_text(rag_inspector, "failure_stage")
                if diagnosis_code:
                    rag_diagnosis_counts[diagnosis_code] += 1
                if failure_stage and failure_stage != "none":
                    rag_failure_stage_counts[failure_stage] += 1
            if event.get("event_type") == "llm":
                llm_calls += 1
                if isinstance(latency, (int, float)):
                    llm_latencies.append(float(latency))
                model = metadata.get("configured_model") or metadata.get("attempt_model") or metadata.get("model")
                if isinstance(model, str) and model:
                    model_counts[model] += 1
                cost = _metadata_number(metadata, "cost_usd_estimated", "cost_usd")
                if cost is not None:
                    llm_costs.append(cost)
                attempt_index = metadata.get("attempt_index")
                fallback_attempt = isinstance(attempt_index, (int, float)) and attempt_index > 1
                if metadata.get("degraded") or metadata.get("fallback_used") or metadata.get("partial_output") or fallback_attempt:
                    fallback_count += 1
                if metadata.get("error") or event.get("status") == "error":
                    llm_error_count += 1

    total_cost = round(sum(llm_costs), 6)
    avg_cost = round(total_cost / len(llm_costs), 6) if llm_costs else 0.0
    return {
        "trace_window": len(recent_traces),
        "total_steps": total_steps,
        "latency": {
            "sample_count": len(step_latencies),
            "p50_ms": _percentile(step_latencies, 0.5),
            "p95_ms": _percentile(step_latencies, 0.95),
            "llm_p50_ms": _percentile(llm_latencies, 0.5),
            "llm_p95_ms": _percentile(llm_latencies, 0.95),
        },
        "llm": {
            "calls": llm_calls,
            "fallback_count": fallback_count,
            "error_count": llm_error_count,
            "models": _top(model_counts),
        },
        "rag": {
            "diagnosis": _top(rag_diagnosis_counts),
            "failure_stage": _top(rag_failure_stage_counts),
        },
        "cost": {
            "sample_count": len(llm_costs),
            "total_usd_estimated": total_cost,
            "avg_usd_per_llm_call_estimated": avg_cost,
        },
    }


def _readiness_status(*, coverage_rate: float, audit_failure: int, learning_failure: int, tool_failure: int, total_events: int, llm_error_count: int = 0) -> dict[str, Any]:
    reasons = []
    if total_events == 0:
        reasons.append("no_runtime_events")
    if coverage_rate < 0.5 and total_events:
        reasons.append("trace_coverage_below_50_percent")
    if audit_failure:
        reasons.append("audit_failures_present")
    if learning_failure:
        reasons.append("learning_failures_present")
    if tool_failure:
        reasons.append("tool_failures_present")
    if llm_error_count:
        reasons.append("llm_errors_present")

    if audit_failure or learning_failure or tool_failure or llm_error_count:
        status = "fail"
    elif total_events and coverage_rate >= 0.8:
        status = "pass"
    elif total_events:
        status = "warn"
    else:
        status = "unknown"
    return {"status": status, "reasons": reasons}


def build_agent_ops_summary(limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    try:
        audit_events = list_audit_events(limit=limit)
        learning_events = list_learning_events(limit=limit)
    except Exception as exc:
        return {
            "schema_version": 1,
            "generated_at": _generated_at(),
            "window": {"limit": limit},
            "status": "unavailable",
            "error": str(exc),
        }

    audit_with_trace = sum(1 for event in audit_events if _trace_id(event))
    learning_with_trace = sum(1 for event in learning_events if _trace_id(event))
    total_events = len(audit_events) + len(learning_events)
    traced_events = audit_with_trace + learning_with_trace
    coverage_rate = round(traced_events / total_events, 3) if total_events else 0.0

    audit_action_counts = Counter(str(event.get("action") or "unknown") for event in audit_events)
    audit_resource_counts = Counter(str(event.get("resource_type") or "unknown") for event in audit_events)
    learning_feature_counts = Counter(str(event.get("feature") or "unknown") for event in learning_events)
    learning_type_counts = Counter(str(event.get("event_type") or "unknown") for event in learning_events)
    tool_counts = Counter(tool_name for event in learning_events if (tool_name := _tool_name(event)))
    tool_success_counts = Counter(
        tool_name
        for event in learning_events
        if (tool_name := _tool_name(event)) and event.get("success") is True
    )
    tool_failure_counts = Counter(
        tool_name
        for event in learning_events
        if (tool_name := _tool_name(event)) and event.get("success") is False
    )
    tool_failures = [
        {
            "tool_name": (event.get("metadata") or {}).get("tool_name"),
            "event_type": event.get("event_type"),
            "student_id": event.get("student_id"),
            "trace_id": _trace_id(event),
            "created_at": event.get("created_at"),
        }
        for event in learning_events
        if (event.get("metadata") or {}).get("tool_name") and event.get("success") is False
    ][:20]

    unique_trace_ids = sorted({trace_id for event in [*audit_events, *learning_events] if (trace_id := _trace_id(event))})
    learning_success = sum(1 for event in learning_events if event.get("success") is True)
    learning_failure = sum(1 for event in learning_events if event.get("success") is False)
    learning_unknown = len(learning_events) - learning_success - learning_failure
    audit_success = sum(1 for event in audit_events if event.get("success") is True)
    audit_failure = len(audit_events) - audit_success
    total_tool_calls = sum(tool_counts.values())
    total_tool_failures = sum(tool_failure_counts.values())
    production = _build_production_summary(trace_limit=20)
    readiness = _readiness_status(
        coverage_rate=coverage_rate,
        audit_failure=audit_failure,
        learning_failure=learning_failure,
        tool_failure=total_tool_failures,
        total_events=total_events,
        llm_error_count=int((production.get("llm") or {}).get("error_count") or 0),
    )

    return {
        "schema_version": 1,
        "generated_at": _generated_at(),
        "window": {"limit": limit},
        "status": _status(total_events, coverage_rate),
        "readiness": readiness,
        "trace_correlation": {
            "audit_total": len(audit_events),
            "audit_with_trace": audit_with_trace,
            "learning_total": len(learning_events),
            "learning_with_trace": learning_with_trace,
            "coverage_rate": coverage_rate,
            "unique_trace_ids": len(unique_trace_ids),
        },
        "audit": {
            "total": len(audit_events),
            "success": audit_success,
            "failure": audit_failure,
            "success_rate": _rate(audit_success, len(audit_events)),
            "by_action": _top(audit_action_counts),
            "by_resource_type": _top(audit_resource_counts),
            "recent": _compact_recent(audit_events, fields=["id", "action", "actor_id", "resource_type", "resource_id", "success", "created_at"]),
        },
        "learning": {
            "total": len(learning_events),
            "success": learning_success,
            "failure": learning_failure,
            "unknown": learning_unknown,
            "success_rate": _rate(learning_success, len(learning_events)),
            "by_feature": _top(learning_feature_counts),
            "by_event_type": _top(learning_type_counts),
            "recent": _compact_recent(learning_events, fields=["id", "student_id", "feature", "event_type", "success", "created_at"]),
        },
        "tools": {
            "total": total_tool_calls,
            "failure": total_tool_failures,
            "success_rate": _rate(total_tool_calls - total_tool_failures, total_tool_calls),
            "by_tool_name": _top(tool_counts),
            "by_success": _top(tool_success_counts),
            "by_failure": _top(tool_failure_counts),
            "failures": tool_failures,
        },
        "production": production,
        "traces": {
            "recent": _build_trace_groups(audit_events, learning_events),
        },
    }
