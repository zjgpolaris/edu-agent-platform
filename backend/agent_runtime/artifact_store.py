from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import text

from agent_runtime.event_store import RunNotFoundError, ensure_runtime_tables, get_run
from agent_runtime.models import ActorRole, utc_now_iso
from db.engine import get_connection


def _retention_days(sensitivity: str) -> int:
    defaults = {"normal": 7, "student_content": 30, "restricted": 7}
    suffix = sensitivity.upper()
    raw = os.getenv(f"EDU_AGENT_RUNTIME_V2_ARTIFACT_RETENTION_DAYS_{suffix}", str(defaults.get(sensitivity, 7)))
    try:
        return max(1, min(int(raw), 365))
    except (TypeError, ValueError):
        return defaults.get(sensitivity, 7)


def _default_expiry(sensitivity: str) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=_retention_days(sensitivity))).isoformat()


def _can_read(*, actor_id: str | None, actor_role: ActorRole, owner_actor_id: str | None, student_id: str | None) -> bool:
    if actor_role == "admin":
        return True
    if actor_role == "teacher":
        from security.auth import auth_required, teacher_has_student_access

        return not auth_required() or actor_id == owner_actor_id or bool(student_id and teacher_has_student_access(actor_id, student_id))
    if actor_role == "student" and actor_id and actor_id in {owner_actor_id, student_id}:
        return True
    return bool(actor_id and owner_actor_id and actor_id == owner_actor_id)


def create_artifact(
    run_id: str,
    *,
    owner_actor_id: str | None,
    student_id: str | None,
    artifact_type: Literal["input", "structured_output", "final_output", "review_payload"],
    sensitivity: Literal["normal", "student_content", "restricted"],
    content: dict[str, Any],
    expires_at: str | None = None,
) -> dict[str, Any]:
    ensure_runtime_tables()
    run = get_run(run_id)
    if owner_actor_id and run.get("actor_id") and owner_actor_id != run["actor_id"]:
        raise PermissionError("artifact owner must match run owner")
    if student_id and run.get("student_id") and student_id != run["student_id"]:
        raise PermissionError("artifact student must match run student")
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    now = utc_now_iso()
    expires_at = expires_at or _default_expiry(sensitivity)
    artifact_id = f"art_{uuid4().hex}"
    with get_connection() as conn:
        conn.execute(text("""INSERT INTO agent_run_artifacts (
            artifact_id, run_id, owner_actor_id, student_id, artifact_type, sensitivity,
            content_json, content_sha256, expires_at, created_at, updated_at
        ) VALUES (
            :artifact_id, :run_id, :owner_actor_id, :student_id, :artifact_type, :sensitivity,
            :content_json, :content_sha256, :expires_at, :created_at, :updated_at
        )"""), {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "owner_actor_id": owner_actor_id,
            "student_id": student_id,
            "artifact_type": artifact_type,
            "sensitivity": sensitivity,
            "content_json": encoded,
            "content_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "expires_at": expires_at,
            "created_at": now,
            "updated_at": now,
        })
    return {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "artifact_type": artifact_type,
        "sensitivity": sensitivity,
        "content_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "expires_at": expires_at,
        "created_at": now,
    }


def get_artifact(artifact_id: str, *, actor_id: str | None, actor_role: ActorRole) -> dict[str, Any]:
    ensure_runtime_tables()
    with get_connection() as conn:
        row = conn.execute(text("SELECT * FROM agent_run_artifacts WHERE artifact_id=:artifact_id"), {"artifact_id": artifact_id}).mappings().first()
    if not row:
        raise RunNotFoundError("agent artifact not found")
    item = dict(row)
    if item.get("expires_at") and str(item["expires_at"]) < datetime.now(timezone.utc).isoformat():
        raise RunNotFoundError("agent artifact expired")
    if not _can_read(
        actor_id=actor_id,
        actor_role=actor_role,
        owner_actor_id=item.get("owner_actor_id"),
        student_id=item.get("student_id"),
    ):
        raise PermissionError("agent artifact access denied")
    item["content"] = json.loads(item.pop("content_json"))
    return item


def list_run_artifacts(run_id: str, *, actor_id: str | None, actor_role: ActorRole) -> list[dict[str, Any]]:
    ensure_runtime_tables()
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT artifact_id FROM agent_run_artifacts
            WHERE run_id=:run_id ORDER BY created_at ASC"""), {"run_id": run_id}).mappings().all()
    artifacts: list[dict[str, Any]] = []
    for row in rows:
        try:
            artifacts.append(get_artifact(str(row["artifact_id"]), actor_id=actor_id, actor_role=actor_role))
        except RunNotFoundError:
            # Expired rows are invisible before the asynchronous purge runs.
            continue
    return artifacts


def purge_expired_artifacts(now: str | None = None) -> int:
    ensure_runtime_tables()
    with get_connection() as conn:
        result = conn.execute(text("DELETE FROM agent_run_artifacts WHERE expires_at IS NOT NULL AND expires_at<:now"), {"now": now or utc_now_iso()})
    return int(result.rowcount or 0)
