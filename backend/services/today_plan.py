"""学生「今日计划」聚合：把作业到期、今日复习、错题薄弱点合成一个
按优先级排序的可执行待办清单（只读、确定性）。

这是平台核心价值"把薄弱点变成下一次练习任务"的统一出口——此前作业、
复习、错题三路信号散落在不同页面，学生首页甚至完全没有作业提醒。

优先级：逾期作业 > 今天截止作业 > 今日复习 > 未来/无期限作业 > 薄弱点攻克。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote


def build_today_plan(
    assignments: list[dict[str, Any]],
    review_remaining: int,
    weakpoints: list[dict[str, Any]],
    today: str,
    *,
    review_total: int = 0,
) -> dict[str, Any]:
    """纯函数：合成今日待办。assignments 为学生视角作业（含 submission/due_date）。"""
    tasks: list[dict[str, Any]] = []
    pending = [a for a in (assignments or []) if a.get("submission") is None]
    overdue: list[dict[str, Any]] = []
    due_today: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for a in pending:
        due = (a.get("due_date") or "").strip()
        if due and due < today:
            overdue.append(a)
        elif due and due == today:
            due_today.append(a)
        else:
            upcoming.append(a)

    def _assignment_task(a: dict[str, Any], priority: str, label: str) -> dict[str, Any]:
        due = (a.get("due_date") or "").strip()
        return {
            "kind": "assignment",
            "priority": priority,
            "title": a.get("title") or "作业",
            "detail": label + (f"（截止 {due}）" if due else ""),
            "href": "/student/assignments",
            "ref_id": a.get("id"),
        }

    for a in overdue:
        tasks.append(_assignment_task(a, "urgent", "已逾期，尽快补交"))
    for a in due_today:
        tasks.append(_assignment_task(a, "high", "今天截止"))

    if review_remaining > 0:
        tasks.append({
            "kind": "review",
            "priority": "high",
            "title": f"完成今日复习（{review_remaining} 个知识点）",
            "detail": "错题按 SM-2 排期，趁记忆还热巩固",
            "href": "/student/review",
            "count": review_remaining,
        })

    for a in upcoming:
        tasks.append(_assignment_task(a, "normal", "待完成"))

    if weakpoints:
        top = weakpoints[0]
        tag = str(top.get("knowledge_tag") or "").strip()
        if tag:
            tasks.append({
                "kind": "weakpoint",
                "priority": "normal",
                "title": f"攻克薄弱点「{tag}」",
                "detail": f"错题本出错 {int(top.get('wrong_count') or 0)} 次，用 AI 辅导逐步突破",
                "href": "/student/auto-tutor?focus=" + quote(tag),
                "ref_id": tag,
            })

    summary = {
        "pending_assignments": len(pending),
        "overdue_assignments": len(overdue),
        "due_today_assignments": len(due_today),
        "review_remaining": review_remaining,
        "review_total": review_total,
        "weakpoint_count": len(weakpoints or []),
        "all_clear": len(tasks) == 0,
    }
    return {"date": today, "tasks": tasks, "summary": summary}


def get_student_today_plan(student_id: str, today: str) -> dict[str, Any]:
    """装配今日计划：读取作业、今日复习 session（不触发 LLM hydrate）、错题薄弱点。"""
    from services.assignment_service import list_student_assignments
    from services.review_service import get_today_session
    from services.weakpoint_service import get_weakpoints

    assignments = list_student_assignments(student_id)

    review_remaining = 0
    review_total = 0
    try:
        session = get_today_session(student_id, today, hydrate=False)
    except Exception:
        session = None
    if session:
        review_total = int(session.get("total") or 0)
        review_remaining = max(review_total - int(session.get("completed") or 0), 0)

    try:
        weakpoints = get_weakpoints(student_id)
    except Exception:
        weakpoints = []

    return build_today_plan(
        assignments, review_remaining, weakpoints, today, review_total=review_total,
    )
