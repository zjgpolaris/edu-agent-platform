from __future__ import annotations

from sqlalchemy import text

from agent_runtime.completion import CompletionEvaluator
from agent_runtime.event_store import append_run_event, ensure_runtime_tables, get_run_state
from agent_runtime.models import utc_now_iso
from agent_runtime.side_effect_store import mark_stale_started_side_effects_unknown
from db.engine import get_connection


def recover_stale_runs(*, updated_before: str, now: str | None = None) -> dict[str, int]:
    ensure_runtime_tables()
    now = now or utc_now_iso()
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT run_id, revision, durability_mode, status, expires_at
            FROM agent_runs
            WHERE status IN ('running','waiting_input','waiting_confirmation')
              AND updated_at<:updated_before"""), {"updated_before": updated_before}).mappings().all()
    result = {
        "failed": 0,
        "awaiting_resume": 0,
        "stale_conflicts": 0,
        "side_effects_unknown": mark_stale_started_side_effects_unknown(updated_before=updated_before),
    }
    evaluator = CompletionEvaluator()
    for row in rows:
        if row["durability_mode"] == "resumable" and (not row["expires_at"] or str(row["expires_at"]) > now):
            result["awaiting_resume"] += 1
            continue
        try:
            state = get_run_state(str(row["run_id"]))
            decision = evaluator.evaluate(state, verifier_error=True)
            append_run_event(
                str(row["run_id"]),
                expected_revision=int(row["revision"]),
                event_type="run_failed",
                public_payload={"error": {"code": "runtime_interrupted", "retryable": True}},
                next_status="failed",
                completion=decision,
            )
            result["failed"] += 1
        except Exception:
            result["stale_conflicts"] += 1
    return result
