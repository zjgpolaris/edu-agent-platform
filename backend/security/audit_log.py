from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from db.engine import get_connection
from student_profile import _json_dump, _safe_metadata, init_db, now_iso
from security.prompt_injection import mask_sensitive
from tracing import current_trace_id


def _ensure_audit_table(conn: Any) -> None:
    conn.execute(text("""CREATE TABLE IF NOT EXISTS audit_events (
          id TEXT PRIMARY KEY, actor_id TEXT, action TEXT NOT NULL,
          resource_type TEXT, resource_id TEXT,
          success INTEGER NOT NULL, metadata_json TEXT NOT NULL,
          created_at TEXT NOT NULL)"""))


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
) -> str | None:
    try:
        init_db()
        audit_id = uuid4().hex
        raw_metadata = dict(metadata or {})
        trace_id = current_trace_id()
        if trace_id and "trace_id" not in raw_metadata:
            raw_metadata["trace_id"] = trace_id
        safe = _mask_metadata(_safe_metadata(raw_metadata))
        with get_connection() as conn:
            _ensure_audit_table(conn)
            conn.execute(
                text("""INSERT INTO audit_events (id, actor_id, action, resource_type, resource_id, success, metadata_json, created_at)
                VALUES (:id, :actor_id, :action, :resource_type, :resource_id, :success, :metadata, :created_at)"""),
                {"id": audit_id, "actor_id": actor_id, "action": action,
                 "resource_type": resource_type, "resource_id": resource_id,
                 "success": int(success), "metadata": _json_dump(safe), "created_at": now_iso()},
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
        events.append(item)
    return events
