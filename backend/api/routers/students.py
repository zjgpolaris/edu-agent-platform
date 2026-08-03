"""学生路由：/api/students/*"""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from security.audit_log import record_audit_event
from security.auth import Actor, assert_student_access, require_auth
from security.rate_limit import check_rate_limit
from student_profile import (
    LearningEvent, delete_learning_event, ensure_profile_memory_entries,
    get_memory_entry, get_student_profile, list_learning_events,
    list_memory_entries, set_memory_entry_status, suggest_review_plan,
    try_record_learning_event,
)
from services.weakpoint_service import get_weakpoints
from services.variant_service import get_or_create_variant
from services.knowledge_graph_service import build_graph as build_knowledge_graph, predict_risks as predict_knowledge_risks

router = APIRouter(prefix="/api/students", tags=["students"])


class LearningEventRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    feature: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    grade: str | None = None
    topic: str | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    success: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntryStatusRequest(BaseModel):
    status: str = Field(pattern="^(enabled|disabled|deleted)$")
    reason: str | None = Field(default=None, max_length=240)


@router.get("/{student_id}/profile")
async def student_profile(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    record_audit_event(actor_id=actor.actor_id, action="student_profile.read", resource_type="student", resource_id=student_id)
    return {"profile": get_student_profile(student_id).model_dump()}


@router.get("/{student_id}/review-plan")
async def student_review_plan(student_id: str, limit: int = 5, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    record_audit_event(actor_id=actor.actor_id, action="student_profile.review_plan", resource_type="student", resource_id=student_id)
    normalized_limit = max(1, min(limit, 10))
    review_plan = suggest_review_plan(student_id, limit=normalized_limit)
    weakpoints = get_weakpoints(student_id)[:normalized_limit]
    review_plan["weakpoints"] = weakpoints
    review_plan["priority_topics"] = [point["knowledge_tag"] for point in weakpoints]
    return {"review_plan": review_plan}


@router.get("/{student_id}/learning-path")
async def student_learning_path(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    record_audit_event(actor_id=actor.actor_id, action="student_profile.learning_path", resource_type="student", resource_id=student_id)
    profile = get_student_profile(student_id)
    review_plan = suggest_review_plan(student_id, limit=10)
    weakpoints = get_weakpoints(student_id)[:10]
    priority_topics = [point["knowledge_tag"] for point in weakpoints]
    progress: dict[str, float] = {}
    for point in weakpoints:
        wrong_count = int(point.get("wrong_count") or 0)
        progress[point["knowledge_tag"]] = 0.25 if wrong_count >= 5 else (0.4 if wrong_count >= 3 else 0.5)
    for topic in profile.weak_topics:
        progress.setdefault(topic, 0.5)
    for topic in profile.strong_topics:
        progress[topic] = 0.8
    milestones = [{"title": action, "completed": False} for action in review_plan.get("recommended_actions", [])]
    graph = build_knowledge_graph(strong_topics=profile.strong_topics, weak_topics=profile.weak_topics, weakpoint_tags=priority_topics)
    graph["at_risk"] = predict_knowledge_risks(graph)
    return {
        "student_id": student_id, "created_at": profile.updated_at, "updated_at": profile.updated_at,
        "weak_topics": profile.weak_topics, "strong_topics": profile.strong_topics,
        "weakpoints": weakpoints, "priority_topics": priority_topics,
        "recommended_actions": review_plan.get("recommended_actions", []),
        "progress": progress, "milestones": milestones, "graph": graph,
    }


@router.get("/{student_id}/review/variant-question")
async def student_variant_question(student_id: str, tag: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    if not tag.strip():
        raise HTTPException(status_code=400, detail="tag 不能为空")
    import datetime
    variant = get_or_create_variant(student_id, tag, today=datetime.date.today().isoformat())
    return {"variant": variant, "tag": tag, "student_id": student_id}


@router.post("/{student_id}/events")
async def student_learning_event(student_id: str, req: LearningEventRequest, actor: Actor = Depends(require_auth)):
    if student_id != req.student_id:
        raise HTTPException(status_code=400, detail="路径 student_id 与请求体不一致")
    assert_student_access(actor, student_id)
    check_rate_limit(f"student-event:{student_id}", limit=120, window_seconds=3600)
    event_id = try_record_learning_event(LearningEvent(**req.model_dump()))
    record_audit_event(actor_id=actor.actor_id, action="student_profile.event_write", resource_type="student", resource_id=student_id, success=bool(event_id), metadata={"feature": req.feature, "event_type": req.event_type})
    return {"event_id": event_id, "ok": bool(event_id)}


@router.get("/{student_id}/events")
async def student_events_list(student_id: str, limit: int = 50, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    events = list_learning_events(student_id=student_id, limit=max(1, min(limit, 200)))
    return {"events": events, "total": len(events)}


@router.get("/{student_id}/memory-entries")
async def student_memory_entries(student_id: str, limit: int = 100, status: str | None = "enabled", type: str | None = None, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    ensure_profile_memory_entries(student_id)
    entries = list_memory_entries(student_id, limit=max(1, min(limit, 200)), status=None if status == "all" else status, memory_type=type, include_deleted=False)
    record_audit_event(actor_id=actor.actor_id, action="memory.entries_read", resource_type="student", resource_id=student_id, metadata={"count": len(entries), "status": status, "type": type})
    return {"memory_entries": [entry.model_dump() for entry in entries], "total": len(entries)}


@router.patch("/{student_id}/memory-entries/{memory_id}")
async def student_memory_entry_update(student_id: str, memory_id: str, req: MemoryEntryStatusRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    existing = get_memory_entry(student_id, memory_id)
    if not existing or existing.status == "deleted":
        raise HTTPException(status_code=404, detail="记忆不存在或无权操作")
    if not set_memory_entry_status(memory_id, student_id, req.status):
        raise HTTPException(status_code=404, detail="记忆不存在或无权操作")
    action = "memory.entry_delete" if req.status == "deleted" else ("memory.entry_disable" if req.status == "disabled" else "memory.entry_enable")
    record_audit_event(actor_id=actor.actor_id, action=action, resource_type="student", resource_id=student_id, metadata={"memory_id": memory_id, "memory_type": existing.type, "reason": req.reason})
    updated = get_memory_entry(student_id, memory_id)
    return {"ok": True, "memory_entry": updated.model_dump() if updated else None}


@router.delete("/{student_id}/memory-entries/{memory_id}")
async def student_memory_entry_delete(student_id: str, memory_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    existing = get_memory_entry(student_id, memory_id)
    if not existing or existing.status == "deleted":
        raise HTTPException(status_code=404, detail="记忆不存在或无权删除")
    if not set_memory_entry_status(memory_id, student_id, "deleted"):
        raise HTTPException(status_code=404, detail="记忆不存在或无权删除")
    record_audit_event(actor_id=actor.actor_id, action="memory.entry_delete", resource_type="student", resource_id=student_id, metadata={"memory_id": memory_id, "memory_type": existing.type})
    return {"ok": True}


@router.delete("/{student_id}/events/{event_id}")
async def student_event_delete(student_id: str, event_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    if not delete_learning_event(event_id, student_id):
        raise HTTPException(status_code=404, detail="事件不存在或无权删除")
    record_audit_event(actor_id=actor.actor_id, action="memory.event_delete", resource_type="student", resource_id=student_id, metadata={"event_id": event_id})
    return {"ok": True}


@router.get("/{student_id}/memory-audit")
async def student_memory_audit(student_id: str, limit: int = 50, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from security.audit_log import list_audit_events
    actions = {"student_profile.read", "student_profile.review_plan", "student_profile.event_write", "memory.event_delete", "memory.entries_read", "memory.entry_disable", "memory.entry_enable", "memory.entry_delete", "tool.confirmation_required", "tool.confirmation_confirmed", "tool.confirmation_cancelled", "tool.role_denied", "tool.denied"}
    events = []
    for event in list_audit_events(limit=max(1, min(limit * 4, 200)), resource_type="student"):
        if event.get("resource_id") == student_id and event.get("action") in actions:
            events.append(event)
        if len(events) >= limit:
            break
    if len(events) < limit:
        for event in list_audit_events(limit=max(1, min(limit * 4, 200)), resource_type="tool"):
            meta = event.get("metadata") or {}
            if meta.get("student_id") == student_id and event.get("action") in actions:
                events.append(event)
            if len(events) >= limit:
                break
    return {"events": events[:limit], "total": len(events[:limit])}


@router.get("/{student_id}/weakpoints")
async def student_weakpoints(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return {"weakpoints": get_weakpoints(student_id)}


@router.delete("/{student_id}/weakpoints/{knowledge_tag}")
async def delete_student_weakpoint(student_id: str, knowledge_tag: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.weakpoint_service import delete_weakpoint
    delete_weakpoint(student_id, knowledge_tag)
    return {"ok": True}


@router.delete("/{student_id}/weakpoints")
async def clear_student_weakpoints(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.weakpoint_service import clear_weakpoints
    clear_weakpoints(student_id)
    return {"ok": True}
