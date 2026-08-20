from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-lifecycle-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from agent_runtime.completion import CompletionEvaluator  # noqa: E402
from agent_runtime.lifecycle import RuntimeRunController  # noqa: E402
from agent_runtime.models import AgentBudget, AgentContext, AgentPlan, AgentStep  # noqa: E402
from agent_runtime.policy import PlanPolicyError  # noqa: E402


def _context(run_id: str) -> AgentContext:
    return AgentContext(
        run_id=run_id,
        agent_type="learning_assistant",
        actor_id="student-lifecycle",
        actor_role="student",
        student_id="student-lifecycle",
        session_id="session-lifecycle",
        trace_id=f"trace-{run_id}",
        durability_mode="observable",
        config_version="lifecycle-smoke",
    )


def _plan(operation: str) -> AgentPlan:
    return AgentPlan(
        plan_id=f"plan-{operation.replace('.', '-')}",
        objective="验证统一生命周期",
        strategy="direct",
        generated_by="template",
        planner_version="lifecycle-smoke",
        steps=[AgentStep(
            step_id="answer",
            kind="generation",
            operation=operation,
            side_effect="external_call",
            timeout_seconds=15,
        )],
    )


def main() -> None:
    budget = AgentBudget(max_steps=1, max_tool_calls=0, max_llm_calls=1)
    controller, created = RuntimeRunController.create(
        _context("run_lifecycle_ok"),
        objective="统一生命周期",
        budget=budget,
        policy_caller="learning_assistant",
    )
    assert created["status"] == "received"
    controller.route({"agent_type": "learning_assistant"})
    controller.admit_plan(_plan("chat_answer"))
    controller.start_step("answer", "chat_answer")
    controller.event("step_completed", public_payload={"step_id": "answer"})
    controller.event("verification_result", public_payload={"status": "not_required"}, next_status="verifying")
    decision = CompletionEvaluator().from_outcome(
        status="completed",
        completed_steps=1,
        total_steps=1,
        verification_status="not_required",
        reason_codes=["lifecycle_smoke"],
    )
    controller.event("run_completed", public_payload={"completion": decision.model_dump()}, next_status="completed", completion=decision)
    completed = controller.get()
    assert completed["status"] == "completed"
    assert completed["revision"] == 6
    assert completed["last_event_sequence"] == 7

    rejected, _ = RuntimeRunController.create(
        _context("run_lifecycle_rejected"),
        objective="拒绝未知能力",
        budget=budget,
        policy_caller="learning_assistant",
    )
    rejected.route({"agent_type": "learning_assistant"})
    try:
        rejected.admit_plan(_plan("unregistered.operation"))
    except PlanPolicyError:
        pass
    else:
        raise AssertionError("unknown operation bypassed capability policy")
    assert rejected.get()["status"] == "routed"

    print("agent_runtime_lifecycle_smoke=PASS")


if __name__ == "__main__":
    main()
