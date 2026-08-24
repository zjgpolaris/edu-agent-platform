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
import json
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
        # 步骤记录 + 退出票学习证据
        rows = conn.execute(
            text("""SELECT topic, success, score, created_at, session_id, event_type, metadata_json
                 FROM learning_events
                 WHERE student_id = :sid
                   AND feature = 'auto_tutor'
                   AND event_type IN (
                       'auto_tutor_step', 'auto_tutor_exit_ticket',
                       'auto_tutor_practice_answered', 'auto_tutor_exit_ticket_answered',
                       'auto_tutor_verified_mastery', 'auto_tutor_content_blocked'
                   )
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
        "total": 0, "mastered": 0, "exit_tickets": 0, "exit_ticket_mastered": 0,
        "practice_total": 0, "practice_correct": 0, "verified_mastery": 0,
        "content_blocked": 0, "false_mastery": 0,
        "last_session_at": "", "last_exit_ticket_at": ""
    })
    practice_sessions: set[str] = set()
    blocked_sessions: set[str] = set()
    verified_mastery_sessions: set[str] = set()
    for r in rows:
        tag = str(r["topic"] or "").strip()
        if not tag:
            continue
        stat = tag_stats[tag]
        event_type = r["event_type"]
        if event_type == "auto_tutor_exit_ticket":
            stat["exit_tickets"] += 1
            if r["success"]:
                stat["exit_ticket_mastered"] += 1
            if r["created_at"] > stat["last_exit_ticket_at"]:
                stat["last_exit_ticket_at"] = r["created_at"]
        elif event_type == "auto_tutor_step":
            stat["total"] += 1
            if r["success"]:
                stat["mastered"] += 1
        elif event_type == "auto_tutor_practice_answered":
            stat["practice_total"] += 1
            if r["session_id"]:
                practice_sessions.add(str(r["session_id"]))
            if r["success"]:
                stat["practice_correct"] += 1
        elif event_type == "auto_tutor_verified_mastery":
            try:
                metadata = json.loads(r["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            valid_mastery = bool(r["success"] and metadata.get("content_validation_status") == "verified")
            if valid_mastery:
                stat["verified_mastery"] += 1
                if r["session_id"]:
                    verified_mastery_sessions.add(str(r["session_id"]))
            else:
                stat["false_mastery"] += 1
        elif event_type == "auto_tutor_content_blocked":
            stat["content_blocked"] += 1
            if r["session_id"]:
                blocked_sessions.add(str(r["session_id"]))
        if r["created_at"] > stat["last_session_at"]:
            stat["last_session_at"] = r["created_at"]

    total_steps = sum(s["total"] for s in tag_stats.values())
    mastered_steps = sum(s["mastered"] for s in tag_stats.values())
    mastery_rate = round(mastered_steps / total_steps * 100, 1) if total_steps else 0.0
    exit_tickets = sum(s["exit_tickets"] for s in tag_stats.values())
    exit_ticket_mastered = sum(s["exit_ticket_mastered"] for s in tag_stats.values())
    exit_ticket_mastery_rate = round(exit_ticket_mastered / exit_tickets * 100, 1) if exit_tickets else 0.0
    practice_total = sum(s["practice_total"] for s in tag_stats.values())
    practice_correct = sum(s["practice_correct"] for s in tag_stats.values())
    false_mastery_count = sum(s["false_mastery"] for s in tag_stats.values())
    evaluated_sessions = practice_sessions | blocked_sessions

    tag_list = sorted([
        {
            "tag": tag,
            "total": stat["total"],
            "mastered": stat["mastered"],
            "mastery_rate": round(stat["mastered"] / stat["total"] * 100, 1) if stat["total"] else 0.0,
            "exit_tickets": stat["exit_tickets"],
            "exit_ticket_mastered": stat["exit_ticket_mastered"],
            "exit_ticket_mastery_rate": round(stat["exit_ticket_mastered"] / stat["exit_tickets"] * 100, 1) if stat["exit_tickets"] else 0.0,
            "still_weak": tag in weakpoint_tags,
            "last_session_at": stat["last_session_at"],
            "last_exit_ticket_at": stat["last_exit_ticket_at"],
            "practice_total": stat["practice_total"],
            "practice_correct": stat["practice_correct"],
            "practice_accuracy": round(stat["practice_correct"] / stat["practice_total"] * 100, 1) if stat["practice_total"] else 0.0,
            "verified_mastery": stat["verified_mastery"],
            "content_blocked": stat["content_blocked"],
        }
        for tag, stat in tag_stats.items()
    ], key=lambda x: -x["total"])

    return {
        "summary": {
            "total_steps": total_steps,
            "mastered_steps": mastered_steps,
            "mastery_rate": mastery_rate,
            "exit_tickets": exit_tickets,
            "exit_ticket_mastered": exit_ticket_mastered,
            "exit_ticket_mastery_rate": exit_ticket_mastery_rate,
            "practice_completion_rate": round(len(practice_sessions) / len(evaluated_sessions) * 100, 1) if evaluated_sessions else 0.0,
            "practice_accuracy": round(practice_correct / practice_total * 100, 1) if practice_total else 0.0,
            "verified_mastery_rate": round(len(verified_mastery_sessions) / len(evaluated_sessions) * 100, 1) if evaluated_sessions else 0.0,
            "content_blocked_rate": round(len(blocked_sessions) / len(evaluated_sessions) * 100, 1) if evaluated_sessions else 0.0,
            "false_mastery_count": false_mastery_count,
            "delayed_retention_rate": None,
            "delayed_retention_status": "NOT_RUN",
            "legacy_practice_result": {"total": total_steps, "correct": mastered_steps, "accuracy": mastery_rate},
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
            text("""SELECT student_id, topic, success, event_type, session_id, metadata_json
                 FROM learning_events
                 WHERE feature = 'auto_tutor'
                   AND event_type IN (
                       'auto_tutor_step', 'auto_tutor_exit_ticket',
                       'auto_tutor_practice_answered', 'auto_tutor_exit_ticket_answered',
                       'auto_tutor_verified_mastery', 'auto_tutor_content_blocked'
                   )
                   AND created_at >= datetime('now', :since)"""),
            {"since": f"-{days} days"},
        ).mappings().fetchall()

    tag_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0, "mastered": 0, "exit_tickets": 0, "exit_ticket_mastered": 0,
        "practice_total": 0, "practice_correct": 0, "verified_mastery": 0,
        "content_blocked": 0, "false_mastery": 0,
        "students": set(), "exit_ticket_students": set()
    })
    practice_sessions: set[tuple[str, str]] = set()
    blocked_sessions: set[tuple[str, str]] = set()
    verified_mastery_sessions: set[tuple[str, str]] = set()
    active_students: set[str] = set()
    students_with_exit_ticket: set[str] = set()
    for r in rows:
        tag = str(r["topic"] or "").strip()
        if not tag:
            continue
        active_students.add(r["student_id"])
        stat = tag_stats[tag]
        event_type = r["event_type"]
        if event_type == "auto_tutor_exit_ticket":
            stat["exit_tickets"] += 1
            if r["success"]:
                stat["exit_ticket_mastered"] += 1
            stat["exit_ticket_students"].add(r["student_id"])
            students_with_exit_ticket.add(r["student_id"])
        elif event_type == "auto_tutor_step":
            stat["total"] += 1
            if r["success"]:
                stat["mastered"] += 1
        elif event_type == "auto_tutor_practice_answered":
            stat["practice_total"] += 1
            if r["session_id"]:
                practice_sessions.add((str(r["student_id"]), str(r["session_id"])))
            if r["success"]:
                stat["practice_correct"] += 1
        elif event_type == "auto_tutor_verified_mastery":
            try:
                metadata = json.loads(r["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            valid_mastery = bool(r["success"] and metadata.get("content_validation_status") == "verified")
            if valid_mastery:
                stat["verified_mastery"] += 1
                if r["session_id"]:
                    verified_mastery_sessions.add((str(r["student_id"]), str(r["session_id"])))
            else:
                stat["false_mastery"] += 1
        elif event_type == "auto_tutor_content_blocked":
            stat["content_blocked"] += 1
            if r["session_id"]:
                blocked_sessions.add((str(r["student_id"]), str(r["session_id"])))
        stat["students"].add(r["student_id"])

    total_steps = sum(s["total"] for s in tag_stats.values())
    mastered_steps = sum(s["mastered"] for s in tag_stats.values())
    mastery_rate = round(mastered_steps / total_steps * 100, 1) if total_steps else 0.0
    exit_tickets = sum(s["exit_tickets"] for s in tag_stats.values())
    exit_ticket_mastered = sum(s["exit_ticket_mastered"] for s in tag_stats.values())
    exit_ticket_mastery_rate = round(exit_ticket_mastered / exit_tickets * 100, 1) if exit_tickets else 0.0
    practice_total = sum(s["practice_total"] for s in tag_stats.values())
    practice_correct = sum(s["practice_correct"] for s in tag_stats.values())
    false_mastery_count = sum(s["false_mastery"] for s in tag_stats.values())
    evaluated_sessions = practice_sessions | blocked_sessions

    tag_list = sorted([
        {
            "tag": tag,
            "student_count": len(stat["students"]),
            "total": stat["total"],
            "mastered": stat["mastered"],
            "mastery_rate": round(stat["mastered"] / stat["total"] * 100, 1) if stat["total"] else 0.0,
            "exit_tickets": stat["exit_tickets"],
            "exit_ticket_mastered": stat["exit_ticket_mastered"],
            "exit_ticket_mastery_rate": round(stat["exit_ticket_mastered"] / stat["exit_tickets"] * 100, 1) if stat["exit_tickets"] else 0.0,
            "exit_ticket_student_count": len(stat["exit_ticket_students"]),
            "practice_total": stat["practice_total"],
            "practice_correct": stat["practice_correct"],
            "practice_accuracy": round(stat["practice_correct"] / stat["practice_total"] * 100, 1) if stat["practice_total"] else 0.0,
            "verified_mastery": stat["verified_mastery"],
            "content_blocked": stat["content_blocked"],
        }
        for tag, stat in tag_stats.items()
    ], key=lambda x: (-x["student_count"], -x["mastery_rate"]))

    return {
        "summary": {
            "total_steps": total_steps,
            "mastered_steps": mastered_steps,
            "mastery_rate": mastery_rate,
            "exit_tickets": exit_tickets,
            "exit_ticket_mastered": exit_ticket_mastered,
            "exit_ticket_mastery_rate": exit_ticket_mastery_rate,
            "practice_completion_rate": round(len(practice_sessions) / len(evaluated_sessions) * 100, 1) if evaluated_sessions else 0.0,
            "practice_accuracy": round(practice_correct / practice_total * 100, 1) if practice_total else 0.0,
            "verified_mastery_rate": round(len(verified_mastery_sessions) / len(evaluated_sessions) * 100, 1) if evaluated_sessions else 0.0,
            "content_blocked_rate": round(len(blocked_sessions) / len(evaluated_sessions) * 100, 1) if evaluated_sessions else 0.0,
            "false_mastery_count": false_mastery_count,
            "delayed_retention_rate": None,
            "delayed_retention_status": "NOT_RUN",
            "legacy_practice_result": {"total": total_steps, "correct": mastered_steps, "accuracy": mastery_rate},
            "active_students": len(active_students),
            "students_with_exit_ticket": len(students_with_exit_ticket),
            "days_analyzed": days,
        },
        "tags": tag_list[:20],
        "generated_at": now_iso(),
    }
