from typing import Literal

from pydantic import BaseModel, Field


TextbookStatus = Literal["ready", "empty", "invalid"]
ItemType = Literal["textbook", "primary", "concept", "timeline"]
SummaryMode = Literal["overview", "exam_points", "mistakes", "compare"]
QuestionType = Literal["single_choice", "short_answer", "fill_blank", "explanation"]


class TextbookListItem(BaseModel):
    id: str
    grade: str
    book: str
    source: str
    status: TextbookStatus
    unit_count: int = 0
    lesson_count: int = 0
    item_count: int = 0
    message: str | None = None


class TextbookLessonTocItem(BaseModel):
    id: str
    title: str
    item_count: int


class TextbookUnitTocItem(BaseModel):
    title: str
    lessons: list[TextbookLessonTocItem]


class TextbookTocResponse(BaseModel):
    book_id: str
    grade: str
    book: str
    status: TextbookStatus
    units: list[TextbookUnitTocItem]


class TextbookItem(BaseModel):
    id: str
    text: str
    topic: str
    type: str
    page: int | str
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    event: str | None = None
    period: str | None = None


class TextbookLessonResponse(BaseModel):
    book_id: str
    lesson_id: str
    grade: str
    book: str
    unit_title: str
    lesson_title: str
    items: list[TextbookItem]


class TextbookAskRequest(BaseModel):
    book_id: str
    lesson_id: str
    question: str = Field(min_length=1, max_length=500)
    selected_text: str | None = Field(default=None, max_length=1000)
    item_id: str | None = None
    session_id: str | None = None
    student_id: str | None = None
    action: str | None = None


class TextbookSummaryRequest(BaseModel):
    book_id: str
    lesson_id: str
    mode: SummaryMode = "overview"
    student_id: str | None = None


class TextbookQuizRequest(BaseModel):
    book_id: str
    lesson_id: str
    question_types: list[QuestionType] = Field(default_factory=lambda: ["single_choice", "short_answer"])
    count: int = Field(default=5, ge=1, le=10)
    focus_item_id: str | None = None
    student_id: str | None = None


class TextbookQuizQuestion(BaseModel):
    id: str
    type: str
    question: str
    options: list[str] | None = None
    answer: str
    explanation: str
    source_item_ids: list[str] = Field(default_factory=list)


class TextbookQuizResponse(BaseModel):
    questions: list[TextbookQuizQuestion] = Field(default_factory=list)
    raw_text: str | None = None


class TextbookQuizSubmitRequest(BaseModel):
    book_id: str
    lesson_id: str
    answers: list[dict]  # [{"question_id": "q1", "user_answer": "..."}]
    student_id: str | None = None
