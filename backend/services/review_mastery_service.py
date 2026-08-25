"""Shared evidence-chain helpers for adaptive review mastery."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import inspect, text

from student_profile import now_iso

RETENTION_INTERVAL = timedelta(hours=24)
ACTIVE_CHAIN_STATUSES = {"awaiting_feedback", "verification_pending", "retention_due"}


def parse_time(value: str) -> datetime:
    normalized = str(value or "").strip().replace("Z", "+00:00")
    result = datetime.fromisoformat(normalized)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def add_retention_interval(value: str) -> str:
    return (parse_time(value) + RETENTION_INTERVAL).isoformat().replace("+00:00", "Z")


def is_due(due_at: str | None, at: str | None = None) -> bool:
    if not due_at:
        return False
    return parse_time(at or now_iso()) >= parse_time(due_at)


def stable_chain_id(student_id: str, knowledge_tag: str, retrieval_evidence_key: str) -> str:
    raw = f"{student_id}|{knowledge_tag}|{retrieval_evidence_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def request_hash(action: str, payload: dict[str, Any]) -> str:
    import json

    raw = json.dumps({"action": action, **payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_review_mastery_schema(conn: Any) -> None:
    """Create/upgrade the local SQLite compatibility schema.

    Non-SQLite deployments must use Alembic 010.
    """
    if conn.dialect.name != "sqlite":
        tables = set(inspect(conn).get_table_names())
        if "review_mastery_state" not in tables:
            raise RuntimeError("review mastery schema is not migrated")
        return
    conn.execute(text("""CREATE TABLE IF NOT EXISTS review_mastery_state (
        student_id TEXT NOT NULL,
        knowledge_tag TEXT NOT NULL,
        status TEXT NOT NULL,
        retrieval_evidence_key TEXT,
        verification_evidence_key TEXT,
        retention_evidence_key TEXT,
        retention_due_at TEXT,
        revision INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(student_id, knowledge_tag))"""))
    conn.execute(text("""CREATE INDEX IF NOT EXISTS idx_review_mastery_due
        ON review_mastery_state(status, retention_due_at)"""))


def get_mastery_state_with_connection(conn: Any, student_id: str, knowledge_tag: str) -> dict[str, Any] | None:
    ensure_review_mastery_schema(conn)
    row = conn.execute(
        text("SELECT * FROM review_mastery_state WHERE student_id=:sid AND knowledge_tag=:tag"),
        {"sid": student_id, "tag": knowledge_tag},
    ).mappings().first()
    return dict(row) if row else None


def set_mastery_state_with_connection(
    conn: Any,
    *,
    student_id: str,
    knowledge_tag: str,
    status: str,
    retrieval_evidence_key: str | None = None,
    verification_evidence_key: str | None = None,
    retention_evidence_key: str | None = None,
    retention_due_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    ensure_review_mastery_schema(conn)
    timestamp = updated_at or now_iso()
    conn.execute(text("""INSERT INTO review_mastery_state (
        student_id, knowledge_tag, status, retrieval_evidence_key,
        verification_evidence_key, retention_evidence_key, retention_due_at,
        revision, updated_at
    ) VALUES (
        :sid, :tag, :status, :retrieval_key, :verification_key, :retention_key,
        :due_at, 0, :updated_at
    ) ON CONFLICT(student_id, knowledge_tag) DO UPDATE SET
        status=excluded.status,
        retrieval_evidence_key=excluded.retrieval_evidence_key,
        verification_evidence_key=excluded.verification_evidence_key,
        retention_evidence_key=excluded.retention_evidence_key,
        retention_due_at=excluded.retention_due_at,
        revision=review_mastery_state.revision+1,
        updated_at=excluded.updated_at"""), {
        "sid": student_id,
        "tag": knowledge_tag,
        "status": status,
        "retrieval_key": retrieval_evidence_key,
        "verification_key": verification_evidence_key,
        "retention_key": retention_evidence_key,
        "due_at": retention_due_at,
        "updated_at": timestamp,
    })
    return get_mastery_state_with_connection(conn, student_id, knowledge_tag) or {}


def list_retention_states_with_connection(
    conn: Any,
    student_id: str,
    *,
    at: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ensure_review_mastery_schema(conn)
    rows = conn.execute(text("""SELECT * FROM review_mastery_state
        WHERE student_id=:sid AND status='retention_due'
        ORDER BY retention_due_at, knowledge_tag"""), {"sid": student_id}).mappings().all()
    due: list[dict[str, Any]] = []
    scheduled: list[dict[str, Any]] = []
    for row in rows:
        target = due if is_due(row.get("retention_due_at"), at) else scheduled
        target.append(dict(row))
    return due, scheduled


def evidence_rows_with_connection(conn: Any, evidence_keys: list[str | None]) -> list[dict[str, Any]]:
    keys = [key for key in evidence_keys if key]
    if not keys:
        return []
    params = {f"key_{index}": key for index, key in enumerate(keys)}
    placeholders = ", ".join(f":key_{index}" for index in range(len(keys)))
    rows = conn.execute(
        text(f"SELECT * FROM weakpoint_evidence WHERE evidence_key IN ({placeholders})"),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def validate_retention_chain(
    *,
    state: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    retention_assessment_id: str,
    retention_fingerprint: str,
    occurred_at: str,
) -> None:
    if state.get("status") != "retention_due" or not is_due(state.get("retention_due_at"), occurred_at):
        raise ValueError("retention_not_due")
    by_key = {row.get("evidence_key"): row for row in evidence_rows}
    retrieval = by_key.get(state.get("retrieval_evidence_key"))
    verification = by_key.get(state.get("verification_evidence_key"))
    if not retrieval or not verification or verification.get("evidence_type") != "independent_correct":
        raise ValueError("evidence_chain_conflict")
    prior_ids = {retrieval.get("assessment_id"), verification.get("assessment_id")}
    prior_prints = {retrieval.get("assessment_fingerprint"), verification.get("assessment_fingerprint")}
    if retention_assessment_id in prior_ids or retention_fingerprint in prior_prints:
        raise ValueError("evidence_chain_conflict")
