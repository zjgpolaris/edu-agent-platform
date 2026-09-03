"""PII-free, AutoTutor-scoped production verification and exact snapshots."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_runtime.evidence_store import load_release_evidence
from agent_runtime.readiness import runtime_schema_readiness
from agent_runtime.rollout_observations import aggregate_autotutor_transition_canary, observation_write_health
from agents.autotutor_canary_admission import evaluate_autotutor_canary_admission
from agents.autotutor_execution import AutoTutorExecutionContext, AutoTutorExecutorSettings
from deployment import deployed_commit, deployment_environment
from security.accounts import trusted_rollout_cohort_status
from security.autotutor_verification_auth import AutoTutorVerificationIdentitySettings

MAX_WINDOW = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_window(start: str | None, end: str | None) -> tuple[str, str | None]:
    if bool(start) != bool(end):
        raise ValueError("window_start and window_end must be provided together")
    if not start:
        return _iso(_now() - MAX_WINDOW), None
    try:
        parsed_start = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        parsed_end = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("verification window must use ISO-8601 timestamps") from None
    if parsed_start.tzinfo is None:
        parsed_start = parsed_start.replace(tzinfo=timezone.utc)
    if parsed_end.tzinfo is None:
        parsed_end = parsed_end.replace(tzinfo=timezone.utc)
    parsed_start = parsed_start.astimezone(timezone.utc)
    parsed_end = parsed_end.astimezone(timezone.utc)
    if parsed_start >= parsed_end or parsed_end - parsed_start > MAX_WINDOW:
        raise ValueError("verification window must be positive and no longer than 7 days")
    if parsed_end > _now() + timedelta(minutes=5):
        raise ValueError("verification window cannot end in the future")
    return _iso(parsed_start), _iso(parsed_end)


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _admission(settings: AutoTutorExecutorSettings, *, environment: str, commit: str) -> dict[str, Any]:
    snapshot = evaluate_autotutor_canary_admission(
        settings=settings,
        context=AutoTutorExecutionContext(
            actor_role="student",
            account_status="active",
            traffic_cohort="verified",
            data_scope="runtime",
            rollout_eligible=True,
            eligibility_reason="verified_runtime_actor",
            environment=environment,
            deployed_commit=commit,
        ),
    )
    return {
        "status": snapshot.status,
        "reason_codes": list(snapshot.reason_codes),
        "schema_revision": snapshot.schema_revision,
        "observation_health": snapshot.observation_health,
        "checked_at": snapshot.checked_at,
        "expires_at": snapshot.expires_at,
    }


def build_autotutor_canary_verification(
    *,
    expected_commit: str | None = None,
    expected_config_version: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    minimum_control: int = 100,
    minimum_graph: int = 100,
    minimum_rollback_control: int = 20,
) -> dict[str, Any]:
    """Build the only phase/blocker/next-action contract for AutoTutor production."""
    minimum_control = max(1, min(int(minimum_control), 100_000))
    minimum_graph = max(1, min(int(minimum_graph), 100_000))
    minimum_rollback_control = max(1, min(int(minimum_rollback_control), 100_000))
    since, until = _parse_window(window_start, window_end)
    commit = deployed_commit()
    environment = deployment_environment()
    if environment == "production":
        minimum_control = max(100, minimum_control)
        minimum_graph = max(100, minimum_graph)
        minimum_rollback_control = max(20, minimum_rollback_control)
    settings = AutoTutorExecutorSettings.from_env()
    verification_identity = AutoTutorVerificationIdentitySettings.from_env()
    expected_commit = (expected_commit or commit).strip()
    expected_config_version = (expected_config_version or settings.config_version).strip()
    try:
        schema = runtime_schema_readiness()
    except Exception as exc:
        schema = {"schema_ready": False, "alembic_version": None, "error_type": exc.__class__.__name__}
    try:
        cohort = trusted_rollout_cohort_status()
    except Exception as exc:
        cohort = {"ready": False, "verified_actor_count": 0, "error_type": exc.__class__.__name__}
    try:
        health = observation_write_health(
            config_version=settings.config_version,
            deployed_commit=commit,
            environment=environment,
            since=since,
            until=until,
        )
    except Exception as exc:
        health = {"status": "unavailable", "ok": False, "failure_count": None, "error_type": exc.__class__.__name__}
    try:
        aggregate = aggregate_autotutor_transition_canary(
            config_version=settings.config_version,
            deployed_commit=commit,
            environment=environment,
            since=since,
            until=until,
            minimum_graph_transitions=minimum_graph,
        )
    except Exception as exc:
        aggregate = {
            "status": "UNKNOWN", "decision": "NO_GO", "blockers": ["canary_query_failed"],
            "error_type": exc.__class__.__name__, "assigned_control_count": 0,
            "assigned_graph_count": 0, "committed_graph_count": 0,
        }
    try:
        evidence = load_release_evidence(
            agent_type="auto_tutor",
            config_version=settings.config_version,
            runtime_mode="active_canary",
            deployed_commit=commit,
            environment=environment,
        )
    except Exception:
        evidence = None
    try:
        admission = _admission(settings, environment=environment, commit=commit)
    except Exception as exc:
        admission = {"status": "denied", "reason_codes": ["admission_check_failed"], "error_type": exc.__class__.__name__}
    blockers: list[str] = []
    if environment != "production":
        blockers.append("environment_not_production")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        blockers.append("deployed_commit_invalid")
    if expected_commit and commit != expected_commit:
        blockers.append("deployed_commit_mismatch")
    if expected_config_version and settings.config_version != expected_config_version:
        blockers.append("config_version_mismatch")
    try:
        schema_revision = int(str(schema.get("alembic_version") or "0"))
    except ValueError:
        schema_revision = 0
    if not schema.get("schema_ready") or schema_revision < 17:
        blockers.append("runtime_schema_not_ready")
    if not settings.config_version:
        blockers.append("config_version_missing")
    if not settings.bucket_salt_configured:
        blockers.append("bucket_salt_missing")
    if not settings.comparator_enabled:
        blockers.append("comparator_disabled")
    if not settings.fallback_enabled:
        blockers.append("fallback_disabled")
    if settings.kill_switch:
        blockers.append("kill_switch_enabled")
    if settings.active_bps > 100:
        blockers.append("production_active_bps_exceeds_one_percent")
    if evidence and int(evidence.get("schema_version") or 0) == 4:
        if evidence.get("cohort_fingerprint") != settings.cohort_fingerprint:
            blockers.append("cohort_fingerprint_mismatch")
        if settings.active_bps == 0 and settings.mode != "legacy":
            blockers.append("rollback_mode_not_legacy")
    if not settings.valid:
        blockers.extend(settings.reason_codes)
    if not health.get("ok"):
        blockers.append("observation_write_unhealthy")
    if verification_identity.required:
        if not verification_identity.configured:
            blockers.append("verification_machine_credential_missing")
        elif not verification_identity.valid:
            blockers.append("verification_machine_credential_invalid")
        if not verification_identity.bootstrap_attested:
            blockers.append("verification_bootstrap_not_attested")
    aggregate_blockers = [str(item) for item in aggregate.get("blockers") or []]
    always_hard = {
        "unauthorized_graph_traffic", "duplicate_effects_detected",
        "duplicate_transition_observations_detected", "observation_write_failure",
    }
    blockers.extend(item for item in aggregate_blockers if item in always_hard)
    graph_count = int(aggregate.get("assigned_graph_count") or 0)
    selected_graph = int(aggregate.get("selected_graph_count") or 0)
    committed_graph = int(aggregate.get("committed_graph_count") or 0)
    control_count = int(aggregate.get("assigned_control_count") or 0)
    if (settings.mode == "active_canary" or graph_count) and committed_graph >= minimum_graph:
        blockers.extend(item for item in aggregate_blockers if item != "insufficient_graph_samples")
    blockers = _unique(blockers)

    evidence_stage = str(evidence.get("evidence_stage") or "legacy") if evidence else None
    evidence_decision = str(evidence.get("decision") or "") if evidence else ""
    legacy_candidate = bool(evidence and int(evidence.get("schema_version") or 0) == 3 and evidence_decision == "GO")
    candidate_present = bool(evidence and evidence_decision == "CANDIDATE_GO")
    final_present = bool(evidence and int(evidence.get("schema_version") or 0) == 4
                         and evidence_stage == "final" and evidence_decision == "GO")
    hard_blocked = bool(blockers)
    if hard_blocked:
        phase, status, decision = "deployment_blocked", "BLOCKED", "NO_GO"
        next_action = "stop_canary" if settings.active_bps else "fix_deployment_contract"
    elif not cohort.get("ready"):
        phase, status, decision, next_action = "deployment_blocked", "NOT_READY", "NO_GO", "approve_verified_cohort"
    elif final_present and settings.active_bps == 0:
        phase, status, decision, next_action = "rollback_verified", "VERIFIED", "GO", "review_v150_entry"
    elif legacy_candidate:
        phase, status, decision, next_action = "legacy_evidence_requires_upgrade", "NOT_READY", "NO_GO", "capture_v4_canary_candidate"
    elif candidate_present and settings.active_bps == 0:
        if until is None:
            phase, status, decision, next_action = "rollback_pending", "NOT_READY", "NO_GO", "capture_exact_rollback_window"
        elif graph_count or selected_graph:
            blockers = _unique([*blockers, "rollback_graph_traffic_detected"])
            phase, status, decision, next_action = "rollback_blocked", "BLOCKED", "NO_GO", "investigate_graph_after_rollback"
        elif control_count < minimum_rollback_control:
            phase, status, decision, next_action = "rollback_collecting", "NOT_READY", "NO_GO", "collect_post_rollback_control"
        else:
            phase, status, decision, next_action = "rollback_ready_for_finalize", "READY", "GO", "finalize_evidence"
    elif candidate_present:
        phase, status, decision, next_action = "candidate_persisted", "READY", "GO", "restore_bps_zero"
    elif settings.mode != "active_canary" or settings.active_bps == 0:
        if control_count < minimum_control:
            phase, status, decision, next_action = "control_collecting", "NOT_READY", "NO_GO", "collect_control"
        else:
            phase, status, decision, next_action = "ready_for_manual_one_percent", "READY", "GO", "review_one_percent_enablement"
    elif committed_graph < minimum_graph:
        phase, status, decision, next_action = "canary_collecting", "NOT_READY", "NO_GO", "collect_canary"
    elif aggregate.get("decision") != "GO":
        phase, status, decision, next_action = "canary_blocked", "BLOCKED", "NO_GO", "stop_canary"
    else:
        phase, status, decision, next_action = "canary_ready_for_snapshot", "READY", "GO", "build_exact_snapshot"

    deployment_converged = bool(
        environment == "production"
        and bool(commit)
        and commit == expected_commit
        and settings.config_version == expected_config_version
    )
    production_verification_ready = bool(
        deployment_converged
        and not blockers
        and (not verification_identity.required or verification_identity.valid)
        and (not verification_identity.required or verification_identity.bootstrap_attested)
    )
    v150_entry_blockers: list[str] = []
    if not final_present:
        v150_entry_blockers.append("final_evidence_missing")
    if phase != "rollback_verified":
        v150_entry_blockers.append("rollback_not_verified")
    v150_entry_blockers.extend(blockers)
    v150_entry_blockers = _unique(v150_entry_blockers)
    v150_entry_ready = bool(final_present and phase == "rollback_verified" and not v150_entry_blockers)

    return {
        "schema_version": 1,
        "agent_type": "auto_tutor",
        "generated_at": _iso(_now()),
        "phase": phase,
        "status": status,
        "decision": decision,
        "next_action": next_action,
        "blockers": blockers,
        "deployment": {
            "expected_commit": expected_commit or None,
            "deployed_commit": commit or None,
            "environment": environment or None,
            "schema_revision": schema.get("alembic_version"),
            "converged": deployment_converged,
        },
        "configuration": settings.safe_summary(),
        "verification_identity": verification_identity.safe_summary(),
        "admission": admission,
        "trusted_cohort": {
            "ready": bool(cohort.get("ready")),
            "verified_actor_count": int(cohort.get("verified_actor_count") or 0),
            **({"error_type": cohort["error_type"]} if cohort.get("error_type") else {}),
        },
        "observation_health": health,
        "progress": {
            "control_transition_count": control_count,
            "committed_graph_transition_count": committed_graph,
            "traffic_sources": aggregate.get("traffic_sources") or {
                "organic": {"control": 0, "graph": 0, "committed_graph": 0},
                "release_verification": {"control": 0, "graph": 0, "committed_graph": 0},
                "total": {"control": control_count, "graph": graph_count, "committed_graph": committed_graph},
            },
            "minimum_control": minimum_control,
            "minimum_graph": minimum_graph,
            "minimum_rollback_control": minimum_rollback_control,
        },
        "rollback": {
            "exact_window": until is not None,
            "assigned_control_count": control_count,
            "assigned_graph_count": graph_count,
            "selected_graph_count": selected_graph,
            "minimum_control": minimum_rollback_control,
            "verified": phase == "rollback_verified",
        },
        "window": {"start": since, "end": until, "exact": until is not None},
        "aggregate": aggregate,
        "evidence": {
            "present": evidence is not None,
            "decision": evidence.get("decision") if evidence else None,
            "stage": evidence_stage,
            "sha256": evidence.get("evidence_sha256") if evidence else None,
            "drills": evidence.get("drills") if evidence else None,
            "candidate_sha256": (
                evidence.get("candidate_evidence_sha256")
                if final_present
                else evidence.get("evidence_sha256") if candidate_present else None
            ),
            "final_sha256": evidence.get("evidence_sha256") if final_present else None,
        },
        "operations": {
            "ci_provenance": "unknown",
            "environment_bootstrap": (
                "attested" if verification_identity.bootstrap_attested else "missing"
            ),
            "api_credential": (
                "configured" if verification_identity.valid
                else "invalid" if verification_identity.configured
                else "missing"
            ),
            "credential_rotation": verification_identity.rotation_state,
        },
        "production_verification_ready": production_verification_ready,
        "v150_entry_ready": v150_entry_ready,
        "v150_entry_decision": "GO" if v150_entry_ready else "NO_GO",
        "v150_entry_blockers": v150_entry_blockers,
    }


def build_autotutor_canary_snapshot(**kwargs: Any) -> dict[str, Any]:
    if not kwargs.get("window_start") or not kwargs.get("window_end"):
        raise ValueError("exact snapshot requires window_start and window_end")
    verification = build_autotutor_canary_verification(**kwargs)
    snapshot_kind = "rollback" if verification["phase"].startswith("rollback_") else "canary"
    snapshot = {
        "schema_version": 1,
        "agent_type": "auto_tutor",
        "snapshot_kind": snapshot_kind,
        "slice": verification["aggregate"].get("slice"),
        "deployment": verification["deployment"],
        "configuration": verification["configuration"],
        "schema": {"revision": verification["deployment"].get("schema_revision")},
        "cohort": verification["trusted_cohort"],
        "admission": verification["admission"],
        "observation_health": verification["observation_health"],
        "aggregate": verification["aggregate"],
        "rollback": verification.get("rollback") or {},
        "phase": verification["phase"],
        "status": verification["status"],
        "decision": verification["decision"],
        "blockers": verification["blockers"],
    }
    return {
        "schema_version": 1,
        "generated_at": verification["generated_at"],
        "snapshot_sha256": _hash_payload(snapshot),
        "snapshot": snapshot,
    }


def validate_autotutor_canary_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("snapshot")
    digest = str(payload.get("snapshot_sha256") or "")
    if not isinstance(snapshot, dict) or digest != _hash_payload(snapshot):
        raise ValueError("AutoTutor production snapshot hash is invalid")
    if snapshot.get("agent_type") != "auto_tutor" or int(snapshot.get("schema_version") or 0) != 1:
        raise ValueError("AutoTutor production snapshot schema is invalid")
    return payload
