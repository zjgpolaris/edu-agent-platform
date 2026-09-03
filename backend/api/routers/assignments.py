"""作业工作流路由：/api/teacher/assignments/*, /api/student/*/assignments/*"""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from security.auth import Actor, assert_student_access, require_auth
from services.assignment_service import (
    create_assignment as _create_assignment,
    get_assignment_submissions as _get_assignment_submissions,
    get_student_badges as _get_student_badges,
    get_teacher_badges as _get_teacher_badges,
    list_student_assignments as _list_student_assignments,
    list_teacher_assignments as _list_teacher_assignments,
    record_question_review_flag as _record_question_review_flag,
    review_assignment_submission as _review_assignment_submission,
    submit_assignment as _submit_assignment,
)
from ._shared import record_event_if_student, require_teacher_actor

router = APIRouter(tags=["assignments"])


class AssignmentQuestion(BaseModel):
    type: str = "single_choice"
    prompt: str
    options: list[str] | None = None
    answer: Any | None = None
    knowledge_tag: str | None = None
    reference_answer: str | None = None
    quality: dict | None = None


class CreateAssignmentRequest(BaseModel):
    title: str
    questions: list[AssignmentQuestion]
    assignee_ids: list[str]
    subject: str | None = None
    grade: str | None = None
    due_date: str | None = None


class SubmitAssignmentRequest(BaseModel):
    answers: list[Any]


class ReviewSubmissionRequest(BaseModel):
    student_id: str
    score: float
    feedback: str | None = None


class QuestionReviewFlagRequest(BaseModel):
    verdict: str
    note: str | None = None


class GenerateQuestionsRequest(BaseModel):
    knowledge_points: list[str]
    difficulty: str = "medium"
    question_type: str = "single_choice"
    subject: str = "历史"
    semantic_check: bool = False


class GeneratedQuestion(BaseModel):
    knowledge_tag: str
    type: str = "single_choice"
    prompt: str
    options: list[str]
    answer: str
    explanation: str
    difficulty: str = "medium"
    quality: dict | None = None


class DifficultyGroupsRequest(BaseModel):
    groups: dict[str, str]


def _gen_true_false(kp: str, difficulty: str, sources: list) -> dict:
    from structured_output import invoke_structured
    from security.prompt_injection import build_untrusted_context_block
    from pydantic import BaseModel as _BM
    from llm_config import llm_fast

    class _TF(_BM):
        statement: str
        answer: str
        explanation: str

    context = build_untrusted_context_block(sources[:3], title="史料") if sources else ""
    prompt = [
        {"role": "system", "content": "你是初中历史教师，根据史料为指定知识点出一道判断题。只输出 JSON：{\"statement\":\"陈述句\",\"answer\":\"正确\",\"explanation\":\"1-2句解析\"}。answer 只能是「正确」或「错误」。"},
        {"role": "user", "content": f"知识点：{kp}\n难度：{difficulty}\n{context}".strip()},
    ]
    try:
        r = invoke_structured(llm_fast, prompt, model=_TF, fallback=None)
    except Exception:
        r = None
    if not r:
        return {"prompt": f"关于「{kp}」的说法是否正确？", "answer": "正确", "explanation": ""}
    return {"prompt": r.statement.strip(), "answer": "错误" if "错" in (r.answer or "") else "正确", "explanation": r.explanation.strip()}


def _gen_subjective(kp: str, difficulty: str, sources: list) -> dict:
    from structured_output import invoke_structured
    from security.prompt_injection import build_untrusted_context_block
    from pydantic import BaseModel as _BM
    from llm_config import llm_fast

    class _SUBJ(_BM):
        question: str
        reference_answer: str

    context = build_untrusted_context_block(sources[:3], title="史料") if sources else ""
    prompt = [
        {"role": "system", "content": "你是初中历史教师，根据史料为指定知识点出一道简答题。只输出 JSON：{\"question\":\"题干\",\"reference_answer\":\"参考答案要点\"}。"},
        {"role": "user", "content": f"知识点：{kp}\n难度：{difficulty}\n{context}".strip()},
    ]
    try:
        r = invoke_structured(llm_fast, prompt, model=_SUBJ, fallback=None)
    except Exception:
        r = None
    if not r:
        return {"prompt": f"请简述「{kp}」的历史意义。", "answer": "", "explanation": ""}
    return {"prompt": r.question.strip(), "answer": "", "explanation": r.reference_answer.strip()}


@router.post("/api/teacher/assignments/generate-questions", response_model=list[GeneratedQuestion])
async def teacher_generate_questions(req: GenerateQuestionsRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    if not req.knowledge_points:
        raise HTTPException(status_code=400, detail="knowledge_points 不能为空")
    if len(req.knowledge_points) > 20:
        raise HTTPException(status_code=400, detail="单次最多生成 20 道题")
    from agents.auto_tutor import _generate_question as _at_gen_question
    from tools.registry import run_tool
    from tools.base import ToolExecutionContext
    from services.question_quality import check_question, check_question_semantic, merge_quality
    from services.assignment_service import get_bad_question_examples
    from llm_config import llm_fast
    import asyncio

    qtype = req.question_type if req.question_type in {"single_choice", "true_false", "subjective"} else "single_choice"
    ctx = ToolExecutionContext(actor_id=actor.actor_id, session_id=f"gen-{actor.actor_id}")
    bad_examples: list[dict] = []
    if req.semantic_check:
        try:
            bad_examples = await run_in_threadpool(get_bad_question_examples, actor.actor_id)
        except Exception:
            bad_examples = []

    def _strip(o: str) -> str:
        return o[3:].strip() if len(o) > 2 and o[1] == "." else o.strip()

    def _with_quality(gq: GeneratedQuestion) -> GeneratedQuestion:
        q_dict = gq.model_dump()
        structural = check_question(q_dict)
        if req.semantic_check:
            try:
                gq.quality = merge_quality(structural, check_question_semantic(q_dict, llm=llm_fast, bad_examples=bad_examples))
            except Exception:
                gq.quality = structural
        else:
            gq.quality = structural
        return gq

    async def _gen_one(kp: str) -> GeneratedQuestion:
        try:
            raw = await run_in_threadpool(run_tool, "search_history_knowledge", {"query": kp, "top_k": 4}, ctx)
            sources = raw if isinstance(raw, list) else []
        except Exception:
            sources = []
        if qtype == "true_false":
            q = await run_in_threadpool(_gen_true_false, kp, req.difficulty, sources)
            return await run_in_threadpool(_with_quality, GeneratedQuestion(knowledge_tag=kp, type="true_false", prompt=q["prompt"], options=[], answer=q["answer"], explanation=q["explanation"], difficulty=req.difficulty))
        if qtype == "subjective":
            q = await run_in_threadpool(_gen_subjective, kp, req.difficulty, sources)
            return await run_in_threadpool(_with_quality, GeneratedQuestion(knowledge_tag=kp, type="subjective", prompt=q["prompt"], options=[], answer="", explanation=q["explanation"], difficulty=req.difficulty))
        q = await run_in_threadpool(_at_gen_question, kp, req.difficulty, sources)
        return await run_in_threadpool(_with_quality, GeneratedQuestion(knowledge_tag=kp, type="single_choice", prompt=q.get("question", ""), options=[_strip(o) for o in q.get("options", [])], answer=(q.get("answer", "A") or "A")[:1].upper(), explanation=q.get("explanation", ""), difficulty=req.difficulty))

    results = await asyncio.gather(*[_gen_one(kp) for kp in req.knowledge_points], return_exceptions=True)
    return [r for r in results if isinstance(r, GeneratedQuestion)]


@router.post("/api/teacher/assignments")
async def teacher_create_assignment(req: CreateAssignmentRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(_create_assignment, actor.actor_id, req.title, [q.model_dump() for q in req.questions], req.assignee_ids, req.subject, req.grade, req.due_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/teacher/assignments")
async def teacher_list_assignments(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    return {"assignments": await run_in_threadpool(_list_teacher_assignments, actor.actor_id)}


@router.get("/api/teacher/assignments/{assignment_id}/submissions")
async def teacher_assignment_submissions(assignment_id: str, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(_get_assignment_submissions, actor.actor_id, assignment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/api/teacher/assignments/{assignment_id}/review")
async def teacher_review_assignment_submission(assignment_id: str, req: ReviewSubmissionRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(_review_assignment_submission, actor.actor_id, assignment_id, req.student_id, req.score, req.feedback)
    except (LookupError, PermissionError, ValueError) as exc:
        code = 404 if isinstance(exc, LookupError) else (403 if isinstance(exc, PermissionError) else 400)
        raise HTTPException(status_code=code, detail=str(exc))


@router.post("/api/teacher/assignments/{assignment_id}/questions/{question_index}/review-flag")
async def teacher_flag_question_review(assignment_id: str, question_index: int, req: QuestionReviewFlagRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(_record_question_review_flag, actor.actor_id, assignment_id, question_index, req.verdict, req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/api/teacher/assignments/{assignment_id}/difficulty-groups")
async def teacher_set_difficulty_groups(assignment_id: str, req: DifficultyGroupsRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.assignment_service import set_difficulty_groups
    try:
        await run_in_threadpool(set_difficulty_groups, actor.actor_id, assignment_id, req.groups)
        return {"ok": True, "assignment_id": assignment_id, "groups": req.groups}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/api/student/{student_id}/assignments")
async def student_list_assignments(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return {"assignments": await run_in_threadpool(_list_student_assignments, student_id)}


@router.get("/api/student/{student_id}/assignments/{assignment_id}/my-questions")
async def student_get_my_questions(student_id: str, assignment_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.assignment_service import get_questions_for_student
    try:
        questions = await run_in_threadpool(get_questions_for_student, student_id, assignment_id)
        return {"questions": questions, "student_id": student_id, "assignment_id": assignment_id}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/student/{student_id}/assignments/{assignment_id}/submit")
async def student_submit_assignment(student_id: str, assignment_id: str, req: SubmitAssignmentRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    try:
        result = await run_in_threadpool(_submit_assignment, student_id, assignment_id, req.answers)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403 if isinstance(exc, PermissionError) else 400, detail=str(exc))
    record_event_if_student(student_id, feature="assignment", event_type="assignment_submitted", score=result.get("score"), success=result.get("status") == "graded", metadata={"assignment_id": assignment_id, "objective_correct": result.get("objective_correct"), "objective_total": result.get("objective_total")})
    return result


@router.get("/api/student/{student_id}/badges")
async def student_badges(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from datetime import date as _d
    from services.review_service import get_today_session
    today = _d.today().isoformat()
    badges = _get_student_badges(student_id, today)
    pending_review = 0
    try:
        session = get_today_session(student_id, today, hydrate=False)
        if session:
            pending_review = max(0, int(session.get("total", 0)) - int(session.get("completed", 0)))
    except Exception:
        pending_review = 0
    badges["pending_review"] = pending_review
    return badges


@router.get("/api/student/{student_id}/weakpoints")
async def student_weakpoints_legacy(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.weakpoint_service import get_weakpoints
    return {"weakpoints": get_weakpoints(student_id)}


@router.delete("/api/student/{student_id}/weakpoints/{knowledge_tag}")
async def delete_student_weakpoint_legacy(student_id: str, knowledge_tag: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.weakpoint_service import delete_weakpoint
    delete_weakpoint(student_id, knowledge_tag)
    return {"ok": True}


@router.delete("/api/student/{student_id}/weakpoints")
async def clear_student_weakpoints_legacy(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    from services.weakpoint_service import clear_weakpoints
    clear_weakpoints(student_id)
    return {"ok": True}


@router.get("/api/student/{student_id}/learning-report")
async def student_learning_report(student_id: str, days: int = 14, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    import json as _json
    from datetime import date as _d, timedelta as _td
    from db.engine import get_connection
    from sqlalchemy import text
    from services.weakpoint_service import get_weakpoints as _get_wps

    def _fetch() -> dict:
        today = _d.today()
        period = max(7, min(int(days), 90))
        since = (today - _td(days=period)).isoformat()
        report: dict = {"student_id": student_id, "generated_at": today.isoformat(), "period_days": period}
        with get_connection() as conn:
            p = conn.execute(text("SELECT weak_topics_json, strong_topics_json, quiz_stats_json, game_stats_json FROM student_profiles WHERE student_id = :sid"), {"sid": student_id}).mappings().fetchone()
            if p:
                weak = _json.loads(p["weak_topics_json"] or "[]")
                strong = _json.loads(p["strong_topics_json"] or "[]")
                total = len(weak) + len(strong)
                qs = _json.loads(p["quiz_stats_json"] or "{}")
                gs = _json.loads(p["game_stats_json"] or "{}")
                report.update(mastery_pct=round(len(strong) / total * 100) if total else None, weak_topic_count=len(weak), strong_topic_count=len(strong), quiz_avg_score=qs.get("average_score"), quiz_attempts=qs.get("attempts", 0), game_avg_score=gs.get("average_score"))
            else:
                report.update(mastery_pct=None, weak_topic_count=0, strong_topic_count=0, quiz_avg_score=None, quiz_attempts=0, game_avg_score=None)
            rv_rows = conn.execute(text("SELECT date, completed, total FROM review_sessions WHERE student_id = :sid AND date >= :since ORDER BY date"), {"sid": student_id, "since": since}).mappings().fetchall()
            done = sum(r["completed"] for r in rv_rows)
            total_tasks = sum(r["total"] for r in rv_rows)
            report.update(review_by_day={r["date"]: {"completed": r["completed"], "total": r["total"]} for r in rv_rows}, review_completed_total=done, review_tasks_total=total_tasks, review_completion_rate=round(done / total_tasks * 100) if total_tasks else None)
            hw_rows = conn.execute(text("SELECT created_at, teacher_score, grade_result_json FROM homework_reviews WHERE student_id = :sid ORDER BY created_at DESC LIMIT 10"), {"sid": student_id}).mappings().fetchall()
            hw_trend = []
            for r in reversed(hw_rows):
                score = r["teacher_score"]
                if score is None:
                    try:
                        result2 = _json.loads(r["grade_result_json"] or "{}")
                        score = result2.get("total_score") or result2.get("score")
                    except Exception:
                        pass
                hw_trend.append({"date": (r["created_at"] or "")[:10], "score": round(float(score), 1) if score is not None else None})
            valid_scores = [h["score"] for h in hw_trend if h["score"] is not None]
            report.update(homework_trend=hw_trend, homework_count=len(hw_trend), homework_avg_score=round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else None)
            ev_rows = conn.execute(text("SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS cnt FROM learning_events WHERE student_id = :sid AND created_at >= :since AND COALESCE(metadata_json, '') NOT LIKE '%release_verification%' GROUP BY day ORDER BY day"), {"sid": student_id, "since": since}).mappings().fetchall()
            activity_by_day = {r["day"]: int(r["cnt"]) for r in ev_rows}
            streak, check = 0, today
            while check.isoformat() in activity_by_day:
                streak += 1
                check -= _td(days=1)
            report.update(activity_by_day=activity_by_day, active_days=len(activity_by_day), streak_days=streak)
            t_row = conn.execute(text("SELECT COUNT(*) AS cnt FROM learning_events WHERE student_id = :sid AND feature = 'auto_tutor' AND event_type = 'session_complete' AND COALESCE(metadata_json, '') NOT LIKE '%release_verification%'"), {"sid": student_id}).mappings().fetchone()
            report["autotutor_sessions"] = int(t_row["cnt"]) if t_row else 0
        wps = _get_wps(student_id)
        report.update(weakpoint_count=len(wps), top_weakpoints=[{"tag": w["knowledge_tag"], "count": w["wrong_count"]} for w in wps[:5]])
        return report

    return await run_in_threadpool(_fetch)
