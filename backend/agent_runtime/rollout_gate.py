from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect as sa_inspect, text

from agent_runtime.readiness import runtime_schema_readiness
from db.engine import get_connection

TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled"}
TERMINAL_EVENT_TYPES = {"run_completed", "run_failed", "run_cancelled"}
EXPECTED_FAILURE_REASONS = {
    "guardrail_blocked",
    "confirmation_required",
    "role_denied",
    "user_cancelled",
    "run_cancelled",
    "cancel_requested",
}
SAFETY_AUDIT_ACTIONS = {
    "agent_runtime.duplicate_side_effect_prevented",
    "agent_runtime.invalid_transition",
    "agent_runtime.high_risk_without_confirmation",
    "tool.idempotent_replay",
}


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evidence_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("evidence_sha256", None)
    return hashlib.sha256(_canonical_json(clean)).hexdigest()


def baseline_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("sha256", None)
    return hashlib.sha256(_canonical_json(clean)).hexdigest()


def seal_rollout_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with baseline and manifest hashes populated."""
    sealed = json.loads(json.dumps(payload, ensure_ascii=False))
    baseline = sealed.get("control_baseline")
    if isinstance(baseline, dict):
        baseline["sha256"] = baseline_sha256(baseline)
    sealed["evidence_sha256"] = evidence_sha256(sealed)
    return sealed


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 2)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_evidence(path: str | Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if not path:
        return None, "rollout_evidence_missing"
    evidence_path = Path(path)
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "rollout_evidence_missing"
    except (OSError, json.JSONDecodeError):
        return None, "rollout_evidence_invalid"
    if not isinstance(payload, dict):
        return None, "rollout_evidence_invalid"
    return payload, None


def _evidence_reasons(
    evidence: dict[str, Any] | None,
    *,
    agent_type: str,
    config_version: str,
    runtime_mode: str,
    deployed_commit: str,
    minimum_terminal_runs: int,
) -> tuple[list[str], dict[str, Any] | None, dict[str, Any]]:
    reasons: list[str] = []
    profiles = {"real_llm": "unknown", "production_rag": "unknown"}
    if evidence is None:
        return ["rollout_evidence_missing"], None, profiles
    if evidence.get("evidence_sha256") != evidence_sha256(evidence):
        reasons.append("rollout_evidence_hash_mismatch")
    for field, expected in (
        ("agent_type", agent_type),
        ("config_version", config_version),
        ("runtime_mode", runtime_mode),
        ("deployed_commit", deployed_commit),
    ):
        if not expected or evidence.get(field) != expected:
            reasons.append(f"evidence_{field}_mismatch")
    raw_profiles = evidence.get("profiles")
    if not isinstance(raw_profiles, dict):
        raw_profiles = {}
    for name in profiles:
        profile = raw_profiles.get(name)
        if isinstance(profile, dict):
            profiles[name] = str(profile.get("status") or "unknown")
            if profile.get("commit") != deployed_commit:
                reasons.append(f"{name}_commit_mismatch")
            if profile.get("status") != "pass":
                reasons.append(f"{name}_profile_not_passed")
        else:
            reasons.append(f"{name}_profile_not_run")
    baseline = evidence.get("control_baseline")
    if not isinstance(baseline, dict):
        reasons.append("control_baseline_missing")
        baseline = None
    else:
        if baseline.get("sha256") != baseline_sha256(baseline):
            reasons.append("control_baseline_hash_mismatch")
        if baseline.get("agent_type") != agent_type:
            reasons.append("control_baseline_agent_mismatch")
        if baseline.get("source") != "server_trace_aggregate":
            reasons.append("control_baseline_source_untrusted")
        if not baseline.get("commit") or not baseline.get("config_version"):
            reasons.append("control_baseline_version_missing")
        if int(baseline.get("sample_count") or 0) < minimum_terminal_runs:
            reasons.append("control_baseline_samples_insufficient")
        if not isinstance(baseline.get("p95_ms"), (int, float)) or float(baseline.get("p95_ms") or 0) <= 0:
            reasons.append("control_baseline_p95_invalid")
    return reasons, baseline, profiles


def _query_rollout_rows(
    *,
    agent_type: str,
    config_version: str,
    runtime_mode: str,
    since: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    with get_connection() as conn:
        tables = set(sa_inspect(conn).get_table_names())
        required = {"agent_runs", "agent_run_events", "agent_side_effects", "audit_events"}
        if not required.issubset(tables):
            raise LookupError("runtime_rollout_schema_unavailable")
        raw_runs = [dict(row) for row in conn.execute(text("""SELECT * FROM agent_runs
            WHERE agent_type=:agent_type AND config_version=:config_version AND created_at>=:since
            ORDER BY created_at ASC"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "since": since,
            }).mappings().all()]
        runs = []
        for run in raw_runs:
            refs = _json_object(run.get("context_refs_json"))
            if refs.get("data_scope", "runtime") == "runtime" and refs.get("runtime_mode") == runtime_mode:
                runs.append(run)
        run_ids = {str(run["run_id"]) for run in runs}
        event_rows = [dict(row) for row in conn.execute(text("""SELECT e.* FROM agent_run_events e
            JOIN agent_runs r ON r.run_id=e.run_id
            WHERE r.agent_type=:agent_type AND r.config_version=:config_version
              AND r.created_at>=:since AND e.data_scope='runtime'
            ORDER BY e.run_id, e.sequence"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "since": since,
            }).mappings().all() if str(row["run_id"]) in run_ids]
        audit_rows = [dict(row) for row in conn.execute(text("""SELECT * FROM audit_events
            WHERE created_at>=:since AND data_scope='runtime'
              AND action IN (
                'agent_runtime.duplicate_side_effect_prevented',
                'agent_runtime.invalid_transition',
                'agent_runtime.high_risk_without_confirmation',
                'tool.idempotent_replay'
              )"""), {"since": since}).mappings().all()]
    matched_audits = []
    for audit in audit_rows:
        metadata = _json_object(audit.get("metadata_json"))
        if str(audit.get("resource_id") or "") in run_ids or str(metadata.get("run_id") or "") in run_ids:
            matched_audits.append(audit)
    return runs, event_rows, matched_audits


def build_rollout_readiness(
    *,
    agent_type: str,
    window_hours: int = 24,
    minimum_terminal_runs: int = 100,
    config_version: str | None = None,
    runtime_mode: str | None = None,
    deployed_commit: str | None = None,
    evidence_path: str | Path | None = None,
    evidence: dict[str, Any] | None = None,
    schema_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed, PII-free rollout decision for one Agent slice."""
    if runtime_mode not in {None, "active", "shadow", "control"}:
        raise ValueError("runtime_mode must be active, shadow or control")
    window_hours = max(1, min(int(window_hours), 24 * 31))
    minimum_terminal_runs = max(1, min(int(minimum_terminal_runs), 100_000))
    config_version = (config_version or os.getenv("EDU_AGENT_RUNTIME_V2_CONFIG_VERSION", "")).strip()[:120]
    if runtime_mode is None:
        shadow = os.getenv("EDU_AGENT_RUNTIME_V2_SHADOW_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
        runtime_mode = "shadow" if shadow else "active"
    deployed_commit = (deployed_commit or os.getenv("EDU_AGENT_DEPLOYED_COMMIT", "")).strip()[:120]
    evidence_path = evidence_path or os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_EVIDENCE_PATH")
    since_dt = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    since = since_dt.isoformat()
    schema = schema_readiness if schema_readiness is not None else runtime_schema_readiness()

    unknown_reasons: list[str] = []
    if not config_version:
        unknown_reasons.append("config_version_missing")
    if not deployed_commit:
        unknown_reasons.append("deployed_commit_missing")
    if not schema.get("schema_ready"):
        unknown_reasons.append("runtime_schema_not_ready")

    try:
        runs, events, audits = _query_rollout_rows(
            agent_type=agent_type,
            config_version=config_version,
            runtime_mode=runtime_mode,
            since=since,
        )
    except Exception as exc:
        return {
            "status": "unknown",
            "agent_type": agent_type,
            "config_version": config_version or None,
            "runtime_mode": runtime_mode,
            "deployed_commit": deployed_commit or None,
            "window_hours": window_hours,
            "minimum_terminal_runs": minimum_terminal_runs,
            "run_count": None,
            "terminal_runs": None,
            "reasons": [str(exc) if isinstance(exc, LookupError) else "rollout_query_failed"],
        }

    events_by_run: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        events_by_run.setdefault(str(event["run_id"]), []).append(event)
    terminal_runs = [run for run in runs if str(run.get("status")) in TERMINAL_STATUSES]
    covered_runs = sum(
        any(int(event.get("sequence") or 0) > 1 and event.get("event_type") != "run_started" for event in events_by_run.get(str(run["run_id"]), []))
        for run in runs
    )
    consistent_terminal = sum(
        bool(run.get("completion_json"))
        and bool(run.get("finished_at"))
        and any(event.get("event_type") in TERMINAL_EVENT_TYPES for event in events_by_run.get(str(run["run_id"]), []))
        for run in terminal_runs
    )
    completion_reasons: dict[str, int] = {}
    unexpected_failures = 0
    partial_runs = 0
    durations: list[float] = []
    invalid_timestamps = 0
    for run in terminal_runs:
        status = str(run.get("status") or "")
        completion = _json_object(run.get("completion_json"))
        reasons = {str(item) for item in completion.get("reason_codes") or []}
        for reason in reasons:
            completion_reasons[reason] = completion_reasons.get(reason, 0) + 1
        if status == "partial":
            partial_runs += 1
        if status == "failed" and not reasons.intersection(EXPECTED_FAILURE_REASONS):
            unexpected_failures += 1
        created = _parse_time(run.get("created_at"))
        finished = _parse_time(run.get("finished_at"))
        if created is None or finished is None or finished < created:
            invalid_timestamps += 1
        else:
            durations.append((finished - created).total_seconds() * 1000)

    audit_counts = {action: 0 for action in SAFETY_AUDIT_ACTIONS}
    for audit in audits:
        action = str(audit.get("action") or "")
        if action in audit_counts:
            audit_counts[action] += 1
    duplicate_events = sum(event.get("event_type") == "side_effect_duplicate_prevented" for event in events)
    duplicate_side_effects = (
        duplicate_events
        + audit_counts["agent_runtime.duplicate_side_effect_prevented"]
        + audit_counts["tool.idempotent_replay"]
    )
    invalid_transitions = audit_counts["agent_runtime.invalid_transition"]
    high_risk_without_confirmation = audit_counts["agent_runtime.high_risk_without_confirmation"]
    event_coverage = _rate(covered_runs, len(runs))
    terminal_consistency = _rate(consistent_terminal, len(terminal_runs))
    unexpected_failure_rate = _rate(unexpected_failures, len(terminal_runs))
    p50_ms = _percentile(durations, 0.50)
    p95_ms = _percentile(durations, 0.95)

    if evidence is None:
        evidence, load_reason = _load_evidence(evidence_path)
        if load_reason:
            unknown_reasons.append(load_reason)
    evidence_reasons, baseline, profiles = _evidence_reasons(
        evidence,
        agent_type=agent_type,
        config_version=config_version,
        runtime_mode=runtime_mode,
        deployed_commit=deployed_commit,
        minimum_terminal_runs=minimum_terminal_runs,
    )
    unknown_reasons.extend(evidence_reasons)
    baseline_p95 = baseline.get("p95_ms") if isinstance(baseline, dict) else None
    p95_regression = None
    if isinstance(p95_ms, (int, float)) and isinstance(baseline_p95, (int, float)) and baseline_p95 > 0:
        p95_regression = round((p95_ms - float(baseline_p95)) / float(baseline_p95), 4)
    if len(terminal_runs) < minimum_terminal_runs:
        unknown_reasons.append("terminal_samples_insufficient")
    if len(durations) < minimum_terminal_runs:
        unknown_reasons.append("latency_samples_insufficient")
    if p95_regression is None:
        unknown_reasons.append("p95_regression_unavailable")

    fail_reasons: list[str] = []
    warn_reasons: list[str] = []
    if duplicate_side_effects:
        fail_reasons.append("duplicate_side_effects_detected")
    if invalid_transitions:
        fail_reasons.append("invalid_transitions_detected")
    if high_risk_without_confirmation:
        fail_reasons.append("high_risk_without_confirmation_detected")
    if terminal_runs and terminal_consistency is not None and terminal_consistency < 1.0:
        fail_reasons.append("terminal_consistency_below_100pct")
    if unexpected_failure_rate is not None and unexpected_failure_rate > 0.02:
        fail_reasons.append("unexpected_failure_rate_above_2pct")
    if event_coverage is not None and event_coverage < 0.80:
        fail_reasons.append("event_coverage_below_80pct")
    elif event_coverage is not None and event_coverage < 0.95:
        warn_reasons.append("event_coverage_below_95pct")
    if p95_regression is not None:
        if p95_regression > 0.10:
            fail_reasons.append("p95_regression_above_10pct")
        elif p95_regression > 0.05:
            warn_reasons.append("p95_regression_above_5pct")

    unknown_reasons = list(dict.fromkeys(unknown_reasons))
    fail_reasons = list(dict.fromkeys(fail_reasons))
    warn_reasons = list(dict.fromkeys(warn_reasons))
    if fail_reasons:
        status = "fail"
        reasons = [*fail_reasons, *unknown_reasons, *warn_reasons]
    elif unknown_reasons:
        status = "unknown"
        reasons = [*unknown_reasons, *warn_reasons]
    elif warn_reasons:
        status = "warn"
        reasons = warn_reasons
    else:
        status = "pass"
        reasons = []

    safe_baseline = None
    if isinstance(baseline, dict):
        safe_baseline = {
            key: baseline.get(key)
            for key in ("commit", "config_version", "environment", "sample_count", "p50_ms", "p95_ms", "source", "sha256")
        }
    return {
        "status": status,
        "agent_type": agent_type,
        "config_version": config_version or None,
        "runtime_mode": runtime_mode,
        "deployed_commit": deployed_commit or None,
        "window_hours": window_hours,
        "minimum_terminal_runs": minimum_terminal_runs,
        "schema_ready": bool(schema.get("schema_ready")),
        "run_count": len(runs),
        "terminal_runs": len(terminal_runs),
        "partial_runs": partial_runs,
        "event_coverage": event_coverage,
        "terminal_consistency": terminal_consistency,
        "unexpected_failure_rate": unexpected_failure_rate,
        "unexpected_failures": unexpected_failures,
        "duplicate_side_effects": duplicate_side_effects,
        "invalid_transitions": invalid_transitions,
        "high_risk_without_confirmation": high_risk_without_confirmation,
        "run_latency": {
            "sample_count": len(durations),
            "invalid_timestamp_count": invalid_timestamps,
            "p50_ms": p50_ms,
            "p95_ms": p95_ms,
        },
        "control_baseline": safe_baseline,
        "p95_regression": p95_regression,
        "profiles": profiles,
        "completion_reason_codes": completion_reasons,
        "reasons": reasons,
    }
