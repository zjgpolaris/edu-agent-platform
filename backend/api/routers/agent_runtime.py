"""Owner-scoped query, replay, resume and cancellation for persisted Agent runs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent_runtime.event_store import (
    RunNotFoundError,
    StaleRevisionError,
    cancel_run,
    get_run,
    list_run_events,
)
from agent_runtime.models import ResumeSignal
from agent_runtime.recovery import recover_stale_runs
from security.auth import Actor, assert_teacher_student_access, auth_required, require_auth

router = APIRouter(tags=["agent-runtime"])


class RunRevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class RunResumeRequest(RunRevisionRequest):
    correlation_key: str = Field(min_length=1, max_length=200)
    input_patch: dict = Field(default_factory=dict)


class RunConfirmRequest(RunRevisionRequest):
    correlation_key: str = Field(min_length=1, max_length=200)
    confirmation_token: str = Field(min_length=1, max_length=4096)


class RecoverRunsRequest(BaseModel):
    updated_before: str


def _client_run_payload(run: dict) -> dict:
    payload = dict(run)
    payload.pop("actor_id", None)
    payload["run_revision"] = int(run["revision"])
    payload["event_cursor"] = int(run.get("last_event_sequence") or 0)
    return payload


def _client_action_payload(result: dict, run: dict) -> dict:
    return {
        **result,
        "run_id": str(run["run_id"]),
        "run_revision": int(run["revision"]),
        "event_cursor": int(run.get("last_event_sequence") or 0),
        "status": str(run["status"]),
    }


def _authorize_run(actor: Actor, run: dict) -> None:
    if run.get("student_id"):
        student_id = str(run["student_id"])
        if not auth_required() or actor.role == "admin":
            return
        if actor.role == "student" and actor.actor_id == student_id:
            return
        if actor.role == "teacher":
            assert_teacher_student_access(actor, student_id, resource_owner_id=run.get("actor_id"))
            return
        raise HTTPException(status_code=403, detail="无权访问该 Agent Run。")
    if not auth_required():
        return
    if actor.role == "admin" or (actor.actor_id and actor.actor_id == run.get("actor_id")):
        return
    raise HTTPException(status_code=403, detail="无权访问该 Agent Run。")


def _load_authorized_run(run_id: str, actor: Actor) -> dict:
    try:
        run = get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent Run 不存在。") from exc
    _authorize_run(actor, run)
    return run


@router.get("/api/agent-runs/{run_id}")
async def get_agent_run(run_id: str, actor: Actor = Depends(require_auth)):
    run = _load_authorized_run(run_id, actor)
    return _client_run_payload(run)


@router.get("/api/agent-runs/{run_id}/events")
async def get_agent_run_events(
    run_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_auth),
):
    run = _load_authorized_run(run_id, actor)
    events = list_run_events(run_id, after=after, limit=limit)
    return {
        "run_id": run_id,
        "run_revision": int(run["revision"]),
        "events": [event.model_dump() for event in events],
        "event_cursor": events[-1].sequence if events else after,
        "status": run["status"],
        "terminal": run["status"] in {"completed", "partial", "failed", "cancelled"},
    }


@router.post("/api/agent-runs/{run_id}/cancel")
async def cancel_agent_run(run_id: str, req: RunRevisionRequest, actor: Actor = Depends(require_auth)):
    _load_authorized_run(run_id, actor)
    try:
        run = cancel_run(run_id, expected_revision=req.expected_revision)
    except StaleRevisionError as exc:
        raise HTTPException(status_code=409, detail="Run revision 已变化，请刷新后重试。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if str(run.get("agent_type") or "") == "learning_assistant":
        from services.learning_assistant_session_service import update_message_for_runtime_run

        update_message_for_runtime_run(
            run_id,
            session_id=run.get("session_id"),
            status="cancelled",
            run_revision=int(run["revision"]),
            event_cursor=int(run.get("last_event_sequence") or 0),
            content="已取消高风险工具确认。",
        )
    return _client_run_payload(run)


@router.post("/api/agent-runs/{run_id}/confirmation-token")
async def refresh_agent_run_confirmation(
    run_id: str,
    req: RunRevisionRequest,
    actor: Actor = Depends(require_auth),
):
    run = _load_authorized_run(run_id, actor)
    if int(run["revision"]) != req.expected_revision:
        raise HTTPException(status_code=409, detail="Run revision 已变化，请刷新后重试。")
    from agent_runtime.resume_registry import issue_learning_assistant_confirmation

    try:
        return issue_learning_assistant_confirmation(run, actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/agent-runs/{run_id}/resume")
async def resume_agent_run(run_id: str, req: RunResumeRequest, actor: Actor = Depends(require_auth)):
    run = _load_authorized_run(run_id, actor)
    if run["status"] not in {"waiting_input", "waiting_confirmation"}:
        raise HTTPException(status_code=409, detail="当前 Run 不处于等待状态。")
    # Product adapters own resume execution. A generic API must never let a
    # client choose an arbitrary agent or operation.
    from agent_runtime.resume_registry import dispatch_resume

    signal = ResumeSignal(
        expected_revision=req.expected_revision,
        kind="input",
        correlation_key=req.correlation_key,
        input_patch=req.input_patch,
    )
    try:
        result = await dispatch_resume(run, signal, actor)
        return _client_action_payload(result, get_run(run_id))
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="该 Agent 尚未注册可恢复处理器。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/agent-runs/{run_id}/confirm")
async def confirm_agent_run(run_id: str, req: RunConfirmRequest, actor: Actor = Depends(require_auth)):
    run = _load_authorized_run(run_id, actor)
    if run["status"] != "waiting_confirmation":
        raise HTTPException(status_code=409, detail="当前 Run 不等待确认。")
    from agent_runtime.resume_registry import dispatch_resume

    signal = ResumeSignal(
        expected_revision=req.expected_revision,
        kind="confirmation",
        correlation_key=req.correlation_key,
        confirmation_token=req.confirmation_token,
    )
    try:
        result = await dispatch_resume(run, signal, actor)
        return _client_action_payload(result, get_run(run_id))
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="该 Agent 尚未注册可恢复处理器。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/admin/agent-runs/recover")
async def recover_agent_runs(req: RecoverRunsRequest, actor: Actor = Depends(require_auth)):
    if auth_required() and actor.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可恢复 Agent Run。")
    return recover_stale_runs(updated_before=req.updated_before)


@router.get("/api/admin/agent-runtime/readiness")
async def get_agent_runtime_readiness(actor: Actor = Depends(require_auth)):
    if auth_required() and actor.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可检查 Agent Runtime readiness。")
    from agent_runtime.readiness import runtime_schema_readiness

    return runtime_schema_readiness()


@router.get("/api/admin/agent-runtime/rollout-readiness")
async def get_agent_runtime_rollout_readiness(
    agent_type: str = Query(min_length=1, max_length=80),
    window_hours: int = Query(default=24, ge=1, le=24 * 31),
    minimum_terminal_runs: int = Query(default=100, ge=1, le=100_000),
    actor: Actor = Depends(require_auth),
):
    if auth_required() and actor.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可检查 Agent Runtime rollout readiness。")
    from agent_runtime.rollout_gate import build_rollout_readiness

    return build_rollout_readiness(
        agent_type=agent_type,
        window_hours=window_hours,
        minimum_terminal_runs=minimum_terminal_runs,
    )
