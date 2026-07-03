"""学生通知服务

支持教师向指定学生发送站内催办通知，学生端可读取未读通知数和消息列表。

对外接口
--------
send_urge_notification(teacher_id, student_ids, message, assignment_ids) -> int
    向多名学生批量写入催办通知，返回成功写入数量。

get_student_notifications(student_id, *, limit, unread_only) -> list[dict]
    读取学生的通知列表。

mark_notification_read(notification_id, student_id) -> bool
    标记单条通知为已读。

mark_all_read(student_id) -> int
    将该学生所有未读通知标记为已读，返回受影响行数。

get_unread_count(student_id) -> int
    快速查询未读数（用于徽标）。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS student_notifications (
            id           TEXT PRIMARY KEY,
            student_id   TEXT NOT NULL,
            teacher_id   TEXT NOT NULL,
            message      TEXT NOT NULL,
            assignment_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at   TEXT NOT NULL,
            read_at      TEXT
        )"""))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sn_student ON student_notifications(student_id, created_at DESC)"
        ))


def send_urge_notification(
    teacher_id: str,
    student_ids: list[str],
    message: str,
    assignment_ids: list[str] | None = None,
) -> int:
    """批量向学生发送催办通知。返回成功写入的数量。"""
    if not student_ids:
        return 0
    _ensure_table()
    ts = now_iso()
    aids_json = json.dumps(assignment_ids or [], ensure_ascii=False)
    inserted = 0
    with get_connection() as conn:
        for sid in student_ids:
            sid = str(sid).strip()
            if not sid:
                continue
            conn.execute(
                text("""INSERT INTO student_notifications
                    (id, student_id, teacher_id, message, assignment_ids_json, created_at)
                    VALUES (:id, :sid, :tid, :msg, :aids, :ts)"""),
                {
                    "id": str(uuid.uuid4()),
                    "sid": sid,
                    "tid": str(teacher_id),
                    "msg": str(message).strip() or "老师提醒你完成未交的作业。",
                    "aids": aids_json,
                    "ts": ts,
                },
            )
            inserted += 1
    return inserted


def get_student_notifications(
    student_id: str,
    *,
    limit: int = 20,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    """读取学生通知列表，按时间倒序。"""
    _ensure_table()
    limit = max(1, min(int(limit), 50))
    clause = "AND read_at IS NULL" if unread_only else ""
    with get_connection() as conn:
        rows = conn.execute(
            text(f"""SELECT id, teacher_id, message, assignment_ids_json, created_at, read_at
                 FROM student_notifications
                 WHERE student_id = :sid {clause}
                 ORDER BY created_at DESC LIMIT :lim"""),
            {"sid": student_id, "lim": limit},
        ).mappings().fetchall()
    result = []
    for r in rows:
        try:
            aids = json.loads(r["assignment_ids_json"] or "[]")
        except Exception:
            aids = []
        result.append({
            "id": r["id"],
            "teacher_id": r["teacher_id"],
            "message": r["message"],
            "assignment_ids": aids,
            "created_at": r["created_at"],
            "read_at": r["read_at"],
            "is_read": r["read_at"] is not None,
        })
    return result


def mark_notification_read(notification_id: str, student_id: str) -> bool:
    """标记单条通知已读。返回是否命中。"""
    _ensure_table()
    with get_connection() as conn:
        result = conn.execute(
            text("""UPDATE student_notifications SET read_at=:ts
                 WHERE id=:id AND student_id=:sid AND read_at IS NULL"""),
            {"ts": now_iso(), "id": notification_id, "sid": student_id},
        )
    return (result.rowcount or 0) > 0


def mark_all_read(student_id: str) -> int:
    """批量标记所有未读通知为已读。"""
    _ensure_table()
    with get_connection() as conn:
        result = conn.execute(
            text("UPDATE student_notifications SET read_at=:ts WHERE student_id=:sid AND read_at IS NULL"),
            {"ts": now_iso(), "sid": student_id},
        )
    return result.rowcount or 0


def get_unread_count(student_id: str) -> int:
    """快速查询未读通知数，用于徽标。"""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) AS cnt FROM student_notifications WHERE student_id=:sid AND read_at IS NULL"),
            {"sid": student_id},
        ).fetchone()
    return int(row[0] or 0) if row else 0
