"""AI 辅导效果追踪服务

从 learning_events 表读取 auto_tutor 步骤数据（_finalize 写入），
无需修改 AutoTutor 逻辑，纯聚合计算。

对外接口
--------
get_student_tutor_effectiveness(student_id, days) -> dict
    学生视角：按知识点统计辅导次数/掌握率/当前是否仍在错题本。

get_class_tutor_effectiveness(teacher_id, days) -> dict
    教师视角：班级整体辅导有效性摘要 + 各知识点聚合。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso


# ── 学生视角 ──────────────────────────────────────────────────────────────────

def get_student_tutor_effectiveness(
    student_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """学生辅导效果：按知识点汇总。

    Returns:
    {
        "summary": {
            "total_steps": int,      # 总辅导步骤数
            "mastered_steps": int,   # 掌握的步骤数
            "mastery_rate": float,   # 掌握率 0-100
            "tags_worked": int,      # 涉及知识点数
            "days_analyzed": int,
        },
        "tags": [
            {
                "tag": str,
                "total": int,         # 辅导次数
                "mastered": int,      # 掌握次数
                "mastery_rate": float,
                "still_weak": bool,   # 是否仍在错题本
                "last_session_at": str,
            },
            ...   # 按 total 降序
        ],
        "generated_at": str,
    }
    """
    days = max(1, min(int(days), 365))
    with get_connection() as conn:
        # 步骤记录
        rows = conn.execute(
            text("""SELECT topic, success, score, created_at, session_id
                 FROM learning_events
                 WHERE student_id = :sid
                   AND feature = 'auto_tutor'
                   AND event_type = 'auto_tutor_step'
                   AND created_at >= datetime('now', :since)
                 ORDER BY created_at DESC"""),
            {"sid": student_id, "since": f"-{days} days"},
        ).mappings().fetchall()

        # 当前错题本
        try:
            wp_rows = conn.execute(
                text("SELECT knowledge_tag FROM weakpoints WHERE student_id = :sid"),
                {"sid": student_id},
            ).mappings().fetchall()
            weakpoint_tags = {r["knowledge_tag"] for r in wp_rows}
        except Exception:
            weakpoint_tags = set()

    tag_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0, "mastered": 0, "last_session_at": ""
    })
    for r in rows:
        tag = str(r["topic"] or "").strip()
        if not tag:
            continue
        stat = tag_stats[tag]
        stat["total"] += 1
        if r["success"]:
            stat["mastered"] += 1
        if r["created_at"] > stat["last_session_at"]:
            stat["last_session_at"] = r["created_at"]

    total_steps = sum(s["total"] for s in tag_stats.values())
    mastered_steps = sum(s["mastered"] for s in tag_stats.values())
    mastery_rate = round(mastered_steps / total_steps * 100, 1) if total_steps else 0.0

    tag_list = sorted([
        {
            "tag": tag,
            "total": stat["total"],
            "mastered": stat["mastered"],
            "mastery_rate": round(stat["mastered"] / stat["total"] * 100, 1) if stat["total"] else 0.0,
            "still_weak": tag in weakpoint_tags,
            "last_session_at": stat["last_session_at"],
        }
        for tag, stat in tag_stats.items()
    ], key=lambda x: -x["total"])

    return {
        "summary": {
            "total_steps": total_steps,
            "mastered_steps": mastered_steps,
            "mastery_rate": mastery_rate,
            "tags_worked": len(tag_stats),
            "days_analyzed": days,
        },
        "tags": tag_list,
        "generated_at": now_iso(),
    }


# ── 教师视角 ──────────────────────────────────────────────────────────────────

def get_class_tutor_effectiveness(
    teacher_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """班级辅导效果：聚合所有学生的 auto_tutor 步骤数据。

    Returns:
    {
        "summary": {
            "total_steps": int,
            "mastered_steps": int,
            "mastery_rate": float,
            "active_students": int,  # 有辅导记录的学生数
            "days_analyzed": int,
        },
        "tags": [
            {
                "tag": str,
                "student_count": int,    # 接触该知识点的学生数
                "total": int,            # 总辅导次数
                "mastered": int,
                "mastery_rate": float,
            },
            ...  # 按 student_count 降序
        ],
        "generated_at": str,
    }
    """
    days = max(1, min(int(days), 365))
    with get_connection() as conn:
        rows = conn.execute(
            text("""SELECT student_id, topic, success
                 FROM learning_events
                 WHERE feature = 'auto_tutor'
                   AND event_type = 'auto_tutor_step'
                   AND created_at >= datetime('now', :since)"""),
            {"since": f"-{days} days"},
        ).mappings().fetchall()

    tag_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0, "mastered": 0, "students": set()
    })
    active_students: set[str] = set()
    for r in rows:
        tag = str(r["topic"] or "").strip()
        if not tag:
            continue
        active_students.add(r["student_id"])
        stat = tag_stats[tag]
        stat["total"] += 1
        if r["success"]:
            stat["mastered"] += 1
        stat["students"].add(r["student_id"])

    total_steps = sum(s["total"] for s in tag_stats.values())
    mastered_steps = sum(s["mastered"] for s in tag_stats.values())
    mastery_rate = round(mastered_steps / total_steps * 100, 1) if total_steps else 0.0

    tag_list = sorted([
        {
            "tag": tag,
            "student_count": len(stat["students"]),
            "total": stat["total"],
            "mastered": stat["mastered"],
            "mastery_rate": round(stat["mastered"] / stat["total"] * 100, 1) if stat["total"] else 0.0,
        }
        for tag, stat in tag_stats.items()
    ], key=lambda x: (-x["student_count"], -x["mastery_rate"]))

    return {
        "summary": {
            "total_steps": total_steps,
            "mastered_steps": mastered_steps,
            "mastery_rate": mastery_rate,
            "active_students": len(active_students),
            "days_analyzed": days,
        },
        "tags": tag_list[:20],
        "generated_at": now_iso(),
    }
