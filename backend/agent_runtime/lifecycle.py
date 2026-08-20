from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_runtime.capability_registry import CapabilityRegistry, build_default_registry
from agent_runtime.event_store import append_run_event, create_run, get_run
from agent_runtime.models import (
    AgentBudget,
    AgentContext,
    AgentPlan,
    CompletionDecision,
    RunStatus,
    RuntimeEvent,
)
from agent_runtime.policy import validate_plan_policy


@dataclass(slots=True)
class RuntimeRunController:
    """Single write boundary for a persisted Agent Runtime lifecycle.

    Product agents keep their domain-specific graph/executor, while all run
    creation, plan admission and state transitions pass through this class.
    """

    run_id: str
    policy_caller: str

    @classmethod
    def create(
        cls,
        context: AgentContext,
        *,
        objective: str,
        budget: AgentBudget,
        policy_caller: str,
        idempotency_key: str | None = None,
        parent_run_id: str | None = None,
        expires_at: str | None = None,
        runtime_mode: str = "active",
    ) -> tuple["RuntimeRunController", dict[str, Any]]:
        created = create_run(
            context,
            objective=objective,
            budget=budget,
            idempotency_key=idempotency_key,
            parent_run_id=parent_run_id,
            expires_at=expires_at,
            runtime_mode=runtime_mode,
        )
        return cls(run_id=str(created["run_id"]), policy_caller=policy_caller), created

    @classmethod
    def attach(cls, run_id: str, *, policy_caller: str) -> "RuntimeRunController":
        get_run(run_id)
        return cls(run_id=run_id, policy_caller=policy_caller)

    def get(self) -> dict[str, Any]:
        return get_run(self.run_id)

    def event(
        self,
        event_type: str,
        *,
        public_payload: dict[str, Any] | None = None,
        internal_metadata: dict[str, Any] | None = None,
        next_status: RunStatus | None = None,
        step_id: str | None = None,
        operation: str | None = None,
        current_step_id: str | None = None,
        plan: dict[str, Any] | None = None,
        step_results: dict[str, Any] | None = None,
        completion: CompletionDecision | None = None,
        used_budget: dict[str, int | float] | None = None,
        input_artifact_refs: list[str] | None = None,
        expected_revision: int | None = None,
    ) -> RuntimeEvent:
        revision = int(self.get()["revision"]) if expected_revision is None else expected_revision
        return append_run_event(
            self.run_id,
            expected_revision=revision,
            event_type=event_type,
            public_payload=public_payload,
            internal_metadata=internal_metadata,
            next_status=next_status,
            step_id=step_id,
            operation=operation,
            current_step_id=current_step_id,
            plan=plan,
            step_results=step_results,
            completion=completion,
            used_budget=used_budget,
            input_artifact_refs=input_artifact_refs,
        )

    def route(self, payload: dict[str, Any], *, input_artifact_refs: list[str] | None = None) -> RuntimeEvent:
        return self.event(
            "route_decided",
            public_payload=payload,
            next_status="routed",
            input_artifact_refs=input_artifact_refs,
        )

    def admit_plan(
        self,
        plan: AgentPlan,
        *,
        registry: CapabilityRegistry | None = None,
    ) -> RuntimeEvent:
        run = self.get()
        budget = AgentBudget.model_validate(run["state"]["budget"])
        validate_plan_policy(
            plan,
            caller=self.policy_caller,
            budget=budget,
            registry=registry or build_default_registry(),
        )
        return self.event(
            "plan_created",
            public_payload={"plan_id": plan.plan_id, "step_count": len(plan.steps)},
            next_status="planned",
            plan=plan.model_dump(),
        )

    def start_step(
        self,
        step_id: str,
        operation: str | None = None,
        *,
        expected_revision: int | None = None,
        **payload: Any,
    ) -> RuntimeEvent:
        public = {"step_id": step_id, **payload}
        if operation:
            public["operation"] = operation
        return self.event(
            "step_started",
            public_payload=public,
            next_status="running",
            step_id=step_id,
            operation=operation,
            current_step_id=step_id,
            expected_revision=expected_revision,
        )

    def wait_for_input(
        self,
        payload: dict[str, Any],
        *,
        step_id: str | None = None,
        input_artifact_refs: list[str] | None = None,
    ) -> RuntimeEvent:
        return self.event(
            "waiting_input",
            public_payload=payload,
            next_status="waiting_input",
            step_id=step_id,
            current_step_id=step_id,
            input_artifact_refs=input_artifact_refs,
        )

    def wait_for_confirmation(self, payload: dict[str, Any], *, step_id: str | None = None) -> RuntimeEvent:
        return self.event(
            "waiting_confirmation",
            public_payload=payload,
            next_status="waiting_confirmation",
            step_id=step_id,
            current_step_id=step_id,
        )
