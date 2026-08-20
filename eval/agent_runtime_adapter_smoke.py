from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.adapters.function import FunctionAdapter  # noqa: E402
from agent_runtime.adapters.langgraph import LangGraphAdapter  # noqa: E402
from agent_runtime.adapters.sequential import SequentialPlanAdapter  # noqa: E402
from agent_runtime.models import AgentContext, AgentPlan, AgentRunState, AgentStep, StepResult  # noqa: E402


class EmptyInput(BaseModel):
    value: int = 1


class Output(BaseModel):
    value: int


class FakeGraph:
    def invoke(self, graph_input, *, config):
        assert config["configurable"]["run_id"] == "run-adapter"
        return {"value": int(graph_input.get("value") or 1)}


def plan(strategy: str, kind: str, operation: str) -> AgentPlan:
    return AgentPlan(
        plan_id=f"plan-{strategy}",
        objective="adapter contract",
        strategy=strategy,
        steps=[AgentStep(step_id="execute", kind=kind, operation=operation)],
        generated_by="template",
        planner_version="adapter-test",
    )


async def collect(adapter, state: AgentRunState, context: AgentContext):
    return [event async for event in adapter.stream(context, state)]


def assert_completed(events) -> None:
    completed = next(event for event in events if event.event == "step_completed")
    assert completed.schema_version == 2
    result = StepResult.model_validate(completed.data["step_result"])
    assert result.status == "completed"


def main() -> None:
    context = AgentContext(
        run_id="run-adapter",
        agent_type="adapter_test",
        trace_id="trace-adapter",
        durability_mode="observable",
        config_version="adapter-test",
    )
    sequential_state = AgentRunState(
        run_id=context.run_id,
        durability_mode="observable",
        status="planned",
        objective="sequential",
        plan=plan("sequential", "control", "test.operation"),
    )
    assert_completed(asyncio.run(collect(
        SequentialPlanAdapter({"test.operation": lambda *_args: {"value": 1}}),
        sequential_state,
        context,
    )))

    function_state = AgentRunState(
        run_id=context.run_id,
        durability_mode="observable",
        status="planned",
        objective="function",
        plan=plan("direct", "control", "test.function"),
        context_refs={"function_input": {"value": 2}},
    )
    assert_completed(asyncio.run(collect(
        FunctionAdapter(input_model=EmptyInput, output_model=Output, executor=lambda value, _context: {"value": value.value}),
        function_state,
        context,
    )))

    graph_state = AgentRunState(
        run_id=context.run_id,
        durability_mode="observable",
        status="planned",
        objective="graph",
        plan=plan("subgraph", "subgraph", "test.graph"),
        context_refs={"graph_input": {"value": 3}},
    )
    assert_completed(asyncio.run(collect(LangGraphAdapter(FakeGraph()), graph_state, context)))
    print("agent_runtime_adapter_smoke=PASS")


if __name__ == "__main__":
    main()
