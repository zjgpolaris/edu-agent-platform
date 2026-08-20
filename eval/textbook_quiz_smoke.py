from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from textbook_learning.schema import TextbookQuizRequest
import textbook_learning.service as quiz_service


class FailingLlm:
    def invoke(self, _messages):
        raise RuntimeError("credentials are not configured")


class UngroundedLlm:
    def invoke(self, _messages):
        class Response:
            content = '{"questions":[{"id":"q1","type":"single_choice","question":"猜一猜？","options":["一","二","三","四"],"answer":"A","explanation":"无来源","source_item_ids":["invented"]}]}'

        return Response()


def _assert_grounded(result, expected_count: int) -> None:
    assert result.generation_source == "trusted_lesson", result
    assert len(result.questions) == expected_count, result
    assert "credential" not in str(result.model_dump()).lower(), result
    for question in result.questions:
        assert question.question and question.answer and question.explanation, question
        assert question.source_item_ids and all(value.startswith("lesson-7-item-") for value in question.source_item_ids), question
        if question.type == "single_choice":
            assert question.options is not None and len(question.options) == 4, question
            assert len(set(question.options)) == 4, question
            assert question.answer in "ABCD", question
            assert all(not option.startswith(("A.", "B.", "C.", "D.")) for option in question.options), question


def model_failure_uses_trusted_lesson() -> None:
    original = quiz_service.llm_fast
    quiz_service.llm_fast = FailingLlm()
    try:
        result = quiz_service.generate_quiz(
            TextbookQuizRequest(
                book_id="history-grade-7b",
                lesson_id="lesson-7",
                count=5,
            )
        )
    finally:
        quiz_service.llm_fast = original
    _assert_grounded(result, 5)
    assert result.generation_reason == "model_unavailable", result


def ungrounded_model_output_is_replaced() -> None:
    original = quiz_service.llm_fast
    quiz_service.llm_fast = UngroundedLlm()
    try:
        result = quiz_service.generate_quiz(
            TextbookQuizRequest(
                book_id="history-grade-7b",
                lesson_id="lesson-7",
                count=3,
                question_types=["single_choice"],
            )
        )
    finally:
        quiz_service.llm_fast = original
    _assert_grounded(result, 3)
    assert result.generation_reason == "model_output_invalid", result


def focused_quiz_uses_requested_item() -> None:
    original = quiz_service.llm_fast
    quiz_service.llm_fast = FailingLlm()
    try:
        result = quiz_service.generate_quiz(
            TextbookQuizRequest(
                book_id="history-grade-7b",
                lesson_id="lesson-7",
                count=1,
                focus_item_id="lesson-7-item-3",
                question_types=["single_choice"],
            )
        )
    finally:
        quiz_service.llm_fast = original
    _assert_grounded(result, 1)
    assert result.questions[0].source_item_ids == ["lesson-7-item-3"], result
    assert "澶渊之盟" in result.questions[0].question, result


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


if __name__ == "__main__":
    cases = [
        ("model_failure_uses_trusted_lesson", model_failure_uses_trusted_lesson),
        ("ungrounded_model_output_is_replaced", ungrounded_model_output_is_replaced),
        ("focused_quiz_uses_requested_item", focused_quiz_uses_requested_item),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    print(f"textbook_quiz_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
