"""Deterministic coverage for real AutoTutor difficulty adaptation."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-adaptive.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents.auto_tutor import _load_persisted_session, _persist_session, start_session, submit_answer  # noqa: E402
from agents.autotutor_content import build_learning_objective, find_curated_content, prepare_content  # noqa: E402
from services.weakpoint_service import get_weakpoints  # noqa: E402


PILOTS = [
    "戊戌变法失败原因",
    "洋务运动目的",
    "赤壁之战的影响",
    "辛亥革命历史意义",
    "鸦片战争影响",
]


def _wrong_answer(session_id: str) -> str:
    state = _load_persisted_session(session_id)
    assert state is not None
    question = state.lesson_plan[state.current_step_index].question or {}
    correct = str(question["answer"])
    return next(letter for letter in "ABCD" if letter != correct)


def main() -> None:
    passed = 0
    for index, objective_label in enumerate(PILOTS):
        started = start_session(
            f"adaptive-{index}",
            grade="八年级上册",
            focus_tags=[objective_label],
        )
        initial = started["current_question"]
        assert initial["difficulty"] == "medium", (objective_label, initial)
        first_id = initial["assessment_id"]
        adapted = submit_answer(
            started["session_id"],
            _wrong_answer(started["session_id"]),
            expected_revision=started["revision"],
            idempotency_key=f"adaptive-answer-{index}-1",
        )
        question = adapted["current_question"]
        ok = bool(
            question
            and question["assessment_id"] != first_id
            and question["difficulty"] == "easy"
            and question["cognitive_action"] in {"recall", "explain"}
            and question["adaptation"]
            and adapted["lesson_plan"][0]["difficulty"] == question["difficulty"]
        )
        print(
            ("OK" if ok else "FAIL"),
            objective_label,
            f"{first_id}->{question.get('assessment_id') if question else None}",
            question.get("difficulty") if question else None,
        )
        passed += int(ok)

        objective = build_learning_objective(objective_label, grade="八年级上册")
        initial_content = prepare_content(objective, {}, kind="practice", target_difficulty="medium")
        easy_one = prepare_content(
            objective,
            {},
            kind="practice",
            target_difficulty="easy",
            excluded_assessment_ids={initial_content.assessment.assessment_id},
            preferred_cognitive_actions=["recall", "explain"],
        )
        easy_two = prepare_content(
            objective,
            {},
            kind="practice",
            target_difficulty="easy",
            excluded_assessment_ids={
                initial_content.assessment.assessment_id,
                easy_one.assessment.assessment_id,
            },
            preferred_cognitive_actions=["recall", "explain"],
        )
        blocked = prepare_content(
            objective,
            {},
            kind="practice",
            target_difficulty="easy",
            excluded_assessment_ids={
                initial_content.assessment.assessment_id,
                easy_one.assessment.assessment_id,
                easy_two.assessment.assessment_id,
            },
            preferred_cognitive_actions=["recall", "explain"],
        )
        assert easy_one.validation.status == "verified"
        assert easy_two.validation.status == "verified"
        assert easy_one.assessment.assessment_id != easy_two.assessment.assessment_id
        assert blocked.validation.status == "blocked"
        assert blocked.assessment is None
        assert "no_fresh_assessment_for_target_difficulty" in blocked.validation.reason_codes

    blocked_start = start_session(
        "adaptive-blocked",
        grade="八年级上册",
        focus_tags=["洋务运动目的"],
    )
    blocked_state = _load_persisted_session(blocked_start["session_id"])
    assert blocked_state is not None
    blocked_objective = blocked_state.lesson_plan[0].objective
    assert blocked_objective is not None
    curated = find_curated_content(blocked_objective)
    assert curated is not None
    blocked_state.lesson_plan[0].assessment_history.extend(
        item.assessment_id for item in curated.practice_items if item.difficulty == "easy"
    )
    _persist_session(blocked_state)
    blocked_result = submit_answer(
        blocked_start["session_id"],
        _wrong_answer(blocked_start["session_id"]),
        expected_revision=blocked_start["revision"],
        idempotency_key="adaptive-blocked-answer",
    )
    blocked_ok = bool(
        blocked_result["status"] == "needs_content"
        and blocked_result["phase"] == "content_blocked"
        and blocked_result["current_question"] is None
        and not get_weakpoints("adaptive-blocked")
    )
    print(("OK" if blocked_ok else "FAIL"), "no_fresh_remedial_item_fail_closed")
    passed += int(blocked_ok)

    total = len(PILOTS) + 1
    print(f"autotutor_adaptive_difficulty={passed}/{total}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
