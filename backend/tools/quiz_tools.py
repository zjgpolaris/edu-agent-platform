from __future__ import annotations

from pydantic import BaseModel, Field

from textbook_learning.schema import QuestionType, TextbookQuizRequest
from textbook_learning.service import generate_quiz as generate_textbook_quiz, get_lesson
from tools.base import ToolResult


class GenerateQuizInput(BaseModel):
    book_id: str = Field(min_length=1)
    lesson_id: str = Field(min_length=1)
    question_types: list[QuestionType] = Field(default_factory=lambda: ["single_choice", "short_answer"])
    count: int = Field(default=3, ge=1, le=10)
    focus_item_id: str | None = None


def generate_quiz(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, GenerateQuizInput) else GenerateQuizInput.model_validate(payload)
    lesson = get_lesson(req.book_id, req.lesson_id)
    quiz = generate_textbook_quiz(
        TextbookQuizRequest(
            book_id=req.book_id,
            lesson_id=req.lesson_id,
            question_types=req.question_types,
            count=req.count,
            focus_item_id=req.focus_item_id,
        )
    )
    return ToolResult(
        tool_name="generate_quiz",
        ok=True,
        data={
            "quiz": quiz.model_dump(),
            "sources": [
                {
                    "source_id": item.id,
                    "topic": item.topic,
                    "content": item.text,
                    "source": lesson.lesson_title,
                }
                for item in lesson.items
                if item.text.strip()
            ][:8],
        },
        metadata={"book_id": req.book_id, "lesson_id": req.lesson_id, "question_count": len(quiz.questions)},
    )
