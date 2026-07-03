"""教师「班级作业完成情况」聚合：跨该教师所有作业，算出每个学生的
已交 / 欠交 / 逾期，并给出班级维度的掉队情况（只读、确定性）。

此前教师只能看到"每份作业的完成率"，看不到"哪个学生跨多份作业欠交最多、
有几份逾期"——催办与识别掉队学生缺一个学生维度的视图。本模块补上。
"""
from __future__ import annotations

import json
from typing import Any


def compute_class_completion(records: list[dict[str, Any]], today: str) -> dict[str, Any]:
    """纯函数：把作业记录按学生聚合。

    records: [{id, title, due_date, assignee_ids: [...], submitted_ids: [...]}]
    逾期定义：作业 due_date < today 且该学生未提交。
    """
    stu: dict[str, dict[str, Any]] = {}
    for r in records:
        due = (r.get("due_date") or "").strip()
        overdue_window = bool(due and due < today)
        submitted = set(r.get("submitted_ids") or [])
        title = r.get("title") or r.get("id") or "作业"
        for sid in r.get("assignee_ids") or []:
            d = stu.setdefault(str(sid), {
                "student_id": str(sid), "assigned": 0, "submitted": 0,
                "pending": 0, "overdue": 0, "overdue_titles": [],
            })
            d["assigned"] += 1
            if str(sid) in submitted:
                d["submitted"] += 1
            else:
                d["pending"] += 1
                if overdue_window:
                    d["overdue"] += 1
                    d["overdue_titles"].append(title)

    students = list(stu.values())
    # 掉队优先：逾期多 > 欠交多 > 学号
    students.sort(key=lambda x: (-x["overdue"], -x["pending"], x["student_id"]))

    total_assigned = sum(x["assigned"] for x in students)
    total_submitted = sum(x["submitted"] for x in students)
    return {
        "date": today,
        "summary": {
            "student_count": len(students),
            "assignment_count": len(records),
            "students_with_overdue": sum(1 for x in students if x["overdue"] > 0),
            "students_all_done": sum(1 for x in students if x["pending"] == 0),
            "overall_submission_rate": round(total_submitted / total_assigned * 100) if total_assigned else 0,
        },
        "students": students,
    }


def get_class_completion_overview(teacher_id: str, today: str) -> dict[str, Any]:
    """装配：拉取该教师全部作业与提交，按学生聚合完成情况。"""
    from sqlalchemy import text

    from db.engine import get_connection
    from services.assignment_service import _ensure_tables

    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT id, title, due_date, assignee_ids_json FROM assignments WHERE teacher_id = :tid"),
            {"tid": teacher_id},
        ).mappings().fetchall()
        records: list[dict[str, Any]] = []
        for r in rows:
            subs = conn.execute(
                text("SELECT student_id FROM assignment_submissions WHERE assignment_id = :aid"),
                {"aid": r["id"]},
            ).mappings().fetchall()
            records.append({
                "id": r["id"], "title": r["title"], "due_date": r["due_date"],
                "assignee_ids": json.loads(r["assignee_ids_json"] or "[]"),
                "submitted_ids": [s["student_id"] for s in subs],
            })
    return compute_class_completion(records, today)
