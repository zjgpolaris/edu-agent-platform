"""Non-tool capabilities enforce authoritative kind, risk and side effects."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime.capability_registry import build_default_registry  # noqa: E402
from agent_runtime.models import AgentBudget, AgentPlan, AgentStep  # noqa: E402
from agent_runtime.policy import PlanPolicyError, validate_plan_policy  # noqa: E402
from agents.auto_tutor import _autotutor_runtime_plan  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def _expect_rejected(plan: AgentPlan) -> None:
    try:
        validate_plan_policy(
            plan,
            caller="auto_tutor",
            budget=AgentBudget(max_steps=4, max_tool_calls=2, max_llm_calls=3),
            registry=build_default_registry(),
        )
    except PlanPolicyError:
        return
    raise AssertionError("invalid non-tool capability contract was accepted")


def main() -> None:
    registry = build_default_registry()
    valid = _autotutor_runtime_plan("policy-session")
    validate_plan_policy(
        valid,
        caller="auto_tutor",
        budget=AgentBudget(max_steps=4, max_tool_calls=2, max_llm_calls=3),
        registry=registry,
    )
    finalize = valid.steps[-1]
    assert finalize.side_effect == "write"
    assert finalize.risk_level == "medium"
    assert finalize.idempotency_key == "autotutor:policy-session:finalize"

    for update in (
        {"side_effect": "none"},
        {"risk_level": "low"},
        {"timeout_seconds": 30},
        {"kind": "generation"},
    ):
        invalid_step = finalize.model_copy(update=update)
        invalid = valid.model_copy(update={"steps": [*valid.steps[:-1], invalid_step]})
        _expect_rejected(invalid)

    try:
        AgentStep(
            step_id="finalize",
            kind="control",
            operation="auto_tutor.finalize",
            side_effect="write",
            risk_level="medium",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("write step without idempotency key was accepted")
    print("agent_runtime_non_tool_policy_smoke=PASS")


if __name__ == "__main__":
    main()
