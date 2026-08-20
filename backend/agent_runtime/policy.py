from __future__ import annotations

from agent_runtime.capability_registry import CapabilityRegistry
from agent_runtime.models import AgentBudget, AgentPlan


class PlanPolicyError(ValueError):
    pass


def validate_plan_policy(
    plan: AgentPlan,
    *,
    caller: str,
    budget: AgentBudget,
    registry: CapabilityRegistry,
) -> AgentPlan:
    if len(plan.steps) > budget.max_steps:
        raise PlanPolicyError("plan exceeds max_steps")
    tool_count = sum(step.kind == "tool" for step in plan.steps)
    if tool_count > budget.max_tool_calls:
        raise PlanPolicyError("plan exceeds max_tool_calls")
    llm_count = sum(step.kind == "generation" or step.side_effect == "external_call" for step in plan.steps)
    if llm_count > budget.max_llm_calls:
        raise PlanPolicyError("plan exceeds max_llm_calls")
    for step in plan.steps:
        try:
            binding = registry.resolve(step.operation, caller)
        except (LookupError, PermissionError) as exc:
            raise PlanPolicyError(str(exc)) from exc
        if binding.kind == "tool":
            spec = TOOLS[str(binding.tool_name)]
            if step.side_effect != spec.side_effect or step.risk_level != spec.risk_level:
                raise PlanPolicyError("tool step risk and side effect must match ToolSpec")
            if step.timeout_seconds != spec.timeout_seconds:
                raise PlanPolicyError("tool step timeout must match ToolSpec")
    return plan


from tools.registry import TOOLS  # noqa: E402  (keeps policy API imports compact)
