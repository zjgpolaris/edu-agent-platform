from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from agent_runtime.models import (
    AgentBudget,
    AgentContext,
    AgentRunState,
    CompletionDecision,
    RunStatus,
    RuntimeEvent,
    utc_now_iso,
)
from agent_runtime.sse import sanitize_public_payload
from agent_runtime.transitions import InvalidTransitionError, validate_transition
from db.engine import get_connection

TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled"}


class RunNotFoundError(LookupError):
    pass


@dataclass(slots=True)
class StaleRevisionError(RuntimeError):
    run_id: str
    expected_revision: int

    def __str__(self) -> str:
        return f"stale revision for {self.run_id}: expected {self.expected_revision}"


def ensure_runtime_tables() -> None:
    """Bootstrap local SQLite only; Alembic 007/008 own deployed database DDL."""
    from db.schema import agent_checkpoints, agent_run_artifacts, agent_run_events, agent_runs, agent_side_effects

    with get_connection() as conn:
        if conn.dialect.name != "sqlite":
            from sqlalchemy import inspect as sa_inspect

            existing = set(sa_inspect(conn).get_table_names())
            required = {"agent_runs", "agent_run_events", "agent_run_artifacts", "agent_checkpoints", "agent_side_effects"}
            missing = sorted(required - existing)
            if missing:
                raise RuntimeError(f"Agent Runtime v2 schema is not migrated: {', '.join(missing)}")
            return
        for table in (agent_runs, agent_run_events, agent_run_artifacts, agent_checkpoints, agent_side_effects):
            table.create(bind=conn, checkfirst=True)


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _idempotency_scope(context: AgentContext) -> str:
    if context.actor_id:
        return f"actor:{context.actor_id}"
    if context.student_id:
        return f"student:{context.student_id}"
    if context.session_id:
        return f"session:{context.session_id}"
    return f"trace:{context.trace_id}"


def _default_resumable_expiry() -> str:
    try:
        ttl_hours = max(1, min(int(os.getenv("EDU_AGENT_RUNTIME_V2_RESUMABLE_TTL_HOURS", "168")), 24 * 90))
    except (TypeError, ValueError):
        ttl_hours = 168
    return (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()


def _state_from_row(row: dict[str, Any]) -> AgentRunState:
    payload = _loads(row.get("state_json"), {})
    payload.update(
        run_id=row["run_id"],
        revision=int(row["revision"]),
        durability_mode=row["durability_mode"],
        status=row["status"],
        objective=row["objective"],
        current_step_id=row.get("current_step_id"),
        plan=_loads(row.get("plan_json"), None),
        completion=_loads(row.get("completion_json"), None),
        budget=_loads(row.get("budget_json"), {}),
        used_budget=_loads(row.get("used_budget_json"), {}),
        context_refs=_loads(row.get("context_refs_json"), {}),
        input_artifact_refs=_loads(row.get("input_artifact_refs_json"), []),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    return AgentRunState.model_validate(payload)


def _public_run(row: dict[str, Any]) -> dict[str, Any]:
    state = _state_from_row(row)
    return {
        "run_id": row["run_id"],
        "agent_type": row["agent_type"],
        "actor_id": row.get("actor_id"),
        "student_id": row.get("student_id"),
        "session_id": row.get("session_id"),
        "parent_run_id": row.get("parent_run_id"),
        "durability_mode": row["durability_mode"],
        "status": row["status"],
        "revision": int(row["revision"]),
        "current_step_id": row.get("current_step_id"),
        "objective": row["objective"],
        "state": state.model_dump(),
        "completion": state.completion.model_dump() if state.completion else None,
        "config_version": row["config_version"],
        "trace_id": row["trace_id"],
        "last_event_sequence": int(row["last_event_sequence"]),
        "expires_at": row.get("expires_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row.get("finished_at"),
    }


def get_run(run_id: str) -> dict[str, Any]:
    ensure_runtime_tables()
    with get_connection() as conn:
        row = conn.execute(text("SELECT * FROM agent_runs WHERE run_id=:run_id"), {"run_id": run_id}).mappings().first()
    if not row:
        raise RunNotFoundError("agent run not found")
    return _public_run(dict(row))


def get_run_state(run_id: str) -> AgentRunState:
    return AgentRunState.model_validate(get_run(run_id)["state"])


def create_run(
    context: AgentContext,
    *,
    objective: str,
    budget: AgentBudget | None = None,
    idempotency_key: str | None = None,
    parent_run_id: str | None = None,
    expires_at: str | None = None,
    runtime_mode: str = "active",
) -> dict[str, Any]:
    if context.durability_mode == "trace_only":
        raise ValueError("trace_only calls must not be persisted as agent_runs")
    ensure_runtime_tables()
    budget = budget or AgentBudget()
    if runtime_mode not in {"control", "shadow", "active"}:
        raise ValueError("runtime_mode must be control, shadow or active")
    scope = _idempotency_scope(context)
    if idempotency_key:
        with get_connection() as conn:
            existing = conn.execute(
                text("SELECT * FROM agent_runs WHERE idempotency_scope=:scope AND idempotency_key=:key"),
                {"scope": scope, "key": idempotency_key},
            ).mappings().first()
        if existing:
            return _public_run(dict(existing))

    now = utc_now_iso()
    if context.durability_mode == "resumable" and expires_at is None:
        expires_at = _default_resumable_expiry()
    clean_objective = " ".join(str(objective).split())[:500] or f"{context.agent_type} request"
    state = AgentRunState(
        run_id=context.run_id,
        durability_mode=context.durability_mode,
        status="received",
        objective=clean_objective,
        budget=budget,
        context_refs={
            "session_id": context.session_id,
            "source_feature": context.source_feature,
            "source_session_id": context.source_session_id,
            "locale": context.locale,
            "data_scope": context.data_scope,
            "runtime_mode": runtime_mode,
            "rollout_bucket": context.rollout_bucket,
        },
        created_at=now,
        updated_at=now,
    )
    event_id = f"evt_{uuid4().hex}"
    try:
        with get_connection() as conn:
            conn.execute(text("""INSERT INTO agent_runs (
                run_id, agent_type, actor_id, student_id, session_id, parent_run_id,
                durability_mode, status, revision, current_step_id, objective,
                context_refs_json, input_artifact_refs_json, plan_json, state_json,
                completion_json, budget_json, used_budget_json, config_version,
                trace_id, idempotency_scope, idempotency_key, last_event_sequence,
                expires_at, created_at, updated_at, finished_at
            ) VALUES (
                :run_id, :agent_type, :actor_id, :student_id, :session_id, :parent_run_id,
                :durability_mode, 'received', 0, NULL, :objective,
                :context_refs_json, '[]', NULL, :state_json,
                NULL, :budget_json, '{}', :config_version,
                :trace_id, :idempotency_scope, :idempotency_key, 1,
                :expires_at, :created_at, :updated_at, NULL
            )"""), {
                "run_id": context.run_id,
                "agent_type": context.agent_type,
                "actor_id": context.actor_id,
                "student_id": context.student_id,
                "session_id": context.session_id,
                "parent_run_id": parent_run_id,
                "durability_mode": context.durability_mode,
                "objective": clean_objective,
                "context_refs_json": json.dumps(state.context_refs, ensure_ascii=False),
                "state_json": json.dumps(state.model_dump(), ensure_ascii=False),
                "budget_json": json.dumps(budget.model_dump(), ensure_ascii=False),
                "config_version": context.config_version,
                "trace_id": context.trace_id,
                "idempotency_scope": scope,
                "idempotency_key": idempotency_key,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            })
            conn.execute(text("""INSERT INTO agent_run_events (
                event_id, run_id, sequence, event_type, step_id, operation, status,
                public_payload_json, internal_metadata_json, data_scope, created_at
            ) VALUES (
                :event_id, :run_id, 1, 'run_started', NULL, NULL, 'received',
                :public_payload_json, '{}', :data_scope, :created_at
            )"""), {
                "event_id": event_id,
                "run_id": context.run_id,
                "public_payload_json": json.dumps({"agent_type": context.agent_type, "durability_mode": context.durability_mode}, ensure_ascii=False),
                "data_scope": context.data_scope,
                "created_at": now,
            })
    except Exception:
        if idempotency_key:
            with get_connection() as conn:
                existing = conn.execute(
                    text("SELECT * FROM agent_runs WHERE idempotency_scope=:scope AND idempotency_key=:key"),
                    {"scope": scope, "key": idempotency_key},
                ).mappings().first()
            if existing:
                return _public_run(dict(existing))
        raise
    return get_run(context.run_id)


def _append_run_event(
    run_id: str,
    *,
    expected_revision: int,
    event_type: str,
    public_payload: dict[str, Any] | None = None,
    internal_metadata: dict[str, Any] | None = None,
    next_status: RunStatus | None = None,
    step_id: str | None = None,
    operation: str | None = None,
    current_step_id: str | None = None,
    plan: dict[str, Any] | None = None,
    step_results: dict[str, Any] | None = None,
    completion: CompletionDecision | None = None,
    used_budget: dict[str, int | float] | None = None,
    input_artifact_refs: list[str] | None = None,
) -> RuntimeEvent:
    ensure_runtime_tables()
    now = utc_now_iso()
    with get_connection() as conn:
        row = conn.execute(text("SELECT * FROM agent_runs WHERE run_id=:run_id"), {"run_id": run_id}).mappings().first()
        if not row:
            raise RunNotFoundError("agent run not found")
        current = dict(row)
        current_revision = int(current["revision"])
        if current_revision != expected_revision:
            raise StaleRevisionError(run_id, expected_revision)
        if current["status"] in TERMINAL_STATUSES:
            raise ValueError("terminal agent run cannot accept new events")
        status = str(next_status or current["status"])
        if next_status is not None and status != current["status"]:
            validate_transition(str(current["status"]), status)

        state = _state_from_row(current)
        payload = state.model_dump()
        payload.update(
            revision=current_revision + 1,
            status=status,
            current_step_id=current_step_id if current_step_id is not None else state.current_step_id,
            updated_at=now,
        )
        if plan is not None:
            payload["plan"] = plan
        if step_results is not None:
            payload["step_results"] = step_results
        if completion is not None:
            payload["completion"] = completion.model_dump()
        if used_budget is not None:
            payload["used_budget"] = used_budget
        if input_artifact_refs is not None:
            payload["input_artifact_refs"] = input_artifact_refs
        next_state = AgentRunState.model_validate(payload)

        sequence = int(current["last_event_sequence"]) + 1
        finished_at = now if status in TERMINAL_STATUSES else None
        update_result = conn.execute(text("""UPDATE agent_runs SET
            status=:status, revision=revision+1, current_step_id=:current_step_id,
            plan_json=:plan_json, state_json=:state_json, completion_json=:completion_json,
            used_budget_json=:used_budget_json, input_artifact_refs_json=:input_artifact_refs_json,
            last_event_sequence=:sequence, updated_at=:updated_at,
            finished_at=COALESCE(:finished_at, finished_at)
            WHERE run_id=:run_id AND revision=:expected_revision
        """), {
            "status": status,
            "current_step_id": next_state.current_step_id,
            "plan_json": json.dumps(next_state.plan.model_dump(), ensure_ascii=False) if next_state.plan else None,
            "state_json": json.dumps(next_state.model_dump(), ensure_ascii=False),
            "completion_json": json.dumps(next_state.completion.model_dump(), ensure_ascii=False) if next_state.completion else None,
            "used_budget_json": json.dumps(next_state.used_budget, ensure_ascii=False),
            "input_artifact_refs_json": json.dumps(next_state.input_artifact_refs, ensure_ascii=False),
            "sequence": sequence,
            "updated_at": now,
            "finished_at": finished_at,
            "run_id": run_id,
            "expected_revision": expected_revision,
        })
        if update_result.rowcount != 1:
            raise StaleRevisionError(run_id, expected_revision)
        safe_payload = sanitize_public_payload(public_payload or {})
        conn.execute(text("""INSERT INTO agent_run_events (
            event_id, run_id, sequence, event_type, step_id, operation, status,
            public_payload_json, internal_metadata_json, data_scope, created_at
        ) VALUES (
            :event_id, :run_id, :sequence, :event_type, :step_id, :operation, :status,
            :public_payload_json, :internal_metadata_json, :data_scope, :created_at
        )"""), {
            "event_id": f"evt_{uuid4().hex}",
            "run_id": run_id,
            "sequence": sequence,
            "event_type": event_type,
            "step_id": step_id,
            "operation": operation,
            "status": status,
            "public_payload_json": json.dumps(safe_payload, ensure_ascii=False),
            "internal_metadata_json": json.dumps(internal_metadata or {}, ensure_ascii=False),
            "data_scope": str(state.context_refs.get("data_scope") or "runtime"),
            "created_at": now,
        })
    return RuntimeEvent(
        run_id=run_id,
        trace_id=str(current["trace_id"]),
        sequence=sequence,
        event=event_type,
        timestamp=now,
        data=safe_payload,
    )


def append_run_event(
    run_id: str,
    *,
    expected_revision: int,
    event_type: str,
    public_payload: dict[str, Any] | None = None,
    internal_metadata: dict[str, Any] | None = None,
    next_status: RunStatus | None = None,
    step_id: str | None = None,
    operation: str | None = None,
    current_step_id: str | None = None,
    plan: dict[str, Any] | None = None,
    step_results: dict[str, Any] | None = None,
    completion: CompletionDecision | None = None,
    used_budget: dict[str, int | float] | None = None,
    input_artifact_refs: list[str] | None = None,
) -> RuntimeEvent:
    try:
        return _append_run_event(
            run_id,
            expected_revision=expected_revision,
            event_type=event_type,
            public_payload=public_payload,
            internal_metadata=internal_metadata,
            next_status=next_status,
            step_id=step_id,
            operation=operation,
            current_step_id=current_step_id,
            plan=plan,
            step_results=step_results,
            completion=completion,
            used_budget=used_budget,
            input_artifact_refs=input_artifact_refs,
        )
    except InvalidTransitionError as exc:
        try:
            from security.audit_log import record_audit_event

            record_audit_event(
                actor_id=None,
                action="agent_runtime.invalid_transition",
                resource_type="agent_run",
                resource_id=run_id,
                success=False,
                metadata={
                    "current_status": exc.current_status,
                    "next_status": exc.next_status,
                    "event_type": event_type,
                    "expected_revision": expected_revision,
                },
            )
        except Exception:
            pass
        raise


def list_run_events(run_id: str, *, after: int = 0, limit: int = 100) -> list[RuntimeEvent]:
    ensure_runtime_tables()
    limit = max(1, min(int(limit), 500))
    with get_connection() as conn:
        run = conn.execute(text("SELECT trace_id FROM agent_runs WHERE run_id=:run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            raise RunNotFoundError("agent run not found")
        rows = conn.execute(text("""SELECT sequence, event_type, public_payload_json, created_at
            FROM agent_run_events WHERE run_id=:run_id AND sequence>:after
            ORDER BY sequence ASC LIMIT :limit"""), {"run_id": run_id, "after": max(after, 0), "limit": limit}).mappings().all()
    return [RuntimeEvent(
        run_id=run_id,
        trace_id=str(run["trace_id"]),
        sequence=int(row["sequence"]),
        event=str(row["event_type"]),
        timestamp=str(row["created_at"]),
        data=_loads(row["public_payload_json"], {}),
    ) for row in rows]


def cancel_run(run_id: str, *, expected_revision: int) -> dict[str, Any]:
    from agent_runtime.completion import CompletionEvaluator

    run = get_run(run_id)
    state = AgentRunState.model_validate(run["state"])
    decision = CompletionEvaluator().from_outcome(
        status="cancelled",
        completed_steps=sum(result.status == "completed" for result in state.step_results.values()),
        total_steps=len(state.plan.steps) if state.plan else len(state.step_results),
        verification_status="not_required",
        reason_codes=["cancel_requested"],
    )
    append_run_event(
        run_id,
        expected_revision=expected_revision,
        event_type="run_cancelled",
        public_payload={"completion": decision.model_dump()},
        next_status="cancelled",
        completion=decision,
    )
    return get_run(run_id)
