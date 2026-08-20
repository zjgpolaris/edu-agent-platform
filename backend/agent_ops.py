from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from security.audit_log import count_audit_events, list_audit_events
from student_profile import count_learning_events, list_learning_events
from trace_store import get_trace_store


def _build_runtime_v2_summary(*, since: str, data_scope: str) -> dict[str, Any]:
    try:
        from sqlalchemy import inspect as sa_inspect, text
        from db.engine import get_connection

        with get_connection() as conn:
            tables = set(sa_inspect(conn).get_table_names())
            required = {"agent_runs", "agent_run_events", "agent_checkpoints"}
            if not required.issubset(tables):
                return {"status": "unknown", "reason": "runtime_v2_schema_unavailable", "run_count": None}
            runs = [dict(row) for row in conn.execute(text("""SELECT r.* FROM agent_runs r
                WHERE r.created_at>=:since AND EXISTS (
                    SELECT 1 FROM agent_run_events e
                    WHERE e.run_id=r.run_id AND e.data_scope=:data_scope
                )"""), {"since": since, "data_scope": data_scope}).mappings().all()]
            event_rows = conn.execute(text("""SELECT run_id, COUNT(*) AS event_count
                FROM agent_run_events WHERE created_at>=:since AND data_scope=:data_scope
                GROUP BY run_id"""), {"since": since, "data_scope": data_scope}).mappings().all()
            checkpoint_rows = conn.execute(text("""SELECT run_id, COUNT(*) AS checkpoint_count
                FROM agent_checkpoints WHERE created_at>=:since GROUP BY run_id"""), {"since": since}).mappings().all()
            event_types = conn.execute(text("""SELECT event_type, COUNT(*) AS count
                FROM agent_run_events WHERE created_at>=:since AND data_scope=:data_scope
                GROUP BY event_type"""), {"since": since, "data_scope": data_scope}).mappings().all()
            runtime_event_details = conn.execute(text("""SELECT event_type, public_payload_json
                FROM agent_run_events WHERE created_at>=:since AND data_scope=:data_scope
                AND event_type IN ('run_failed','side_effect_duplicate_prevented','runtime_comparison')"""), {
                    "since": since,
                    "data_scope": data_scope,
                }).mappings().all()
            runtime_audits = []
            if "audit_events" in tables:
                runtime_audits = conn.execute(text("""SELECT action, COUNT(*) AS count
                    FROM audit_events WHERE created_at>=:since AND action LIKE 'agent_runtime.%'
                    GROUP BY action"""), {"since": since}).mappings().all()
    except Exception as exc:
        return {"status": "unknown", "reason": "runtime_v2_query_failed", "error_type": exc.__class__.__name__, "run_count": None}

    if not runs:
        return {
            "status": "unknown",
            "reason": "no_runtime_v2_samples",
            "run_count": 0,
            "event_count": 0,
            "event_coverage": None,
            "checkpoint_run_count": 0,
            "by_runtime_mode": {},
            "event_coverage_by_runtime_mode": {},
            "waiting_run_count": None,
            "recovery_interrupted_total": None,
            "duplicate_side_effect_prevented_total": None,
            "invalid_transition_total": None,
            "legacy_v2_disagreement_total": None,
        }
    status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    agent_counts = Counter(str(run.get("agent_type") or "unknown") for run in runs)
    mode_counts = Counter(str(run.get("durability_mode") or "unknown") for run in runs)
    config_counts = Counter(str(run.get("config_version") or "unknown") for run in runs)
    revision_counts = Counter(str(run.get("revision") if run.get("revision") is not None else "unknown") for run in runs)
    step_counts = Counter(str(run.get("current_step_id") or "none") for run in runs)
    runtime_mode_counts: Counter[str] = Counter()
    runtime_mode_by_run: dict[str, str] = {}
    completion_reasons: Counter[str] = Counter()
    for run in runs:
        try:
            completion = json.loads(run.get("completion_json") or "{}")
        except Exception:
            completion = {}
        try:
            context_refs = json.loads(run.get("context_refs_json") or "{}")
        except Exception:
            context_refs = {}
        runtime_mode = str(context_refs.get("runtime_mode") or "unknown")
        runtime_mode_counts[runtime_mode] += 1
        runtime_mode_by_run[str(run["run_id"])] = runtime_mode
        completion_reasons.update(str(code) for code in completion.get("reason_codes") or [])
    events_by_run = {str(row["run_id"]): int(row["event_count"] or 0) for row in event_rows}
    checkpoints_by_run = {str(row["run_id"]): int(row["checkpoint_count"] or 0) for row in checkpoint_rows}
    terminal = [run for run in runs if run.get("status") in {"completed", "partial", "failed", "cancelled"}]
    inconsistent_terminal = sum(1 for run in terminal if not run.get("completion_json") or not run.get("finished_at"))
    resumable = [run for run in runs if run.get("durability_mode") == "resumable"]
    audit_counts = {str(row["action"]): int(row["count"] or 0) for row in runtime_audits}
    recovery_interrupted = 0
    duplicate_prevented = audit_counts.get("agent_runtime.duplicate_side_effect_prevented", 0)
    legacy_v2_disagreement = 0
    for event in runtime_event_details:
        try:
            payload = json.loads(event.get("public_payload_json") or "{}")
        except Exception:
            payload = {}
        if event.get("event_type") == "run_failed" and (payload.get("error") or {}).get("code") == "runtime_interrupted":
            recovery_interrupted += 1
        elif event.get("event_type") == "side_effect_duplicate_prevented":
            duplicate_prevented += 1
        elif event.get("event_type") == "runtime_comparison" and payload.get("agreement") is False:
            legacy_v2_disagreement += 1
    event_coverage_by_runtime_mode = {}
    for runtime_mode, mode_run_count in runtime_mode_counts.items():
        covered = sum(
            events_by_run.get(run_id, 0) > 0
            for run_id, recorded_mode in runtime_mode_by_run.items()
            if recorded_mode == runtime_mode
        )
        event_coverage_by_runtime_mode[runtime_mode] = _rate(covered, mode_run_count)
    return {
        "status": "ok",
        "run_count": len(runs),
        "event_count": sum(events_by_run.values()),
        "event_coverage": _rate(sum(events_by_run.get(str(run["run_id"]), 0) > 0 for run in runs), len(runs)),
        "terminal_consistency_rate": _rate(len(terminal) - inconsistent_terminal, len(terminal)) if terminal else None,
        "checkpoint_run_count": sum(checkpoints_by_run.get(str(run["run_id"]), 0) > 0 for run in resumable),
        "resumable_run_count": len(resumable),
        "checkpoint_coverage": _rate(sum(checkpoints_by_run.get(str(run["run_id"]), 0) > 0 for run in resumable), len(resumable)) if resumable else None,
        "by_status": dict(status_counts),
        "by_agent": dict(agent_counts),
        "by_durability_mode": dict(mode_counts),
        "by_runtime_mode": dict(runtime_mode_counts),
        "event_coverage_by_runtime_mode": event_coverage_by_runtime_mode,
        "by_config_version": dict(config_counts),
        "by_revision": dict(revision_counts),
        "by_current_step": dict(step_counts),
        "completion_reason_codes": dict(completion_reasons),
        "runtime_audit_actions": audit_counts,
        "waiting_run_count": status_counts.get("waiting_input", 0) + status_counts.get("waiting_confirmation", 0),
        "recovery_interrupted_total": recovery_interrupted,
        "duplicate_side_effect_prevented_total": duplicate_prevented,
        "invalid_transition_total": audit_counts.get("agent_runtime.invalid_transition", 0),
        "legacy_v2_disagreement_total": legacy_v2_disagreement,
        "by_event_type": {str(row["event_type"]): int(row["count"] or 0) for row in event_types},
    }


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


def _data_scope(event: dict[str, Any]) -> str:
    value = event.get("data_scope") or (event.get("metadata") or {}).get("data_scope")
    if value == "demo_seed":
        value = "demo"
    return value if value in {"runtime", "eval", "demo"} else "runtime"


def _outcome_class(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") or {}
    explicit = metadata.get("outcome_class")
    if explicit in {"success", "expected_control", "user_denied", "degraded", "unexpected_failure"}:
        return str(explicit)
    if event.get("success") is not False:
        return "success"
    if metadata.get("user_denied") is True or metadata.get("reason") == "user_denied":
        return "user_denied"
    if event.get("action") in {"tool.confirmation_required", "tool.role_denied", "tool.denied", "guardrail.blocked"} or metadata.get("error_code") in {
        "confirmation_required",
        "role_denied",
        "invalid_confirmation",
        "guardrail_blocked",
    }:
        return "expected_control"
    if metadata.get("degraded") is True:
        return "degraded"
    return "unexpected_failure"


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
        if _outcome_class(event) == "unexpected_failure":
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
        if _outcome_class(event) == "unexpected_failure":
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


def _build_production_summary(trace_limit: int = 20, *, data_scope: str = "runtime") -> dict[str, Any]:
    recent_traces = get_trace_store().list_recent_traces(limit=trace_limit, data_scope=data_scope)
    step_latencies: list[float] = []
    llm_latencies: list[float] = []
    llm_costs: list[float] = []
    model_counts: Counter[str] = Counter()
    rag_diagnosis_counts: Counter[str] = Counter()
    rag_failure_stage_counts: Counter[str] = Counter()
    fallback_count = 0
    llm_error_count = 0
    repair_attempts: set[tuple[str, str, int, str]] = set()
    repair_successes: set[tuple[str, str, int, str]] = set()
    routing_count = 0
    plan_step_count = 0
    total_steps = 0
    llm_calls = 0

    for trace in recent_traces:
        for event in trace.get("events") or []:
            metadata = event.get("metadata") or {}
            if _data_scope({"metadata": metadata}) != data_scope:
                continue
            total_steps += 1
            if event.get("event_type") == "repair":
                repair_key = (
                    str(trace.get("trace_id") or ""),
                    str(metadata.get("step_id") or event.get("step_name") or "repair"),
                    int(metadata.get("attempt") or 1),
                    str(metadata.get("operation") or metadata.get("repair_type") or "unknown"),
                )
                repair_attempts.add(repair_key)
                if event.get("status") == "success":
                    repair_successes.add(repair_key)
            if event.get("event_type") == "routing":
                routing_count += 1
            if event.get("event_type") == "plan_step":
                plan_step_count += 1
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
    repair_count = len(repair_attempts)
    repair_success_count = len(repair_successes)
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
        "runtime": {
            "routing_count": routing_count,
            "plan_step_count": plan_step_count,
            "repair_count": repair_count,
            "repair_success_count": repair_success_count,
            "repair_success_rate": _rate(repair_success_count, repair_count),
            "repair_rate": _rate(repair_count, routing_count),
        },
    }


def _readiness_status(
    *,
    coverage_rate: float,
    audit_failure: int,
    learning_failure: int,
    tool_failure: int,
    total_events: int,
    minimum_runtime_events: int,
    window_hours: int,
    llm_error_count: int = 0,
) -> dict[str, Any]:
    reasons: list[str] = []
    sample_sufficient = total_events >= minimum_runtime_events
    # Tool failures are a diagnostic slice of learning failures, not an
    # additional population. Counting them twice made readiness look worse
    # whenever the same tool event appeared in both cards.
    unexpected_failures = audit_failure + learning_failure + llm_error_count
    if total_events == 0:
        reasons.append("no_runtime_events")
    elif not sample_sufficient:
        reasons.append("insufficient_runtime_samples")
    if total_events and coverage_rate < 0.5:
        reasons.append("trace_coverage_below_50_percent")
    elif total_events and coverage_rate < 0.8:
        reasons.append("trace_coverage_below_80_percent")
    if audit_failure:
        reasons.append("unexpected_audit_failures_present")
    if learning_failure:
        reasons.append("unexpected_learning_failures_present")
    if tool_failure:
        reasons.append("unexpected_tool_failures_present")
    if llm_error_count:
        reasons.append("llm_errors_present")

    if unexpected_failures:
        status = "fail"
    elif not sample_sufficient:
        status = "unknown"
    elif coverage_rate < 0.5:
        status = "fail"
    elif coverage_rate >= 0.8:
        status = "pass"
    else:
        status = "warn"
    return {
        "status": status,
        "sample_sufficient": sample_sufficient,
        "runtime_event_count": total_events,
        "minimum_runtime_events": minimum_runtime_events,
        "window_hours": window_hours,
        "unexpected_failure_count": unexpected_failures,
        "reasons": reasons,
    }


def build_agent_ops_summary(
    limit: int = 100,
    *,
    scope: str = "runtime",
    window_hours: int | None = None,
    minimum_runtime_events: int | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    active_scope = "demo" if scope == "demo_seed" else scope
    if active_scope not in {"runtime", "eval", "demo"}:
        raise ValueError("invalid AgentOps data scope")
    configured_window = window_hours if window_hours is not None else int(os.getenv("EDU_AGENT_OPS_RUNTIME_WINDOW_HOURS", "24"))
    configured_window = max(1, min(int(configured_window), 24 * 30))
    minimum_events = minimum_runtime_events if minimum_runtime_events is not None else int(os.getenv("EDU_AGENT_OPS_MIN_RUNTIME_EVENTS", "100"))
    minimum_events = max(1, min(int(minimum_events), 10000))
    since = (datetime.now(timezone.utc) - timedelta(hours=configured_window)).isoformat()
    try:
        audit_events = list_audit_events(limit=limit, data_scope=active_scope, since=since)
        learning_events = list_learning_events(limit=limit, data_scope=active_scope, since=since)
        audit_scope_counts = {
            data_scope: count_audit_events(data_scope=data_scope, since=since)
            for data_scope in ("runtime", "eval", "demo")
        }
        learning_scope_counts = {
            data_scope: count_learning_events(data_scope=data_scope, since=since)
            for data_scope in ("runtime", "eval", "demo")
        }
    except Exception as exc:
        return {
            "schema_version": 2,
            "generated_at": _generated_at(),
            "window": {"limit": limit, "scope": active_scope, "window_hours": configured_window, "since": since},
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
        if (tool_name := _tool_name(event)) and _outcome_class(event) == "success"
    )
    tool_failure_counts = Counter(
        tool_name
        for event in learning_events
        if (tool_name := _tool_name(event)) and _outcome_class(event) == "unexpected_failure"
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
        if (event.get("metadata") or {}).get("tool_name") and _outcome_class(event) == "unexpected_failure"
    ][:20]

    unique_trace_ids = sorted({trace_id for event in [*audit_events, *learning_events] if (trace_id := _trace_id(event))})
    learning_success = sum(1 for event in learning_events if _outcome_class(event) == "success")
    learning_failure = sum(1 for event in learning_events if _outcome_class(event) == "unexpected_failure")
    learning_expected_control = sum(1 for event in learning_events if _outcome_class(event) == "expected_control")
    learning_user_denied = sum(1 for event in learning_events if _outcome_class(event) == "user_denied")
    learning_degraded = sum(1 for event in learning_events if _outcome_class(event) == "degraded")
    learning_unknown = len(learning_events) - learning_success - learning_failure - learning_expected_control - learning_user_denied - learning_degraded
    assistant_feedback = [
        str((event.get("metadata") or {}).get("feedback"))
        for event in learning_events
        if event.get("feature") == "learning_assistant" and event.get("event_type") == "answer_feedback"
    ]
    assistant_feedback_total = len(assistant_feedback)
    assistant_resolved = assistant_feedback.count("resolved")
    assistant_unresolved = assistant_feedback.count("unresolved")
    assistant_questions = [event for event in learning_events if event.get("feature") == "learning_assistant" and event.get("event_type") in {"question_asked", "followup_asked"}]
    assistant_followups = sum(1 for event in assistant_questions if event.get("event_type") == "followup_asked")
    assistant_answers = [event for event in learning_events if event.get("feature") == "learning_assistant" and event.get("event_type") == "answer_completed"]
    assistant_fallbacks = sum(1 for event in assistant_answers if (event.get("metadata") or {}).get("fallback_used") is True)
    assistant_real_llm = sum(1 for event in assistant_answers if (event.get("metadata") or {}).get("generation_mode") == "llm")
    assistant_routes = [event for event in learning_events if event.get("feature") == "learning_assistant" and event.get("event_type") == "intent_detected"]
    assistant_semantic_routes = sum(1 for event in assistant_routes if (event.get("metadata") or {}).get("routing_mode") == "semantic")
    assistant_rollout_modes = Counter(
        str(((event.get("metadata") or {}).get("rollout") or {}).get("route_mode") or "control")
        for event in assistant_routes
    )
    assistant_planner_active = sum(
        1 for event in assistant_routes
        if (((event.get("metadata") or {}).get("rollout") or {}).get("planner_mode") == "composition_active")
    )
    assistant_shadow_comparisons = [
        event for event in assistant_routes
        if (event.get("metadata") or {}).get("shadow_agreement") is not None
    ]
    assistant_shadow_agreements = sum(
        1 for event in assistant_shadow_comparisons
        if (event.get("metadata") or {}).get("shadow_agreement") is True
    )
    assistant_clarifications = [event for event in learning_events if event.get("feature") == "learning_assistant" and event.get("event_type") == "clarification_requested"]
    assistant_multi_intent = sum(1 for event in assistant_routes if int((event.get("metadata") or {}).get("task_count") or 0) > 1)
    assistant_planned_answers = [event for event in assistant_answers if int((event.get("metadata") or {}).get("total_steps") or 0) > 0]
    assistant_completed_plans = sum(1 for event in assistant_planned_answers if (event.get("metadata") or {}).get("completion_status") == "completed")
    assistant_partial_plans = sum(1 for event in assistant_planned_answers if (event.get("metadata") or {}).get("completion_status") == "partial")
    assistant_verified_answers = sum(1 for event in assistant_answers if (event.get("metadata") or {}).get("verification_status") == "verified")
    assistant_failed_verifications = sum(1 for event in assistant_answers if (event.get("metadata") or {}).get("verification_status") == "failed")
    assistant_required_verifications = assistant_verified_answers + assistant_failed_verifications
    assistant_clarification_resolved = sum(1 for event in assistant_answers if (event.get("metadata") or {}).get("clarification_resolved") is True)
    assistant_routing_feedback = [event for event in learning_events if event.get("feature") == "learning_assistant" and (event.get("metadata") or {}).get("routing_correct") is not None]
    assistant_routing_correct = sum(1 for event in assistant_routing_feedback if (event.get("metadata") or {}).get("routing_correct") is True)
    context_feedback = [
        event for event in learning_events
        if event.get("feature") == "learning_assistant"
        and event.get("event_type") == "answer_feedback"
        and int((event.get("metadata") or {}).get("history_messages") or 0) > 0
    ]
    context_resolved = sum(1 for event in context_feedback if (event.get("metadata") or {}).get("feedback") == "resolved")
    created_sessions = {
        str(event.get("session_id")) for event in learning_events
        if event.get("feature") == "learning_assistant" and event.get("event_type") == "session_created" and event.get("session_id")
    }
    resumed_sessions = {
        str(event.get("session_id")) for event in learning_events
        if event.get("feature") == "learning_assistant" and event.get("event_type") == "session_resumed" and event.get("session_id")
    }
    autotutor_question_sessions = {
        str((event.get("metadata") or {}).get("assistant_session_id")) for event in learning_events
        if event.get("feature") == "auto_tutor" and event.get("event_type") == "autotutor_question_asked" and (event.get("metadata") or {}).get("assistant_session_id")
    }
    autotutor_return_sessions = {
        str((event.get("metadata") or {}).get("assistant_session_id")) for event in learning_events
        if event.get("feature") == "auto_tutor" and event.get("event_type") == "autotutor_question_returned" and (event.get("metadata") or {}).get("assistant_session_id")
    }
    audit_success = sum(1 for event in audit_events if _outcome_class(event) == "success")
    audit_failure = sum(1 for event in audit_events if _outcome_class(event) == "unexpected_failure")
    audit_expected_control = sum(1 for event in audit_events if _outcome_class(event) == "expected_control")
    audit_user_denied = sum(1 for event in audit_events if _outcome_class(event) == "user_denied")
    audit_degraded = sum(1 for event in audit_events if _outcome_class(event) == "degraded")
    total_tool_calls = sum(tool_counts.values())
    total_tool_failures = sum(tool_failure_counts.values())
    production = _build_production_summary(trace_limit=20, data_scope=active_scope)
    runtime_v2 = _build_runtime_v2_summary(since=since, data_scope=active_scope)
    readiness = _readiness_status(
        coverage_rate=coverage_rate,
        audit_failure=audit_failure,
        learning_failure=learning_failure,
        tool_failure=total_tool_failures,
        total_events=audit_scope_counts[active_scope] + learning_scope_counts[active_scope],
        minimum_runtime_events=minimum_events,
        window_hours=configured_window,
        llm_error_count=int((production.get("llm") or {}).get("error_count") or 0),
    ) if active_scope == "runtime" else {
        "status": "not_applicable",
        "sample_sufficient": audit_scope_counts[active_scope] + learning_scope_counts[active_scope] >= minimum_events,
        "runtime_event_count": audit_scope_counts[active_scope] + learning_scope_counts[active_scope],
        "minimum_runtime_events": minimum_events,
        "window_hours": configured_window,
        "unexpected_failure_count": audit_failure + learning_failure,
        "reasons": ["readiness_is_runtime_only"],
    }

    return {
        "schema_version": 2,
        "generated_at": _generated_at(),
        "window": {"limit": limit, "scope": active_scope, "window_hours": configured_window, "since": since},
        "data_scope": {
            "active": active_scope,
            "audit": audit_scope_counts,
            "learning": learning_scope_counts,
            "counts_are_window_samples": True,
        },
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
            "unexpected_failure": audit_failure,
            "expected_control": audit_expected_control,
            "user_denied": audit_user_denied,
            "degraded": audit_degraded,
            "effective_total": audit_success + audit_failure,
            "success_rate": _rate(audit_success, audit_success + audit_failure),
            "by_action": _top(audit_action_counts),
            "by_resource_type": _top(audit_resource_counts),
            "recent": _compact_recent(audit_events, fields=["id", "action", "actor_id", "resource_type", "resource_id", "success", "created_at"]),
        },
        "learning": {
            "total": len(learning_events),
            "success": learning_success,
            "failure": learning_failure,
            "unexpected_failure": learning_failure,
            "expected_control": learning_expected_control,
            "user_denied": learning_user_denied,
            "degraded": learning_degraded,
            "unknown": learning_unknown,
            "effective_total": learning_success + learning_failure,
            "success_rate": _rate(learning_success, learning_success + learning_failure),
            "by_feature": _top(learning_feature_counts),
            "by_event_type": _top(learning_type_counts),
            "recent": _compact_recent(learning_events, fields=["id", "student_id", "feature", "event_type", "success", "created_at"]),
        },
        "learning_assistant": {
            "feedback_total": assistant_feedback_total,
            "resolved": assistant_resolved,
            "unresolved": assistant_unresolved,
            "resolution_rate": _rate(assistant_resolved, assistant_feedback_total),
            "unresolved_rate": _rate(assistant_unresolved, assistant_feedback_total),
            "question_total": len(assistant_questions),
            "followup_total": assistant_followups,
            "followup_rate": _rate(assistant_followups, len(assistant_questions)),
            "context_feedback_total": len(context_feedback),
            "context_resolved": context_resolved,
            "context_resolution_rate": _rate(context_resolved, len(context_feedback)),
            "answer_total": len(assistant_answers),
            "answer_fallback_total": assistant_fallbacks,
            "answer_fallback_rate": _rate(assistant_fallbacks, len(assistant_answers)),
            "answer_real_llm_total": assistant_real_llm,
            "answer_real_llm_rate": _rate(assistant_real_llm, len(assistant_answers)),
            "routing_total": len(assistant_routes),
            "semantic_routing_total": assistant_semantic_routes,
            "semantic_routing_rate": _rate(assistant_semantic_routes, len(assistant_routes)),
            "rollout_by_mode": _top(assistant_rollout_modes),
            "semantic_active_total": assistant_rollout_modes.get("semantic_active", 0),
            "semantic_active_rate": _rate(assistant_rollout_modes.get("semantic_active", 0), len(assistant_routes)),
            "shadow_total": assistant_rollout_modes.get("shadow", 0),
            "shadow_rate": _rate(assistant_rollout_modes.get("shadow", 0), len(assistant_routes)),
            "shadow_comparison_total": len(assistant_shadow_comparisons),
            "shadow_agreement_rate": _rate(assistant_shadow_agreements, len(assistant_shadow_comparisons)),
            "planner_active_total": assistant_planner_active,
            "planner_active_rate": _rate(assistant_planner_active, len(assistant_routes)),
            "clarification_total": len(assistant_clarifications),
            "clarification_rate": _rate(len(assistant_clarifications), len(assistant_routes)),
            "clarification_resolved_total": assistant_clarification_resolved,
            "clarification_resolution_rate": _rate(assistant_clarification_resolved, len(assistant_clarifications)),
            "routing_feedback_total": len(assistant_routing_feedback),
            "routing_accuracy": _rate(assistant_routing_correct, len(assistant_routing_feedback)),
            "multi_intent_total": assistant_multi_intent,
            "multi_intent_rate": _rate(assistant_multi_intent, len(assistant_routes)),
            "planned_answer_total": len(assistant_planned_answers),
            "plan_completed_total": assistant_completed_plans,
            "plan_completion_rate": _rate(assistant_completed_plans, len(assistant_planned_answers)),
            "partial_completion_total": assistant_partial_plans,
            "partial_completion_rate": _rate(assistant_partial_plans, len(assistant_planned_answers)),
            "verification_required_total": assistant_required_verifications,
            "verification_verified_total": assistant_verified_answers,
            "verification_failed_total": assistant_failed_verifications,
            "verification_pass_rate": _rate(assistant_verified_answers, assistant_required_verifications),
            "session_created_total": len(created_sessions),
            "session_resumed_total": len(created_sessions & resumed_sessions),
            "session_resume_rate": _rate(len(created_sessions & resumed_sessions), len(created_sessions)),
            "autotutor_question_total": len(autotutor_question_sessions),
            "autotutor_return_total": len(autotutor_question_sessions & autotutor_return_sessions),
            "autotutor_return_rate": _rate(len(autotutor_question_sessions & autotutor_return_sessions), len(autotutor_question_sessions)),
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
        "runtime_v2": runtime_v2,
        "traces": {
            "recent": _build_trace_groups(audit_events, learning_events),
        },
    }
