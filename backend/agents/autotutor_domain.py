"""Pure AutoTutor orchestration projections shared by legacy and LangGraph paths."""
from __future__ import annotations

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
