"""错题本知识点追踪服务"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso

_WEAKPOINTS_TTL_DAYS = 90


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS weakpoints (
              student_id TEXT NOT NULL, knowledge_tag TEXT NOT NULL,
              wrong_count INTEGER NOT NULL DEFAULT 1,
              last_wrong_at TEXT NOT NULL, source TEXT NOT NULL,
              PRIMARY KEY (student_id, knowledge_tag))"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weakpoints_student ON weakpoints(student_id)"))


def record_weakpoint(student_id: str, knowledge_tag: str, source: str) -> None:
    _ensure_table()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO weakpoints (student_id, knowledge_tag, wrong_count, last_wrong_at, source)
            VALUES (:student_id, :tag, 1, :ts, :source)
            ON CONFLICT(student_id, knowledge_tag) DO UPDATE SET
              wrong_count = weakpoints.wrong_count + 1,
              last_wrong_at = excluded.last_wrong_at,
              source = excluded.source"""),
            {"student_id": student_id, "tag": knowledge_tag, "ts": now_iso(), "source": source},
        )


def get_weakpoints(student_id: str) -> list[dict[str, Any]]:
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT knowledge_tag, wrong_count, last_wrong_at, source FROM weakpoints WHERE student_id = :student_id ORDER BY wrong_count DESC, last_wrong_at DESC"),
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
