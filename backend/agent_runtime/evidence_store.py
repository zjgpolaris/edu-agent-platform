from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.exc import IntegrityError

from db.engine import get_connection


def _canonical_sha256(payload: dict[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_release_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    from agent_runtime.rollout_gate import baseline_sha256, evidence_sha256

    digest = str(payload.get("evidence_sha256") or "")
    if not digest or digest != evidence_sha256(payload):
        raise ValueError("release evidence hash is missing or invalid")
    required = ("agent_type", "config_version", "runtime_mode", "deployed_commit", "environment")
    if any(not str(payload.get(field) or "").strip() for field in required):
        raise ValueError("release evidence provenance is incomplete")
    is_autotutor = payload.get("agent_type") == "auto_tutor"
    valid_modes = {"active_canary"} if is_autotutor else {"shadow", "active"}
    if payload.get("runtime_mode") not in valid_modes:
        raise ValueError("release evidence runtime mode is invalid")
    generated_at = payload.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("release evidence generated_at is invalid") from None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if not now - timedelta(days=7) <= generated.astimezone(timezone.utc) <= now + timedelta(minutes=5):
        raise ValueError("release evidence is stale or generated in the future")
    schema_version = int(payload.get("schema_version") or 1)
    if schema_version not in ({3, 4} if is_autotutor else {1, 2}):
        raise ValueError("release evidence schema is unsupported")
    if is_autotutor:
        aggregate = payload.get("aggregate")
        window = payload.get("window")
        drills = payload.get("drills")
        production_snapshot = payload.get("production_snapshot")
        if (
            not isinstance(aggregate, dict)
            or not isinstance(window, dict)
            or not window.get("start")
            or not window.get("end")
            or payload.get("cohort") != "verified"
            or int(payload.get("migration_revision") or 0) < 16
        ):
            raise ValueError("AutoTutor release evidence provenance is incomplete")
        from agent_runtime.autotutor_canary_verification import validate_autotutor_canary_snapshot

        validate_autotutor_canary_snapshot({
            "snapshot": production_snapshot,
            "snapshot_sha256": payload.get("snapshot_sha256"),
        })
        snapshot_deployment = production_snapshot.get("deployment") or {}
        snapshot_configuration = production_snapshot.get("configuration") or {}
        snapshot_schema = production_snapshot.get("schema") or {}
        if (
            production_snapshot.get("aggregate") != aggregate
            or snapshot_deployment.get("deployed_commit") != payload.get("deployed_commit")
            or snapshot_deployment.get("environment") != payload.get("environment")
            or snapshot_configuration.get("config_version") != payload.get("config_version")
            or str(snapshot_schema.get("revision") or "") != str(payload.get("migration_revision") or "")
        ):
            raise ValueError("AutoTutor production snapshot does not match evidence")
        if schema_version == 4:
            stage = payload.get("evidence_stage")
            cohort_fingerprint = str(payload.get("cohort_fingerprint") or "")
            runtime_state_fingerprint = str(payload.get("runtime_state_fingerprint") or "")
            if (
                stage not in {"candidate", "final"}
                or not cohort_fingerprint.startswith("sha256:")
                or not runtime_state_fingerprint.startswith("sha256:")
                or snapshot_configuration.get("cohort_fingerprint") != cohort_fingerprint
                or snapshot_configuration.get("runtime_state_fingerprint") != runtime_state_fingerprint
            ):
                raise ValueError("AutoTutor v4 evidence fingerprints are invalid")
        try:
            window_start = datetime.fromisoformat(str(window["start"]).replace("Z", "+00:00"))
            window_end = datetime.fromisoformat(str(window["end"]).replace("Z", "+00:00"))
            if window_start.tzinfo is None:
                window_start = window_start.replace(tzinfo=timezone.utc)
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            raise ValueError("AutoTutor release evidence window is invalid") from None
        if window_start >= window_end:
            raise ValueError("AutoTutor release evidence window is invalid")
        aggregate_slice = aggregate.get("slice") if isinstance(aggregate.get("slice"), dict) else {}
        if (
            aggregate_slice.get("deployed_commit") != payload.get("deployed_commit")
            or aggregate_slice.get("config_version") != payload.get("config_version")
            or aggregate_slice.get("environment") != payload.get("environment")
            or aggregate_slice.get("traffic_cohort") != payload.get("cohort")
            or aggregate_slice.get("since") != window.get("start")
            or aggregate_slice.get("until") != window.get("end")
        ):
            raise ValueError("AutoTutor aggregate slice does not match evidence")
        if schema_version == 4 and payload.get("evidence_stage") == "candidate":
            attestation = payload.get("drill_attestation")
            if payload.get("decision") != "CANDIDATE_GO" or payload.get("blockers"):
                raise ValueError("AutoTutor candidate evidence decision is invalid")
            if aggregate.get("status") != "GO" or aggregate.get("decision") != "GO":
                raise ValueError("AutoTutor candidate evidence requires a GO aggregate")
            if (
                production_snapshot.get("snapshot_kind") != "canary"
                or snapshot_configuration.get("mode") != "active_canary"
                or not 1 <= int(snapshot_configuration.get("active_bps") or 0) <= 100
            ):
                raise ValueError("AutoTutor candidate snapshot is not an approved production canary")
            required_candidate_drills = {"restart", "writer_failure", "kill_switch"}
            if not isinstance(drills, dict) or any(drills.get(name) != "pass" for name in required_candidate_drills):
                raise ValueError("AutoTutor candidate evidence drills are incomplete")
            if (
                not isinstance(attestation, dict)
                or attestation.get("attestation_type") != "environment_approved_operator"
                or payload.get("drill_attestation_sha256") != _canonical_sha256(attestation)
                or attestation.get("deployed_commit") != payload.get("deployed_commit")
                or attestation.get("config_version") != payload.get("config_version")
                or attestation.get("environment") != payload.get("environment")
                or attestation.get("window") != payload.get("window")
                or any((attestation.get("results") or {}).get(name) != drills.get(name) for name in required_candidate_drills)
            ):
                raise ValueError("AutoTutor candidate rehearsal attestation is invalid")
        if payload.get("decision") == "GO":
            if aggregate.get("status") != "GO" or aggregate.get("decision") != "GO":
                raise ValueError("AutoTutor GO evidence requires a GO aggregate")
            required_drills = {"restart", "writer_failure", "kill_switch", "rollback"}
            if not isinstance(drills, dict) or any(drills.get(name) != "pass" for name in required_drills):
                raise ValueError("AutoTutor GO evidence drills are incomplete")
        if schema_version == 4 and payload.get("evidence_stage") == "final":
            candidate_digest = str(payload.get("candidate_evidence_sha256") or "")
            rollback_snapshot = payload.get("rollback_snapshot")
            rollback_digest = str(payload.get("rollback_snapshot_sha256") or "")
            if payload.get("decision") != "GO" or not re.fullmatch(r"[0-9a-f]{64}", candidate_digest):
                raise ValueError("AutoTutor final evidence provenance is incomplete")
            validate_autotutor_canary_snapshot({"snapshot": rollback_snapshot, "snapshot_sha256": rollback_digest})
            rollback_configuration = rollback_snapshot.get("configuration") or {}
            rollback_deployment = rollback_snapshot.get("deployment") or {}
            rollback_metrics = rollback_snapshot.get("rollback") or {}
            if (
                rollback_snapshot.get("snapshot_kind") != "rollback"
                or rollback_snapshot.get("phase") != "rollback_ready_for_finalize"
                or rollback_snapshot.get("status") != "READY"
                or rollback_snapshot.get("decision") != "GO"
                or rollback_deployment.get("deployed_commit") != payload.get("deployed_commit")
                or rollback_deployment.get("environment") != payload.get("environment")
                or rollback_configuration.get("config_version") != payload.get("config_version")
                or rollback_configuration.get("cohort_fingerprint") != payload.get("cohort_fingerprint")
                or rollback_configuration.get("mode") != "legacy"
                or int(rollback_configuration.get("active_bps") or 0) != 0
                or int(rollback_metrics.get("assigned_graph_count") or 0) != 0
                or int(rollback_metrics.get("selected_graph_count") or 0) != 0
                or int(rollback_metrics.get("assigned_control_count") or 0) < int(rollback_metrics.get("minimum_control") or 20)
            ):
                raise ValueError("AutoTutor final evidence rollback proof is invalid")
            candidate = load_release_evidence(evidence_sha256=candidate_digest)
            if (
                candidate is None
                or candidate.get("evidence_stage") != "candidate"
                or candidate.get("decision") != "CANDIDATE_GO"
                or any(candidate.get(field) != payload.get(field) for field in (
                    "deployed_commit", "config_version", "environment", "cohort_fingerprint",
                    "runtime_state_fingerprint", "window", "snapshot_sha256", "aggregate",
                    "drill_attestation_sha256",
                ))
            ):
                raise ValueError("AutoTutor final evidence candidate is not persisted or does not match")
        return _persist_release_evidence(payload, digest=digest, schema_version=schema_version)
    if schema_version == 2 and not str(payload.get("image_digest") or "").strip():
        raise ValueError("release evidence image digest is required for schema v2")
    profiles = payload.get("profiles")
    required_profiles = (
        ("offline", "real_llm", "production_rag")
        if schema_version == 1
        else ("offline", "real_llm_business_eval", "production_rag", "llm_capabilities")
    )
    if not isinstance(profiles, dict) or any(
        not isinstance(profiles.get(name), dict) or profiles[name].get("status") != "pass"
        or profiles[name].get("commit") != payload.get("deployed_commit")
        for name in required_profiles
    ):
        raise ValueError("release evidence profiles are incomplete or not passed")
    if schema_version == 2:
        capability = profiles["llm_capabilities"]
        if (
            capability.get("image_digest") != payload.get("image_digest")
            or capability.get("runtime_config_version") != payload.get("config_version")
            or capability.get("environment") != payload.get("environment")
            or not str(capability.get("manifest_sha256") or "").startswith("sha256:")
        ):
            raise ValueError("release evidence LLM capability provenance is invalid")
    baseline = payload.get("control_baseline")
    if (
        not isinstance(baseline, dict)
        or baseline.get("sha256") != baseline_sha256(baseline)
        or baseline.get("source") != "server_trace_aggregate"
        or baseline.get("environment") != payload.get("environment")
        or not baseline.get("commit")
        or not baseline.get("config_version")
        or int(baseline.get("sample_count") or 0) <= 0
    ):
        raise ValueError("release evidence control baseline is invalid")
    return _persist_release_evidence(payload, digest=digest, schema_version=schema_version)


def _persist_release_evidence(payload: dict[str, Any], *, digest: str, schema_version: int) -> dict[str, Any]:
    evidence_id = f"evidence_{uuid4().hex}"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        with get_connection() as conn:
            if "agent_release_evidence" not in set(sa_inspect(conn).get_table_names()):
                raise LookupError("release evidence schema is not migrated")
            if schema_version == 2:
                from llm.capability_store import load_capability_manifest_by_hash
                profiles = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {}
                capability = profiles["llm_capabilities"]
                manifest = load_capability_manifest_by_hash(str(capability["manifest_sha256"]), connection=conn)
                if manifest is None:
                    raise ValueError("release evidence capability manifest is not persisted")
                expected = {
                    "deployed_commit": payload["deployed_commit"],
                    "image_digest": payload["image_digest"],
                    "runtime_config_version": payload["config_version"],
                    "environment": payload["environment"],
                }
                if any(str(manifest.get(field) or "") != str(value) for field, value in expected.items()):
                    raise ValueError("release evidence capability manifest provenance does not match")
            conn.execute(text("""INSERT INTO agent_release_evidence (
                evidence_id, agent_type, config_version, runtime_mode, deployed_commit,
                environment, evidence_sha256, payload_json, created_at
            ) VALUES (
                :evidence_id, :agent_type, :config_version, :runtime_mode, :deployed_commit,
                :environment, :evidence_sha256, :payload_json, :created_at
            )"""), {
                "evidence_id": evidence_id,
                "agent_type": payload["agent_type"],
                "config_version": payload["config_version"],
                "runtime_mode": payload["runtime_mode"],
                "deployed_commit": payload["deployed_commit"],
                "environment": payload["environment"],
                "evidence_sha256": digest,
                "payload_json": encoded,
                "created_at": _now(),
            })
    except IntegrityError:
        existing = load_release_evidence(evidence_sha256=digest)
        if existing is None:
            raise
        return existing
    return payload


def load_release_evidence(
    *,
    agent_type: str | None = None,
    config_version: str | None = None,
    runtime_mode: str | None = None,
    deployed_commit: str | None = None,
    environment: str | None = None,
    evidence_sha256: str | None = None,
) -> dict[str, Any] | None:
    filters: list[str] = []
    params: dict[str, Any] = {}
    for column, value in (
        ("agent_type", agent_type),
        ("config_version", config_version),
        ("runtime_mode", runtime_mode),
        ("deployed_commit", deployed_commit),
        ("environment", environment),
        ("evidence_sha256", evidence_sha256),
    ):
        if value:
            filters.append(f"{column}=:{column}")
            params[column] = value
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        if "agent_release_evidence" not in set(sa_inspect(conn).get_table_names()):
            return None
        row = conn.execute(text(
            f"SELECT payload_json, evidence_sha256 FROM agent_release_evidence {where} ORDER BY created_at DESC LIMIT 1"
        ), params).mappings().first()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    from agent_runtime.rollout_gate import evidence_sha256 as calculate_evidence_sha256

    digest = str(row["evidence_sha256"] or "")
    if payload.get("evidence_sha256") != digest or calculate_evidence_sha256(payload) != digest:
        return None
    return payload
