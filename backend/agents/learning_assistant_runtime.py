from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Iterator

from agents.learning_assistant_planner import (
    ALLOWED_GENERATION_OPERATIONS,
    ALLOWED_TOOL_OPERATIONS,
    PlanStep,
    TaskPlan,
)
from trace_store import emit_trace_event


ToolRunner = Callable[[str, dict[str, Any]], Any]
ToolSummary = Callable[[Any], dict[str, Any]]
GenerationRunner = Callable[[str, PlanStep, dict[str, dict[str, Any]]], dict[str, Any]]


def _public_step(step: PlanStep, status: str, *, sequence: int, latency_ms: float | None = None, result_summary: str | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "step_id": step.step_id,
        "title": step.title,
        "kind": step.kind,
        "operation": step.operation,
        "sequence": sequence,
        "status": status,
        "latency_ms": latency_ms,
        "result_summary": result_summary,
        "error": error,
    }
    emit_trace_event(
        agent_name="learning_assistant",
        step_name=f"Plan Step · {step.title}",
        event_type="plan_step",
        status=status,
        latency_ms=latency_ms,
        metadata={
            "step_id": step.step_id,
            "operation": step.operation,
            "kind": step.kind,
            "sequence": sequence,
            "result_summary": result_summary,
            "error_code": (error or {}).get("code"),
        },
    )
    return payload


def _tool_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _criteria_failure(step: PlanStep, result: dict[str, Any]) -> str | None:
    data = _tool_data(result)
    for criterion in step.success_criteria:
        if criterion == "tool_result_ok" and result.get("ok") is not True:
            return "tool_result_not_ok"
        if criterion == "source_count_gte_1" and not (data.get("sources") or []):
            return "no_sources"
        if criterion == "lesson_present" and not data.get("lesson"):
            return "lesson_missing"
        if criterion == "question_count_matches":
            expected = int(step.input.get("count") or 1)
            quiz = data.get("quiz") or {}
            questions = quiz.get("questions") or data.get("questions") or []
            if len(questions) < expected:
                return "question_count_mismatch"
        if criterion == "recommended_action_present":
            review = data.get("review_plan") or data
            if not (review.get("recommended_actions") or []):
                return "recommended_action_missing"
        if criterion == "non_empty_output" and not (result.get("response") or data):
            return "empty_generation"
    return None


def _error_payload(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def stream_task_plan(
    plan: TaskPlan,
    *,
    run_tool: ToolRunner,
    summarize_tool: ToolSummary,
    run_generation: GenerationRunner,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Execute a validated plan and finish with one internal execution_complete event."""
    outputs: dict[str, dict[str, Any]] = {}
    tool_results: list[dict[str, Any]] = []
    generation_results: list[dict[str, Any]] = []
    completed_steps = 0
    used_tool_count = 0
    completion_status = "completed"
    partial_reason: str | None = None
    failed_step: str | None = None

    for sequence, step in enumerate(plan.steps, start=1):
        if any(dep not in outputs for dep in step.depends_on):
            completion_status = "partial" if completed_steps else "failed"
            partial_reason = "dependency_not_completed"
            failed_step = step.step_id
            error = _error_payload("dependency_not_completed", "前置步骤没有完成，已停止后续任务。")
            yield "plan_step", _public_step(step, "failed", sequence=sequence, error=error)
            break

        started = perf_counter()
        yield "plan_step", _public_step(step, "running", sequence=sequence)
        try:
            if step.kind == "tool":
                if step.operation not in ALLOWED_TOOL_OPERATIONS:
                    raise ValueError(f"tool operation is not allowed: {step.operation}")
                yield "tool_start", {"tool_name": step.operation, "step_id": step.step_id}
                raw = run_tool(step.operation, step.input)
                used_tool_count += 1
                payload = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
                tool_results.append(payload)
                summary = summarize_tool(raw)
                summary["step_id"] = step.step_id
                yield "tool_result", summary
                error = payload.get("error") or {}
                if error.get("code") == "confirmation_required":
                    latency = round((perf_counter() - started) * 1000, 2)
                    completion_status = "waiting_confirmation"
                    partial_reason = "confirmation_required"
                    failed_step = step.step_id
                    yield "plan_step", _public_step(step, "waiting_confirmation", sequence=sequence, latency_ms=latency, result_summary=summary.get("result_summary"), error=error)
                    break
                failure = _criteria_failure(step, payload)
                retryable_read_failure = step.operation in {"search_history_knowledge", "get_textbook_lesson"} and (
                    failure == "no_sources" or error.get("code") == "tool_failed"
                )
                if retryable_read_failure:
                    retry_payload = dict(step.input)
                    if step.operation == "search_history_knowledge":
                        topic = str(retry_payload.get("topic") or "").strip()
                        original_query = str(retry_payload.get("query") or "").strip()
                        retry_payload["query"] = (topic or original_query)[:420] + " 核心史实 原因 影响"
                    repair_payload = {
                        "step_id": step.step_id,
                        "operation": step.operation,
                        "failure_code": failure or error.get("code"),
                        "repair_type": "query_rewrite" if step.operation == "search_history_knowledge" else "read_retry",
                        "attempt": 1,
                    }
                    emit_trace_event(
                        agent_name="learning_assistant",
                        step_name="Repair Attempt",
                        event_type="repair",
                        status="running",
                        metadata=repair_payload,
                    )
                    yield "repair_attempt", repair_payload
                    retried_raw = run_tool(step.operation, retry_payload)
                    used_tool_count += 1
                    retried_payload = retried_raw.model_dump() if hasattr(retried_raw, "model_dump") else dict(retried_raw)
                    tool_results[-1] = retried_payload
                    retried_summary = summarize_tool(retried_raw)
                    retried_summary["step_id"] = step.step_id
                    retried_summary["repair_attempt"] = 1
                    yield "tool_result", retried_summary
                    retried_failure = _criteria_failure(step, retried_payload)
                    if not retried_failure:
                        payload = retried_payload
                        summary = retried_summary
                        error = payload.get("error") or {}
                        failure = None
                        emit_trace_event(
                            agent_name="learning_assistant",
                            step_name="Repair Attempt",
                            event_type="repair",
                            status="success",
                            metadata={**repair_payload, "result_summary": "修复后步骤成功"},
                        )
                    else:
                        failure = retried_failure
                        error = retried_payload.get("error") or {}
                        emit_trace_event(
                            agent_name="learning_assistant",
                            step_name="Repair Attempt",
                            event_type="repair",
                            status="failed",
                            metadata={**repair_payload, "result_summary": "修复后仍未达到完成标准"},
                        )
                if failure:
                    latency = round((perf_counter() - started) * 1000, 2)
                    completion_status = "partial" if completed_steps else "failed"
                    partial_reason = failure
                    failed_step = step.step_id
                    detail = payload.get("error") or _error_payload(failure, "该步骤没有产生足够的可验证结果。", retryable=failure in {"no_sources"})
                    yield "plan_step", _public_step(step, "failed", sequence=sequence, latency_ms=latency, result_summary=summary.get("result_summary"), error=detail)
                    break
                outputs[step.step_id] = {"kind": "tool", "operation": step.operation, "payload": payload}
                latency = round((perf_counter() - started) * 1000, 2)
                completed_steps += 1
                yield "plan_step", _public_step(step, "completed", sequence=sequence, latency_ms=latency, result_summary=summary.get("result_summary"))
                continue

            if step.operation not in ALLOWED_GENERATION_OPERATIONS:
                raise ValueError(f"generation operation is not allowed: {step.operation}")
            generated = run_generation(step.operation, step, outputs)
            if not isinstance(generated, dict):
                raise ValueError("generation operation returned invalid result")
            generated = {**generated, "operation": step.operation, "step_id": step.step_id}
            failure = _criteria_failure(step, generated)
            if generated.get("ok") is False and not failure:
                failure = str((generated.get("error") or {}).get("code") or "generation_failed")
            if failure:
                latency = round((perf_counter() - started) * 1000, 2)
                completion_status = "partial" if completed_steps else "failed"
                partial_reason = failure
                failed_step = step.step_id
                error = generated.get("error") or _error_payload(failure, "生成步骤未达到完成标准。", retryable=True)
                yield "plan_step", _public_step(step, "failed", sequence=sequence, latency_ms=latency, error=error)
                break
            outputs[step.step_id] = {"kind": "generation", "operation": step.operation, "payload": generated}
            generation_results.append(generated)
            latency = round((perf_counter() - started) * 1000, 2)
            completed_steps += 1
            yield "plan_step", _public_step(step, "completed", sequence=sequence, latency_ms=latency, result_summary=str(generated.get("result_summary") or "生成完成"))
        except Exception as exc:
            latency = round((perf_counter() - started) * 1000, 2)
            completion_status = "partial" if completed_steps else "failed"
            partial_reason = "execution_exception"
            failed_step = step.step_id
            error = _error_payload("execution_exception", str(exc) or "任务步骤执行失败。", retryable=step.kind != "tool")
            yield "plan_step", _public_step(step, "failed", sequence=sequence, latency_ms=latency, error=error)
            break

    yield "execution_complete", {
        "completion_status": completion_status,
        "completed_steps": completed_steps,
        "total_steps": len(plan.steps),
        "partial_reason": partial_reason,
        "failed_step": failed_step,
        "tool_results": tool_results,
        "generation_results": generation_results,
        "outputs": outputs,
        "used_tool_count": used_tool_count,
    }
