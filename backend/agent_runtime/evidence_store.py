from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.exc import IntegrityError

from db.engine import get_connection


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
    if schema_version not in ({3} if is_autotutor else {1, 2}):
        raise ValueError("release evidence schema is unsupported")
    if is_autotutor:
        aggregate = payload.get("aggregate")
        window = payload.get("window")
        drills = payload.get("drills")
        if (
            not isinstance(aggregate, dict)
            or not isinstance(window, dict)
            or not window.get("start")
            or not window.get("end")
            or payload.get("cohort") != "verified"
            or int(payload.get("migration_revision") or 0) < 16
        ):
            raise ValueError("AutoTutor release evidence provenance is incomplete")
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
        if payload.get("decision") == "GO":
            if aggregate.get("status") != "GO" or aggregate.get("decision") != "GO":
                raise ValueError("AutoTutor GO evidence requires a GO aggregate")
            required_drills = {"restart", "writer_failure", "kill_switch"}
            if not isinstance(drills, dict) or any(drills.get(name) != "pass" for name in required_drills):
                raise ValueError("AutoTutor GO evidence drills are incomplete")
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
