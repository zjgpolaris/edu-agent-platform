"""Source-only observation acquisition for AutoTutor transitions."""
from __future__ import annotations

import copy
import time
from typing import Any
from uuid import uuid4

from agents.autotutor_execution import AutoTutorExecutionContext, AutoTutorObservationBundle


def _blocked_payload(step: Any, reason: str) -> dict[str, Any]:
    return {
        "objective_label": step.knowledge_point,
        "message": "当前教材证据或审定题目不足，暂不生成题目，也不会改变你的掌握记录。",
        "reason": reason,
        "suggested_actions": ["换一个相关知识点", "进入随问继续提问"],
    }


def _acquire_content_observation(
    *,
    before: Any,
    raw_step: Any,
    step_index: int,
    tool_context: Any,
    correction: str = "",
) -> dict[str, Any]:
    """Acquire retrieval/content into a detached step DTO without state mutation."""
    from agents import auto_tutor as at

    step = at.LessonStep.model_validate(
        raw_step.model_dump(mode="json") if hasattr(raw_step, "model_dump") else copy.deepcopy(raw_step)
    )
    step.status = "active"
    step.objective = step.objective or at.build_learning_objective(
        step.knowledge_point,
        source_tag=step.source_tag,
        grade=before.grade,
        lesson=before.lesson_id,
        misconception_hint=step.rationale,
    )
    retrieval_data: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    retrieval_error: str | None = None
    try:
        result = at.run_tool(
            "search_history_knowledge",
            {
                "query": step.knowledge_point,
                "grade": before.grade,
                "lesson": before.lesson_id,
                "topic": step.objective.entity or step.knowledge_point,
                "k": 4,
            },
            context=tool_context,
        )
        if result.ok:
            retrieval_data = dict(result.data or {})
            sources = [item for item in retrieval_data.get("sources", []) if isinstance(item, dict)]
        else:
            retrieval_error = result.error.message if result.error else "retrieval_failed"
    except Exception as exc:
        retrieval_error = exc.__class__.__name__

    current_assessment_id = str((step.question or {}).get("assessment_id") or "")
    if current_assessment_id and current_assessment_id not in step.assessment_history:
        step.assessment_history.append(current_assessment_id)
    prepared = at.prepare_content(
        step.objective,
        retrieval_data,
        kind="practice",
        variant_index=step.attempts,
        target_difficulty=step.difficulty,
        excluded_assessment_ids=set(step.assessment_history),
        preferred_cognitive_actions=["recall", "explain"] if step.replanned else None,
        selection_seed=f"{before.session_id}:{step_index}:{step.attempts}",
    )
    step.evidence_decision = prepared.evidence
    step.content_validation = prepared.validation
    step.content_version = prepared.content_version
    step.evidence_label = prepared.evidence_label
    step.sources = [item for item in sources if item.get("answer_bearing") is True][:4]
    if prepared.validation.status != "verified" or prepared.teaching is None or prepared.assessment is None:
        reason = prepared.blocked_reason or retrieval_error or "content_validation_failed"
        step.status = "content_blocked"
        step.question = None
        step.teaching = None
        step.content_blocked = _blocked_payload(step, reason)
        return step.model_dump(mode="json")

    step.teaching = prepared.teaching.model_dump(mode="json")
    if step.replanned and correction.strip():
        step.teaching["explanation"] = f"先纠正刚才的混淆：{correction.strip()} {step.teaching['explanation']}"
        step.teaching["example"] = f"先对照你刚才选择的说法，再判断它回答的是不是“{step.objective.target_outcome}”。"
    step.question = at.assessment_to_question(prepared.assessment)
    step.difficulty = prepared.assessment.difficulty
    if prepared.assessment.assessment_id not in step.assessment_history:
        step.assessment_history.append(prepared.assessment.assessment_id)
    step.content_blocked = None
    return step.model_dump(mode="json")


def _acquire_exit_ticket_observation(*, before: Any, target: Any, generated_from: str) -> dict[str, Any] | None:
    from agents import auto_tutor as at

    if target.objective is None:
        return None
    retrieval_data = {
        "sources": target.sources,
        "evidence_sufficiency": target.evidence_decision.model_dump(mode="json") if target.evidence_decision else {},
    }
    practice_id = str((target.question or {}).get("assessment_id") or "") or None
    practice = at._assessment_from_question(target.question) if target.question else None
    prepared = at.prepare_content(
        target.objective,
        retrieval_data,
        kind="exit_ticket",
        target_difficulty="medium",
        excluded_assessment_ids=set(target.assessment_history),
        preferred_cognitive_actions=["apply"],
        selection_seed=f"{before.session_id}:exit-ticket:{target.objective.objective_id}",
        excluded_assessment_id=practice_id,
        excluded_assessment=practice,
    )
    if prepared.validation.status != "verified" or prepared.assessment is None:
        return None
    return at.ExitTicket(
        knowledge_point=target.knowledge_point,
        source_tag=target.source_tag,
        difficulty=prepared.assessment.difficulty,
        strategy="课后退出票检验：用一道迁移题确认本节辅导是否真正生效。",
        question=at.assessment_to_question(prepared.assessment),
        sources=target.sources[:4],
        generated_from=generated_from,
        objective=target.objective,
        content_validation=prepared.validation,
        content_version=prepared.content_version,
        evidence_label=prepared.evidence_label,
    ).model_dump(mode="json")


class DefaultAutoTutorObservationProvider:
    """Capture nondeterministic inputs once; never execute a transition mutation."""

    def prepare(
        self,
        *,
        before: Any,
        command: dict[str, Any],
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundle:
        from agents import auto_tutor as at
        from agents.autotutor_domain import replan_policy

        before_dump = before.model_dump(mode="json")
        kind = str(command.get("transition_kind") or "")
        if kind not in {"start", "lesson_answer", "exit_ticket_answer", "recovery_resume"}:
            raise ValueError("observation_transition_kind_invalid")
        tool_context = at._tool_context(before.student_id, context.actor_id, context.actor_role)
        plan: list[dict[str, Any]] = []
        content = None
        advance_content = None
        reflection = None
        exit_ticket = None
        grade = before.grade
        calls = {
            "model": 0,
            "retrieval": 0,
            "tool": 0,
            "network": 0,
            "clock_reads": 1,
            "id_allocations": 1,
            "selection_seed_reads": 1,
        }

        if kind == "start":
            profile = at.get_student_profile(before.student_id)
            try:
                weakpoints = at.get_weakpoints(before.student_id)
            except Exception:
                weakpoints = []
            focus_tags = [str(item) for item in command.get("focus_tags") or [] if str(item).strip()]
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
            grade = grade or getattr(profile, "grade", None)
            plan_state = before.model_copy(deep=True)
            plan_state.grade = grade
            steps = at._generate_plan(
                plan_state,
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
                for step in steps
            ]
            content = _acquire_content_observation(
                before=plan_state,
                raw_step=steps[0],
                step_index=0,
                tool_context=tool_context,
            )
            calls["retrieval"] = calls["tool"] = 1

        elif kind == "lesson_answer":
            index = before.current_step_index
            current = before.lesson_plan[index]
            answer = str(command.get("answer") or "")
            is_correct, _ = at._judge(current, answer)
            attempts = current.attempts + 1
            retryable = not is_correct and attempts < at.MAX_ATTEMPTS_PER_STEP and before.replans < at.MAX_REPLANS
            if retryable:
                record = at._acquire_reflection_observation(current, answer, step_index=index)
                reflection = record.model_dump(mode="json")
                local = current.model_copy(deep=True)
                local.attempts = attempts
                local.replanned = True
                later = before.lesson_plan[index + 1:]
                replanned = replan_policy(
                    current_difficulty=local.difficulty,
                    later_difficulties=[item.difficulty for item in later],
                    adjustment=record.adjustment,
                    explanation=record.explanation,
                    later_labels=[item.knowledge_point for item in later],
                )
                local.difficulty = replanned.current_difficulty
                local.strategy = replanned.strategy
                feedback = at.build_answer_feedback(at._assessment_from_question(current.question or {}), answer)
                content = _acquire_content_observation(
                    before=before,
                    raw_step=local,
                    step_index=index,
                    tool_context=tool_context,
                    correction=str(feedback.get("correction") or ""),
                )
                calls["model"] = calls["retrieval"] = calls["tool"] = 1
            else:
                next_index = index + 1
                if next_index < len(before.lesson_plan) and next_index < at.MAX_STEPS:
                    advance_content = _acquire_content_observation(
                        before=before,
                        raw_step=before.lesson_plan[next_index],
                        step_index=next_index,
                        tool_context=tool_context,
                    )
                    calls["retrieval"] = calls["tool"] = 1
                else:
                    target = before.lesson_plan[0].model_copy(deep=True)
                    if not is_correct:
                        target.status = "struggling"
                        generated_from = "struggling_step"
                    elif target.replanned:
                        generated_from = "replanned_step"
                    else:
                        generated_from = "fallback"
                    exit_ticket = _acquire_exit_ticket_observation(
                        before=before,
                        target=target,
                        generated_from=generated_from,
                    )

        bundle = AutoTutorObservationBundle(
            transition_id=f"ato_{uuid4().hex}",
            transition_kind=kind,
            command=copy.deepcopy(command),
            plan=plan,
            content=content,
            reflection=reflection,
            advance_content=advance_content,
            exit_ticket=exit_ticket,
            clock={"captured_at": time.time()},
            identifiers={"session_id": before.session_id, "trace_id": before.trace_id},
            selection={"seed_scope": f"{before.session_id}:{before.revision}:{kind}", "grade": str(grade or "")},
            call_counts=calls,
            provenance={"provider": "source_only_v1.49.2", "source": "single_external_call_set"},
        )
        bundle.assert_no_derived_outcome()
        if before.model_dump(mode="json") != before_dump:
            raise RuntimeError("observation_provider_mutated_before")
        return bundle


DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER = DefaultAutoTutorObservationProvider()
