"""语文功能路由：作文批改、一次修订与同一 Run 的教师复核。"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_runtime.artifact_store import create_artifact, list_run_artifacts
from agent_runtime.checkpoint_store import prune_terminal_checkpoints, save_checkpoint
from agent_runtime.completion import CompletionEvaluator
from agent_runtime.context import RuntimeV2Settings
from agent_runtime.event_store import get_run
from agent_runtime.lifecycle import RuntimeRunController
from agent_runtime.models import (
    AgentBudget,
    AgentContext,
    AgentPlan,
    AgentStep,
    default_data_scope,
)
from security.audit_log import record_audit_event
from security.auth import Actor, assert_student_access, assert_teacher_student_access, require_auth
from tracing import current_trace_id, trace_context
from ._shared import require_teacher_actor, trace_meta

router = APIRouter(prefix="/api/chinese", tags=["chinese"])


class EssayRequest(BaseModel):
    essay: str = Field(min_length=1, max_length=30_000)
    student_id: str = Field(min_length=1, max_length=128)


class EssayReviewRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=96)
    approved: bool
    teacher_comments: str = Field(default="", max_length=2000)
    decision: str = Field(default="approved", pattern="^(approved|edited|rejected)$")
    score_override: float | None = Field(default=None, ge=0, le=100)
    expected_revision: int | None = Field(default=None, ge=0)


class BatchEssayRequest(BaseModel):
    essays: list[dict]
    class_id: str | None = None


def _essay_plan(run_id: str) -> AgentPlan:
    return AgentPlan(
        plan_id=f"plan_{uuid4().hex}",
        objective="完成作文结构化评分、审校与必要的一次修订",
        strategy="subgraph",
        generated_by="template",
        planner_version="essay-grader-v2",
        steps=[
            AgentStep(step_id="grade", kind="generation", operation="essay.grade_structured", side_effect="external_call", risk_level="low", timeout_seconds=30),
            AgentStep(step_id="critic", kind="verification", operation="essay.critic", depends_on=["grade"], side_effect="external_call", risk_level="low", timeout_seconds=20),
            AgentStep(step_id="revise", kind="generation", operation="essay.revise", depends_on=["critic"], side_effect="external_call", risk_level="low", timeout_seconds=30),
            AgentStep(step_id="finalize", kind="control", operation="essay.finalize", depends_on=["revise"], side_effect="none", risk_level="low"),
        ],
    )


def _artifact_by_type(artifacts: list[dict], artifact_type: str) -> dict | None:
    return next((artifact for artifact in reversed(artifacts) if artifact.get("artifact_type") == artifact_type), None)


@router.post("/essay/grade")
async def grade_essay(req: EssayRequest, actor: Actor = Depends(require_auth)):
    from agents.essay_grader import EssayState, build_grader_graph
    from security.prompt_injection import check_user_input

    if actor.role == "teacher":
        assert_teacher_student_access(actor, req.student_id)
    else:
        assert_student_access(actor, req.student_id)
    check_user_input(req.essay)
    run_id = f"run_{uuid4().hex}"
    trace_id = current_trace_id() or f"trace_{uuid4().hex}"
    runtime_settings = RuntimeV2Settings.from_env()
    runtime_active, _ = runtime_settings.rollout_decision("essay_grader", str(actor.actor_id or req.student_id))
    review_resume_enabled = runtime_active and runtime_settings.resumable_ready
    context = AgentContext(
        run_id=run_id,
        agent_type="essay_grader",
        actor_id=actor.actor_id,
        actor_role=actor.role,
        student_id=req.student_id,
        session_id=run_id,
        trace_id=trace_id,
        data_scope=default_data_scope(),
        durability_mode="resumable" if review_resume_enabled else "observable",
        config_version=runtime_settings.config_version,
    )
    budget = AgentBudget(max_steps=4, max_tool_calls=0, max_llm_calls=3, max_replans=1, max_wall_time_ms=120_000)
    controller, _ = RuntimeRunController.create(
        context,
        objective="作文结构化批改",
        budget=budget,
        policy_caller="chinese_api",
        idempotency_key=None,
        runtime_mode=("shadow" if runtime_settings.shadow_mode else "active") if runtime_active else "control",
    )
    input_artifact = create_artifact(
        run_id,
        owner_actor_id=actor.actor_id,
        student_id=req.student_id,
        artifact_type="input",
        sensitivity="student_content",
        content={"essay": req.essay},
    )
    plan = _essay_plan(run_id)
    controller.route({"agent_type": "essay_grader"}, input_artifact_refs=[input_artifact["artifact_id"]])
    controller.admit_plan(plan)
    controller.start_step("grade", "essay.grade_structured")

    with trace_context(
        name="POST /api/chinese/essay/grade",
        metadata=trace_meta("essay_grader", "/api/chinese/essay/grade", student_id=req.student_id, run_id=run_id),
        user_id=req.student_id,
    ):
        graph = build_grader_graph()
        state: EssayState = {
            "essay": req.essay,
            "student_id": req.student_id,
            "run_id": run_id,
            "draft_score": {},
            "draft_comments": "",
            "final_score": {},
            "final_comments": "",
            "revision_count": 0,
            "critique_approved": False,
            "needs_human_review": False,
            "review_reason": None,
        }
        result = await graph.ainvoke(state)

    structured_artifact = create_artifact(
        run_id,
        owner_actor_id=actor.actor_id,
        student_id=req.student_id,
        artifact_type="structured_output",
        sensitivity="student_content",
        content={
            "draft_score": result.get("draft_score") or {},
            "draft_comments": result.get("draft_comments") or "",
            "final_score": result.get("final_score") or {},
            "final_comments": result.get("final_comments") or "",
            "revision_count": int(result.get("revision_count") or 0),
            "review_reason": result.get("review_reason"),
        },
    )
    refs = [input_artifact["artifact_id"], structured_artifact["artifact_id"]]
    if result.get("needs_human_review") and review_resume_enabled:
        controller.wait_for_input(
            {
                "reason": result.get("review_reason") or "critic_disagreement",
                "draft_score": result.get("draft_score") or {},
                "revision_count": int(result.get("revision_count") or 0),
            },
            step_id="finalize",
            input_artifact_refs=refs,
        )
        waiting = get_run(run_id)
        save_checkpoint(
            run_id,
            revision=waiting["revision"],
            node_name="waiting_human_review",
            state={"structured_output_artifact_id": structured_artifact["artifact_id"]},
        )
        completion_status = "waiting_input"
    elif result.get("needs_human_review"):
        controller.event("verification_result", public_payload={"status": "partial", "reason": "human_review_resume_disabled"}, next_status="verifying", input_artifact_refs=refs)
        decision = CompletionEvaluator().from_outcome(
            status="partial",
            completed_steps=3,
            total_steps=4,
            verification_status="partial",
            reason_codes=["human_review_resume_disabled"],
            deliverable_refs=[structured_artifact["artifact_id"]],
            unresolved_items=["teacher_review"],
        )
        controller.event("run_completed", public_payload={"completion": decision.model_dump()}, next_status="partial", completion=decision)
        completion_status = "partial"
    else:
        controller.event("verification_result", public_payload={"status": "verified"}, next_status="verifying", input_artifact_refs=refs)
        decision = CompletionEvaluator().from_outcome(
            status="completed",
            completed_steps=4,
            total_steps=4,
            verification_status="not_required",
            reason_codes=["rubric_and_critic_passed"],
            deliverable_refs=[structured_artifact["artifact_id"]],
        )
        controller.event("run_completed", public_payload={"completion": decision.model_dump(), "score": result.get("final_score") or {}}, next_status="completed", completion=decision)
        completion_status = "completed"

    comments = result.get("final_comments") or result.get("draft_comments") or ""
    score = result.get("final_score") or result.get("draft_score") or {}
    return {
        "student_id": req.student_id,
        "session_id": run_id,
        "run_id": run_id,
        "run_revision": get_run(run_id)["revision"],
        "score": score,
        "comments": comments,
        "completion_status": completion_status,
        "needs_human_review": bool(result.get("needs_human_review")),
        "review_reason": result.get("review_reason"),
        "review_resume_enabled": review_resume_enabled,
    }


@router.post("/essay/review-result")
async def submit_essay_review(req: EssayReviewRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        run = get_run(req.session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="作文批改 Run 不存在") from exc
    if run["agent_type"] != "essay_grader" or run["status"] != "waiting_input":
        raise HTTPException(status_code=409, detail="该作文当前不等待教师复核")
    if run.get("student_id"):
        assert_teacher_student_access(actor, str(run["student_id"]), resource_owner_id=run.get("actor_id"))
    expected_revision = req.expected_revision if req.expected_revision is not None else int(run["revision"])
    if expected_revision != int(run["revision"]):
        raise HTTPException(status_code=409, detail="Run revision 已变化，请刷新后重试")
    artifacts = list_run_artifacts(req.session_id, actor_id=actor.actor_id, actor_role=actor.role)
    structured = _artifact_by_type(artifacts, "structured_output")
    if structured is None:
        raise HTTPException(status_code=409, detail="作文评分产物缺失")
    draft = structured["content"]
    final_score = dict(draft.get("draft_score") or {})
    if req.score_override is not None:
        final_score["teacher_total_score"] = round(float(req.score_override), 1)
    final_comments = req.teacher_comments.strip() or str(draft.get("draft_comments") or "")
    output_artifact = create_artifact(
        req.session_id,
        owner_actor_id=run.get("actor_id"),
        student_id=run.get("student_id"),
        artifact_type="final_output",
        sensitivity="student_content",
        content={
            "decision": req.decision,
            "approved": req.approved,
            "final_score": final_score,
            "final_comments": final_comments,
            "teacher_id": actor.actor_id,
        },
    )
    controller = RuntimeRunController.attach(req.session_id, policy_caller="chinese_api")
    controller.start_step("finalize", "essay.finalize", review_step_id="teacher_review", expected_revision=expected_revision)
    controller.event("verification_result", public_payload={"status": "teacher_reviewed", "decision": req.decision}, next_status="verifying")
    terminal_status = "completed" if req.approved and req.decision != "rejected" else "partial"
    decision = CompletionEvaluator().from_outcome(
        status=terminal_status,
        completed_steps=4 if terminal_status == "completed" else 3,
        total_steps=4,
        verification_status="not_required",
        reason_codes=[f"teacher_review_{req.decision}"],
        deliverable_refs=[output_artifact["artifact_id"]],
        unresolved_items=[] if terminal_status == "completed" else ["teacher_rejected"],
    )
    controller.event(
        "run_completed",
        public_payload={"completion": decision.model_dump(), "score": final_score},
        next_status=terminal_status,
        completion=decision,
    )
    prune_terminal_checkpoints(req.session_id)
    record_audit_event(
        actor_id=actor.actor_id,
        action="teacher.essay_review",
        resource_type="essay",
        resource_id=req.session_id,
        metadata={"decision": req.decision, "score_override": req.score_override, "student_id": run.get("student_id")},
    )
    return {
        "status": terminal_status,
        "decision": req.decision,
        "run_id": req.session_id,
        "run_revision": get_run(req.session_id)["revision"],
        "score": final_score,
        "comments": final_comments,
    }


@router.get("/essay/review-stats")
async def essay_review_stats(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from security.audit_log import list_audit_events

    events = list_audit_events(action="teacher.essay_review", limit=200)
    counts = {"approved": 0, "edited": 0, "rejected": 0}
    for event in events:
        decision = (event.get("metadata") or {}).get("decision", "approved")
        if decision in counts:
            counts[decision] += 1
    return {"total": sum(counts.values()), **counts}


@router.post("/essay/grade/batch")
async def batch_grade_essays(req: BatchEssayRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    if len(req.essays) > 50:
        raise HTTPException(status_code=400, detail="单次最多批改 50 篇作文")
    from security.prompt_injection import check_user_input
    from services.batch_essay_service import batch_grade, compute_summary

    for item in req.essays:
        check_user_input(item.get("essay", ""))
    results = await batch_grade(req.essays)
    return {"results": results, "summary": compute_summary(results)}
