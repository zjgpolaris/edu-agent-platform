from __future__ import annotations

import inspect
from time import perf_counter
from typing import Any, Awaitable, Callable
from uuid import uuid4

from agent_runtime.budget import BudgetExceededError, BudgetTracker
from agent_runtime.models import (
    AgentContext,
    AgentPlan,
    AgentRunState,
    AgentStep,
    ResumeSignal,
    RuntimeEvent,
    StepResult,
)
from tools.registry import TOOLS, run_tool

OperationHandler = Callable[[AgentStep, dict[str, StepResult], AgentContext], Any | Awaitable[Any]]

_LEGACY_TOOL_TO_CAPABILITY = {
    "search_history_knowledge": "history.search",
    "get_textbook_lesson": "textbook.lesson",
    "generate_quiz": "quiz.generate",
    "suggest_review_plan": "profile.review_plan",
    "recommend_character": "character.recommend",
    "start_timeline_game": "timeline.start",
    "delete_demo_memory": "memory.delete_demo",
}


def map_legacy_task_plan(plan: Any, *, planner_version: str = "learning-assistant-v1") -> AgentPlan:
    steps: list[AgentStep] = []
    for legacy in plan.steps:
        if legacy.kind == "tool":
            spec = TOOLS[legacy.operation]
            side_effect = spec.side_effect
            risk_level = spec.risk_level
            timeout = spec.timeout_seconds
            operation = _LEGACY_TOOL_TO_CAPABILITY.get(legacy.operation, legacy.operation)
        else:
            side_effect = "external_call"
            risk_level = "low"
            timeout = 20
            operation = legacy.operation
        idempotency_key = None
        if side_effect in {"write", "session_create"}:
            idempotency_key = f"legacy:{legacy.step_id}:{uuid4().hex}"
        steps.append(AgentStep(
            step_id=legacy.step_id,
            kind="tool" if legacy.kind == "tool" else "generation",
            operation=operation,
            input=dict(legacy.input),
            depends_on=list(legacy.depends_on),
            success_criteria=list(legacy.success_criteria),
            side_effect=side_effect,
            risk_level=risk_level,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout,
        ))
    return AgentPlan(
        plan_id=f"plan_{uuid4().hex}",
        objective=plan.objective,
        strategy="sequential",
        steps=steps,
        generated_by="deterministic",
        planner_version=planner_version,
    )


class SequentialPlanAdapter:
    def __init__(self, handlers: dict[str, OperationHandler] | None = None) -> None:
        self.handlers = handlers or {}

    async def _execute(
        self,
        step: AgentStep,
        outputs: dict[str, StepResult],
        context: AgentContext,
        *,
        run_revision: int,
    ) -> Any:
        handler = self.handlers.get(step.operation)
        if handler is not None:
            result = handler(step, outputs, context)
            return await result if inspect.isawaitable(result) else result
        tool_name = next((name for name, capability in _LEGACY_TOOL_TO_CAPABILITY.items() if capability == step.operation), None)
        if tool_name:
            from tools.base import ToolExecutionContext

            result = run_tool(tool_name, step.input, ToolExecutionContext(
                actor_id=context.actor_id,
                role=context.actor_role,
                student_id=context.student_id,
                request_source=context.agent_type,
                run_id=context.run_id,
                step_id=step.step_id,
                run_revision=run_revision,
            ))
            return result.model_dump()
        raise LookupError(f"no executor registered for operation: {step.operation}")

    async def stream(self, context: AgentContext, state: AgentRunState):
        if state.plan is None:
            raise ValueError("sequential adapter requires state.plan")
        tracker = BudgetTracker(state.budget)
        outputs = dict(state.step_results)
        sequence = 0
        for step_index, step in enumerate(state.plan.steps):
            sequence += 1
            if any(dependency not in outputs for dependency in step.depends_on):
                result = StepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    status="failed",
                    error={"code": "dependency_not_completed", "message": "前置步骤未完成。"},
                )
                outputs[step.step_id] = result
                yield RuntimeEvent(
                    run_id=context.run_id,
                    trace_id=context.trace_id,
                    sequence=sequence,
                    event="step_failed",
                    data={"step_result": result.model_dump()},
                )
                return
            try:
                tracker.consume("steps")
                if step.kind == "tool":
                    tracker.consume("tool_calls")
                elif step.kind in {"generation", "subgraph"}:
                    tracker.consume("llm_calls")
            except BudgetExceededError as exc:
                result = StepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    status="failed",
                    error={"code": "budget_exceeded", "message": str(exc)},
                )
                outputs[step.step_id] = result
                yield RuntimeEvent(
                    run_id=context.run_id,
                    trace_id=context.trace_id,
                    sequence=sequence,
                    event="step_failed",
                    data={"step_result": result.model_dump(), "used_budget": tracker.snapshot()},
                )
                return

            yield RuntimeEvent(
                run_id=context.run_id,
                trace_id=context.trace_id,
                sequence=sequence,
                event="step_started",
                data={"step_id": step.step_id, "operation": step.operation, "kind": step.kind},
            )
            started = perf_counter()
            try:
                # The engine persists this adapter's step_started event before
                # resuming the generator. Each completed prior step contributes
                # two persisted milestones (started + completed). A
                # confirmation token therefore binds to the revision at which
                # the waiting result will be persisted, not to a stale caller
                # revision.
                waiting_revision = state.revision + (step_index * 2) + 2
                raw = await self._execute(
                    step,
                    outputs,
                    context,
                    run_revision=waiting_revision,
                )
                raw_payload = raw.model_dump() if hasattr(raw, "model_dump") else raw
                ok = not isinstance(raw_payload, dict) or raw_payload.get("ok") is not False
                error = raw_payload.get("error") if isinstance(raw_payload, dict) else None
                if isinstance(error, dict) and error.get("code") == "confirmation_required":
                    status = "waiting_confirmation"
                else:
                    status = "completed" if ok else "failed"
                output = raw_payload if isinstance(raw_payload, dict) else {"result": raw_payload}
                source_ids = []
                for source in ((output.get("data") or {}).get("sources") or output.get("sources") or []):
                    if isinstance(source, dict) and (source_id := source.get("source_id")):
                        source_ids.append(str(source_id))
                result = StepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    status=status,
                    output=output,
                    source_ids=source_ids,
                    error=error if not ok else None,
                    retryable=bool((error or {}).get("retryable")) if isinstance(error, dict) else False,
                    side_effect_committed=ok and step.side_effect in {"write", "session_create"},
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                )
            except Exception as exc:
                result = StepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    status="failed",
                    error={"code": "execution_exception", "message": str(exc)[:300]},
                    retryable=step.side_effect in {"none", "read"},
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                )
            outputs[step.step_id] = result
            yield RuntimeEvent(
                run_id=context.run_id,
                trace_id=context.trace_id,
                sequence=sequence,
                event="step_completed" if result.status == "completed" else (
                    "waiting_confirmation" if result.status == "waiting_confirmation" else "step_failed"
                ),
                data={"step_result": result.model_dump(), "used_budget": tracker.snapshot()},
            )
            if result.status != "completed":
                return

    async def resume(self, context: AgentContext, state: AgentRunState, signal: ResumeSignal):
        if state.status not in {"waiting_input", "waiting_confirmation"}:
            raise ValueError("run is not waiting")
        async for event in self.stream(context, state):
            yield event

    async def cancel(self, context: AgentContext, state: AgentRunState) -> RuntimeEvent:
        return RuntimeEvent(
            run_id=context.run_id,
            trace_id=context.trace_id,
            sequence=0,
            event="run_cancelled",
            data={"status": "cancelled"},
        )
