"""作业批改路由：/api/homework/*"""
from typing import Any, Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from security.auth import Actor, assert_student_access, require_auth
from security.audit_log import record_audit_event
from security.rate_limit import check_rate_limit
from homework_grading.schema import HomeworkGradeRequest
from homework_grading.service import extract_homework_from_upload, grade_homework
from homework_grading.review_store import apply_decision, get_review, list_reviews, save_review
from materials.service import MaterialSetupError
from student_profile import LearningEvent, try_record_learning_event
from services.weakpoint_service import record_weakpoint
from tracing import trace_context
from ._shared import trace_meta

router = APIRouter(prefix="/api/homework", tags=["homework"])


class HomeworkReviewDecisionRequest(BaseModel):
    decision: Literal["accepted", "edited", "rejected"]
    teacher_note: str | None = Field(default=None, max_length=2000)
    teacher_score: float | None = Field(default=None, ge=0, le=100)


def _record_review_decision_learning_signals(review: dict[str, Any], req: HomeworkReviewDecisionRequest) -> str | None:
    student_id = review.get("student_id") or (review.get("grade_request") or {}).get("student_id")
    if not student_id:
        return None
    grade_request = review.get("grade_request") or {}
    grade_result = review.get("grade_result") or {}
    weak_points = [item for item in grade_result.get("weak_points") or [] if isinstance(item, str) and item.strip()]
    normalized_score = grade_result.get("normalized_score")
    if req.teacher_score is not None:
        normalized_score = max(0, min(req.teacher_score / 100, 1))
    try:
        score_value = float(normalized_score) if normalized_score is not None else None
    except (TypeError, ValueError):
        score_value = None
    event_id = try_record_learning_event(LearningEvent(
        student_id=student_id, feature="homework_grading", event_type=f"teacher_review_{req.decision}",
        grade=grade_request.get("grade"), topic="、".join(weak_points[:3]) or None,
        score=score_value, success=(score_value >= 0.6) if score_value is not None else (req.decision != "rejected"),
        metadata={"review_id": review.get("id"), "decision": req.decision, "teacher_score": req.teacher_score, "teacher_note_present": bool(req.teacher_note), "weak_points": weak_points[:8], "original_event_id": grade_result.get("event_id")},
    ))
    if req.decision in {"accepted", "edited"}:
        tags = list(weak_points)
        for item in grade_result.get("items") or []:
            if not isinstance(item, dict):
                continue
            try:
                max_score = float(item.get("max_score") or 1)
                item_score = float(item.get("score") or 0)
            except (TypeError, ValueError):
                max_score, item_score = 1, 0
            if bool(item.get("is_correct")) and max_score > 0 and item_score / max_score >= 0.6:
                continue
            tags.extend(tag for tag in item.get("knowledge_tags") or [] if isinstance(tag, str))
        for tag in dict.fromkeys([tag for tag in tags if tag.strip()]):
            record_weakpoint(student_id, tag, "homework_teacher_review")
    return event_id


@router.post("/parse")
async def homework_parse(
    file: UploadFile = File(...),
    grade: str | None = Form(None),
    subject: str | None = Form("历史"),
    task_type: str = Form("history_short_answer"),
    ocr_mode: str = Form("multimodal"),
    preprocess: bool = Form(True),
    actor: Actor = Depends(require_auth),
):
    if task_type not in {"history_short_answer", "history_material_analysis", "history_single_choice"}:
        raise HTTPException(status_code=400, detail="题型无效")
    check_rate_limit(f"homework-parse:{actor.actor_id}", limit=30, window_seconds=3600)
    data = await file.read()
    record_audit_event(actor_id=actor.actor_id, action="homework.parse", metadata={"filename": file.filename, "content_type": file.content_type, "task_type": task_type, "bytes": len(data)})
    with trace_context(name="POST /api/homework/parse", metadata=trace_meta("homework_parse", "/api/homework/parse", filename=file.filename, content_type=file.content_type, task_type=task_type, grade=grade, subject=subject, ocr_mode=ocr_mode, preprocess=preprocess, bytes=len(data), stream=False), user_id=actor.actor_id):
        try:
            result = await run_in_threadpool(extract_homework_from_upload, file.filename or "homework-upload", file.content_type or "", data, task_type=task_type, grade=grade, subject=subject, ocr_mode=ocr_mode, preprocess=preprocess)
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MaterialSetupError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="作业识别失败，请稍后重试") from exc


@router.post("/grade")
async def homework_grade(req: HomeworkGradeRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
    rate_key = req.student_id or actor.actor_id or "anonymous"
    check_rate_limit(f"homework-grade:{rate_key}", limit=60, window_seconds=3600)
    with trace_context(name="POST /api/homework/grade", metadata=trace_meta("homework_grade", "/api/homework/grade", task_type=req.task_type, grade=req.grade, subject=req.subject, student_id=req.student_id, item_count=len(req.items), stream=False), user_id=req.student_id or actor.actor_id):
        try:
            result = await run_in_threadpool(grade_homework, req)
            record_audit_event(actor_id=actor.actor_id, action="homework.grade", resource_type="student" if req.student_id else "homework", resource_id=req.student_id, metadata={"item_count": len(req.items), "score": result.normalized_score, "needs_human_review": result.needs_human_review})
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="作业批改失败，请稍后重试") from exc


@router.post("/reviews")
async def homework_save_review(req: dict, actor: Actor = Depends(require_auth)):
    grade_request = req.get("grade_request") or {}
    grade_result = req.get("grade_result") or {}
    if not grade_result:
        raise HTTPException(status_code=400, detail="grade_result required")
    review_id = save_review(actor_id=actor.actor_id, student_id=grade_request.get("student_id"), grade_request=grade_request, grade_result=grade_result)
    record_audit_event(actor_id=actor.actor_id, action="homework.review_saved", resource_type="homework", metadata={"review_id": review_id, "needs_human_review": grade_result.get("needs_human_review")})
    return {"ok": True, "review_id": review_id}
