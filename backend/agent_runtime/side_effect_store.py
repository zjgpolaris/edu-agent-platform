from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agent_runtime.event_store import ensure_runtime_tables, get_run
from agent_runtime.models import utc_now_iso
from db.engine import get_connection

SideEffectStatus = Literal["started", "committed", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class SideEffectClaim:
    record: dict[str, Any]
    acquired: bool

    @property
    def replayable(self) -> bool:
        return not self.acquired and self.record["status"] in {"committed", "failed"}


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for source, target in (("result_json", "result"), ("error_json", "error")):
        raw = payload.pop(source, None)
        try:
            payload[target] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            payload[target] = None
    return payload


def get_side_effect(run_id: str, idempotency_key: str) -> dict[str, Any] | None:
    ensure_runtime_tables()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM agent_side_effects WHERE run_id=:run_id AND idempotency_key=:key"),
            {"run_id": run_id, "key": idempotency_key},
        ).mappings().first()
    return _decode(dict(row)) if row else None


def claim_side_effect(
    *,
    run_id: str,
    step_id: str,
    operation: str,
    idempotency_key: str,
    input_payload: dict[str, Any],
) -> SideEffectClaim:
    ensure_runtime_tables()
    run = get_run(run_id)
    plan = (run.get("state") or {}).get("plan") or {}
    step = next((item for item in plan.get("steps") or [] if item.get("step_id") == step_id), None)
    if step is None:
        raise ValueError("side-effect step is not present in the admitted plan")
    if run.get("status") != "running":
        raise ValueError("side effects may only execute while the run is running")
    if run.get("current_step_id") != step_id:
        raise ValueError("side-effect step is not the current run step")
    if step.get("operation") != operation or step.get("idempotency_key") != idempotency_key:
        raise ValueError("side-effect claim does not match the admitted plan")
    if step.get("input") != input_payload:
        raise ValueError("side-effect input does not match the admitted plan")
    if step.get("side_effect") not in {"write", "session_create"}:
        raise ValueError("admitted step is not a durable side effect")
    existing = get_side_effect(run_id, idempotency_key)
    if existing:
        if existing["step_id"] != step_id or existing["operation"] != operation:
            raise ValueError("side-effect idempotency key is bound to another step")
        return SideEffectClaim(existing, acquired=False)
    now = utc_now_iso()
    side_effect_id = f"sfx_{uuid4().hex}"
    try:
        with get_connection() as conn:
            conn.execute(text("""INSERT INTO agent_side_effects (
                side_effect_id, run_id, step_id, operation, idempotency_key,
                status, resource_ref, result_json, error_json, created_at, updated_at
            ) VALUES (
                :side_effect_id, :run_id, :step_id, :operation, :idempotency_key,
                'started', NULL, NULL, NULL, :created_at, :updated_at
            )"""), {
                "side_effect_id": side_effect_id,
                "run_id": run_id,
                "step_id": step_id,
                "operation": operation,
                "idempotency_key": idempotency_key,
                "created_at": now,
                "updated_at": now,
            })
    except IntegrityError:
        existing = get_side_effect(run_id, idempotency_key)
        if existing is None:
            raise
        if existing["step_id"] != step_id or existing["operation"] != operation:
            raise ValueError("side-effect idempotency key is bound to another step")
        return SideEffectClaim(existing, acquired=False)
    record = get_side_effect(run_id, idempotency_key)
    if record is None:
        raise RuntimeError("side-effect claim was not persisted")
    return SideEffectClaim(record, acquired=True)


def _finish_side_effect(
    run_id: str,
    idempotency_key: str,
    *,
    status: SideEffectStatus,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    resource_ref: str | None = None,
) -> dict[str, Any]:
    if status not in {"committed", "failed", "unknown"}:
        raise ValueError("invalid terminal side-effect status")
    with get_connection() as conn:
        updated = conn.execute(text("""UPDATE agent_side_effects SET
            status=:status, resource_ref=:resource_ref, result_json=:result_json,
            error_json=:error_json, updated_at=:updated_at
            WHERE run_id=:run_id AND idempotency_key=:key AND status='started'
        """), {
            "status": status,
            "resource_ref": resource_ref,
            "result_json": json.dumps(result, ensure_ascii=False) if result is not None else None,
            "error_json": json.dumps(error, ensure_ascii=False) if error is not None else None,
            "updated_at": utc_now_iso(),
            "run_id": run_id,
            "key": idempotency_key,
        })
    record = get_side_effect(run_id, idempotency_key)
    if record is None:
        raise LookupError("side-effect record not found")
    if updated.rowcount != 1 and record["status"] != status:
        raise ValueError("side-effect claim is no longer writable")
    return record


def commit_side_effect(run_id: str, idempotency_key: str, result: dict[str, Any], *, resource_ref: str | None = None) -> dict[str, Any]:
    return _finish_side_effect(run_id, idempotency_key, status="committed", result=result, resource_ref=resource_ref)


def fail_side_effect(run_id: str, idempotency_key: str, result: dict[str, Any]) -> dict[str, Any]:
    return _finish_side_effect(run_id, idempotency_key, status="failed", result=result)


def mark_side_effect_unknown(run_id: str, idempotency_key: str, error: dict[str, Any]) -> dict[str, Any]:
    return _finish_side_effect(run_id, idempotency_key, status="unknown", error=error)


def mark_stale_started_side_effects_unknown(*, updated_before: str) -> int:
    ensure_runtime_tables()
    with get_connection() as conn:
        updated = conn.execute(text("""UPDATE agent_side_effects SET
            status='unknown',
            error_json=:error_json,
            updated_at=:updated_at
            WHERE status='started' AND updated_at<:updated_before
        """), {
            "error_json": json.dumps({"code": "runtime_interrupted"}, ensure_ascii=False),
            "updated_at": utc_now_iso(),
            "updated_before": updated_before,
        })
    return int(updated.rowcount or 0)
