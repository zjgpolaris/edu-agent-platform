from __future__ import annotations

from typing import AsyncIterator

from agent_runtime.adapters.base import RuntimeAdapter
from agent_runtime.completion import CompletionEvaluator
from agent_runtime.event_store import append_run_event, create_run, get_run, get_run_state
from agent_runtime.models import AgentContext, AgentPlan, AgentRunState, RuntimeEvent, StepResult


class AgentRuntimeEngine:
    def __init__(self, *, completion_evaluator: CompletionEvaluator | None = None) -> None:
        self.completion_evaluator = completion_evaluator or CompletionEvaluator()

    def create(self, context: AgentContext, *, objective: str, plan: AgentPlan | None = None, idempotency_key: str | None = None) -> AgentRunState:
        created = create_run(context, objective=objective, idempotency_key=idempotency_key)
        state = AgentRunState.model_validate(created["state"])
        # Idempotent creation may resolve to the already-running canonical run.
        # Never append route/plan events to the newly requested, non-canonical id.
        if created["run_id"] != context.run_id or state.status != "received":
            return state
        append_run_event(
            context.run_id,
            expected_revision=state.revision,
            event_type="route_decided",
            public_payload={"agent_type": context.agent_type},
            next_status="routed",
        )
        state = get_run_state(context.run_id)
        if plan is not None:
            append_run_event(
                context.run_id,
                expected_revision=state.revision,
                event_type="plan_created",
                public_payload={"plan_id": plan.plan_id, "step_count": len(plan.steps)},
                next_status="planned",
                plan=plan.model_dump(),
            )
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
        started = append_run_event(
            context.run_id,
            expected_revision=state.revision,
            event_type="step_started",
            public_payload={"status": "running"},
            next_status="running",
        )
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
                current = get_run_state(context.run_id)
                next_status = None
                if event.event == "waiting_input":
                    next_status = "waiting_input"
                elif event.event == "waiting_confirmation":
                    next_status = "waiting_confirmation"
                persisted = append_run_event(
                    context.run_id,
                    expected_revision=current.revision,
                    event_type=event.event,
                    public_payload=event.data,
                    next_status=next_status,
                    step_results={key: value.model_dump() for key, value in step_results.items()},
                )
                yield persisted
                if next_status:
                    return
        except Exception as exc:
            state = get_run_state(context.run_id)
            decision = self.completion_evaluator.evaluate(state, verifier_error=True)
            failed = append_run_event(
                context.run_id,
                expected_revision=state.revision,
                event_type="run_failed",
                public_payload={"error": {"code": "runtime_exception", "message": str(exc)[:300]}},
                next_status="failed",
                completion=decision,
            )
            yield failed
            return

        state = get_run_state(context.run_id)
        verifying = append_run_event(
            context.run_id,
            expected_revision=state.revision,
            event_type="verification_result",
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
        terminal = append_run_event(
            context.run_id,
            expected_revision=state.revision,
            event_type=terminal_event,
            public_payload={"completion": decision.model_dump()},
            next_status=decision.status,
            completion=decision,
        )
        yield terminal

    def get(self, run_id: str) -> dict:
        return get_run(run_id)
