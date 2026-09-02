"""Side-effect-free observation acquisition for AutoTutor v1.49.1 transitions."""
from __future__ import annotations

import copy
import time
from uuid import uuid4
from typing import Any

from agents.autotutor_execution import (
    AutoTutorExecutionContext,
    AutoTutorObservationBundle,
)


class DefaultAutoTutorObservationProvider:
    """Acquire external inputs once on a private state clone.

    The compatibility rules run with ``_transition_active`` so learning/Runtime
    writes are queued only on the disposable clone and trace emission is denied.
    Only source observations are returned; the clone itself never leaves here.
    """

    def prepare(
        self,
        *,
        before: Any,
        command: dict[str, Any],
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundle:
        from agents import auto_tutor as at

        before_dump = before.model_dump(mode="json") if hasattr(before, "model_dump") else copy.deepcopy(before)
        candidate = at.AutoTutorState.model_validate(copy.deepcopy(before_dump))
        candidate._sequence = max((step.sequence for step in candidate.runtime_steps), default=0)
        candidate._transition_active = True
        candidate._observation_capture = True
        candidate._pending_learning_events.clear()
        candidate._pending_weakpoint_evidence.clear()
        candidate._pending_review_memory = None
        transition_kind = str(command.get("transition_kind") or "")
        if transition_kind not in {"start", "lesson_answer", "exit_ticket_answer", "recovery_resume"}:
            raise ValueError("observation_transition_kind_invalid")
        tool_ctx = at._tool_context(candidate.student_id, context.actor_id, context.actor_role)
        plan: list[dict[str, Any]] = []
        content: dict[str, Any] | None = None
        advance_content: dict[str, Any] | None = None
        reflection: dict[str, Any] | None = None
        exit_ticket: dict[str, Any] | None = None
        calls = {
            "model": 0,
            "retrieval": 0,
            "tool": 0,
            "network": 0,
            "clock_reads": 1,
            "id_allocations": 1,
            "selection_seed_reads": 1,
        }

        if transition_kind == "start":
            profile = at.get_student_profile(candidate.student_id)
            try:
                weakpoints = at.get_weakpoints(candidate.student_id)
            except Exception:
                weakpoints = []
            focus_tags = [str(item) for item in (command.get("focus_tags") or []) if str(item).strip()]
            if focus_tags:
                focus = set(focus_tags)
                existing = {str(item.get("knowledge_tag") or "") for item in weakpoints}
                extra = [
                    {"knowledge_tag": tag, "wrong_count": 1, "last_wrong_at": "", "source": "assignment"}
                    for tag in focus_tags if tag not in existing
                ]
                weakpoints = [item for item in weakpoints if item.get("knowledge_tag") in focus] + extra + [
                    item for item in weakpoints if item.get("knowledge_tag") not in focus
                ]
            if not candidate.grade:
                candidate.grade = getattr(profile, "grade", None)
            candidate.lesson_plan = at._generate_plan(
                candidate,
                weakpoints,
                profile,
                focus_tags=focus_tags or None,
                focus_reason=str(command.get("focus_reason") or "") or None,
            )
            plan = [
                {
                    "knowledge_point": step.knowledge_point,
                    "source_tag": step.source_tag,
                    "difficulty": step.difficulty,
                    "strategy": step.strategy,
                    "tool": step.tool,
                    "rationale": step.rationale,
                }
                for step in candidate.lesson_plan
            ]
            at._KERNEL_ACT(candidate, candidate.lesson_plan[0], tool_ctx)
            content = candidate.lesson_plan[0].model_dump(mode="json")
            calls["retrieval"] = 1
            calls["tool"] = 1
        elif transition_kind in {"lesson_answer", "exit_ticket_answer"}:
            answer = str(command.get("answer") or "")
            previous_reflections = len(candidate.reflect_log)
            previous_index = candidate.current_step_index
            at._KERNEL_MUTATE_ANSWER(candidate, answer, tool_ctx)
            if len(candidate.reflect_log) > previous_reflections:
                reflection = candidate.reflect_log[-1].model_dump(mode="json")
                calls["model"] = 1
                calls["retrieval"] = 1
                calls["tool"] = 1
            if candidate.phase in {"lesson", "content_blocked"} and candidate.lesson_plan:
                observed = candidate.lesson_plan[candidate.current_step_index].model_dump(mode="json")
                if candidate.current_step_index != previous_index:
                    advance_content = observed
                    calls["retrieval"] = 1
                    calls["tool"] = 1
                else:
                    content = observed
            if candidate.exit_ticket is not None:
                exit_ticket = candidate.exit_ticket.model_dump(mode="json")

        bundle = AutoTutorObservationBundle(
            transition_id=f"ato_{uuid4().hex}",
            transition_kind=transition_kind,  # type: ignore[arg-type]
            command=copy.deepcopy(command),
            plan=plan,
            content=content,
            reflection=reflection,
            advance_content=advance_content,
            exit_ticket=exit_ticket,
            clock={"captured_at": time.time()},
            identifiers={"session_id": candidate.session_id, "trace_id": candidate.trace_id},
            selection={
                "seed_scope": f"{candidate.session_id}:{candidate.revision}:{transition_kind}",
                "grade": str(candidate.grade or ""),
            },
            call_counts=calls,
            provenance={"provider": "default_v1.49.1", "source": "single_external_call_set"},
        )
        bundle.assert_no_derived_outcome()
        if before_dump != (before.model_dump(mode="json") if hasattr(before, "model_dump") else before):
            raise RuntimeError("observation_provider_mutated_before")
        return bundle


DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER = DefaultAutoTutorObservationProvider()
