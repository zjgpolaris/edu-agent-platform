"""教师「今日教学队列」聚合：把教师首页的多路待办信号收口到后端。

前端此前并发请求待复核、完成情况、班级学情、共性错题与命题质量看板，
再自行拼装今日优先动作。本模块复用已有确定性服务，在后端统一口径、
排序与降级策略，供教师首页和 pilot smoke 共同验证。
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import text

from db.engine import get_connection
from student_profile import _json_load, init_db

QueueSource = Callable[[], Any]


def _source_error(source: str, exc: Exception) -> dict[str, str]:
    return {"source": source, "message": str(exc) or "加载失败"}


def _top_weak_topic() -> tuple[str, int] | None:
    """复用班级学情的最小弱点聚合口径，避免为 today queue 调用 FastAPI route。"""
    init_db()
    weak_dist: dict[str, int] = {}
    with get_connection() as conn:
        rows = conn.execute(text("SELECT weak_topics_json FROM student_profiles")).mappings().fetchall()
    for row in rows:
        for topic in _json_load(row["weak_topics_json"], []) or []:
            tag = str(topic).strip()
            if tag:
                weak_dist[tag] = weak_dist.get(tag, 0) + 1
    if not weak_dist:
        return None
    return sorted(weak_dist.items(), key=lambda x: x[1], reverse=True)[0]


def build_teacher_today_queue(
    *,
    today: str,
    pending_reviews: int = 0,
    completion: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    top_weak_topic: tuple[str, int] | None = None,
    wrong_analysis: dict[str, Any] | None = None,
    source_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """纯函数：按教师首页既有规则合成今日队列。"""
    items: list[dict[str, Any]] = []

    if pending_reviews > 0:
        items.append({
            "key": "reviews",
            "tone": "danger",
            "label": "待复核",
            "title": f"{pending_reviews} 份作业/批改等待确认",
            "detail": "先处理需要教师判断的 AI 批改结果，避免学生反馈卡在待审核状态。",
            "href": "/teacher/grading?tab=homework",
            "cta": "进入批改",
            "priority": 10,
        })

    blind_spots = int(((quality or {}).get("effectiveness") or {}).get("blind_spots_open") or 0)
    if blind_spots > 0:
        items.append({
            "key": "quality-blind-spots",
            "tone": "warm",
            "label": "质检盲区",
            "title": f"{blind_spots} 处 AI 质检盲区待复核",
            "detail": "这些题 AI 判为合格但真实正确率异常低，复核后会回流命题质检。",
            "href": "/teacher/quality-dashboard",
            "cta": "去复核",
            "priority": 20,
        })

    completion = completion or {}
    students = completion.get("students") or []
    behind = [s for s in students if int(s.get("pending") or 0) > 0]
    overdue = int((completion.get("summary") or {}).get("students_with_overdue") or 0)
    if not overdue:
        overdue = sum(1 for s in behind if int(s.get("overdue") or 0) > 0)
    if behind:
        items.append({
            "key": "completion",
            "tone": "warm" if overdue > 0 else "gold",
            "label": "有逾期" if overdue > 0 else "待催办",
            "title": f"{len(behind)} 名学生还有作业未交",
            "detail": f"其中 {overdue} 名学生存在逾期作业，建议优先催办。" if overdue > 0 else "可查看完成情况并对欠交学生发送提醒。",
            "href": "/teacher/assignments",
            "cta": "查看作业",
            "priority": 30,
        })

    if top_weak_topic:
        tag, count = top_weak_topic
        items.append({
            "key": "weak-topic",
            "tone": "jade",
            "label": "讲评重点",
            "title": f"优先讲评「{tag}」",
            "detail": f"{count} 名学生暴露该薄弱点，可先看班级学情再生成讲评建议。",
            "href": "/teacher/class-analytics",
            "cta": "查看学情",
            "priority": 40,
        })

    wrong = ((wrong_analysis or {}).get("questions") or [None])[0]
    if wrong:
        tag = wrong.get("knowledge_tag")
        assignment_title = wrong.get("assignment_title")
        wrong_count = int(wrong.get("student_count_wrong") or 0)
        items.append({
            "key": "wrong-question",
            "tone": "gold",
            "label": "共性错题",
            "title": f"复盘「{tag}」错题" if tag else "复盘全班高错率题",
            "detail": f"来自{f'「{assignment_title}」' if assignment_title else '近期作业'}，{wrong_count} 人答错。",
            "href": "/teacher/class-analytics",
            "cta": "查看难题榜",
            "priority": 50,
        })

    items.sort(key=lambda item: int(item.get("priority") or 999))
    visible_items = items[:4]
    return {
        "date": today,
        "items": visible_items,
        "summary": {
            "pending_reviews": pending_reviews,
            "blind_spots_open": blind_spots,
            "students_behind": len(behind),
            "students_with_overdue": overdue,
            "top_weak_topic": top_weak_topic[0] if top_weak_topic else None,
        },
        "source_errors": source_errors or [],
    }


def get_teacher_today_queue(teacher_id: str, today: str) -> dict[str, Any]:
    """装配教师今日队列。单个来源失败时降级为空信号并记录 source_errors。"""
    from homework_grading.review_store import list_reviews
    from services.assignment_service import get_teacher_badges
    from services.completion_overview import get_class_completion_overview
    from services.lecture_review_service import aggregate_class_wrong_questions
    from services.quality_dashboard import get_teacher_quality_dashboard

    errors: list[dict[str, str]] = []

    def load(source: str, fn: QueueSource, fallback: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - 降级路径由集成场景覆盖
            errors.append(_source_error(source, exc))
            return fallback

    badges = load("teacher_badges", lambda: get_teacher_badges(teacher_id), {})
    homework_reviews = load("homework_reviews", lambda: list_reviews(decision="pending", limit=50), [])
    completion = load("completion_overview", lambda: get_class_completion_overview(teacher_id, today), {})
    quality = load("quality_dashboard", lambda: get_teacher_quality_dashboard(teacher_id), {})
    top_weak = load("class_analytics", _top_weak_topic, None)
    wrong = load("class_wrong_analysis", lambda: aggregate_class_wrong_questions(teacher_id, 8, 5), {})

    return build_teacher_today_queue(
        today=today,
        pending_reviews=int((badges or {}).get("pending_review") or 0) + len(homework_reviews or []),
        completion=completion,
        quality=quality,
        top_weak_topic=top_weak,
        wrong_analysis=wrong,
        source_errors=errors,
    )
