from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SourceType = Literal["pdf", "image"]
MaterialTask = Literal["summary", "quiz", "explanation", "all"]
OcrMode = Literal["auto", "page", "textbook", "multimodal"]
OcrQualityLevel = Literal["high", "medium", "low"]


class OcrQuality(BaseModel):
    level: OcrQualityLevel
    chinese_ratio: float = 0
    noise_count: int = 0
    symbol_density: float = 0
    char_count: int = 0
    needs_review: bool = False


class OcrRegion(BaseModel):
    name: str
    label: str
    text: str
    quality_level: OcrQualityLevel = "medium"
    warnings: list[str] = Field(default_factory=list)


class OcrCorrection(BaseModel):
    original: str
    replacement: str
    reason: str
    count: int = Field(default=1, ge=1)
    region: str | None = None


class MaterialPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str
    source_type: SourceType


class MaterialParseResponse(BaseModel):
    filename: str
    content_type: str
    source_type: SourceType
    text: str
    pages: list[MaterialPage]
    warnings: list[str] = Field(default_factory=list)
    quality: OcrQuality | None = None
    regions: list[OcrRegion] = Field(default_factory=list)
    corrections: list[OcrCorrection] = Field(default_factory=list)
    ocr_mode: OcrMode | None = None


class MaterialGenerateRequest(BaseModel):
    text: str = Field(min_length=20, max_length=50000)
    grade: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default=None, max_length=40)
    task: MaterialTask = "all"


class MaterialQuizQuestion(BaseModel):
    id: str
    type: str
    question: str
    options: list[str] | None = None
    answer: str
    explanation: str


class MaterialSummary(BaseModel):
    title: str
    key_points: list[str] = Field(default_factory=list)
    study_notes: list[str] = Field(default_factory=list)
    classroom_questions: list[str] = Field(default_factory=list)


class MaterialAnalyzeResponse(BaseModel):
    summary: MaterialSummary | None = None
    explanation: str | None = None
    questions: list[MaterialQuizQuestion] = Field(default_factory=list)
    raw_text: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MaterialSaveRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="", max_length=120)
    source_type: SourceType
    grade: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default=None, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    text: str = Field(min_length=20, max_length=100000)
    pages: list[MaterialPage] = Field(default_factory=list)
    ocr_mode: OcrMode | None = None
    quality: OcrQuality | None = None
    warnings: list[str] = Field(default_factory=list)


class MaterialRecord(BaseModel):
    material_id: str
    title: str
    filename: str
    subject: str | None = None
    grade: str | None = None
    source_type: SourceType
    text_chars: int = 0
    page_count: int = 0
    chunk_count: int = 0
    created_at: str
    updated_at: str


class MaterialDetailResponse(BaseModel):
    material: MaterialRecord
    pages: list[MaterialPage]
    warnings: list[str] = Field(default_factory=list)


class MaterialQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=4, ge=1, le=8)


class MaterialSource(BaseModel):
    material_id: str
    title: str
    page: int | None = None
    chunk_id: str
    score: float = 0
    source_mode: str = "vector"
    snippet: str


class MaterialAnswerResponse(BaseModel):
    material_id: str
    answer: str
    sources: list[MaterialSource] = Field(default_factory=list)
