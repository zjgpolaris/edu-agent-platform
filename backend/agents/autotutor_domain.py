"""Pure AutoTutor orchestration projections shared by legacy and LangGraph paths."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal


Difficulty = Literal["easy", "medium", "hard"]
Adjustment = Literal["reteach", "lower_difficulty", "change_example", "advance"]
_DOWNGRADE: dict[str, Difficulty] = {"hard": "medium", "medium": "easy", "easy": "easy"}


@dataclass(frozen=True)
class ReplanPolicyResult:
    current_difficulty: Difficulty
    later_difficulties: tuple[Difficulty, ...]
    strategy: str
    changes: tuple[str, ...]


@dataclass(frozen=True)
class AnswerJudgement:
    is_correct: bool
    selected_option: str
    correct_option: str


@dataclass(frozen=True)
class AutoTutorTransitionCandidate:
    """Side-effect-free result produced from a transition envelope."""

    after: dict[str, Any]
    effect_intents: tuple[dict[str, Any], ...]
    visited_nodes: tuple[str, ...]


def judge_answer(*, answer: str, correct_answer: str, content_verified: bool) -> AnswerJudgement:
    """Judge one bounded multiple-choice answer without state or I/O."""
    if not content_verified:
        raise RuntimeError("invalid content cannot enter judge")
    correct = str(correct_answer or "").strip()[:1].upper()
    if correct not in {"A", "B", "C", "D"}:
        raise RuntimeError("verified assessment has no valid answer")
    selected = str(answer or "").strip()[:1].upper()
    return AnswerJudgement(
        is_correct=bool(selected) and selected == correct,
        selected_option=selected,
        correct_option=correct,
    )


def replan_policy(
    *,
    current_difficulty: Difficulty,
    later_difficulties: list[Difficulty],
    adjustment: Adjustment,
    explanation: str,
    later_labels: list[str] | None = None,
) -> ReplanPolicyResult:
    """Return deterministic re-plan mutations without touching state or I/O."""
    next_current = current_difficulty
    next_later = list(later_difficulties)
    changes: list[str] = []
    labels = later_labels or [str(index + 1) for index in range(len(next_later))]
    if adjustment in {"lower_difficulty", "reteach"}:
        next_current = _DOWNGRADE.get(current_difficulty, "easy")
        if next_current != current_difficulty:
            changes.append(f"当前步难度 {current_difficulty}→{next_current}")
        for index, difficulty in enumerate(next_later):
            if difficulty == "hard":
                next_later[index] = "medium"
                changes.append(f"后续「{labels[index]}」难度 hard→medium")

    if adjustment == "reteach":
        strategy = f"先补讲：{explanation}"
    elif adjustment == "change_example":
        strategy = f"换一个生活化例子重新解释：{explanation}"
    elif adjustment == "lower_difficulty":
        strategy = f"降低认知负担，先讲最基础史实：{explanation}"
    else:
        strategy = explanation
    if not changes:
        changes.append("保持难度，换一道同知识点的题重新检验")
    return ReplanPolicyResult(
        current_difficulty=next_current,
        later_difficulties=tuple(next_later),
        strategy=strategy,
        changes=tuple(changes),
    )


def _apply_content_observation(
    state: dict[str, Any],
    observation: dict[str, Any],
    *,
    step_index: int,
) -> list[str]:
    """Apply only captured retrieval/content-generation output to candidate state."""
    steps = _list(state.get("lesson_plan"))
    if step_index < 0 or step_index >= len(steps):
        raise ValueError("shadow_input_incomplete")
    step = _mapping(steps[step_index])
    steps[step_index] = step
    state["lesson_plan"] = steps
    outcome = str(observation.get("outcome") or "")
    if outcome == "blocked":
        step["status"] = "content_blocked"
        step["question"] = None
        state["status"] = "needs_content"
        state["phase"] = "content_blocked"
        return ["content_gate"]
    if outcome != "verified":
        raise ValueError("shadow_input_incomplete")
    assessment = _mapping(observation.get("assessment"))
    assessment_id = str(assessment.get("assessment_id") or "")
    if not assessment_id:
        raise ValueError("shadow_input_incomplete")
    question = _mapping(step.get("question"))
    question["assessment_id"] = assessment_id
    if assessment.get("difficulty"):
        question["difficulty"] = str(assessment["difficulty"])
        step["difficulty"] = str(assessment["difficulty"])
    step["question"] = question
    step["status"] = "active"
    state["status"] = "awaiting_answer"
    state["phase"] = "lesson"
    return ["retrieve", "content_gate", "teach", "prepare_assessment", "wait_answer"]


def _apply_exit_ticket_observation(
    state: dict[str, Any],
    observation: dict[str, Any],
) -> list[str]:
    if str(observation.get("outcome") or "") == "blocked":
        steps = _list(state.get("lesson_plan"))
        if steps:
            index = min(max(int(state.get("current_step_index") or 0), 0), len(steps) - 1)
            step = steps[index] if isinstance(steps[index], dict) else _mapping(steps[index])
            steps[index] = step
            step["status"] = "content_blocked"
            step["question"] = None
        state["status"] = "needs_content"
        state["phase"] = "content_blocked"
        return ["content_gate"]
    ticket = _mapping(observation.get("ticket"))
    assessment = _mapping(ticket.get("assessment"))
    assessment_id = str(assessment.get("assessment_id") or "")
    if not assessment_id:
        raise ValueError("shadow_input_incomplete")
    state["exit_ticket"] = {
        "knowledge_point": str(ticket.get("knowledge_point") or ""),
        "source_tag": ticket.get("source_tag"),
        "difficulty": str(assessment.get("difficulty") or "medium"),
        "generated_from": str(ticket.get("generated_from") or "fallback"),
        "question": {
            "assessment_id": assessment_id,
            "objective_id": assessment.get("objective_id"),
            "difficulty": str(assessment.get("difficulty") or "medium"),
        },
        "content_validation": {"status": "verified"},
    }
    state["status"] = "awaiting_answer"
    state["phase"] = "exit_ticket"
    return ["prepare_exit_ticket", "wait_answer"]


def _advance_candidate(
    state: dict[str, Any],
    observation: dict[str, Any],
) -> list[str]:
    next_index = int(state.get("current_step_index") or 0) + 1
    steps = _list(state.get("lesson_plan"))
    if next_index < len(steps) and next_index < 2:
        state["current_step_index"] = next_index
        return ["advance", *_apply_content_observation(state, observation, step_index=next_index)]
    return ["advance", *_apply_exit_ticket_observation(state, observation)]


def _verified_mastery_candidate(state: dict[str, Any], *, exit_correct: bool) -> bool:
    steps = _list(state.get("lesson_plan"))
    primary = _mapping(steps[0]) if steps else {}
    practice = _mapping(primary.get("practice_result"))
    ticket = _mapping(state.get("exit_ticket"))
    ticket_question = _mapping(ticket.get("question"))
    practice_id = str(practice.get("assessment_id") or "")
    exit_id = str(ticket_question.get("assessment_id") or "")
    practice_objective = str(practice.get("objective_id") or "")
    exit_objective = str(ticket_question.get("objective_id") or "")
    return bool(
        state.get("content_gate_mode") == "enforce"
        and practice.get("content_validation_status") == "verified"
        and practice.get("is_correct") is True
        and exit_correct
        and practice_id
        and exit_id
        and practice_id != exit_id
        and practice_objective
        and practice_objective == exit_objective
    )


def _finalize_candidate(state: dict[str, Any]) -> list[dict[str, Any]]:
    result = _mapping(state.get("exit_ticket_result"))
    steps = _list(state.get("lesson_plan"))
    primary = steps[0] if steps and isinstance(steps[0], dict) else (_mapping(steps[0]) if steps else {})
    verified = bool(state.get("verified_mastery"))
    if verified and primary:
        primary["status"] = "mastered"
    if verified:
        weakpoint_action = "independent_correct_evidence_recorded"
    elif result and (not bool(result.get("is_correct")) or primary.get("status") == "struggling"):
        weakpoint_action = "weakpoint_recorded"
    elif result and state.get("content_gate_mode") in {"off", "shadow"}:
        weakpoint_action = "rollout_unverified_no_mastery_write"
    else:
        weakpoint_action = "not_recorded"
    state["evidence"] = {
        "exit_ticket_recorded": bool(result),
        "weakpoint_action": weakpoint_action,
        "review_action": "no_new_review_needed",
        "verified_mastery": verified,
    }
    state["phase"] = "completed"
    state["status"] = "completed"
    intents: list[dict[str, Any]] = []
    if result:
        intents.append({"kind": "learning_event"})
        intents.append({"kind": "review"})
    if weakpoint_action != "not_recorded":
        intents.append({"kind": "weakpoint"})
    return intents


def apply_autotutor_transition(envelope: dict[str, Any]) -> AutoTutorTransitionCandidate:
    """Independently compute a candidate state without I/O or Legacy after-state access."""
    if envelope.get("schema_version") != "v1.48.1-transition":
        raise ValueError("shadow_input_incomplete")
    if any(key in envelope for key in ("legacy_after", "expected_projection", "expected_state")):
        raise ValueError("shadow_expected_state_forbidden")
    kind = str(envelope.get("transition_kind") or "")
    before = _mapping(envelope.get("before"))
    command = _mapping(envelope.get("command"))
    observations = _mapping(envelope.get("observations"))
    state = copy.deepcopy(before)
    visited: list[str] = []
    effect_intents: list[dict[str, Any]] = []

    if kind == "start":
        plan = []
        for raw in _list(observations.get("plan")):
            item = _mapping(raw)
            plan.append({
                "knowledge_point": str(item.get("knowledge_point") or ""),
                "difficulty": str(item.get("difficulty") or "medium"),
                "status": "pending",
                "attempts": 0,
                "replanned": False,
                "question": None,
            })
        if not plan:
            raise ValueError("shadow_input_incomplete")
        state["lesson_plan"] = plan
        state["current_step_index"] = 0
        state["replans"] = 0
        visited.append("plan")
        visited.extend(_apply_content_observation(state, _mapping(observations.get("content")), step_index=0))
    elif kind == "lesson_answer":
        steps = _list(state.get("lesson_plan"))
        index = int(state.get("current_step_index") or 0)
        if index < 0 or index >= len(steps):
            raise ValueError("shadow_input_incomplete")
        step = _mapping(steps[index])
        steps[index] = step
        state["lesson_plan"] = steps
        step["attempts"] = int(step.get("attempts") or 0) + 1
        question = _mapping(step.get("question"))
        judgement = judge_answer(
            answer=str(command.get("answer") or ""),
            correct_answer=str(question.get("answer") or ""),
            content_verified=True,
        )
        visited.append("judge")
        step["practice_result"] = {
            "assessment_id": question.get("assessment_id"),
            "objective_id": question.get("objective_id"),
            "is_correct": judgement.is_correct,
            "content_validation_status": "verified",
        }
        if judgement.is_correct:
            step["status"] = "practiced"
            visited.extend(_advance_candidate(state, _mapping(observations.get("advance"))))
        elif step["attempts"] < 3 and int(state.get("replans") or 0) < 3:
            reflection = _mapping(observations.get("reflection"))
            adjustment = str(reflection.get("adjustment") or "")
            if adjustment not in {"reteach", "lower_difficulty", "change_example", "advance"}:
                raise ValueError("shadow_input_incomplete")
            visited.append("reflect")
            state["replans"] = int(state.get("replans") or 0) + 1
            step["replanned"] = True
            later = [item if isinstance(item, dict) else _mapping(item) for item in steps[index + 1:]]
            replan = replan_policy(
                current_difficulty=str(step.get("difficulty") or "medium"),  # type: ignore[arg-type]
                later_difficulties=[str(item.get("difficulty") or "medium") for item in later],  # type: ignore[list-item]
                adjustment=adjustment,  # type: ignore[arg-type]
                explanation=str(reflection.get("explanation") or ""),
                later_labels=[str(item.get("knowledge_point") or "") for item in later],
            )
            step["difficulty"] = replan.current_difficulty
            step["strategy"] = replan.strategy
            for item, difficulty in zip(later, replan.later_difficulties, strict=True):
                item["difficulty"] = difficulty
            state["reflect_log"] = [
                *_list(state.get("reflect_log")),
                {
                    "step_index": index,
                    "knowledge_point": step.get("knowledge_point"),
                    "adjustment": adjustment,
                },
            ]
            visited.append("re_plan")
            visited.extend(_apply_content_observation(state, _mapping(observations.get("content")), step_index=index))
        else:
            step["status"] = "struggling"
            visited.append("re_plan")
            visited.extend(_advance_candidate(state, _mapping(observations.get("advance"))))
    elif kind == "exit_ticket_answer":
        ticket = _mapping(state.get("exit_ticket"))
        question = _mapping(ticket.get("question"))
        judgement = judge_answer(
            answer=str(command.get("answer") or ""),
            correct_answer=str(question.get("answer") or ""),
            content_verified=True,
        )
        visited.append("verify_exit_ticket")
        verified = _verified_mastery_candidate(state, exit_correct=judgement.is_correct)
        state["verified_mastery"] = verified
        state["exit_ticket_result"] = {
            "is_correct": judgement.is_correct,
            "selected_answer": judgement.selected_option,
            "correct_answer": judgement.correct_option,
            "verified_mastery": verified,
        }
        effect_intents = _finalize_candidate(state)
        visited.extend(["build_evidence_intent", "finalize"])
    elif kind == "recovery_resume":
        visited.append("recovery_resume")
    else:
        raise ValueError("shadow_input_incomplete")

    return AutoTutorTransitionCandidate(
        after=state,
        effect_intents=tuple(effect_intents),
        visited_nodes=tuple(visited),
    )


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def next_action_for_state(state: dict[str, Any]) -> str:
    status = str(state.get("status") or "")
    phase = str(state.get("phase") or "")
    if status == "completed" or phase == "completed":
        return "finalize"
    if status == "needs_content" or phase == "content_blocked":
        return "content_blocked"
    if phase == "exit_ticket":
        return "wait_exit_ticket"
    if status == "awaiting_answer":
        return "wait_answer"
    return "unknown"


def canonical_autotutor_projection(value: Any) -> dict[str, Any]:
    """Project orchestration state only; exclude IDs, answers, text and latency."""
    state = _mapping(value)
    steps: list[dict[str, Any]] = []
    for raw_step in _list(state.get("lesson_plan")):
        step = _mapping(raw_step)
        question = _mapping(step.get("question"))
        steps.append({
            "knowledge_point": str(step.get("knowledge_point") or "")[:120],
            "difficulty": str(step.get("difficulty") or ""),
            "status": str(step.get("status") or ""),
            "attempts": max(0, int(step.get("attempts") or 0)),
            "replanned": bool(step.get("replanned")),
            "assessment_fingerprint": str(question.get("assessment_id") or "")[:160] or None,
        })
    reflections = [_mapping(item) for item in _list(state.get("reflect_log"))]
    latest_reflection = reflections[-1] if reflections else {}
    exit_result = _mapping(state.get("exit_ticket_result"))
    exit_ticket = _mapping(state.get("exit_ticket"))
    evidence = _mapping(state.get("evidence"))
    verified = bool(state.get("verified_mastery"))
    mastery = _mapping(state.get("mastery"))
    if mastery:
        verified = verified or mastery.get("status") == "verified"
    evidence_intents = sorted(
        key
        for key, present in {
            "learning_event": bool(evidence.get("exit_ticket_recorded")),
            "weakpoint": bool(evidence.get("weakpoint_action") and evidence.get("weakpoint_action") != "not_recorded"),
            "review": bool(evidence.get("review_action") and evidence.get("review_action") != "not_scheduled"),
        }.items()
        if present
    )
    return {
        "schema_version": "v1.48-shadow",
        "status": str(state.get("status") or ""),
        "phase": str(state.get("phase") or ""),
        "current_step_index": max(0, int(state.get("current_step_index") or 0)),
        "replans": max(0, int(state.get("replans") or 0)),
        "steps": steps,
        "reflection_adjustment": str(latest_reflection.get("adjustment") or "") or None,
        "exit_ticket": {
            "prepared": bool(exit_ticket) or str(state.get("phase") or "") in {"exit_ticket", "completed"},
            "passed": exit_result.get("is_correct") if isinstance(exit_result.get("is_correct"), bool) else None,
        },
        "verified_mastery": verified,
        "evidence_intents": evidence_intents,
        "next_action": next_action_for_state(state),
    }


_PARITY_FIELDS = {
    "status": "status_mismatch",
    "phase": "phase_mismatch",
    "current_step_index": "step_index_mismatch",
    "replans": "plan_shape_mismatch",
    "steps": "plan_shape_mismatch",
    "reflection_adjustment": "reflection_action_mismatch",
    "exit_ticket": "exit_ticket_mismatch",
    "verified_mastery": "verified_mastery_mismatch",
    "evidence_intents": "evidence_intent_mismatch",
    "next_action": "next_action_mismatch",
}


def parity_mismatch_reasons(legacy: dict[str, Any], graph: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field, reason in _PARITY_FIELDS.items():
        if legacy.get(field) != graph.get(field) and reason not in reasons:
            reasons.append(reason)
    return reasons
