"""Scoped rehearsal facts and a rollback-only dependency probe.

No process control, configuration mutation or business transition is performed here.
Probe evidence is deliberately NOT a full production writer-failure attestation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents.autotutor_execution import AutoTutorExecutorSettings, AutoTutorExecutionContext, select_executor
from db.engine import engine, get_connection
from deployment import deployed_commit, deployment_environment
from security.autotutor_verification_auth import _allowed_verification_students, _traffic_secret

# Include PID to distinguish forked workers; a change proves a different process,
# not necessarily a service restart. The operator must separately confirm restart.
_BOOT = uuid4().hex


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _seal(payload: dict) -> dict:
    signature = hmac.new(_traffic_secret(), ("autotutor-rehearsal-v1:" + digest(payload)).encode(), hashlib.sha256).hexdigest()
    return {"payload": payload, "signature": signature}


def _previous(receipt: dict, current: dict) -> dict:
    payload = receipt.get("payload")
    if not isinstance(payload, dict) or not hmac.compare_digest(str(receipt.get("signature", "")), _seal(payload)["signature"]):
        raise ValueError("rehearsal_receipt_invalid")
    for field in ("commit", "config_version", "cohort_fingerprint", "environment", "session_sha256", "verification_run_sha256"):
        if payload.get(field) != current.get(field):
            raise ValueError("rehearsal_receipt_binding_mismatch")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(payload["captured_at"])).total_seconds()
        if not 0 <= age <= 3600:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("rehearsal_receipt_expired") from None
    return payload


def readonly_writer_probe(*, settings, verification_run_id: str) -> dict:
    """Attempt the actual writer on a private read-only transaction, always rollback.

    Only a database-enforced read-only violation counts as the expected fault.
    Authentication, connectivity, missing schema and unrelated errors do not pass.
    """
    from agent_runtime.rollout_observations import record_rollout_observation

    @contextmanager
    def isolated():
        with engine.connect() as conn:
            tx = conn.begin()
            sqlite = conn.dialect.name == "sqlite"
            original = None
            try:
                if sqlite:
                    original = int(conn.execute(text("PRAGMA query_only")).scalar())
                    conn.execute(text("PRAGMA query_only=ON"))
                elif conn.dialect.name == "postgresql":
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                else:
                    raise ValueError("rehearsal_dialect_unsupported")
                yield conn
            finally:
                tx.rollback()
                if sqlite and original is not None:
                    conn.execute(text("PRAGMA query_only=" + str(original)))
                    conn.rollback()

    try:
        record_rollout_observation(
            agent_type="auto_tutor", runtime_mode="control", status="rehearsal_probe",
            latency_ms=0, trace_id=None, data_scope="eval", config_version=settings.config_version,
            deployed_commit=deployed_commit(), environment=deployment_environment(),
            traffic_source="release_verification", verification_run_id=verification_run_id,
            _connection_factory=isolated,
        )
    except DBAPIError as exc:
        original = exc.orig
        expected = getattr(original, "pgcode", None) == "25006" or getattr(original, "sqlite_errorcode", None) == 8
        if expected:
            return {"status": "pass", "fault": "database_read_only", "scope": "isolated_rollback_only_transaction"}
        raise ValueError("rehearsal_probe_unexpected_database_error") from None
    raise ValueError("rehearsal_probe_did_not_fail")


def capture_rehearsal(*, student_id: str, session_id: str, verification_run_id: str,
                      expected_commit: str, expected_config_version: str,
                      operation: str = "checkpoint", previous: dict | None = None) -> dict:
    if deployment_environment() != "production" or deployed_commit() != expected_commit:
        raise ValueError("rehearsal_deployment_mismatch")
    settings = AutoTutorExecutorSettings.from_env()
    if settings.config_version != expected_config_version or settings.mode != "active_canary" or not 1 <= settings.active_bps <= 100:
        raise ValueError("rehearsal_configuration_mismatch")
    if set(settings.reason_codes) - {"kill_switch_enabled"}:
        raise ValueError("rehearsal_configuration_invalid")
    if operation not in {"checkpoint", "restart_verify", "restart_resume_verify", "kill_switch_verify", "writer_probe"}:
        raise ValueError("rehearsal_operation_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", verification_run_id):
        raise ValueError("rehearsal_run_invalid")
    if student_id not in _allowed_verification_students():
        raise ValueError("rehearsal_actor_not_allowlisted")
    with get_connection() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        account = conn.execute(text("SELECT role,account_status,traffic_cohort FROM accounts WHERE actor_id=:id"), {"id": student_id}).mappings().first()
        if not account or (account["role"], account["account_status"], account["traffic_cohort"]) != ("student", "active", "verified"):
            raise ValueError("rehearsal_actor_not_trusted")
        row = conn.execute(text("SELECT student_id,trace_id,revision,state_json,inflight_idempotency_key FROM autotutor_sessions WHERE session_id=:id"), {"id": session_id}).mappings().first()
        if not row or row["student_id"] != student_id or row["inflight_idempotency_key"]:
            raise ValueError("rehearsal_session_unavailable")
        observations = conn.execute(text("""SELECT selected_executor,transition_id,admission_reason,fallback_reason
            FROM agent_rollout_observations WHERE trace_id=:trace AND agent_type='auto_tutor'
            AND verification_run_id=:run AND traffic_source='release_verification'
            AND deployed_commit=:commit AND config_version=:config AND environment='production'
            AND data_scope='runtime' ORDER BY created_at,observation_id"""), {
                "trace": row["trace_id"], "run": verification_run_id, "commit": expected_commit, "config": expected_config_version,
            }).mappings().all()
        if not observations or any(not observation["transition_id"] for observation in observations):
            raise ValueError("rehearsal_verification_session_required")
        effects = conn.execute(text("SELECT effect_key FROM learning_events WHERE session_id=:id ORDER BY effect_key"), {"id": session_id}).scalars().all()
        if any(not key for key in effects) or len(set(effects)) != len(effects):
            raise ValueError("rehearsal_duplicate_or_unattributed_effects")
        transition_ids = [o["transition_id"] for o in observations]
        if len(set(transition_ids)) != len(transition_ids):
            raise ValueError("rehearsal_duplicate_observations")
        state = json.loads(row["state_json"])
        if state.get("revision") != row["revision"]:
            raise ValueError("rehearsal_revision_mismatch")
    payload = {
        "schema_version": 1, "kind": "autotutor_rehearsal_observation", "operation": operation,
        "commit": expected_commit, "config_version": expected_config_version, "environment": "production",
        "cohort_fingerprint": settings.cohort_fingerprint, "mode": settings.mode, "active_bps": settings.active_bps,
        "kill_switch": settings.kill_switch, "process_instance": digest([_BOOT, os.getpid()]),
        "captured_at": datetime.now(timezone.utc).isoformat(), "session_sha256": digest(session_id),
        "verification_run_sha256": digest(verification_run_id), "state_sha256": digest(state),
        "effects_sha256": digest(effects), "effect_count": len(effects), "revision": row["revision"],
        "session_status": state.get("status"), "selected_executor": state.get("executor_mode"),
        "observation_count": len(observations), "duplicate_effects": 0, "duplicate_observations": 0,
        "checks": {}, "production_attestation": False,
    }
    if operation in {"restart_verify", "restart_resume_verify", "kill_switch_verify"}:
        old = _previous(previous or {}, payload)
        payload["previous_sha256"] = digest(previous)
        if operation == "restart_verify":
            passed = (old["operation"] == "checkpoint" and old["process_instance"] != payload["process_instance"]
                      and old["selected_executor"] == "graph_active" and payload["selected_executor"] == "graph_active"
                      and not old["kill_switch"] and not settings.kill_switch
                      and old["session_status"] == "awaiting_answer"
                      and all(old[key] == payload[key] for key in ("state_sha256", "revision", "effects_sha256", "observation_count", "active_bps")))
            payload["checks"]["state_survived_process_change"] = passed
        elif operation == "restart_resume_verify":
            passed = (old["operation"] == "restart_verify" and old["checks"].get("state_survived_process_change") is True
                      and payload["revision"] == old["revision"] + 1
                      and payload["observation_count"] == old["observation_count"] + 1
                      and not settings.kill_switch and payload["selected_executor"] == "graph_active")
            payload["checks"]["resumed_once_after_process_change"] = bool(passed)
        else:
            passed = (old["operation"] == "checkpoint" and not old["kill_switch"] and settings.kill_switch
                      and old["selected_executor"] == "graph_active" and payload["selected_executor"] == "legacy"
                      and payload["revision"] == old["revision"] + 1 and payload["observation_count"] == old["observation_count"] + 1
                      and old["active_bps"] == payload["active_bps"]
                      and observations[-1]["selected_executor"] == "legacy"
                      and observations[-1]["fallback_reason"] == "kill_switch_enabled")
            payload["checks"]["kill_switch_downgraded_transition"] = bool(passed)
    if operation == "writer_probe":
        if settings.kill_switch:
            raise ValueError("rehearsal_probe_requires_healthy_canary")
        from agents.autotutor_canary_admission import _infrastructure_snapshot
        context = AutoTutorExecutionContext(actor_id=student_id, actor_role="student", account_status="active",
            traffic_cohort="verified", data_scope="runtime", rollout_eligible=True,
            eligibility_reason="verified_runtime_actor", environment="production", deployed_commit=expected_commit)
        baseline = _infrastructure_snapshot(settings=settings, context=context)
        if select_executor(subject=student_id, context=context, settings=settings, admission=baseline).mode != "graph_active":
            raise ValueError("rehearsal_probe_requires_graph_subject")
        payload["writer_probe"] = readonly_writer_probe(settings=settings, verification_run_id=verification_run_id)
        failed = _infrastructure_snapshot(settings=settings, context=context,
            _health_reader=lambda **kwargs: {"ok": False, "status": "unavailable"})
        payload["checks"]["uncached_admission_denied_on_writer_unavailable"] = (
            not failed.admitted and select_executor(subject=student_id, context=context, settings=settings, admission=failed).mode == "legacy")
        payload["coverage_limit"] = "does_not_test_cached_admission_or_postcommit_writer_failure"
    return _seal(payload)
