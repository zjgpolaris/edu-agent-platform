"""跨路由共享的工具函数和辅助类型。"""
import json
from typing import Any

from fastapi import HTTPException
from security.audit_log import record_audit_event
from security.auth import Actor, auth_required
from security.prompt_injection import evaluate_user_input, mask_sensitive
from student_profile import LearningEvent, try_record_learning_event


def sse_frame(event: str, data: dict, *, event_id: int | str | None = None) -> str:
    cursor = f"id: {event_id}\n" if event_id is not None else ""
    return f"{cursor}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def next_stream_event(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def trace_meta(feature: str, route: str, **metadata) -> dict:
    return {"feature": feature, "route": route, **metadata}


def record_event_if_student(
    student_id: str | None,
    *,
    session_id: str | None = None,
    feature: str,
    event_type: str,
    grade: str | None = None,
    topic: str | None = None,
    book_id: str | None = None,
    lesson_id: str | None = None,
    score: float | None = None,
    success: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not student_id:
        return
    try_record_learning_event(
        LearningEvent(
            student_id=student_id,
            session_id=session_id,
            feature=feature,
            event_type=event_type,
            grade=grade,
            topic=topic,
            book_id=book_id,
            lesson_id=lesson_id,
            score=score,
            success=success,
            metadata=metadata or {},
        )
    )


def enforce_guardrails(
    text: str,
    *,
    actor: Actor,
    route: str,
    student_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    result = evaluate_user_input(text)
    if not result.blocked:
        return
    record_audit_event(
        actor_id=actor.actor_id,
        action="guardrail.blocked",
        resource_type=resource_type,
        resource_id=resource_id or student_id,
        success=False,
        metadata={
            "route": route,
            "student_id": student_id,
            "query": mask_sensitive(text),
            **result.to_metadata(),
        },
    )
    raise HTTPException(status_code=400, detail=result.message)


def require_teacher_actor(actor: Actor) -> None:
    if not auth_required():
        return
    if actor.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师可访问")
