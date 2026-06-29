from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from materials.schema import OcrMode, OcrQuality

HomeworkTaskType = Literal["history_short_answer", "history_material_analysis", "history_single_choice"]
HomeworkConfidence = Literal["high", "medium", "low"]


class ExtractedHomeworkItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=40)
    question: str = Field(default="", max_length=5000)
    student_answer: str = Field(default="", max_length=10000)
    reference_context: str = Field(default="", max_length=8000)
    question_type: str = Field(default="history_short_answer", max_length=80)
    options: list[str] = Field(default_factory=list)
    correct_answer: str | None = Field(default=None, max_length=200)
    knowledge_tags: list[str] = Field(default_factory=list)
    confidence: HomeworkConfidence = "medium"
    warnings: list[str] = Field(default_factory=list)


class HomeworkExtractResponse(BaseModel):
    filename: str
    task_type: HomeworkTaskType
    grade: str | None = None
    subject: str | None = None
    raw_text: str
    items: list[ExtractedHomeworkItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quality: OcrQuality | None = None
    ocr_mode: OcrMode | None = None
    needs_review: bool = True


class HomeworkGradeRequest(BaseModel):
    task_type: HomeworkTaskType = "history_short_answer"
    grade: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default="历史", max_length=40)
    student_id: str | None = Field(default=None, max_length=128)
    items: list[ExtractedHomeworkItem] = Field(min_length=1, max_length=20)


class HomeworkGradedItem(BaseModel):
    item_id: str
    question: str
    student_answer: str
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    grade_level: str = "待复核"
    is_correct: bool = False
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    knowledge_tags: list[str] = Field(default_factory=list)
    correct_answer: str | None = Field(default=None, max_length=200)
    explanation: str = ""
    revision_suggestion: str = ""


class HomeworkFollowUpQuestion(BaseModel):
    question: str
    answer: str


class HomeworkGradeResponse(BaseModel):
    total_score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    normalized_score: float = Field(ge=0, le=1)
    grade_level: str
    items: list[HomeworkGradedItem] = Field(default_factory=list)
    overall_feedback: str
    weak_points: list[str] = Field(default_factory=list)
    follow_up_quiz: list[HomeworkFollowUpQuestion] = Field(default_factory=list)
    needs_human_review: bool = False
    review_reason: str | None = None
    event_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
