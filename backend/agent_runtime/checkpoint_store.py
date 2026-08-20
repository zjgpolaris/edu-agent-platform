from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from agent_runtime.event_store import ensure_runtime_tables, get_run
from agent_runtime.models import utc_now_iso
from db.engine import get_connection


def save_checkpoint(
    run_id: str,
    *,
    revision: int,
    node_name: str,
    state: dict[str, Any],
    side_effect_ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_runtime_tables()
    run = get_run(run_id)
    if run["durability_mode"] != "resumable":
        raise ValueError("checkpoints are only valid for resumable runs")
    if int(run["revision"]) != revision:
        raise ValueError("checkpoint revision must match current run revision")
    checkpoint_id = f"chk_{uuid4().hex}"
    created_at = utc_now_iso()
    with get_connection() as conn:
        conn.execute(text("""INSERT INTO agent_checkpoints (
            checkpoint_id, run_id, revision, node_name, state_json,
            side_effect_ledger_json, created_at
        ) VALUES (
            :checkpoint_id, :run_id, :revision, :node_name, :state_json,
            :side_effect_ledger_json, :created_at
        )"""), {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "revision": revision,
            "node_name": node_name,
            "state_json": json.dumps(state, ensure_ascii=False),
            "side_effect_ledger_json": json.dumps(side_effect_ledger or [], ensure_ascii=False),
            "created_at": created_at,
        })
    return {
        "checkpoint_id": checkpoint_id,
        "run_id": run_id,
        "revision": revision,
        "node_name": node_name,
        "created_at": created_at,
    }


def latest_checkpoint(run_id: str) -> dict[str, Any] | None:
    ensure_runtime_tables()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT * FROM agent_checkpoints
            WHERE run_id=:run_id ORDER BY revision DESC, created_at DESC LIMIT 1"""), {"run_id": run_id}).mappings().first()
    if not row:
        return None
    payload = dict(row)
    payload["state"] = json.loads(payload.pop("state_json"))
    payload["side_effect_ledger"] = json.loads(payload.pop("side_effect_ledger_json"))
    return payload


def prune_terminal_checkpoints(
    run_id: str,
    *,
    keep: int = 5,
    retention_days: int = 30,
    now: datetime | None = None,
) -> int:
    ensure_runtime_tables()
    keep = max(1, keep)
    retention_days = max(1, min(int(retention_days), 365))
    run = get_run(run_id)
    if run["status"] not in {"completed", "partial", "failed", "cancelled"}:
        return 0
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=retention_days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT checkpoint_id, created_at FROM agent_checkpoints
            WHERE run_id=:run_id ORDER BY revision DESC, created_at DESC"""), {"run_id": run_id}).mappings().all()
        stale_ids = {
            str(row["checkpoint_id"])
            for index, row in enumerate(rows)
            if index >= keep or str(row["created_at"]) < cutoff
        }
        removed = 0
        for checkpoint_id in stale_ids:
            removed += int(conn.execute(text("DELETE FROM agent_checkpoints WHERE checkpoint_id=:id"), {"id": checkpoint_id}).rowcount or 0)
    return removed
