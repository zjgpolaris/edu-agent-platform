from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from db.engine import get_connection
from student_profile import _json_dump, _safe_metadata, init_db, now_iso
from security.prompt_injection import mask_sensitive
from tracing import current_trace_id


VALID_DATA_SCOPES = {"runtime", "eval", "demo"}
VALID_OUTCOME_CLASSES = {"success", "expected_control", "user_denied", "degraded", "unexpected_failure"}
EXPECTED_CONTROL_ACTIONS = {
    "tool.confirmation_required",
    "tool.role_denied",
    "tool.denied",
    "guardrail.blocked",
}


def normalize_data_scope(value: str | None) -> str:
    normalized = (value or "runtime").strip().lower()
    if normalized == "demo_seed":
        normalized = "demo"
    return normalized if normalized in VALID_DATA_SCOPES else "runtime"


def classify_outcome(action: str, success: bool, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("outcome_class")
    if explicit in VALID_OUTCOME_CLASSES:
        return str(explicit)
    if success:
        return "success"
    if metadata.get("user_denied") is True or metadata.get("reason") == "user_denied":
        return "user_denied"
    if action in EXPECTED_CONTROL_ACTIONS:
        return "expected_control"
    if metadata.get("degraded") is True:
        return "degraded"
    return "unexpected_failure"


def _ensure_audit_table(conn: Any) -> None:
    conn.execute(text("""CREATE TABLE IF NOT EXISTS audit_events (
          id TEXT PRIMARY KEY, actor_id TEXT, action TEXT NOT NULL,
          resource_type TEXT, resource_id TEXT,
          success INTEGER NOT NULL, data_scope TEXT NOT NULL DEFAULT 'runtime', metadata_json TEXT NOT NULL,
          created_at TEXT NOT NULL)"""))
    if conn.dialect.name == "sqlite":
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(audit_events)"))}
        if "data_scope" not in columns:
            conn.execute(text("ALTER TABLE audit_events ADD COLUMN data_scope TEXT NOT NULL DEFAULT 'runtime'"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_events_scope_created ON audit_events(data_scope, created_at)"))


def _mask_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {k: mask_sensitive(v) if isinstance(v, str) else v for k, v in metadata.items()}


def record_audit_event(
    *,
    actor_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    success: bool = True,
    metadata: dict[str, Any] | None = None,
    data_scope: str | None = None,
) -> str | None:
    try:
        init_db()
        audit_id = uuid4().hex
        raw_metadata = dict(metadata or {})
        trace_id = current_trace_id()
        if trace_id and "trace_id" not in raw_metadata:
            raw_metadata["trace_id"] = trace_id
        scope = normalize_data_scope(data_scope or raw_metadata.get("data_scope") or os.getenv("EDU_AGENT_DATA_SCOPE", "runtime"))
        raw_metadata["data_scope"] = scope
        raw_metadata["outcome_class"] = classify_outcome(action, success, raw_metadata)
        safe = _mask_metadata(_safe_metadata(raw_metadata))
        with get_connection() as conn:
            _ensure_audit_table(conn)
            conn.execute(
                text("""INSERT INTO audit_events (id, actor_id, action, resource_type, resource_id, success, data_scope, metadata_json, created_at)
                VALUES (:id, :actor_id, :action, :resource_type, :resource_id, :success, :data_scope, :metadata, :created_at)"""),
                {"id": audit_id, "actor_id": actor_id, "action": action,
                 "resource_type": resource_type, "resource_id": resource_id,
                 "success": int(success), "data_scope": scope, "metadata": _json_dump(safe), "created_at": now_iso()},
            )
        return audit_id
    except Exception:
        return None


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), 500))


def list_audit_events(
    *,
    limit: int = 100,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    data_scope: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    init_db()
    filters = []
    params: dict[str, Any] = {}
    if actor_id:
        filters.append("actor_id = :actor_id")
        params["actor_id"] = actor_id
    if action:
        filters.append("action = :action")
        params["action"] = action
    if resource_type:
        filters.append("resource_type = :resource_type")
        params["resource_type"] = resource_type
    if data_scope:
        filters.append("data_scope = :data_scope")
        params["data_scope"] = normalize_data_scope(data_scope)
    if since:
        filters.append("created_at >= :since")
        params["since"] = since
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params["limit"] = _clamp_limit(limit)
    with get_connection() as conn:
        _ensure_audit_table(conn)
        rows = conn.execute(
            text(f"SELECT * FROM audit_events {where} ORDER BY created_at DESC LIMIT :limit"),
            params,
        ).mappings().fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["success"] = bool(item["success"])
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item["data_scope"] = normalize_data_scope(item.get("data_scope") or item["metadata"].get("data_scope"))
        item["metadata"].setdefault("data_scope", item["data_scope"])
        item["metadata"].setdefault("outcome_class", classify_outcome(str(item.get("action") or ""), item["success"], item["metadata"]))
        events.append(item)
    return events


def count_audit_events(*, data_scope: str, since: str | None = None) -> int:
    init_db()
    filters = ["data_scope = :data_scope"]
    params: dict[str, Any] = {"data_scope": normalize_data_scope(data_scope)}
    if since:
        filters.append("created_at >= :since")
        params["since"] = since
    with get_connection() as conn:
        _ensure_audit_table(conn)
        return int(conn.execute(
            text(f"SELECT COUNT(*) FROM audit_events WHERE {' AND '.join(filters)}"),
            params,
        ).scalar_one())
