"""自适应复习、打卡、偏好、薄弱点根因路由"""
from datetime import date as _date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from security.auth import Actor, assert_student_access, require_auth
from services.review_service import (
    ReviewConflictError,
    create_today_session,
    get_mastery_overview,
    get_today_session,
    public_review_session,
    submit_answer as _submit_review,
)
from services.check_in_service import check_in, get_check_in_status, get_achievements, get_check_in_history
from services.learning_preference_service import get_preferences, set_preferences, get_preference_schema
from services.root_cause_service import analyze_root_cause, get_latest_root_cause, get_root_cause_summary

router = APIRouter(tags=["review"])


class ReviewSubmitRequest(BaseModel):
    task_index: int = Field(ge=0)
    selected_answer: str = Field(pattern="^[A-Da-d]$")


class PreferenceUpdateRequest(BaseModel):
    preferences: dict[str, str]


class AnalyzeRootCauseRequest(BaseModel):
    question_text: str | None = None
    student_answer: str
    correct_answer: str
    wrong_count: int = 1


@router.get("/api/students/{student_id}/review/today")
async def review_today(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    today = _date.today().isoformat()
    session = await run_in_threadpool(get_today_session, student_id, today)
    if session:
        return public_review_session(session)
    created = await run_in_threadpool(create_today_session, student_id, today)
    return public_review_session(created)


@router.post("/api/students/{student_id}/review/submit")
async def review_submit(student_id: str, req: ReviewSubmitRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    try:
        return await run_in_threadpool(
            _submit_review,
            student_id,
            _date.today().isoformat(),
            req.task_index,
            req.selected_answer,
        )
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/students/{student_id}/mastery-overview")
async def student_mastery_overview(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_mastery_overview, student_id)


@router.get("/api/students/{student_id}/today")
async def student_today_plan(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.today_plan import get_student_today_plan
    return await run_in_threadpool(get_student_today_plan, student_id, _date.today().isoformat())


@router.get("/api/students/{student_id}/weekly-summary")
async def student_weekly_summary(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.weekly_summary_service import build_weekly_summary
    return await run_in_threadpool(build_weekly_summary, student_id)


@router.get("/api/students/{student_id}/tutor-effectiveness")
async def student_tutor_effectiveness(student_id: str, days: int = 30, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    return await run_in_threadpool(get_student_tutor_effectiveness, student_id, max(1, min(days, 365)))


@router.get("/api/students/{student_id}/notifications")
async def student_notifications(student_id: str, unread_only: bool = False, limit: int = 20, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.notification_service import get_student_notifications
    items = await run_in_threadpool(get_student_notifications, student_id, limit=limit, unread_only=unread_only)
    return {"notifications": items, "count": len(items)}


@router.post("/api/students/{student_id}/notifications/{notification_id}/read")
async def student_notification_read_one(student_id: str, notification_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.notification_service import mark_notification_read
    hit = await run_in_threadpool(mark_notification_read, notification_id, student_id)
    return {"ok": True, "marked_read": 1 if hit else 0}


@router.post("/api/students/{student_id}/notifications/read-all")
async def student_notifications_read_all(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.notification_service import mark_all_read
    n = await run_in_threadpool(mark_all_read, student_id)
    return {"marked_read": n}


@router.post("/api/students/{student_id}/check-in")
async def student_check_in(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(check_in, student_id)


@router.get("/api/students/{student_id}/check-in/status")
async def student_check_in_status(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_check_in_status, student_id)


@router.get("/api/students/{student_id}/achievements")
async def student_achievements(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_achievements, student_id)


@router.get("/api/students/{student_id}/check-in/history")
async def student_check_in_history(student_id: str, days: int = 90, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_check_in_history, student_id, days)


@router.get("/api/students/{student_id}/preferences")
async def student_get_preferences(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_preferences, student_id)


@router.put("/api/students/{student_id}/preferences")
async def student_set_preferences(student_id: str, req: PreferenceUpdateRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(set_preferences, student_id, req.preferences)


@router.get("/api/preferences/schema")
async def preference_schema():
    return get_preference_schema()


@router.post("/api/students/{student_id}/weakpoints/{knowledge_tag}/analyze")
async def analyze_weakpoint_root_cause(student_id: str, knowledge_tag: str, req: AnalyzeRootCauseRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(analyze_root_cause, student_id, knowledge_tag, req.question_text or "", req.student_answer, req.correct_answer, req.wrong_count)


@router.get("/api/students/{student_id}/weakpoints/{knowledge_tag}/root-cause")
async def get_weakpoint_root_cause(student_id: str, knowledge_tag: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_latest_root_cause, student_id, knowledge_tag)


@router.get("/api/students/{student_id}/root-cause/summary")
async def get_student_root_cause_summary(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_root_cause_summary, student_id)
