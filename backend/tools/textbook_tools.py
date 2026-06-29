from __future__ import annotations

from pydantic import BaseModel, Field

from textbook_learning.loader import get_lesson
from tools.base import ToolResult


class GetTextbookLessonInput(BaseModel):
    book_id: str = Field(min_length=1)
    lesson_id: str = Field(min_length=1)


def get_textbook_lesson(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, GetTextbookLessonInput) else GetTextbookLessonInput.model_validate(payload)
    lesson = get_lesson(req.book_id, req.lesson_id)
    return ToolResult(
        tool_name="get_textbook_lesson",
        ok=True,
        data={"lesson": lesson.model_dump()},
        metadata={"book_id": req.book_id, "lesson_id": req.lesson_id},
    )
