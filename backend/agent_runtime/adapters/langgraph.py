from __future__ import annotations

import inspect
from typing import Any, Callable

from agent_runtime.models import AgentContext, AgentRunState, ResumeSignal, RuntimeEvent, StepResult


class LangGraphAdapter:
    """Map a compiled graph's node updates to EduAgent-owned runtime events."""

    def __init__(
        self,
        graph: Any,
        *,
        input_mapper: Callable[[AgentContext, AgentRunState], dict[str, Any]] | None = None,
    ) -> None:
        self.graph = graph
        self.input_mapper = input_mapper or (lambda _context, state: dict(state.context_refs.get("graph_input") or {}))

    async def stream(self, context: AgentContext, state: AgentRunState):
        graph_input = self.input_mapper(context, state)
        config = {"configurable": {"thread_id": context.run_id, "run_id": context.run_id}}
        sequence = 0
        if hasattr(self.graph, "astream"):
            iterator = self.graph.astream(graph_input, config=config, stream_mode="updates")
            async for update in iterator:
                for node_name, payload in (update.items() if isinstance(update, dict) else [("graph", update)]):
                    sequence += 1
                    if isinstance(payload, dict) and payload.get("__interrupt__"):
                        yield RuntimeEvent(
                            run_id=context.run_id,
                            trace_id=context.trace_id,
                            sequence=sequence,
                            event="waiting_input",
                            data={"node": node_name, "interrupt": payload.get("__interrupt__")},
                        )
                        return
                    step_id = str(node_name)
                    operation = f"{context.agent_type}.{step_id}"
                    result = StepResult(
                        step_id=step_id,
                        operation=operation,
                        status="completed",
                        output=payload if isinstance(payload, dict) else {"result": payload},
                    )
                    yield RuntimeEvent(
                        run_id=context.run_id,
                        trace_id=context.trace_id,
                        sequence=sequence,
                        event="step_completed",
                        data={"node": step_id, "step_result": result.model_dump()},
                    )
            return
        result = self.graph.invoke(graph_input, config=config)
        if inspect.isawaitable(result):
            result = await result
        step_id = state.current_step_id or (state.plan.steps[0].step_id if state.plan else "graph")
        operation = state.plan.steps[0].operation if state.plan else f"{context.agent_type}.graph"
        step_result = StepResult(
            step_id=step_id,
            operation=operation,
            status="completed",
            output=result if isinstance(result, dict) else {"result": result},
        )
        yield RuntimeEvent(
            run_id=context.run_id,
            trace_id=context.trace_id,
            sequence=1,
            event="step_completed",
            data={"node": "graph", "step_result": step_result.model_dump()},
        )

    async def resume(self, context: AgentContext, state: AgentRunState, signal: ResumeSignal):
        if state.status not in {"waiting_input", "waiting_confirmation"}:
            raise ValueError("run is not waiting")
        try:
            from langgraph.types import Command

            resume_value: Any = signal.input_patch or {"confirmed": signal.kind == "confirmation"}
            graph_input = Command(resume=resume_value)
        except Exception:
            graph_input = signal.input_patch
        config = {"configurable": {"thread_id": context.run_id, "run_id": context.run_id}}
        sequence = 0
        async for update in self.graph.astream(graph_input, config=config, stream_mode="updates"):
            for node_name, payload in (update.items() if isinstance(update, dict) else [("graph", update)]):
                sequence += 1
                step_id = str(node_name)
                operation = f"{context.agent_type}.{step_id}"
                result = StepResult(
                    step_id=step_id,
                    operation=operation,
                    status="completed",
                    output=payload if isinstance(payload, dict) else {"result": payload},
                )
                yield RuntimeEvent(
                    run_id=context.run_id,
                    trace_id=context.trace_id,
                    sequence=sequence,
                    event="step_completed",
                    data={"node": step_id, "step_result": result.model_dump()},
                )

    async def cancel(self, context: AgentContext, state: AgentRunState) -> RuntimeEvent:
        return RuntimeEvent(
            run_id=context.run_id,
            trace_id=context.trace_id,
            sequence=0,
            event="run_cancelled",
            data={"status": "cancelled"},
        )
