from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from agent_runtime.models import ResumeSignal
from security.auth import Actor

ResumeHandler = Callable[[dict[str, Any], ResumeSignal, Actor], Awaitable[dict[str, Any]]]
_HANDLERS: dict[str, ResumeHandler] = {}


def issue_learning_assistant_confirmation(run: dict[str, Any], actor: Actor) -> dict[str, Any]:
    """Issue an ephemeral token for the current owner-scoped waiting step.

    Confirmation tokens are deliberately not persisted in run events or message
    metadata.  Reconnects obtain a replacement token bound to the current run
    revision through the authenticated Runtime API.
    """
    if str(run.get("agent_type") or "") != "learning_assistant":
        raise ValueError("该 Agent 不支持工具确认")
    if str(run.get("status") or "") != "waiting_confirmation":
        raise ValueError("当前 Run 不等待确认")

    from agent_runtime.capability_registry import build_default_registry
    from agent_runtime.models import AgentPlan
    from tools.base import ToolExecutionContext
    from tools.registry import issue_runtime_confirmation_token

    plan = AgentPlan.model_validate((run.get("state") or {}).get("plan"))
    step = next((item for item in plan.steps if item.step_id == (run.get("current_step_id") or "")), None)
    if step is None or len(plan.steps) != 1:
        raise ValueError("该确认只能恢复单一高风险步骤")
    binding = build_default_registry().resolve(step.operation, "learning_assistant")
    if binding.kind != "tool" or not binding.tool_name:
        raise ValueError("等待确认的步骤不是受控工具")
    token = issue_runtime_confirmation_token(
        binding.tool_name,
        step.input,
        ToolExecutionContext(
            actor_id=actor.actor_id,
            role=actor.role,
            student_id=run.get("student_id"),
            request_source="agent_runtime_confirmation_refresh",
            run_id=str(run["run_id"]),
            step_id=step.step_id,
            run_revision=int(run["revision"]),
        ),
    )
    return {
        "run_id": str(run["run_id"]),
        "run_revision": int(run["revision"]),
        "event_cursor": int(run.get("last_event_sequence") or 0),
        "step_id": step.step_id,
        "tool_name": binding.tool_name,
        "confirmation_token": token,
    }


async def _resume_auto_tutor(run: dict[str, Any], signal: ResumeSignal, actor: Actor) -> dict[str, Any]:
    if signal.kind != "input":
        raise ValueError("AutoTutor 仅接受答题恢复信号")
    answer = str(signal.input_patch.get("answer") or "").strip()
    if not answer or len(answer) > 8:
        raise ValueError("AutoTutor 恢复需要 1-8 个字符的 answer")
    from agents.auto_tutor import get_session, submit_answer
    from agent_runtime.context import rollout_eligibility
    from agent_runtime.models import default_data_scope

    session_id = str(run.get("session_id") or "")
    session = await asyncio.to_thread(get_session, session_id)
    if str(session.get("run_id") or "") != str(run["run_id"]):
        raise ValueError("AutoTutor session 与 run 不匹配")
    data_scope = default_data_scope()
    eligible, eligibility_reason = rollout_eligibility(actor, data_scope)
    return await asyncio.to_thread(
        submit_answer,
        session_id,
        answer,
        actor_id=actor.actor_id,
        actor_role=actor.role,
        account_status=actor.account_status,
        traffic_cohort=actor.traffic_cohort,
        data_scope=data_scope,
        rollout_eligible=eligible,
        eligibility_reason=eligibility_reason,
        expected_revision=int(session["revision"]),
        idempotency_key=signal.correlation_key,
    )


async def _resume_essay_grader(run: dict[str, Any], signal: ResumeSignal, actor: Actor) -> dict[str, Any]:
    if signal.kind != "input":
        raise ValueError("作文复核仅接受人工输入信号")
    from api.routers.chinese import EssayReviewRequest, submit_essay_review

    payload = signal.input_patch
    request = EssayReviewRequest(
        session_id=str(run["run_id"]),
        approved=bool(payload.get("approved")),
        teacher_comments=str(payload.get("teacher_comments") or ""),
        decision=str(payload.get("decision") or ("approved" if payload.get("approved") else "rejected")),
        score_override=payload.get("score_override"),
        expected_revision=signal.expected_revision,
    )
    return await submit_essay_review(request, actor)


async def _confirm_learning_assistant(run: dict[str, Any], signal: ResumeSignal, actor: Actor) -> dict[str, Any]:
    if signal.kind != "confirmation" or not signal.confirmation_token:
        raise ValueError("学习助手高风险步骤需要 confirmation token")
    from agent_runtime.artifact_store import create_artifact
    from agent_runtime.capability_registry import build_default_registry
    from agent_runtime.event_store import get_run
    from agent_runtime.lifecycle import RuntimeRunController
    from agent_runtime.completion import CompletionEvaluator
    from agent_runtime.models import AgentPlan, StepResult
    from tools.base import ToolExecutionContext
    from tools.registry import issue_runtime_confirmation_token, run_tool

    plan = AgentPlan.model_validate((run.get("state") or {}).get("plan"))
    step = next((item for item in plan.steps if item.step_id == (run.get("current_step_id") or "")), None)
    if step is None or len(plan.steps) != 1:
        raise ValueError("该确认只能恢复单一高风险步骤")
    binding = build_default_registry().resolve(step.operation, "learning_assistant")
    if binding.kind != "tool" or not binding.tool_name:
        raise ValueError("等待确认的步骤不是受控工具")

    controller = RuntimeRunController.attach(str(run["run_id"]), policy_caller="learning_assistant")
    controller.start_step(
        step.step_id,
        step.operation,
        expected_revision=signal.expected_revision,
        resume="confirmation",
    )
    result = run_tool(
        binding.tool_name,
        step.input,
        ToolExecutionContext(
            actor_id=actor.actor_id,
            role=actor.role,
            student_id=run.get("student_id"),
            confirmed=True,
            confirmation_token=signal.confirmation_token,
            request_source="agent_runtime_confirm",
            run_id=str(run["run_id"]),
            step_id=step.step_id,
            run_revision=signal.expected_revision,
            idempotency_key=step.idempotency_key,
            capability_operation=step.operation,
            data_scope=str(((run.get("state") or {}).get("context_refs") or {}).get("data_scope") or "runtime"),
        ),
    )
    if not result.ok:
        controller.wait_for_confirmation(
            {"step_id": step.step_id, "error": result.error.model_dump() if result.error else {}},
            step_id=step.step_id,
        )
        waiting_run = get_run(str(run["run_id"]))
        from services.learning_assistant_session_service import update_message_for_runtime_run

        update_message_for_runtime_run(
            str(run["run_id"]),
            session_id=run.get("session_id"),
            status="waiting_confirmation",
            run_revision=int(waiting_run["revision"]),
            event_cursor=int(waiting_run.get("last_event_sequence") or 0),
        )
        result_payload = result.model_dump()
        response = {
            "ok": False,
            "run_id": run["run_id"],
            "tool_result": result_payload,
            "run_revision": waiting_run["revision"],
        }
        if result.error and result.error.code == "invalid_confirmation":
            replacement_token = issue_runtime_confirmation_token(
                binding.tool_name,
                step.input,
                ToolExecutionContext(
                    actor_id=actor.actor_id,
                    role=actor.role,
                    student_id=run.get("student_id"),
                    request_source="agent_runtime_confirm_retry",
                    run_id=str(run["run_id"]),
                    step_id=step.step_id,
                    run_revision=int(waiting_run["revision"]),
                ),
            )
            response["confirmation_token"] = replacement_token
        return response

    final_response = "高风险工具已确认并执行完成。"
    final_payload = {
        "response": final_response,
        "completion_status": "completed",
        "tool_results": [result.model_dump()],
        "verification_summary": {"status": "not_required", "completion_allowed": True},
        "plan_summary": {"completed_steps": 1, "total_steps": 1},
    }
    artifact = create_artifact(
        str(run["run_id"]),
        owner_actor_id=run.get("actor_id"),
        student_id=run.get("student_id"),
        artifact_type="final_output",
        sensitivity="normal",
        content={"final": final_payload},
    )
    step_result = StepResult(
        step_id=step.step_id,
        operation=step.operation,
        status="completed",
        output=result.model_dump(),
        side_effect_committed=step.side_effect in {"write", "session_create"},
    )
    controller.event(
        "step_completed",
        public_payload={"step_result": step_result.model_dump()},
        step_results={step.step_id: step_result.model_dump()},
    )
    controller.event(
        "verification_result",
        public_payload={"status": "not_required"},
        next_status="verifying",
    )
    decision = CompletionEvaluator().from_outcome(
        status="completed",
        completed_steps=1,
        total_steps=1,
        verification_status="not_required",
        reason_codes=["confirmed_side_effect_completed"],
        deliverable_refs=[artifact["artifact_id"]],
    )
    controller.event(
        "run_completed",
        public_payload={"completion": decision.model_dump()},
        next_status="completed",
        completion=decision,
    )
    completed = get_run(str(run["run_id"]))
    from services.learning_assistant_session_service import update_message_for_runtime_run

    update_message_for_runtime_run(
        str(run["run_id"]),
        session_id=run.get("session_id"),
        status="completed",
        run_revision=int(completed["revision"]),
        event_cursor=int(completed.get("last_event_sequence") or 0),
        tool_result=result.model_dump(),
        content=final_response,
    )
    return {
        "ok": True,
        "run_id": run["run_id"],
        "run_revision": completed["revision"],
        "response": final_response,
        "tool_result": result.model_dump(),
        "completion": decision.model_dump(),
    }


_DEFAULT_HANDLERS: dict[str, ResumeHandler] = {
    "auto_tutor": _resume_auto_tutor,
    "essay_grader": _resume_essay_grader,
    "learning_assistant": _confirm_learning_assistant,
}


def register_resume_handler(agent_type: str, handler: ResumeHandler) -> None:
    if agent_type in _HANDLERS:
        raise ValueError(f"resume handler already registered: {agent_type}")
    _HANDLERS[agent_type] = handler


async def dispatch_resume(run: dict[str, Any], signal: ResumeSignal, actor: Actor) -> dict[str, Any]:
    if int(run["revision"]) != signal.expected_revision:
        raise ValueError("stale run revision")
    handler = _HANDLERS.get(str(run["agent_type"])) or _DEFAULT_HANDLERS.get(str(run["agent_type"]))
    if handler is None:
        raise LookupError("resume handler not registered")
    return await handler(run, signal, actor)
