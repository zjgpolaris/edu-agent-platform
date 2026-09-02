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
from security.auth import Actor, assert_teacher_student_access, auth_required, require_admin, require_auth

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


class AutoTutorCanarySnapshotRequest(BaseModel):
    expected_commit: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    expected_config_version: str = Field(min_length=1, max_length=120)
    window_start: str = Field(min_length=10, max_length=80)
    window_end: str = Field(min_length=10, max_length=80)
    minimum_control: int = Field(default=100, ge=1, le=100_000)
    minimum_graph: int = Field(default=100, ge=1, le=100_000)
    minimum_rollback_control: int = Field(default=20, ge=1, le=100_000)


class AutoTutorCanaryEvidenceRequest(BaseModel):
    evidence: dict


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
async def recover_agent_runs(req: RecoverRunsRequest, actor: Actor = Depends(require_admin)):
    return recover_stale_runs(updated_before=req.updated_before)


@router.get("/api/admin/agent-runtime/readiness")
async def get_agent_runtime_readiness(actor: Actor = Depends(require_admin)):
    from agent_runtime.readiness import runtime_schema_readiness

    return runtime_schema_readiness()


@router.get("/api/admin/agent-runtime/rollout-readiness")
async def get_agent_runtime_rollout_readiness(
    agent_type: str = Query(min_length=1, max_length=80),
    window_hours: int = Query(default=24, ge=1, le=24 * 31),
    minimum_terminal_runs: int = Query(default=100, ge=1, le=100_000),
    actor: Actor = Depends(require_admin),
):
    from agent_runtime.rollout_gate import build_rollout_readiness

    return build_rollout_readiness(
        agent_type=agent_type,
        window_hours=window_hours,
        minimum_terminal_runs=minimum_terminal_runs,
    )


@router.get("/api/admin/agent-runtime/rollout-status")
async def get_agent_runtime_rollout_status(
    agent_type: str = Query(min_length=1, max_length=80),
    window_hours: int = Query(default=168, ge=1, le=24 * 31),
    minimum_samples: int = Query(default=100, ge=1, le=100_000),
    actor: Actor = Depends(require_admin),
):
    from agent_runtime.rollout_status import build_rollout_status

    if minimum_samples < 100:
        from deployment import deployment_environment

        if deployment_environment() == "production":
            raise HTTPException(status_code=400, detail="生产 rollout 最少需要 100 个样本。")
    try:
        return build_rollout_status(
            agent_type=agent_type,
            window_hours=window_hours,
            minimum_samples=minimum_samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/admin/agent-runtime/autotutor-canary/verification")
async def get_autotutor_canary_verification(
    expected_commit: str | None = Query(default=None, min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$"),
    expected_config_version: str | None = Query(default=None, min_length=1, max_length=120),
    window_start: str | None = Query(default=None, min_length=10, max_length=80),
    window_end: str | None = Query(default=None, min_length=10, max_length=80),
    minimum_control: int = Query(default=100, ge=1, le=100_000),
    minimum_graph: int = Query(default=100, ge=1, le=100_000),
    minimum_rollback_control: int = Query(default=20, ge=1, le=100_000),
    actor: Actor = Depends(require_admin),
):
    from agent_runtime.autotutor_canary_verification import build_autotutor_canary_verification

    try:
        return build_autotutor_canary_verification(
            expected_commit=expected_commit,
            expected_config_version=expected_config_version,
            window_start=window_start,
            window_end=window_end,
            minimum_control=minimum_control,
            minimum_graph=minimum_graph,
            minimum_rollback_control=minimum_rollback_control,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/admin/agent-runtime/autotutor-canary/snapshots")
async def create_autotutor_canary_snapshot(
    req: AutoTutorCanarySnapshotRequest,
    actor: Actor = Depends(require_admin),
):
    from agent_runtime.autotutor_canary_verification import build_autotutor_canary_snapshot

    try:
        return build_autotutor_canary_snapshot(**req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/admin/agent-runtime/autotutor-canary/evidence")
async def get_autotutor_canary_evidence(
    include_payload: bool = Query(default=False),
    actor: Actor = Depends(require_admin),
):
    from agent_runtime.evidence_store import load_release_evidence
    from agents.autotutor_execution import AutoTutorExecutorSettings
    from deployment import deployed_commit, deployment_environment

    settings = AutoTutorExecutorSettings.from_env()
    evidence = load_release_evidence(
        agent_type="auto_tutor",
        config_version=settings.config_version,
        runtime_mode="active_canary",
        deployed_commit=deployed_commit(),
        environment=deployment_environment(),
    )
    if evidence is None:
        return {
            "present": False,
            "decision": None,
            "evidence_sha256": None,
            "candidate_sha256": None,
            "final_sha256": None,
            "v150_entry_ready": False,
            "v150_entry_blockers": ["final_evidence_missing", "rollback_not_verified"],
        }
    if include_payload:
        return {"present": True, "payload": evidence}
    final = bool(
        int(evidence.get("schema_version") or 0) == 4
        and evidence.get("evidence_stage") == "final"
        and evidence.get("decision") == "GO"
    )
    rollback_runtime = bool(settings.mode == "legacy" and settings.active_bps == 0 and not settings.kill_switch)
    v150_entry_ready = bool(final and rollback_runtime)
    v150_entry_blockers = []
    if not final:
        v150_entry_blockers.append("final_evidence_missing")
    if not rollback_runtime:
        v150_entry_blockers.append("rollback_not_verified")
    return {
        "present": True,
        "schema_version": evidence.get("schema_version"),
        "decision": evidence.get("decision"),
        "evidence_stage": evidence.get("evidence_stage"),
        "candidate_evidence_sha256": evidence.get("candidate_evidence_sha256"),
        "candidate_sha256": (
            evidence.get("candidate_evidence_sha256") if final else evidence.get("evidence_sha256")
        ),
        "final_sha256": evidence.get("evidence_sha256") if final else None,
        "evidence_sha256": evidence.get("evidence_sha256"),
        "generated_at": evidence.get("generated_at"),
        "deployed_commit": evidence.get("deployed_commit"),
        "config_version": evidence.get("config_version"),
        "environment": evidence.get("environment"),
        "window": evidence.get("window"),
        "drills": evidence.get("drills"),
        "v150_entry_ready": v150_entry_ready,
        "v150_entry_blockers": v150_entry_blockers,
    }


@router.post("/api/admin/agent-runtime/autotutor-canary/evidence")
async def persist_autotutor_canary_evidence(
    req: AutoTutorCanaryEvidenceRequest,
    actor: Actor = Depends(require_admin),
):
    from agent_runtime.evidence_store import save_release_evidence
    from agents.autotutor_execution import AutoTutorExecutorSettings
    from deployment import deployed_commit, deployment_environment

    try:
        settings = AutoTutorExecutorSettings.from_env()
        expected = {
            "agent_type": "auto_tutor",
            "runtime_mode": "active_canary",
            "deployed_commit": deployed_commit(),
            "config_version": settings.config_version,
            "environment": deployment_environment(),
        }
        if any(req.evidence.get(field) != value for field, value in expected.items()):
            raise ValueError("AutoTutor evidence does not match the current deployment")
        if int(req.evidence.get("schema_version") or 0) == 4 and (
            req.evidence.get("cohort_fingerprint") != settings.cohort_fingerprint
        ):
            raise ValueError("AutoTutor evidence cohort fingerprint does not match the current deployment")
        evidence = save_release_evidence(req.evidence)
    except (TypeError, ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "present": True,
        "decision": evidence.get("decision"),
        "evidence_sha256": evidence.get("evidence_sha256"),
    }
