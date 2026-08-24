from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-idempotency-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from agent_runtime.capability_registry import CapabilityBinding, build_default_registry  # noqa: E402
from agent_runtime.lifecycle import RuntimeRunController  # noqa: E402
from agent_runtime.models import AgentBudget, AgentContext, AgentPlan, AgentStep  # noqa: E402
from agent_runtime.side_effect_store import (  # noqa: E402
    claim_side_effect,
    get_side_effect,
    mark_stale_started_side_effects_unknown,
)
from agent_ops import build_agent_ops_summary  # noqa: E402
from tools.base import ToolExecutionContext, ToolResult, ToolSpec  # noqa: E402
from tools.registry import TOOLS, run_tool  # noqa: E402


class SideEffectInput(BaseModel):
    value: str


CALLS: list[str] = []


def _handler(payload: SideEffectInput) -> ToolResult:
    CALLS.append(payload.value)
    if payload.value == "raise":
        raise RuntimeError("ambiguous external failure")
    return ToolResult(tool_name="runtime_test_write", ok=True, data={"value": payload.value})


def _controller(run_id: str, *, value: str, key: str) -> RuntimeRunController:
    context = AgentContext(
        run_id=run_id,
        agent_type="learning_assistant",
        actor_id="student-idempotency",
        actor_role="student",
        student_id="student-idempotency",
        session_id=run_id,
        trace_id=f"trace-{run_id}",
        durability_mode="observable",
        config_version="idempotency-smoke",
    )
    controller, _ = RuntimeRunController.create(
        context,
        objective="验证副作用幂等",
        budget=AgentBudget(max_steps=1, max_tool_calls=1, max_llm_calls=0),
        policy_caller="learning_assistant",
    )
    plan = AgentPlan(
        plan_id=f"plan-{run_id}",
        objective="执行一次受控写操作",
        strategy="direct",
        generated_by="template",
        planner_version="idempotency-smoke",
        steps=[AgentStep(
            step_id="write",
            kind="tool",
            operation="runtime.test_write",
            input={"value": value},
            side_effect="write",
            risk_level="low",
            idempotency_key=key,
            timeout_seconds=10,
        )],
    )
    registry = build_default_registry()
    spec = TOOLS["runtime_test_write"]
    registry.register(CapabilityBinding(
        name="runtime.test_write",
        version="1",
        kind="tool",
        input_model=SideEffectInput,
        output_model=ToolResult,
        executor="eval:runtime_test_write",
        allowed_callers=["learning_assistant"],
        tool_name=spec.name,
        durability_mode="observable",
        step_kind="tool",
        side_effect=spec.side_effect,
        risk_level=spec.risk_level,
        default_timeout_seconds=spec.timeout_seconds,
    ))
    controller.route({"agent_type": "learning_assistant"})
    controller.admit_plan(plan, registry=registry)
    controller.start_step("write", "runtime.test_write")
    return controller


def _context(controller: RuntimeRunController, key: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        actor_id="student-idempotency",
        role="student",
        student_id="student-idempotency",
        request_source="idempotency_smoke",
        run_id=controller.run_id,
        step_id="write",
        run_revision=controller.get()["revision"],
        idempotency_key=key,
        capability_operation="runtime.test_write",
    )


def main() -> None:
    TOOLS["runtime_test_write"] = ToolSpec(
        name="runtime_test_write",
        description="test-only durable write",
        input_model=SideEffectInput,
        handler=_handler,
        risk_level="low",
        side_effect="write",
        required_role="student",
        timeout_seconds=10,
    )
    try:
        controller = _controller("run_idempotency_commit", value="once", key="write-once")
        first = run_tool("runtime_test_write", {"value": "once"}, _context(controller, "write-once"))
        second = run_tool("runtime_test_write", {"value": "once"}, _context(controller, "write-once"))
        assert first.ok and second.ok
        assert CALLS.count("once") == 1
        assert second.metadata["idempotent_replay"] is True
        assert get_side_effect(controller.run_id, "write-once")["status"] == "committed"

        ambiguous = _controller("run_idempotency_unknown", value="raise", key="write-unknown")
        failed = run_tool("runtime_test_write", {"value": "raise"}, _context(ambiguous, "write-unknown"))
        blocked = run_tool("runtime_test_write", {"value": "raise"}, _context(ambiguous, "write-unknown"))
        assert failed.error and failed.error.code == "tool_failed"
        assert blocked.error and blocked.error.code == "side_effect_outcome_unknown"
        assert CALLS.count("raise") == 1

        in_progress = _controller("run_idempotency_started", value="held", key="write-held")
        claim = claim_side_effect(
            run_id=in_progress.run_id,
            step_id="write",
            operation="runtime.test_write",
            idempotency_key="write-held",
            input_payload={"value": "held"},
        )
        assert claim.acquired
        blocked_running = run_tool("runtime_test_write", {"value": "held"}, _context(in_progress, "write-held"))
        assert blocked_running.error and blocked_running.error.code == "side_effect_in_progress"
        assert "held" not in CALLS

        active_scope = os.getenv("EDU_AGENT_DATA_SCOPE", "runtime")
        runtime_ops = build_agent_ops_summary(limit=100, scope=active_scope, minimum_runtime_events=0)["runtime_v2"]
        assert runtime_ops["duplicate_side_effect_prevented_total"] == 1
        assert runtime_ops["side_effects_by_status"] == {"committed": 1, "started": 1, "unknown": 1}
        assert mark_stale_started_side_effects_unknown(updated_before="9999-01-01T00:00:00+00:00") == 1
        assert get_side_effect(in_progress.run_id, "write-held")["status"] == "unknown"
    finally:
        TOOLS.pop("runtime_test_write", None)

    print("agent_runtime_idempotency_smoke=PASS")


if __name__ == "__main__":
    main()
