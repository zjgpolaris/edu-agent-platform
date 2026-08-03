"""教师管理路由：/api/teacher/*"""
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from security.audit_log import record_audit_event
from security.auth import Actor, require_auth
from student_profile import get_student_profile, list_learning_events
from ._shared import require_teacher_actor, trace_meta
from llm_config import llm_fast

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


class ClassAnalytics(BaseModel):
    total_students: int
    active_students: int
    average_quiz_score: float | None
    average_game_score: float | None
    weak_topics_distribution: dict[str, int]
    strong_topics_distribution: dict[str, int]
    top_weak_topics: list[tuple[str, int]]
    activity_by_day: dict[str, int]


class TeachingSuggestionRequest(BaseModel):
    focus: str = Field(default="weak_topics", description="weak_topics, strong_topics, activity")


@router.get("/students")
def teacher_list_students(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from security.accounts import list_students
    return list_students()


@router.get("/students/{student_id}/profile")
def teacher_student_profile(student_id: str, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    return get_student_profile(student_id).model_dump()


@router.get("/students/{student_id}/events")
def teacher_student_events(student_id: str, limit: int = 50, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from student_profile import init_db
    from db.engine import get_connection
    from sqlalchemy import text
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM learning_events WHERE student_id = :student_id ORDER BY created_at DESC LIMIT :limit"),
            {"student_id": student_id, "limit": limit},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router.get("/class-analytics")
async def teacher_class_analytics(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from student_profile import init_db, _json_load
    from db.engine import get_connection
    from sqlalchemy import text
    from datetime import datetime, timedelta, timezone

    init_db()
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        students = conn.execute(text("SELECT DISTINCT student_id FROM student_profiles")).mappings().fetchall()
        student_ids = [row["student_id"] for row in students]
        active_rows = conn.execute(
            text("SELECT DISTINCT student_id FROM learning_events WHERE created_at >= :since"),
            {"since": seven_days_ago},
        ).mappings().fetchall()
        active_ids = {row["student_id"] for row in active_rows}
        profiles = conn.execute(text("SELECT * FROM student_profiles")).mappings().fetchall()

        def _score_from_stats(value: str | None) -> float | None:
            stats = _json_load(value, {})
            if not isinstance(stats, dict):
                return None
            score = stats.get("average_score")
            try:
                return float(score) if score is not None else None
            except (TypeError, ValueError):
                return None

        quiz_scores = [score for row in profiles if (score := _score_from_stats(row["quiz_stats_json"])) is not None]
        game_scores = [score for row in profiles if (score := _score_from_stats(row["game_stats_json"])) is not None]
        weak_dist: dict[str, int] = {}
        for row in profiles:
            for topic in _json_load(row["weak_topics_json"], []) or []:
                weak_dist[str(topic)] = weak_dist.get(str(topic), 0) + 1
        strong_dist: dict[str, int] = {}
        for row in profiles:
            for topic in _json_load(row["strong_topics_json"], []) or []:
                strong_dist[str(topic)] = strong_dist.get(str(topic), 0) + 1
        activity_rows = conn.execute(
            text("SELECT substr(created_at, 1, 10) as date, COUNT(DISTINCT student_id) as count FROM learning_events WHERE created_at >= :since GROUP BY substr(created_at, 1, 10)"),
            {"since": seven_days_ago},
        ).mappings().fetchall()
        activity_by_day = {row["date"]: row["count"] for row in activity_rows}

    return ClassAnalytics(
        total_students=len(student_ids),
        active_students=len(active_ids),
        average_quiz_score=sum(quiz_scores) / len(quiz_scores) if quiz_scores else None,
        average_game_score=sum(game_scores) / len(game_scores) if game_scores else None,
        weak_topics_distribution=weak_dist,
        strong_topics_distribution=strong_dist,
        top_weak_topics=sorted(weak_dist.items(), key=lambda x: x[1], reverse=True)[:5],
        activity_by_day=activity_by_day,
    ).model_dump()


@router.get("/materials")
async def teacher_list_materials(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from materials.store import list_material_records
    from student_profile import init_db
    from db.engine import get_connection
    from sqlalchemy import text
    init_db()
    with get_connection() as conn:
        students = conn.execute(text("SELECT DISTINCT student_id FROM student_profiles")).mappings().fetchall()
        student_ids = [f"actor:{row['student_id']}" for row in students]
    materials = []
    for owner_key in student_ids:
        materials.extend(list_material_records(owner_key))
    return {"materials": [m.model_dump() for m in materials]}


@router.post("/teaching-suggestions")
async def teacher_teaching_suggestions(req: TeachingSuggestionRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from structured_output import parse_json_object, StructuredOutputError
    analytics = await teacher_class_analytics(actor)
    weak_topics = analytics.get("top_weak_topics", [])
    total_students = max(int(analytics.get("total_students") or 0), 1)
    weak_lines = [f"- {topic}: {count} 名学生，约 {round((int(count) / total_students) * 100)}%" for topic, count in weak_topics[:5]]
    weak_text = "\n".join(weak_lines) or "暂无"
    prompt = f"""你是中学历史教研组长，请基于班级学情生成可直接用于下一节课的讲评建议。

班级概况：
- 学生总数：{analytics['total_students']}
- 活跃学生：{analytics['active_students']}
- 平均测验分：{analytics.get('average_quiz_score', '无数据')}
- 平均游戏分：{analytics.get('average_game_score', '无数据')}

高频薄弱点（来自错题本/学习画像聚合）：
{weak_text}

只输出 JSON，不要 Markdown，不要解释：
{{"suggestions": ["建议1"], "activities": ["活动1"], "key_topics": ["知识点1"], "homework_suggestions": ["作业建议1"]}}"""
    response = llm_fast.invoke([{"role": "user", "content": prompt}]).content
    try:
        return parse_json_object(response)
    except StructuredOutputError:
        return {"suggestions": [], "activities": [], "key_topics": [], "homework_suggestions": []}


@router.post("/lecture-review")
async def teacher_lecture_review(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.lecture_review_service import generate_lecture_review
    try:
        return await run_in_threadpool(generate_lecture_review, actor.actor_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讲评材料生成失败: {exc}") from exc


@router.get("/homework-reviews")
async def teacher_list_reviews(decision: str | None = None, limit: int = 50, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from homework_grading.review_store import list_reviews
    reviews = list_reviews(decision=decision or None, limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


@router.post("/homework-reviews/{review_id}/decision")
async def teacher_review_decision(review_id: str, req: dict, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from homework_grading.review_store import apply_decision, get_review
    from pydantic import BaseModel as _BM
    from typing import Literal as _Lit

    decision = req.get("decision")
    teacher_note = req.get("teacher_note")
    teacher_score = req.get("teacher_score")
    if decision not in {"accepted", "edited", "rejected"}:
        raise HTTPException(status_code=422, detail="decision must be accepted/edited/rejected")
    ok = apply_decision(review_id, teacher_id=actor.actor_id, decision=decision, teacher_note=teacher_note, teacher_score=teacher_score)
    if not ok:
        raise HTTPException(status_code=404, detail="review not found")
    review = get_review(review_id)
    # learning signal recording delegated to inline helper
    from api.routers.homework import _record_review_decision_learning_signals, HomeworkReviewDecisionRequest as _HRDR
    _req = _HRDR(decision=decision, teacher_note=teacher_note, teacher_score=teacher_score)
    event_id = _record_review_decision_learning_signals(review, _req) if review else None
    record_audit_event(actor_id=actor.actor_id, action=f"homework.review_{decision}", resource_type="homework", metadata={"review_id": review_id, "teacher_score": teacher_score, "event_id": event_id})
    return {"ok": True, "event_id": event_id}


@router.get("/completion-overview")
async def teacher_completion_overview(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.completion_overview import get_class_completion_overview
    from datetime import date as _d
    return await run_in_threadpool(get_class_completion_overview, actor.actor_id, _d.today().isoformat())


@router.get("/today-queue")
async def teacher_today_queue(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.teacher_today_queue import get_teacher_today_queue
    from datetime import date as _d
    return await run_in_threadpool(get_teacher_today_queue, actor.actor_id, _d.today().isoformat())


@router.post("/urge-students")
async def teacher_urge_students(req: dict, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    student_ids = req.get("student_ids", [])
    message = req.get("message", "")
    assignment_ids = req.get("assignment_ids", [])
    if not student_ids:
        raise HTTPException(status_code=400, detail="student_ids 不能为空")
    if len(student_ids) > 50:
        raise HTTPException(status_code=400, detail="单次催办最多 50 名学生")
    from services.notification_service import send_urge_notification
    msg = (message or "").strip() or "老师提醒你完成未交的作业，请尽快提交！"
    count = await run_in_threadpool(send_urge_notification, actor.actor_id, student_ids, msg, assignment_ids or [])
    record_audit_event(actor_id=actor.actor_id, action="teacher.urge_students", resource_type="notification", success=count > 0, metadata={"student_count": count, "has_custom_msg": bool(message.strip())})
    return {"sent": count, "teacher_id": actor.actor_id}


@router.get("/class-wrong-analysis")
async def teacher_class_wrong_analysis(limit_assignments: int = 10, top_n: int = 15, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.lecture_review_service import aggregate_class_wrong_questions
    return await run_in_threadpool(aggregate_class_wrong_questions, actor.actor_id, max(1, min(limit_assignments, 30)), max(1, min(top_n, 50)))


@router.get("/tutor-effectiveness")
async def teacher_tutor_effectiveness(days: int = 30, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.tutor_effectiveness_service import get_class_tutor_effectiveness
    return await run_in_threadpool(get_class_tutor_effectiveness, actor.actor_id, max(1, min(days, 365)))


@router.get("/class-mastery-heatmap")
async def teacher_class_mastery_heatmap(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from collections import defaultdict
    from db.engine import get_connection
    from sqlalchemy import text

    def _fetch():
        _ensure = __import__("services.weakpoint_service", fromlist=["_ensure_table"])
        _ensure._ensure_table()
        with get_connection() as conn:
            rows = conn.execute(text("SELECT knowledge_tag, wrong_count, correct_streak, student_id FROM weakpoints ORDER BY knowledge_tag")).mappings().fetchall()
            total_row = conn.execute(text("SELECT COUNT(DISTINCT student_id) AS cnt FROM weakpoints")).mappings().fetchone()
        total_students = int(total_row["cnt"] or 0) if total_row else 0
        tag_data: dict = defaultdict(lambda: {"students": set(), "wrong_sum": 0, "strength_sum": 0.0})
        for r in rows:
            tag, wc, cs = r["knowledge_tag"], int(r["wrong_count"] or 0), int(r["correct_streak"] or 0)
            strength = round(min(1.0, max(0.1, 1.0 - min(wc * 0.15, 0.9) + cs * 0.2)), 3)
            tag_data[tag]["students"].add(r["student_id"])
            tag_data[tag]["wrong_sum"] += wc
            tag_data[tag]["strength_sum"] += strength
        result = [{"tag": t, "student_count": (sc := len(d["students"])), "avg_wrong": round(d["wrong_sum"] / sc, 1) if sc else 0.0, "avg_strength": round(d["strength_sum"] / sc, 3) if sc else 0.5} for t, d in tag_data.items()]
        result.sort(key=lambda x: (-x["student_count"], -x["avg_wrong"]))
        return {"tags": result, "total_students": total_students, "total_tags": len(result)}

    return await run_in_threadpool(_fetch)


@router.get("/class-risk-analysis")
async def teacher_class_risk_analysis(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from collections import defaultdict
    from db.engine import get_connection
    from sqlalchemy import text
    from services.knowledge_graph_service import aggregate_class_risks

    def _fetch():
        _ensure = __import__("services.weakpoint_service", fromlist=["_ensure_table"])
        _ensure._ensure_table()
        with get_connection() as conn:
            rows = conn.execute(text("SELECT student_id, knowledge_tag FROM weakpoints")).mappings().fetchall()
        by_student: dict = defaultdict(list)
        for r in rows:
            by_student[r["student_id"]].append(r["knowledge_tag"])
        return aggregate_class_risks([{"student_id": sid, "weak_tags": tags} for sid, tags in by_student.items()])

    return await run_in_threadpool(_fetch)


@router.get("/class-knowledge-matrix")
async def teacher_class_knowledge_matrix(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from collections import defaultdict
    from db.engine import get_connection
    from sqlalchemy import text

    def _fetch():
        _ensure = __import__("services.weakpoint_service", fromlist=["_ensure_table"])
        _ensure._ensure_table()
        with get_connection() as conn:
            rows = conn.execute(text("SELECT student_id, knowledge_tag, wrong_count, correct_streak FROM weakpoints ORDER BY student_id, knowledge_tag")).mappings().fetchall()
        student_ids = sorted(set(r["student_id"] for r in rows))
        tag_counts: dict = defaultdict(int)
        student_tag_data: dict = defaultdict(dict)
        for r in rows:
            sid, tag = r["student_id"], r["knowledge_tag"]
            wc, cs = int(r["wrong_count"] or 0), int(r["correct_streak"] or 0)
            strength = round(min(1.0, max(0.1, 1.0 - min(wc * 0.15, 0.9) + cs * 0.2)), 3)
            student_tag_data[sid][tag] = strength
            tag_counts[tag] += 1
        tags = sorted(tag_counts.keys(), key=lambda t: -tag_counts[t])[:50]
        matrix = [[student_tag_data[sid].get(tag, 1.0) for tag in tags] for sid in student_ids]
        students = [{"id": sid, "name": f"学生{i+1}"} for i, sid in enumerate(student_ids)]
        return {"students": students, "tags": tags, "matrix": matrix}

    return await run_in_threadpool(_fetch)


@router.get("/badges")
async def teacher_badges(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.assignment_service import get_teacher_badges as _get_teacher_badges
    return await run_in_threadpool(_get_teacher_badges, actor.actor_id)


@router.get("/quality-dashboard")
async def teacher_quality_dashboard(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from services.quality_dashboard import get_teacher_quality_dashboard
    return await run_in_threadpool(get_teacher_quality_dashboard, actor.actor_id)
