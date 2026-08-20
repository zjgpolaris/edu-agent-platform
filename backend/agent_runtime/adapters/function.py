from __future__ import annotations

import inspect
from time import perf_counter
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from agent_runtime.models import AgentContext, AgentRunState, ResumeSignal, RuntimeEvent, StepResult

FunctionExecutor = Callable[[BaseModel, AgentContext], Any | Awaitable[Any]]


class FunctionAdapter:
    def __init__(self, *, input_model: type[BaseModel], output_model: type[BaseModel], executor: FunctionExecutor) -> None:
        self.input_model = input_model
        self.output_model = output_model
        self.executor = executor

    async def stream(self, context: AgentContext, state: AgentRunState):
        raw_input = state.context_refs.get("function_input") or {}
        validated_input = self.input_model.model_validate(raw_input)
        step = state.plan.steps[0] if state.plan else None
        step_id = state.current_step_id or (step.step_id if step else f"{context.agent_type}.execute")
        operation = step.operation if step else context.agent_type
        yield RuntimeEvent(
            run_id=context.run_id,
            trace_id=context.trace_id,
            sequence=1,
            event="step_started",
            data={"step_id": step_id, "operation": operation},
        )
        started = perf_counter()
        result = self.executor(validated_input, context)
        result = await result if inspect.isawaitable(result) else result
        validated_output = self.output_model.model_validate(result)
        step_result = StepResult(
            step_id=step_id,
            operation=operation,
            status="completed",
            output=validated_output.model_dump(),
            latency_ms=round((perf_counter() - started) * 1000, 2),
        )
        yield RuntimeEvent(
            run_id=context.run_id,
            trace_id=context.trace_id,
            sequence=2,
            event="step_completed",
            data={"step_result": step_result.model_dump()},
        )

    async def resume(self, context: AgentContext, state: AgentRunState, signal: ResumeSignal):
        raise ValueError("function capability is not resumable")
        yield  # pragma: no cover

    async def cancel(self, context: AgentContext, state: AgentRunState) -> RuntimeEvent:
        return RuntimeEvent(
            run_id=context.run_id,
            trace_id=context.trace_id,
            sequence=0,
            event="run_cancelled",
            data={"status": "cancelled"},
        )
