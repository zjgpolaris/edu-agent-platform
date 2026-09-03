from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection
from deployment import deployed_commit, deployment_environment, runtime_config_version

VALID_MODES = {"control", "shadow", "active"}
VALID_SCOPES = {"runtime", "eval", "demo"}
VALID_COHORTS = {"demo", "unverified", "verified", "operator", "anonymous", "legacy_untrusted"}
VALID_ELIGIBILITY_REASONS = {
    "verified_runtime_actor", "demo_actor", "unverified_actor", "operator_actor",
    "eval_scope", "demo_scope", "anonymous_actor", "legacy_untrusted",
}
VALID_TRAFFIC_SOURCES = {"organic", "release_verification"}
BASELINE_STATUSES = {"completed", "partial", "failed"}
OBSERVATION_FAILURE_ACTION = "agent_runtime.rollout_observation_write_failed"
_failure_audit_lock = threading.Lock()
_last_failure_audit: dict[str, float] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(float(ordered[index]), 2)


def _distribution(values: list[int]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def deployment_metadata() -> dict[str, str]:
    return {
        "deployed_commit": deployed_commit(),
        "config_version": runtime_config_version(),
        "environment": deployment_environment(),
    }


def record_rollout_observation(
    *,
    agent_type: str,
    runtime_mode: str,
    status: str,
    latency_ms: int,
    trace_id: str | None,
    data_scope: str | None = None,
    config_version: str | None = None,
    deployed_commit: str | None = None,
    environment: str | None = None,
    traffic_cohort: str | None = None,
    rollout_eligible: bool | None = None,
    eligibility_reason: str | None = None,
    assigned_executor: str | None = None,
    selected_executor: str | None = None,
    transition_kind: str | None = None,
    transition_id: str | None = None,
    observation_schema_version: str | None = None,
    outcome_schema_version: str | None = None,
    commit_status: str | None = None,
    assignment_reason: str | None = None,
    admission_status: str | None = None,
    admission_reason: str | None = None,
    admission_checked_at: str | None = None,
    comparator_matched: bool | None = None,
    fallback_reason: str | None = None,
    provider_latency_ms: int | None = None,
    executor_latency_ms: int | None = None,
    comparator_latency_ms: int | None = None,
    observation_external_calls: int | None = None,
    effect_intent_count: int | None = None,
    traffic_source: str = "organic",
    verification_run_id: str | None = None,
) -> str:
    if runtime_mode not in VALID_MODES:
        raise ValueError("runtime_mode must be control, shadow or active")
    metadata = deployment_metadata()
    config = (config_version or metadata["config_version"]).strip()[:120]
    commit = (deployed_commit or metadata["deployed_commit"]).strip()[:120]
    target_environment = (environment or metadata["environment"]).strip()[:80]
    scope = (data_scope or os.getenv("EDU_AGENT_DATA_SCOPE", "runtime")).strip().lower()
    if scope == "demo_seed":
        scope = "demo"
    if scope not in VALID_SCOPES:
        scope = "runtime"
    cohort = str(traffic_cohort or ("verified" if deployment_environment() != "production" else "legacy_untrusted"))
    if cohort not in VALID_COHORTS:
        cohort = "legacy_untrusted"
    if rollout_eligible is None:
        rollout_eligible = deployment_environment() != "production" and scope == "runtime"
    reason = str(eligibility_reason or ("verified_runtime_actor" if rollout_eligible else "legacy_untrusted"))
    if reason not in VALID_ELIGIBILITY_REASONS:
        reason = "legacy_untrusted"
    if scope != "runtime":
        rollout_eligible = False
        reason = "eval_scope" if scope == "eval" else "demo_scope"
    if not config or not commit:
        raise ValueError("deployment commit and runtime config version are required")
    source = str(traffic_source or "organic").strip().lower()
    if source not in VALID_TRAFFIC_SOURCES:
        raise ValueError("traffic_source must be organic or release_verification")
    verification_id = str(verification_run_id or "").strip()
    if source == "release_verification" and not verification_id:
        raise ValueError("release verification traffic requires verification_run_id")
    if source == "organic" and verification_id:
        raise ValueError("organic traffic cannot have verification_run_id")
    observation_id = f"obs_{uuid4().hex}"
    with get_connection() as conn:
        if "agent_rollout_observations" not in set(sa_inspect(conn).get_table_names()):
            raise LookupError("rollout observation schema is not migrated")
        conn.execute(text("""INSERT INTO agent_rollout_observations (
            observation_id, agent_type, config_version, runtime_mode, deployed_commit,
            environment, status, latency_ms, trace_id, data_scope, created_at
            , traffic_cohort, rollout_eligible, eligibility_reason
            , assigned_executor, selected_executor, transition_kind, transition_id
            , observation_schema_version, outcome_schema_version, commit_status
            , assignment_reason, admission_status, admission_reason, admission_checked_at
            , comparator_matched, fallback_reason
            , provider_latency_ms, executor_latency_ms, comparator_latency_ms
            , observation_external_calls, effect_intent_count
            , traffic_source, verification_run_id
        ) VALUES (
            :observation_id, :agent_type, :config_version, :runtime_mode, :deployed_commit,
            :environment, :status, :latency_ms, :trace_id, :data_scope, :created_at
            , :traffic_cohort, :rollout_eligible, :eligibility_reason
            , :assigned_executor, :selected_executor, :transition_kind, :transition_id
            , :observation_schema_version, :outcome_schema_version, :commit_status
            , :assignment_reason, :admission_status, :admission_reason, :admission_checked_at
            , :comparator_matched, :fallback_reason
            , :provider_latency_ms, :executor_latency_ms, :comparator_latency_ms
            , :observation_external_calls, :effect_intent_count
            , :traffic_source, :verification_run_id
        )"""), {
            "observation_id": observation_id,
            "agent_type": agent_type[:80],
            "config_version": config,
            "runtime_mode": runtime_mode,
            "deployed_commit": commit,
            "environment": target_environment,
            "status": status[:40],
            "latency_ms": max(0, int(latency_ms)),
            "trace_id": trace_id[:160] if trace_id else None,
            "data_scope": scope,
            "created_at": _now(),
            "traffic_cohort": cohort,
            "rollout_eligible": 1 if rollout_eligible else 0,
            "eligibility_reason": reason,
            "assigned_executor": str(assigned_executor)[:20] if assigned_executor else None,
            "selected_executor": str(selected_executor)[:20] if selected_executor else None,
            "transition_kind": str(transition_kind)[:40] if transition_kind else None,
            "transition_id": str(transition_id)[:160] if transition_id else None,
            "observation_schema_version": str(observation_schema_version)[:60] if observation_schema_version else None,
            "outcome_schema_version": str(outcome_schema_version)[:60] if outcome_schema_version else None,
            "commit_status": str(commit_status)[:40] if commit_status else None,
            "assignment_reason": str(assignment_reason)[:120] if assignment_reason else None,
            "admission_status": str(admission_status)[:20] if admission_status else None,
            "admission_reason": str(admission_reason)[:240] if admission_reason else None,
            "admission_checked_at": str(admission_checked_at)[:80] if admission_checked_at else None,
            "comparator_matched": None if comparator_matched is None else (1 if comparator_matched else 0),
            "fallback_reason": str(fallback_reason)[:120] if fallback_reason else None,
            "provider_latency_ms": max(0, int(provider_latency_ms)) if provider_latency_ms is not None else None,
            "executor_latency_ms": max(0, int(executor_latency_ms)) if executor_latency_ms is not None else None,
            "comparator_latency_ms": max(0, int(comparator_latency_ms)) if comparator_latency_ms is not None else None,
            "observation_external_calls": max(0, int(observation_external_calls)) if observation_external_calls is not None else None,
            "effect_intent_count": max(0, int(effect_intent_count)) if effect_intent_count is not None else None,
            "traffic_source": source,
            "verification_run_id": verification_id[:80] if verification_id else None,
        })
    return observation_id


def try_record_rollout_observation(**kwargs: Any) -> str | None:
    try:
        return record_rollout_observation(**kwargs)
    except Exception as exc:
        reason = (
            "schema_unavailable" if isinstance(exc, LookupError)
            else "provenance_invalid" if isinstance(exc, ValueError)
            else "database_error"
        )
        now = time.monotonic()
        should_audit = False
        with _failure_audit_lock:
            if now - _last_failure_audit.get(reason, 0.0) >= 60:
                _last_failure_audit[reason] = now
                should_audit = True
        if should_audit:
            try:
                from security.audit_log import record_audit_event

                record_audit_event(
                    actor_id=None,
                    action=OBSERVATION_FAILURE_ACTION,
                    resource_type="agent_rollout_observation",
                    resource_id=str(kwargs.get("agent_type") or "unknown")[:80],
                    success=False,
                    data_scope=str(kwargs.get("data_scope") or os.getenv("EDU_AGENT_DATA_SCOPE", "runtime")),
                    metadata={
                        "reason_code": reason,
                        "error_type": exc.__class__.__name__,
                        "agent_type": str(kwargs.get("agent_type") or "unknown")[:80],
                        "runtime_mode": str(kwargs.get("runtime_mode") or "unknown")[:20],
                        "config_version": str(kwargs.get("config_version") or runtime_config_version())[:120],
                        "deployed_commit": str(kwargs.get("deployed_commit") or deployed_commit())[:120],
                        "environment": str(kwargs.get("environment") or deployment_environment())[:80],
                    },
                )
            except Exception:
                pass
        return None


def observation_write_health(
    *,
    window_minutes: int = 15,
    config_version: str | None = None,
    deployed_commit: str | None = None,
    environment: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    since_value = since or (datetime.now(timezone.utc) - timedelta(minutes=max(1, min(window_minutes, 24 * 60)))).isoformat()
    until_clause = " AND created_at<:until" if until else ""
    try:
        with get_connection() as conn:
            tables = set(sa_inspect(conn).get_table_names())
            if "agent_rollout_observations" not in tables or "audit_events" not in tables:
                return {"status": "unavailable", "ok": False, "failure_count": None, "reason": "schema_unavailable"}
            rows = conn.execute(text(f"""SELECT metadata_json, COUNT(*) AS count FROM audit_events
                WHERE action=:action AND data_scope='runtime' AND created_at>=:since
                {until_clause}
                GROUP BY metadata_json"""), {
                    "action": OBSERVATION_FAILURE_ACTION,
                    "since": since_value,
                    "until": until,
                }).mappings().all()
        by_reason: dict[str, int] = {}
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            if config_version is not None and metadata.get("config_version") != config_version:
                continue
            if deployed_commit is not None and metadata.get("deployed_commit") != deployed_commit:
                continue
            if environment is not None and metadata.get("environment") != environment:
                continue
            reason = str(metadata.get("reason_code") or "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + int(row["count"] or 0)
        total = sum(by_reason.values())
        return {
            "status": "ok" if total == 0 else "degraded",
            "ok": total == 0,
            "window_minutes": window_minutes,
            "failure_count": total,
            "by_reason": by_reason,
        }
    except Exception as exc:
        return {"status": "unavailable", "ok": False, "failure_count": None, "error_type": exc.__class__.__name__}


def aggregate_control_baseline(
    *,
    agent_type: str,
    config_version: str,
    deployed_commit: str,
    environment: str,
    minimum_samples: int = 100,
    data_scope: str = "runtime",
) -> dict[str, Any]:
    with get_connection() as conn:
        if "agent_rollout_observations" not in set(sa_inspect(conn).get_table_names()):
            raise LookupError("rollout observation schema is not migrated")
        rows = conn.execute(text("""SELECT latency_ms, status, created_at FROM agent_rollout_observations
            WHERE agent_type=:agent_type AND config_version=:config_version
              AND runtime_mode='control' AND deployed_commit=:deployed_commit
              AND environment=:environment AND data_scope=:data_scope AND rollout_eligible=1
            ORDER BY created_at ASC"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "deployed_commit": deployed_commit,
                "environment": environment,
                "data_scope": data_scope,
            }).mappings().all()
    durations = [int(row["latency_ms"]) for row in rows if str(row["status"]) in BASELINE_STATUSES]
    included_rows = [row for row in rows if str(row["status"]) in BASELINE_STATUSES]
    if len(durations) < max(1, int(minimum_samples)):
        raise ValueError(f"control baseline requires {minimum_samples} samples; observed {len(durations)}")
    return {
        "agent_type": agent_type,
        "commit": deployed_commit,
        "config_version": config_version,
        "environment": environment,
        "sample_count": len(durations),
        "p50_ms": _percentile(durations, 0.50),
        "p95_ms": _percentile(durations, 0.95),
        "source": "server_trace_aggregate",
        "trust_contract": "verified-cohort-v1",
        "observed_from": included_rows[0]["created_at"],
        "observed_to": included_rows[-1]["created_at"],
    }


def control_observation_progress(
    *,
    agent_type: str,
    config_version: str,
    deployed_commit: str,
    environment: str,
    minimum_samples: int = 100,
    data_scope: str = "runtime",
) -> dict[str, Any]:
    """Return a PII-free view of the exact rows eligible for a control baseline."""
    with get_connection() as conn:
        if "agent_rollout_observations" not in set(sa_inspect(conn).get_table_names()):
            raise LookupError("rollout observation schema is not migrated")
        rows = conn.execute(text("""SELECT latency_ms, status, created_at FROM agent_rollout_observations
            WHERE agent_type=:agent_type AND config_version=:config_version
              AND runtime_mode='control' AND deployed_commit=:deployed_commit
              AND environment=:environment AND data_scope=:data_scope AND rollout_eligible=1
            ORDER BY created_at ASC"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "deployed_commit": deployed_commit,
                "environment": environment,
                "data_scope": data_scope,
        }).mappings().all()
        excluded_rows = conn.execute(text("""SELECT eligibility_reason, COUNT(*) AS count
            FROM agent_rollout_observations
            WHERE agent_type=:agent_type AND config_version=:config_version
              AND runtime_mode='control' AND deployed_commit=:deployed_commit
              AND environment=:environment AND rollout_eligible=0
            GROUP BY eligibility_reason"""), {
            "agent_type": agent_type,
            "config_version": config_version,
            "deployed_commit": deployed_commit,
            "environment": environment,
        }).mappings().all()
    included = [row for row in rows if str(row["status"]) in BASELINE_STATUSES]
    durations = [int(row["latency_ms"]) for row in included]
    required = max(1, int(minimum_samples))
    excluded_by_reason = {str(row["eligibility_reason"]): int(row["count"] or 0) for row in excluded_rows}
    excluded_samples = sum(excluded_by_reason.values())
    return {
        "commit": deployed_commit or None,
        "config_version": config_version or None,
        "environment": environment or None,
        "terminal_samples": len(included),
        "minimum_samples": required,
        "observed_total": len(included) + excluded_samples,
        "excluded_samples": excluded_samples,
        "excluded_by_reason": excluded_by_reason,
        "sample_sufficient": len(included) >= required,
        "baseline_ready": len(included) >= required and bool(durations),
        "p50_ms": _percentile(durations, 0.50),
        "p95_ms": _percentile(durations, 0.95),
        "observed_from": included[0]["created_at"] if included else None,
        "observed_to": included[-1]["created_at"] if included else None,
    }


def observation_summary(*, agent_type: str, config_version: str, data_scope: str = "runtime") -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT runtime_mode, status, COUNT(*) AS count
            FROM agent_rollout_observations
            WHERE agent_type=:agent_type AND config_version=:config_version AND data_scope=:data_scope
            GROUP BY runtime_mode, status"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "data_scope": data_scope,
            }).mappings().all()
    return {"agent_type": agent_type, "config_version": config_version, "groups": [dict(row) for row in rows]}


def aggregate_autotutor_transition_canary(
    *,
    config_version: str,
    deployed_commit: str,
    environment: str,
    since: str,
    until: str | None = None,
    minimum_graph_transitions: int = 100,
    data_scope: str = "runtime",
    traffic_cohort: str = "verified",
) -> dict[str, Any]:
    """Evaluate one immutable AutoTutor canary slice; unrelated rows never enter its denominator."""
    where_until = " AND created_at<:until" if until else ""
    params = {
        "config_version": config_version,
        "deployed_commit": deployed_commit,
        "environment": environment,
        "since": since,
        "until": until,
        "data_scope": data_scope,
        "traffic_cohort": traffic_cohort,
    }
    with get_connection() as conn:
        if "agent_rollout_observations" not in set(sa_inspect(conn).get_table_names()):
            raise LookupError("rollout observation schema is not migrated")
        rows = conn.execute(text(f"""SELECT * FROM agent_rollout_observations
            WHERE agent_type='auto_tutor' AND config_version=:config_version
              AND deployed_commit=:deployed_commit AND environment=:environment
              AND data_scope=:data_scope AND traffic_cohort=:traffic_cohort
              AND rollout_eligible=1 AND created_at>=:since{where_until}
            ORDER BY created_at ASC"""), params).mappings().all()
        observed_count = int(conn.execute(text(f"""SELECT COUNT(*) FROM agent_rollout_observations
            WHERE agent_type='auto_tutor' AND config_version=:config_version
              AND deployed_commit=:deployed_commit AND environment=:environment
              AND created_at>=:since{where_until}"""), params).scalar_one())
        unauthorized = int(conn.execute(text(f"""SELECT COUNT(*) FROM agent_rollout_observations
            WHERE agent_type='auto_tutor' AND config_version=:config_version
              AND deployed_commit=:deployed_commit AND environment=:environment
              AND created_at>=:since{where_until}
              AND (assigned_executor='graph_active' OR selected_executor='graph_active')
              AND (data_scope!=:data_scope OR traffic_cohort!=:traffic_cohort OR rollout_eligible!=1)"""), params).scalar_one())
        effect_rows = []
        if "learning_events" in set(sa_inspect(conn).get_table_names()):
            effect_rows = conn.execute(text(f"""SELECT effect_key, metadata_json FROM learning_events
                WHERE feature='auto_tutor' AND effect_key IS NOT NULL
                  AND created_at>=:since{where_until}"""), params).mappings().all()

    graph_rows = [row for row in rows if str(row.get("assigned_executor") or "") == "graph_active"]
    control_rows = [row for row in rows if str(row.get("assigned_executor") or "") == "legacy"]
    selected_graph = [row for row in graph_rows if str(row.get("selected_executor") or "") == "graph_active"]
    committed_graph = [
        row for row in selected_graph
        if str(row.get("commit_status") or "") in {"committed", "completed"}
    ]
    fallback_rows = [
        row for row in graph_rows
        if str(row.get("selected_executor") or "") != "graph_active" or bool(row.get("fallback_reason"))
    ]
    compared = [row for row in graph_rows if row.get("comparator_matched") is not None]
    mismatches = [row for row in compared if int(row.get("comparator_matched") or 0) != 1]
    provider_calls = sum(int(row.get("observation_external_calls") or 0) for row in graph_rows)
    eligible_trace_ids = {str(row.get("trace_id")) for row in rows if row.get("trace_id")}
    exact_effect_keys: list[str] = []
    for row in effect_rows:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if str(metadata.get("trace_id") or "") in eligible_trace_ids:
            exact_effect_keys.append(str(row.get("effect_key") or ""))
    duplicate_effect_count = sum(1 for count in Counter(exact_effect_keys).values() if count > 1)
    transition_ids = [str(row.get("transition_id")) for row in rows if row.get("transition_id")]
    duplicate_observation_count = sum(1 for count in Counter(transition_ids).values() if count > 1)
    latencies: dict[str, dict[str, float | None]] = {}
    for field in ("provider_latency_ms", "executor_latency_ms", "comparator_latency_ms", "latency_ms"):
        values = [int(row[field]) for row in graph_rows if row.get(field) is not None]
        latencies[field.removesuffix("_ms")] = {"p50_ms": _percentile(values, 0.50), "p95_ms": _percentile(values, 0.95)}
    control_total = [int(row["latency_ms"]) for row in control_rows if row.get("latency_ms") is not None]
    control_p95 = _percentile(control_total, 0.95)
    active_p95 = latencies["latency"]["p95_ms"]

    def source_counts(source: str | None = None) -> dict[str, int]:
        selected = [
            row for row in rows
            if source is None or str(row.get("traffic_source") or "organic") == source
        ]
        return {
            "control": sum(str(row.get("assigned_executor") or "") == "legacy" for row in selected),
            "graph": sum(str(row.get("assigned_executor") or "") == "graph_active" for row in selected),
            "committed_graph": sum(
                str(row.get("assigned_executor") or "") == "graph_active"
                and str(row.get("selected_executor") or "") == "graph_active"
                and str(row.get("commit_status") or "") in {"committed", "completed"}
                for row in selected
            ),
        }

    traffic_sources = {
        "organic": source_counts("organic"),
        "release_verification": source_counts("release_verification"),
        "total": source_counts(),
    }

    denominator = len(graph_rows)
    fallback_rate = round(len(fallback_rows) / denominator, 6) if denominator else None
    comparator_match_rate = round((len(compared) - len(mismatches)) / denominator, 6) if denominator else None
    covered_kinds = sorted({str(row.get("transition_kind") or "") for row in graph_rows if row.get("transition_kind")})
    required_kinds = {"start", "lesson_answer", "exit_ticket_answer"}
    missing_kinds = sorted(required_kinds - set(covered_kinds))
    provenance_complete = [
        row for row in graph_rows
        if row.get("transition_id")
        and row.get("observation_schema_version") == "v1.49.2-observation"
        and row.get("outcome_schema_version") == "v1.49.2-outcome"
        and str(row.get("commit_status") or "") in {"committed", "completed", "fallback"}
    ]
    blockers: list[str] = []
    if len(committed_graph) < max(1, int(minimum_graph_transitions)):
        blockers.append("insufficient_graph_samples")
    if len(compared) != denominator or mismatches:
        blockers.append("comparator_not_exact")
    if fallback_rate is None or fallback_rate >= 0.01:
        blockers.append("fallback_rate_above_one_percent")
    if unauthorized:
        blockers.append("unauthorized_graph_traffic")
    if missing_kinds:
        blockers.append("transition_kind_coverage_incomplete")
    if duplicate_effect_count:
        blockers.append("duplicate_effects_detected")
    if duplicate_observation_count:
        blockers.append("duplicate_transition_observations_detected")
    if control_p95 is None:
        blockers.append("control_baseline_missing")
    elif active_p95 is not None and (active_p95 > control_p95 * 1.20 or active_p95 - control_p95 > 50):
        blockers.append("active_latency_regression")
    if any(str(row.get("observation_schema_version") or "") != "v1.49.2-observation" for row in graph_rows):
        blockers.append("observation_schema_mismatch")
    if any(str(row.get("outcome_schema_version") or "") != "v1.49.2-outcome" for row in graph_rows):
        blockers.append("outcome_schema_mismatch")
    if any(not row.get("transition_id") or str(row.get("commit_status") or "") not in {"committed", "completed", "fallback"} for row in graph_rows):
        blockers.append("transition_provenance_incomplete")
    if any(str(row.get("admission_status") or "") != "admitted" for row in graph_rows):
        blockers.append("admission_provenance_incomplete")
    health = observation_write_health(
        config_version=config_version,
        deployed_commit=deployed_commit,
        environment=environment,
        since=since,
        until=until,
    )
    if not health.get("ok"):
        blockers.append("observation_write_failure")

    hard_blockers = set(blockers) - {"insufficient_graph_samples", "transition_kind_coverage_incomplete"}
    status = "GO" if not blockers else "NOT_READY" if "insufficient_graph_samples" in blockers and not hard_blockers else "NO_GO"
    return {
        "status": status,
        "decision": "GO" if status == "GO" else "NO_GO",
        "blockers": blockers,
        "slice": {
            "agent_type": "auto_tutor", "config_version": config_version,
            "deployed_commit": deployed_commit, "environment": environment,
            "data_scope": data_scope, "traffic_cohort": traffic_cohort,
            "since": since, "until": until,
        },
        "transition_count": len(rows),
        "observed_transition_count": observed_count,
        "eligible_transition_count": len(rows),
        "traffic_sources": traffic_sources,
        "assigned_control_count": len(control_rows),
        "assigned_graph_count": denominator,
        "selected_graph_count": len(selected_graph),
        "committed_graph_count": len(committed_graph),
        "fallback_count": len(fallback_rows),
        "fallback_rate": fallback_rate,
        "comparator_observed_count": len(compared),
        "comparator_mismatch_count": len(mismatches),
        "comparator_unknown_count": denominator - len(compared),
        "comparator_match_rate": comparator_match_rate,
        "transition_kind_coverage": covered_kinds,
        "missing_transition_kinds": missing_kinds,
        "provenance_coverage": round(len(provenance_complete) / denominator, 6) if denominator else None,
        "fallback_by_reason": {
            reason: sum(1 for row in fallback_rows if str(row.get("fallback_reason") or "unknown") == reason)
            for reason in sorted({str(row.get("fallback_reason") or "unknown") for row in fallback_rows})
        },
        "assignment_by_reason": dict(Counter(str(row.get("assignment_reason") or "unknown") for row in rows)),
        "admission_by_status": dict(Counter(str(row.get("admission_status") or "unknown") for row in rows)),
        "commit_status_distribution": dict(Counter(str(row.get("commit_status") or "unknown") for row in rows)),
        "unauthorized_graph_count": unauthorized,
        "observation_external_calls": provider_calls,
        "effect_intent_count": sum(int(row.get("effect_intent_count") or 0) for row in graph_rows),
        "observation_external_call_distribution": _distribution([int(row.get("observation_external_calls") or 0) for row in graph_rows]),
        "effect_intent_distribution": _distribution([int(row.get("effect_intent_count") or 0) for row in graph_rows]),
        "duplicate_effect_count": duplicate_effect_count,
        "duplicate_transition_observation_count": duplicate_observation_count,
        "control_latency": {"p50_ms": _percentile(control_total, 0.50), "p95_ms": control_p95},
        "latency_regression": {
            "relative": round(active_p95 / control_p95, 6) if active_p95 is not None and control_p95 else None,
            "absolute_ms": round(active_p95 - control_p95, 2) if active_p95 is not None and control_p95 is not None else None,
        },
        "latency": latencies,
        "observation_write_health": health,
    }
