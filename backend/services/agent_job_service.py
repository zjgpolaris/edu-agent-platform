from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text

from db.engine import get_connection
from trace_store import current_trace_id, emit_trace_event

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
ALL_STATUSES = {"pending", "running", *TERMINAL_STATUSES}


def _emit_job_trace(step_name: str, event_type: str, *, status: str = "success", metadata: dict[str, Any] | None = None) -> None:
    if current_trace_id():
        emit_trace_event("agent_job", step_name, event_type, status=status, metadata=metadata)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS agent_jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            actor_id TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            result_json TEXT,
            idempotency_key TEXT,
            trace_id TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            timeout_seconds INTEGER NOT NULL DEFAULT 300,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        )"""))
        conn.execute(text("""CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_jobs_actor_idempotency
            ON agent_jobs(actor_id, idempotency_key)"""))
        conn.execute(text("""CREATE INDEX IF NOT EXISTS idx_agent_jobs_status_created
            ON agent_jobs(status, created_at)"""))


def _decode(row: Any) -> dict[str, Any]:
    item = dict(row._mapping)
    item["payload"] = json.loads(item.pop("payload_json") or "{}")
    raw_result = item.pop("result_json")
    item["result"] = json.loads(raw_result) if raw_result else None
    item["cancel_requested"] = bool(item["cancel_requested"])
    return item


def get_job(job_id: str, *, actor_id: str | None = None) -> dict[str, Any] | None:
    _ensure_table()
    query = "SELECT * FROM agent_jobs WHERE id=:id"
    params: dict[str, Any] = {"id": job_id}
    if actor_id is not None:
        query += " AND actor_id=:actor_id"
        params["actor_id"] = actor_id
    with get_connection() as conn:
        row = conn.execute(text(query), params).fetchone()
    return _decode(row) if row else None


def list_pending_jobs(limit: int = 20) -> list[dict[str, Any]]:
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            text("""SELECT * FROM agent_jobs WHERE status='pending' AND cancel_requested=0
                ORDER BY created_at ASC LIMIT :limit"""),
            {"limit": max(1, min(int(limit), 100))},
        ).fetchall()
    return [_decode(row) for row in rows]


def create_job(
    job_type: str,
    payload: dict[str, Any],
    *,
    actor_id: str | None = None,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    max_attempts: int = 3,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    if not job_type.strip():
        raise ValueError("job_type is required")
    if not isinstance(payload, dict):
        raise ValueError("job payload must be an object")
    if max_attempts < 1 or timeout_seconds < 1:
        raise ValueError("max_attempts and timeout_seconds must be positive")
    _ensure_table()
    if idempotency_key:
        with get_connection() as conn:
            existing = conn.execute(
                text("""SELECT * FROM agent_jobs
                     WHERE ((actor_id=:actor_id) OR (actor_id IS NULL AND :actor_id IS NULL))
                       AND idempotency_key=:key"""),
                {"actor_id": actor_id, "key": idempotency_key},
            ).fetchone()
        if existing:
            return _decode(existing)

    job_id = f"job_{uuid.uuid4().hex}"
    now = _now()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO agent_jobs (
                id, job_type, actor_id, status, payload_json, idempotency_key,
                trace_id, max_attempts, timeout_seconds, created_at, updated_at
            ) VALUES (
                :id, :job_type, :actor_id, 'pending', :payload_json, :idempotency_key,
                :trace_id, :max_attempts, :timeout_seconds, :created_at, :updated_at
            )"""),
            {
                "id": job_id,
                "job_type": job_type,
                "actor_id": actor_id,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "max_attempts": max_attempts,
                "timeout_seconds": timeout_seconds,
                "created_at": now,
                "updated_at": now,
            },
        )
    return get_job(job_id) or {}


def claim_job(job_id: str) -> dict[str, Any] | None:
    _ensure_table()
    now = _now()
    with get_connection() as conn:
        updated = conn.execute(
            text("""UPDATE agent_jobs SET
                status='running', attempts=attempts+1, started_at=:now,
                updated_at=:now, error=NULL
                WHERE id=:id AND status='pending' AND cancel_requested=0"""),
            {"id": job_id, "now": now},
        )
    return get_job(job_id) if updated.rowcount == 1 else None


def request_cancel(job_id: str, *, actor_id: str | None = None) -> dict[str, Any] | None:
    job = get_job(job_id, actor_id=actor_id)
    if not job or job["status"] in TERMINAL_STATUSES:
        return job
    now = _now()
    with get_connection() as conn:
        conn.execute(
            text("""UPDATE agent_jobs SET
                cancel_requested=1,
                status=CASE WHEN status='pending' THEN 'cancelled' ELSE status END,
                finished_at=CASE WHEN status='pending' THEN :now ELSE finished_at END,
                updated_at=:now
                WHERE id=:id"""),
            {"id": job_id, "now": now},
        )
    return get_job(job_id, actor_id=actor_id)


def _finish(job_id: str, status: str, *, result: Any = None, error: str | None = None) -> dict[str, Any]:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"invalid terminal status: {status}")
    now = _now()
    with get_connection() as conn:
        conn.execute(
            text("""UPDATE agent_jobs SET status=:status, result_json=:result_json,
                error=:error, finished_at=:now, updated_at=:now WHERE id=:id"""),
            {
                "id": job_id,
                "status": status,
                "result_json": json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                "error": error,
                "now": now,
            },
        )
    return get_job(job_id) or {}


def fail_or_retry(job_id: str, error: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if job["cancel_requested"]:
        return _finish(job_id, "cancelled", error="cancelled by request")
    if job["attempts"] < job["max_attempts"]:
        now = _now()
        with get_connection() as conn:
            conn.execute(
                text("""UPDATE agent_jobs SET status='pending', error=:error,
                    started_at=NULL, updated_at=:now WHERE id=:id"""),
                {"id": job_id, "error": error, "now": now},
            )
        return get_job(job_id) or {}
    return _finish(job_id, "failed", error=error)


def execute_job(job_id: str, handler: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    job = claim_job(job_id)
    if not job:
        existing = get_job(job_id)
        if not existing:
            raise KeyError(job_id)
        return existing

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"agent-job-{job_id[-8:]}")
    _emit_job_trace(
        job["job_type"],
        "job_start",
        status="pending",
        metadata={"job_id": job_id, "attempt": job["attempts"]},
    )
    future = executor.submit(handler, job["payload"])
    try:
        result = future.result(timeout=job["timeout_seconds"])
        latest = get_job(job_id) or job
        if latest["cancel_requested"]:
            return _finish(job_id, "cancelled", error="cancelled by request")
        completed = _finish(job_id, "succeeded", result=result)
        _emit_job_trace(job["job_type"], "job_result", metadata={"job_id": job_id})
        return completed
    except FutureTimeoutError:
        future.cancel()
        timed_out = fail_or_retry(job_id, f"job timed out after {job['timeout_seconds']}s")
        _emit_job_trace(job["job_type"], "job_error", status="error", metadata={"job_id": job_id, "reason": "timeout"})
        return timed_out
    except Exception as exc:
        failed = fail_or_retry(job_id, str(exc))
        _emit_job_trace(job["job_type"], "job_error", status="error", metadata={"job_id": job_id, "reason": str(exc)})
        return failed
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def recover_stale_jobs(stale_before: str) -> dict[str, int]:
    """Return stale running jobs to pending, or dead-letter them after max attempts."""
    _ensure_table()
    now = _now()
    with get_connection() as conn:
        retry = conn.execute(
            text("""UPDATE agent_jobs SET status='pending', started_at=NULL,
                error='recovered stale running job', updated_at=:now
                WHERE status='running' AND updated_at<:stale_before
                  AND cancel_requested=0 AND attempts<max_attempts"""),
            {"now": now, "stale_before": stale_before},
        ).rowcount
        failed = conn.execute(
            text("""UPDATE agent_jobs SET status='failed',
                error='stale running job exceeded max attempts', finished_at=:now, updated_at=:now
                WHERE status='running' AND updated_at<:stale_before
                  AND cancel_requested=0 AND attempts>=max_attempts"""),
            {"now": now, "stale_before": stale_before},
        ).rowcount
        cancelled = conn.execute(
            text("""UPDATE agent_jobs SET status='cancelled',
                error='cancelled during recovery', finished_at=:now, updated_at=:now
                WHERE status='running' AND updated_at<:stale_before AND cancel_requested=1"""),
            {"now": now, "stale_before": stale_before},
        ).rowcount
    return {"retried": retry, "failed": failed, "cancelled": cancelled}
