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
    if payload.get("runtime_mode") not in {"shadow", "active"}:
        raise ValueError("release evidence runtime mode must be shadow or active")
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
    profiles = payload.get("profiles")
    required_profiles = ("offline", "real_llm", "production_rag")
    if not isinstance(profiles, dict) or any(
        not isinstance(profiles.get(name), dict) or profiles[name].get("status") != "pass"
        or profiles[name].get("commit") != payload.get("deployed_commit")
        for name in required_profiles
    ):
        raise ValueError("release evidence profiles are incomplete or not passed")
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
    evidence_id = f"evidence_{uuid4().hex}"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        with get_connection() as conn:
            if "agent_release_evidence" not in set(sa_inspect(conn).get_table_names()):
                raise LookupError("release evidence schema is not migrated")
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
