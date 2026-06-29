from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from student_profile import LearningEvent, get_student_profile as load_student_profile, record_learning_event as save_learning_event, suggest_review_plan as build_review_plan
from tools.base import ToolResult


class GetStudentProfileInput(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)


class SuggestReviewPlanInput(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=5, ge=1, le=10)


class RecordLearningEventInput(LearningEvent):
    pass


class DeleteDemoMemoryInput(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    memory_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=240)


def get_student_profile(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, GetStudentProfileInput) else GetStudentProfileInput.model_validate(payload)
    profile = load_student_profile(req.student_id)
    return ToolResult(
        tool_name="get_student_profile",
        ok=True,
        data={"profile": profile.model_dump()},
        metadata={"student_id": req.student_id, "weak_topic_count": len(profile.weak_topics), "recent_topic_count": len(profile.recent_topics)},
    )


def suggest_review_plan(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, SuggestReviewPlanInput) else SuggestReviewPlanInput.model_validate(payload)
    plan = build_review_plan(req.student_id, limit=req.limit)
    return ToolResult(
        tool_name="suggest_review_plan",
        ok=True,
        data={"review_plan": plan},
        metadata={"student_id": req.student_id, "action_count": len(plan.get("recommended_actions") or [])},
    )


def record_learning_event(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, RecordLearningEventInput) else RecordLearningEventInput.model_validate(payload)
    event_id = save_learning_event(req)
    return ToolResult(
        tool_name="record_learning_event",
        ok=True,
        data={"event_id": event_id},
        metadata={"student_id": req.student_id, "feature": req.feature, "event_type": req.event_type},
    )


def delete_demo_memory(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, DeleteDemoMemoryInput) else DeleteDemoMemoryInput.model_validate(payload)
    if not req.memory_id.startswith("demo_"):
        raise ValueError("演示删除工具只能处理 demo_ 开头的记忆。")
    return ToolResult(
        tool_name="delete_demo_memory",
        ok=True,
        data={"deleted": True, "memory_id": req.memory_id, "scope": "demo_only"},
        metadata={"student_id": req.student_id, "memory_id": req.memory_id, "scope": "demo_only", "reason": req.reason},
    )
