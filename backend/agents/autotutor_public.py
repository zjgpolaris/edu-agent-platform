"""Student-safe serialization contracts for AutoTutor cross-feature handoff."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.autotutor_content import Difficulty


class PublicTeachingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(default="", max_length=1200)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    example: str | None = Field(default=None, max_length=600)


class AutoTutorAssistantContextPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    autotutor_session_id: str = Field(default="", max_length=128)
    phase: Literal["lesson", "exit_ticket", "content_blocked", "completed"] = "lesson"
    knowledge_point: str = Field(default="", max_length=160)
    difficulty: Difficulty = "medium"
    teaching: PublicTeachingContext | None = None
    question: str | None = Field(default=None, max_length=500)
    return_path: Literal["/student/auto-tutor"] = "/student/auto-tutor"


class AutoTutorAssistantHandoff(BaseModel):
    """Internal ownership envelope. Only ``context`` may cross the API boundary."""

    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=128)
    context: AutoTutorAssistantContextPublic


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def sanitize_autotutor_assistant_context(
    value: dict[str, Any] | None,
    *,
    source_session_id: str | None = None,
) -> dict[str, Any]:
    """Build from an allowlist so unknown or legacy nested fields cannot escape."""
    raw = value if isinstance(value, dict) else {}
    teaching_raw = raw.get("teaching") if isinstance(raw.get("teaching"), dict) else None
    teaching = None
    if teaching_raw is not None:
        key_points = [
            _clean_text(item, 240)
            for item in (teaching_raw.get("key_points") or [])[:8]
            if _clean_text(item, 240)
        ]
        explanation = _clean_text(teaching_raw.get("explanation"), 1200)
        example = _clean_text(teaching_raw.get("example"), 600) or None
        if explanation or key_points or example:
            teaching = PublicTeachingContext(
                explanation=explanation,
                key_points=key_points,
                example=example,
            )

    phase = str(raw.get("phase") or "lesson")
    if phase not in {"lesson", "exit_ticket", "content_blocked", "completed"}:
        phase = "lesson"
    difficulty = str(raw.get("difficulty") or "medium")
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"
    public = AutoTutorAssistantContextPublic(
        autotutor_session_id=_clean_text(
            raw.get("autotutor_session_id") or source_session_id,
            128,
        ),
        phase=phase,  # type: ignore[arg-type]
        knowledge_point=_clean_text(raw.get("knowledge_point"), 160),
        difficulty=difficulty,  # type: ignore[arg-type]
        teaching=teaching,
        question=_clean_text(raw.get("question"), 500) or None,
    )
    return public.model_dump(mode="json")
