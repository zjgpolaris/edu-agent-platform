from __future__ import annotations

from typing import AsyncIterator

from agent_runtime.adapters.base import RuntimeAdapter
from agent_runtime.completion import CompletionEvaluator
from agent_runtime.event_store import get_run, get_run_state
from agent_runtime.lifecycle import RuntimeRunController
from agent_runtime.models import AgentBudget, AgentContext, AgentPlan, AgentRunState, RuntimeEvent, StepResult


class AgentRuntimeEngine:
    def __init__(self, *, completion_evaluator: CompletionEvaluator | None = None) -> None:
        self.completion_evaluator = completion_evaluator or CompletionEvaluator()

    def create(
        self,
        context: AgentContext,
        *,
        objective: str,
        plan: AgentPlan | None = None,
        idempotency_key: str | None = None,
        policy_caller: str | None = None,
    ) -> AgentRunState:
        budget = AgentBudget(
            max_steps=max(1, len(plan.steps)) if plan else 3,
            max_tool_calls=sum(step.kind == "tool" for step in plan.steps) if plan else 3,
            max_llm_calls=sum(step.kind in {"generation", "subgraph"} or step.side_effect == "external_call" for step in plan.steps) if plan else 3,
        )
        caller = policy_caller or {
            "history_character": "history_ui",
            "essay_grader": "chinese_api",
            "debate": "debate_api",
        }.get(context.agent_type, context.agent_type)
        controller, created = RuntimeRunController.create(
            context,
            objective=objective,
            budget=budget,
            policy_caller=caller,
            idempotency_key=idempotency_key,
        )
        state = AgentRunState.model_validate(created["state"])
        # Idempotent creation may resolve to the already-running canonical run.
        # Never append route/plan events to the newly requested, non-canonical id.
        if created["run_id"] != context.run_id or state.status != "received":
            return state
        controller.route({"agent_type": context.agent_type})
        if plan is not None:
            controller.admit_plan(plan)
        return get_run_state(context.run_id)

    async def stream(
        self,
        context: AgentContext,
        adapter: RuntimeAdapter,
        *,
        evidence_required: bool = False,
        known_source_ids: set[str] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        state = get_run_state(context.run_id)
        if state.status != "planned":
            raise ValueError("runtime execution requires a planned run")
        caller = {"history_character": "history_ui", "essay_grader": "chinese_api", "debate": "debate_api"}.get(context.agent_type, context.agent_type)
        controller = RuntimeRunController.attach(context.run_id, policy_caller=caller)
        started = controller.event("step_started", public_payload={"status": "running"}, next_status="running")
        yield started
        state = get_run_state(context.run_id)
        step_results = dict(state.step_results)
        try:
            async for event in adapter.stream(context, state):
                if event.event == "generation_delta":
                    yield event
                    continue
                result_payload = event.data.get("step_result")
                if isinstance(result_payload, dict):
                    result = StepResult.model_validate(result_payload)
                    step_results[result.step_id] = result
                next_status = None
                if event.event == "waiting_input":
                    next_status = "waiting_input"
                elif event.event == "waiting_confirmation":
                    next_status = "waiting_confirmation"
                event_step_id = str(event.data.get("step_id") or "") or None
                event_operation = str(event.data.get("operation") or "") or None
                persisted = controller.event(
                    event.event,
                    public_payload=event.data,
                    next_status=next_status,
                    step_id=event_step_id,
                    operation=event_operation,
                    current_step_id=event_step_id if event.event == "step_started" else None,
                    step_results={key: value.model_dump() for key, value in step_results.items()},
                )
                yield persisted
                if next_status:
                    return
        except Exception as exc:
            state = get_run_state(context.run_id)
            decision = self.completion_evaluator.evaluate(state, verifier_error=True)
            failed = controller.event(
                "run_failed",
                public_payload={"error": {"code": "runtime_exception", "message": str(exc)[:300]}},
                next_status="failed",
                completion=decision,
            )
            yield failed
            return

        state = get_run_state(context.run_id)
        verifying = controller.event(
            "verification_result",
            public_payload={"status": "verifying"},
            next_status="verifying",
        )
        yield verifying
        state = get_run_state(context.run_id)
        decision = self.completion_evaluator.evaluate(
            state,
            evidence_required=evidence_required,
            known_source_ids=known_source_ids or set(),
        )
        terminal_event = "run_completed" if decision.status in {"completed", "partial"} else "run_failed"
        terminal = controller.event(
            terminal_event,
            public_payload={"completion": decision.model_dump()},
            next_status=decision.status,
            completion=decision,
        )
        yield terminal

    def get(self, run_id: str) -> dict:
        return get_run(run_id)
