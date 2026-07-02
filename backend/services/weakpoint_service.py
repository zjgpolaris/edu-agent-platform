"""错题本知识点追踪服务"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import inspect, text

from db.engine import get_connection
from student_profile import now_iso

_WEAKPOINTS_TTL_DAYS = 90
_MASTERY_THRESHOLD = 2  # 连续答对多少次判定掌握并移出错题本


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS weakpoints (
              student_id TEXT NOT NULL, knowledge_tag TEXT NOT NULL,
              wrong_count INTEGER NOT NULL DEFAULT 1,
              last_wrong_at TEXT NOT NULL, source TEXT NOT NULL,
              correct_streak INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (student_id, knowledge_tag))"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weakpoints_student ON weakpoints(student_id)"))
        # 旧库补列
        existing = {c["name"] for c in inspect(conn).get_columns("weakpoints")}
        if "correct_streak" not in existing:
            conn.execute(text("ALTER TABLE weakpoints ADD COLUMN correct_streak INTEGER NOT NULL DEFAULT 0"))


def record_weakpoint(student_id: str, knowledge_tag: str, source: str) -> None:
    """记录/强化一个薄弱点（答错）。答错说明未掌握，连对计数清零。"""
    _ensure_table()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO weakpoints (student_id, knowledge_tag, wrong_count, last_wrong_at, source, correct_streak)
            VALUES (:student_id, :tag, 1, :ts, :source, 0)
            ON CONFLICT(student_id, knowledge_tag) DO UPDATE SET
              wrong_count = weakpoints.wrong_count + 1,
              last_wrong_at = excluded.last_wrong_at,
              source = excluded.source,
              correct_streak = 0"""),
            {"student_id": student_id, "tag": knowledge_tag, "ts": now_iso(), "source": source},
        )


def record_correct_evidence(
    student_id: str,
    knowledge_tag: str,
    *,
    mastery_threshold: int = _MASTERY_THRESHOLD,
) -> dict[str, Any]:
    """答对一次：累积掌握证据，连续答对达阈值才移出错题本。

    - 未被跟踪的 tag：no-op，返回 {"removed": False, "reason": "not_tracked"}。
    - 已跟踪：correct_streak+1；达到 mastery_threshold 则删除（判定掌握）。
    替代此前"答对即删"的粗暴逻辑。
    """
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT correct_streak FROM weakpoints WHERE student_id=:sid AND knowledge_tag=:tag"),
            {"sid": student_id, "tag": knowledge_tag},
        ).mappings().fetchone()
        if not row:
            return {"removed": False, "reason": "not_tracked"}
        streak = int(row["correct_streak"] or 0) + 1
        if streak >= mastery_threshold:
            conn.execute(
                text("DELETE FROM weakpoints WHERE student_id=:sid AND knowledge_tag=:tag"),
                {"sid": student_id, "tag": knowledge_tag},
            )
            return {"removed": True, "correct_streak": streak}
        conn.execute(
            text("UPDATE weakpoints SET correct_streak=:s WHERE student_id=:sid AND knowledge_tag=:tag"),
            {"s": streak, "sid": student_id, "tag": knowledge_tag},
        )
        return {"removed": False, "correct_streak": streak}


def get_weakpoints(student_id: str) -> list[dict[str, Any]]:
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT knowledge_tag, wrong_count, last_wrong_at, source, correct_streak FROM weakpoints WHERE student_id = :student_id ORDER BY wrong_count DESC, last_wrong_at DESC"),
            {"student_id": student_id},
        ).mappings().fetchall()
    return [dict(row) for row in rows]


def delete_weakpoint(student_id: str, knowledge_tag: str) -> None:
    _ensure_table()
    with get_connection() as conn:
        conn.execute(text("DELETE FROM weakpoints WHERE student_id = :student_id AND knowledge_tag = :tag"), {"student_id": student_id, "tag": knowledge_tag})


def clear_weakpoints(student_id: str) -> None:
    _ensure_table()
    with get_connection() as conn:
        conn.execute(text("DELETE FROM weakpoints WHERE student_id = :student_id"), {"student_id": student_id})


def clear_stale_weakpoints(days: int = _WEAKPOINTS_TTL_DAYS) -> int:
    """Remove weakpoint entries not updated in `days` days. Returns deleted count."""
    _ensure_table()
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    with get_connection() as conn:
        result = conn.execute(text("DELETE FROM weakpoints WHERE last_wrong_at < :cutoff"), {"cutoff": cutoff})
        return result.rowcount
