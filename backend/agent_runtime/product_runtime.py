from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_runtime.artifact_store import create_artifact, list_run_artifacts
from agent_runtime.completion import CompletionEvaluator
from agent_runtime.context import RuntimeV2Settings
from agent_runtime.event_store import get_run
from agent_runtime.lifecycle import RuntimeRunController
from agent_runtime.models import (
    AgentBudget,
    AgentContext,
    AgentPlan,
    StepResult,
    default_data_scope,
)


@dataclass(slots=True)
class ObservableProductRun:
    run_id: str
    agent_type: str
    actor_id: str | None
    actor_role: str
    student_id: str | None
    step_id: str
    operation: str
    replay: bool = False

    @classmethod
    def start(
        cls,
        *,
        agent_type: str,
        actor_id: str | None,
        actor_role: str,
        student_id: str | None,
        session_id: str | None,
        trace_id: str,
        objective: str,
        plan: AgentPlan,
        idempotency_key: str | None = None,
        traffic_cohort: str = "unverified",
        rollout_eligible: bool = False,
    ) -> "ObservableProductRun | None":
        settings = RuntimeV2Settings.from_env()
        if not settings.observable_ready:
            return None
        subject = str(actor_id or student_id or session_id or trace_id)
        active, bucket = settings.rollout_decision(agent_type, subject, rollout_eligible=rollout_eligible)
        if not active:
            return None
        role = actor_role if actor_role in {"anonymous", "student", "teacher", "admin"} else "anonymous"
        context = AgentContext(
            run_id=f"run_{uuid4().hex}",
            agent_type=agent_type,
            actor_id=actor_id,
            actor_role=role,
            student_id=student_id,
            session_id=session_id,
            trace_id=trace_id,
            data_scope=default_data_scope(),
            durability_mode="observable",
            config_version=settings.config_version,
            rollout_bucket=bucket,
            traffic_cohort=traffic_cohort,
            rollout_eligible=rollout_eligible,
        )
        policy_caller = {
            "history_character": "history_ui",
            "debate": "debate_api",
        }.get(agent_type, agent_type)
        controller, created = RuntimeRunController.create(
            context,
            objective=objective,
            budget=AgentBudget(
                max_steps=max(1, len(plan.steps)),
                max_tool_calls=sum(step.kind == "tool" for step in plan.steps),
                max_llm_calls=sum(step.kind in {"generation", "subgraph"} or step.side_effect == "external_call" for step in plan.steps),
            ),
            policy_caller=policy_caller,
            idempotency_key=idempotency_key,
            runtime_mode="shadow" if settings.shadow_mode else "active",
        )
        instance = cls(
            run_id=str(created["run_id"]),
            agent_type=agent_type,
            actor_id=actor_id,
            actor_role=role,
            student_id=student_id,
            step_id=plan.steps[0].step_id,
            operation=plan.steps[0].operation,
            replay=created["status"] != "received" or str(created["run_id"]) != context.run_id,
        )
        if instance.replay:
            return instance
        controller.route({"agent_type": agent_type})
        controller.admit_plan(plan)
        controller.start_step(instance.step_id, instance.operation)
        return instance

    def replay_output(self) -> dict[str, Any] | None:
        run = get_run(self.run_id)
        if run["status"] not in {"completed", "partial", "failed", "cancelled"}:
            return None
        artifacts = list_run_artifacts(self.run_id, actor_id=self.actor_id, actor_role=self.actor_role)
        artifact = next((item for item in reversed(artifacts) if item.get("artifact_type") == "final_output"), None)
        if artifact is None:
            return {
                "run_id": self.run_id,
                "run_revision": run["revision"],
                "event_cursor": run["last_event_sequence"],
                "completion_status": run["status"],
                "output_expired": True,
                "idempotent_replay": True,
            }
        return {
            **dict((artifact.get("content") or {}).get("final") or {}),
            "run_id": self.run_id,
            "run_revision": run["revision"],
            "event_cursor": run["last_event_sequence"],
            "idempotent_replay": True,
        }

    def milestone(self, event_type: str, payload: dict[str, Any]) -> int:
        run = get_run(self.run_id)
        if run["status"] in {"completed", "partial", "failed", "cancelled"}:
            return int(run["last_event_sequence"])
        event = RuntimeRunController.attach(
            self.run_id,
            policy_caller={"history_character": "history_ui", "debate": "debate_api"}.get(self.agent_type, self.agent_type),
        ).event(
            event_type,
            public_payload=payload,
            step_id=self.step_id,
            operation=self.operation,
        )
        return event.sequence

    def finish(
        self,
        final: dict[str, Any],
        *,
        status: str,
        verification_status: str,
        reason_codes: list[str],
        source_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if status not in {"completed", "partial"}:
            raise ValueError("observable product finish requires completed or partial")
        artifact = create_artifact(
            self.run_id,
            owner_actor_id=self.actor_id,
            student_id=self.student_id,
            artifact_type="final_output",
            sensitivity="student_content" if self.student_id else "normal",
            content={"final": final},
        )
        step_result = StepResult(
            step_id=self.step_id,
            operation=self.operation,
            status="completed" if status == "completed" else "partial",
            output={"artifact_id": artifact["artifact_id"]},
            source_ids=list(dict.fromkeys(source_ids or [])),
        )
        controller = RuntimeRunController.attach(
            self.run_id,
            policy_caller={"history_character": "history_ui", "debate": "debate_api"}.get(self.agent_type, self.agent_type),
        )
        controller.event(
            "step_completed" if status == "completed" else "step_failed",
            public_payload={"step_result": step_result.model_dump()},
            step_id=self.step_id,
            operation=self.operation,
            step_results={self.step_id: step_result.model_dump()},
        )
        controller.event("verification_result", public_payload={"status": verification_status}, next_status="verifying")
        decision = CompletionEvaluator().from_outcome(
            status=status,
            completed_steps=1 if status == "completed" else 0,
            total_steps=1,
            verification_status=verification_status,
            reason_codes=reason_codes,
            deliverable_refs=[artifact["artifact_id"]],
            unresolved_items=[] if status == "completed" else [self.step_id],
        )
        terminal = controller.event(
            "run_completed",
            public_payload={"completion": decision.model_dump()},
            next_status=status,
            completion=decision,
        )
        current = get_run(self.run_id)
        return {
            **final,
            "run_id": self.run_id,
            "run_revision": current["revision"],
            "event_cursor": terminal.sequence,
            "completion_status": status,
            "verification_summary": decision.model_dump(),
        }

    def fail(self, exc: Exception) -> None:
        run = get_run(self.run_id)
        if run["status"] in {"completed", "partial", "failed", "cancelled"}:
            return
        decision = CompletionEvaluator().from_outcome(
            status="failed",
            completed_steps=0,
            total_steps=1,
            verification_status="failed",
            reason_codes=["product_runtime_exception"],
            unresolved_items=[self.step_id],
        )
        RuntimeRunController.attach(
            self.run_id,
            policy_caller={"history_character": "history_ui", "debate": "debate_api"}.get(self.agent_type, self.agent_type),
        ).event(
            "run_failed",
            public_payload={"error": {"code": "product_runtime_exception", "message": str(exc)[:240]}},
            next_status="failed",
            completion=decision,
        )
