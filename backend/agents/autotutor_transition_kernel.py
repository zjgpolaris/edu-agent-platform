"""Deterministic AutoTutor transition kernel for Legacy and LangGraph executors."""
from __future__ import annotations

import copy
from typing import Any

from agents.autotutor_execution import (
    AutoTutorObservationBundle,
    AutoTutorTransitionDiagnostics,
    AutoTutorTransitionOutcome,
)
from agents.autotutor_domain import replan_policy


def initialize_transition_draft(before: Any):
    from agents import auto_tutor as at

    payload = before.model_dump(mode="json") if hasattr(before, "model_dump") else copy.deepcopy(before)
    state = at.AutoTutorState.model_validate(payload)
    state._sequence = max((step.sequence for step in state.runtime_steps), default=0)
    state._transition_active = True
    state._pending_learning_events.clear()
    state._pending_weakpoint_evidence.clear()
    state._pending_review_memory = None
    return state


def _record_observed_content(state: Any, step: Any, *, kind: str = "practice") -> None:
    from agents import auto_tutor as at

    validation = getattr(step, "content_validation", None)
    if validation is None or validation.status != "verified" or not step.question:
        at._block_content(
            state,
            step,
            str((step.content_blocked or {}).get("reason") or "content_validation_failed"),
        )
        return
    at._record_content_event(
        state,
        step,
        "auto_tutor_content_verified",
        metadata={
            "assessment_id": step.question.get("assessment_id"),
            "assessment_kind": kind,
            "content_validation_status": "verified",
            "mastery_eligible": state.content_gate_mode == "enforce",
            "generation_mode": step.question.get("generation_mode"),
        },
    )
    at._emit(state, "content_gate", "Content Gate · 内容验证", "content_gate", metadata={"knowledge_point": step.knowledge_point})
    at._emit(
        state,
        "reteach" if step.replanned else "teach",
        "Re-teach · 调整讲解" if step.replanned else "Teach · 知识讲解",
        "reteach" if step.replanned else "teach",
        metadata={"knowledge_point": step.knowledge_point, "difficulty": step.difficulty},
    )
    at._emit(state, "act_question", "Act · 有效练习", "act", metadata={"assessment_id": step.question.get("assessment_id")})
    at._emit(state, "observe", "Observe · 等待作答", "observe", "waiting_answer", metadata={"step_index": state.current_step_index})


def _apply_exit_ticket(state: Any, payload: dict[str, Any] | None) -> None:
    from agents import auto_tutor as at

    if not payload:
        primary = state.lesson_plan[0] if state.lesson_plan else None
        if primary is not None:
            at._block_content(state, primary, "exit_ticket_observation_missing")
        return
    state.exit_ticket = at.ExitTicket.model_validate(copy.deepcopy(payload))
    state.phase = "exit_ticket"
    state.status = "awaiting_answer"
    target = state.lesson_plan[0]
    at._record_content_event(
        state,
        target,
        "auto_tutor_content_verified",
        metadata={
            "assessment_id": state.exit_ticket.question.get("assessment_id"),
            "assessment_kind": "exit_ticket",
            "content_validation_status": "verified",
            "mastery_eligible": state.content_gate_mode == "enforce",
            "generation_mode": state.exit_ticket.question.get("generation_mode"),
        },
    )
    at._emit(
        state,
        "exit_ticket",
        "Exit Ticket · 生成退出票",
        "exit_ticket",
        "waiting_answer",
        metadata={
            "knowledge_point": state.exit_ticket.knowledge_point,
            "assessment_id": state.exit_ticket.question.get("assessment_id"),
            "generated_from": state.exit_ticket.generated_from,
        },
    )


def _apply_advance(state: Any, observations: AutoTutorObservationBundle) -> None:
    from agents import auto_tutor as at

    if observations.advance_content:
        next_index = state.current_step_index + 1
        if next_index >= len(state.lesson_plan):
            raise ValueError("observation_advance_content_unexpected")
        state.current_step_index = next_index
        at._emit(
            state,
            "next_step",
            "Next Step · 进入下一知识点",
            "plan",
            metadata={"step_index": next_index, "knowledge_point": state.lesson_plan[next_index].knowledge_point},
        )
        state.lesson_plan[next_index] = at.LessonStep.model_validate(copy.deepcopy(observations.advance_content))
        _record_observed_content(state, state.lesson_plan[next_index])
        return
    _apply_exit_ticket(state, observations.exit_ticket)


def apply_start_transition(state: Any, observations: AutoTutorObservationBundle) -> None:
    from agents import auto_tutor as at

    if not observations.plan or not observations.content:
        raise ValueError("observation_start_incomplete")
    if not state.grade and observations.selection.get("grade"):
        state.grade = observations.selection["grade"]
    state.lesson_plan = [at.LessonStep.model_validate(item) for item in observations.plan]
    state.current_step_index = 0
    state.replans = 0
    at._emit(
        state,
        "plan",
        "Plan · 规划本节课",
        "plan",
        metadata={"targeted_points": [step.knowledge_point for step in state.lesson_plan]},
    )
    state.lesson_plan[0] = at.LessonStep.model_validate(copy.deepcopy(observations.content))
    _record_observed_content(state, state.lesson_plan[0])


def apply_lesson_answer_transition(
    state: Any,
    answer: str,
    observations: AutoTutorObservationBundle,
    *,
    claimed_revision: int,
) -> tuple[bool, Any | None]:
    from agents import auto_tutor as at
    from agents.autotutor_content import answer_feedback as build_answer_feedback

    step = state.lesson_plan[state.current_step_index]
    step.attempts += 1
    is_correct, _ = at._judge(step, answer)
    assessment = at._assessment_from_question(step.question or {})
    feedback = build_answer_feedback(assessment, answer)
    state.answer_feedback = feedback
    step.practice_result = {
        "assessment_id": assessment.assessment_id,
        "objective_id": assessment.objective_id,
        "is_correct": is_correct,
        "selected_answer": feedback["selected_option"],
        "content_validation_status": step.content_validation.status if step.content_validation else "blocked",
    }
    at._record_content_event(
        state,
        step,
        "auto_tutor_practice_answered",
        success=is_correct,
        metadata={
            "assessment_id": assessment.assessment_id,
            "assessment_kind": "practice",
            "content_validation_status": step.content_validation.status if step.content_validation else "blocked",
            "mastery_eligible": False,
            "generation_mode": assessment.generation_mode,
            "is_correct": is_correct,
        },
    )
    at._emit(
        state,
        "judge",
        "Judge · 判分",
        "judge",
        "success" if is_correct else "failed",
        metadata={"knowledge_point": step.knowledge_point, "is_correct": is_correct, "attempt": step.attempts},
    )
    state.step_history.append({
        "step_index": state.current_step_index,
        "knowledge_point": step.knowledge_point,
        "answer": (answer or "")[:1].upper(),
        "is_correct": is_correct,
        "attempt": step.attempts,
    })
    reflection_record = None
    if is_correct:
        step.status = "practiced"
        state.mastery_delta[step.knowledge_point] = 0.0
        _apply_advance(state, observations)
        state.revision = claimed_revision + 1
        return True, None

    if step.attempts < at.MAX_ATTEMPTS_PER_STEP and state.replans < at.MAX_REPLANS:
        if not observations.reflection or not observations.content:
            raise ValueError("observation_reflection_incomplete")
        reflection_record = at.ReflectionRecord.model_validate(copy.deepcopy(observations.reflection))
        at._emit(
            state,
            "reflect",
            "Reflect · 反思诊断",
            "reflect",
            metadata={
                "knowledge_point": step.knowledge_point,
                "diagnosis": reflection_record.diagnosis,
                "adjustment": reflection_record.adjustment,
            },
        )
        state.replans += 1
        step.replanned = True
        later = state.lesson_plan[state.current_step_index + 1:]
        replanned = replan_policy(
            current_difficulty=step.difficulty,
            later_difficulties=[item.difficulty for item in later],
            adjustment=reflection_record.adjustment,
            explanation=reflection_record.explanation,
            later_labels=[item.knowledge_point for item in later],
        )
        step.difficulty = replanned.current_difficulty
        step.strategy = replanned.strategy
        for item, difficulty in zip(later, replanned.later_difficulties, strict=True):
            item.difficulty = difficulty
        at._emit(state, "re_plan", "Re-plan · 调整计划", "re_plan", metadata={"plan_changes": list(replanned.changes)})
        observed_step = at.LessonStep.model_validate(copy.deepcopy(observations.content))
        # Preserve the deterministic judgement just applied; the provider copy
        # contains the same values, but these assignments make ownership clear.
        observed_step.attempts = step.attempts
        observed_step.practice_result = step.practice_result
        state.lesson_plan[state.current_step_index] = observed_step
        state.reflect_log.append(reflection_record)
        _record_observed_content(state, observed_step)
        state.revision = claimed_revision + 1
        return False, reflection_record

    step.status = "struggling"
    state.mastery_delta[step.knowledge_point] = -0.2
    at._emit(state, "give_up_step", "Re-plan · 标记薄弱并前进", "re_plan", metadata={"knowledge_point": step.knowledge_point})
    _apply_advance(state, observations)
    state.revision = claimed_revision + 1
    return False, None


def apply_exit_answer_transition(state: Any, answer: str, *, claimed_revision: int) -> bool:
    from agents import auto_tutor as at

    correct, _ = at._KERNEL_SUBMIT_EXIT_TICKET(state, answer)
    at._KERNEL_FINALIZE(state)
    state.revision = claimed_revision + 1
    return correct


def apply_recovery_transition(_state: Any) -> None:
    return None


def build_transition_outcome(
    *,
    state: Any,
    before: Any,
    observations: AutoTutorObservationBundle,
    last_correct: bool | None,
    reflection: Any | None,
) -> AutoTutorTransitionOutcome:
    from agents import auto_tutor as at

    state.updated_at = float(observations.clock.get("captured_at") or state.updated_at)
    before_sequence = max(
        (getattr(item, "sequence", 0) for item in getattr(before, "runtime_steps", []) or []),
        default=0,
    )
    for item in state.runtime_steps:
        if item.sequence > before_sequence:
            item.latency_ms = None
    public = at._public_state(state)
    if reflection is not None:
        public["reflection"] = at._public_reflection(reflection)
    if last_correct is not None:
        public["last_answer_correct"] = last_correct
    return AutoTutorTransitionOutcome(
        executor_mode=state.executor_mode,
        next_state=state,
        learning_events=list(state._pending_learning_events),
        weakpoint_evidence=list(state._pending_weakpoint_evidence),
        review_memory=state._pending_review_memory,
        runtime_events=[item.model_dump(mode="json") for item in state.runtime_steps],
        runtime_finalize={"run_id": state.run_id} if state.status == "completed" and state.run_id else None,
        public_result=public,
        diagnostics=AutoTutorTransitionDiagnostics(
            transition_id=observations.transition_id,
            observation_external_calls=sum(
                int(observations.call_counts.get(key, 0))
                for key in ("model", "retrieval", "tool", "network")
            ),
        ),
    )


def execute_autotutor_transition(
    *,
    before: Any,
    command: dict[str, Any],
    observations: AutoTutorObservationBundle,
) -> AutoTutorTransitionOutcome:
    """Compute a full outcome without external calls or persistence."""
    from agents import auto_tutor as at

    observations.assert_no_derived_outcome()
    state = initialize_transition_draft(before)
    kind = observations.transition_kind
    last_correct: bool | None = None
    reflection = None
    if kind == "start":
        apply_start_transition(state, observations)
    elif kind == "lesson_answer":
        last_correct, reflection = apply_lesson_answer_transition(
            state,
            str(command.get("answer") or ""),
            observations,
            claimed_revision=int(command.get("claimed_revision", state.revision)),
        )
    elif kind == "exit_ticket_answer":
        last_correct = apply_exit_answer_transition(
            state,
            str(command.get("answer") or ""),
            claimed_revision=int(command.get("claimed_revision", state.revision)),
        )
    elif kind == "recovery_resume":
        apply_recovery_transition(state)
    else:
        raise ValueError("observation_transition_kind_invalid")
    return build_transition_outcome(
        state=state,
        before=before,
        observations=observations,
        last_correct=last_correct,
        reflection=reflection,
    )
