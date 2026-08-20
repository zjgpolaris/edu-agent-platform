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
    run.pop("actor_id", None)
    return run


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
        "events": [event.model_dump() for event in events],
        "event_cursor": events[-1].sequence if events else after,
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
    run.pop("actor_id", None)
    return run


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
        return await dispatch_resume(run, signal, actor)
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
        return await dispatch_resume(run, signal, actor)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="该 Agent 尚未注册可恢复处理器。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/admin/agent-runs/recover")
async def recover_agent_runs(req: RecoverRunsRequest, actor: Actor = Depends(require_auth)):
    if auth_required() and actor.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可恢复 Agent Run。")
    return recover_stale_runs(updated_before=req.updated_before)
