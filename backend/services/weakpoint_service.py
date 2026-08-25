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
        _ensure_tables_with_connection(conn)


def _ensure_tables_with_connection(conn: Any) -> None:
    if conn.dialect.name != "sqlite":
        tables = set(inspect(conn).get_table_names())
        missing = {"weakpoints", "weakpoint_evidence"} - tables
        if missing:
            raise RuntimeError(f"weakpoint schema is not migrated: {', '.join(sorted(missing))}")
        return
    conn.execute(text("""CREATE TABLE IF NOT EXISTS weakpoints (
          student_id TEXT NOT NULL, knowledge_tag TEXT NOT NULL,
          wrong_count INTEGER NOT NULL DEFAULT 1,
          last_wrong_at TEXT NOT NULL, source TEXT NOT NULL,
          correct_streak INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (student_id, knowledge_tag))"""))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weakpoints_student ON weakpoints(student_id)"))
    conn.execute(text("""CREATE TABLE IF NOT EXISTS weakpoint_evidence (
          evidence_key TEXT PRIMARY KEY,
          student_id TEXT NOT NULL,
          knowledge_tag TEXT NOT NULL,
          evidence_type TEXT NOT NULL,
          source_feature TEXT NOT NULL,
          source_session_id TEXT,
          assessment_id TEXT,
          evidence_stage TEXT,
          assessment_fingerprint TEXT,
          parent_evidence_key TEXT,
          eligible_at TEXT,
          occurred_at TEXT,
          created_at TEXT NOT NULL)"""))
    conn.execute(text("""CREATE INDEX IF NOT EXISTS idx_weakpoint_evidence_student_tag_created
          ON weakpoint_evidence(student_id, knowledge_tag, created_at)"""))
    existing = {c["name"] for c in inspect(conn).get_columns("weakpoints")}
    if "correct_streak" not in existing:
        conn.execute(text("ALTER TABLE weakpoints ADD COLUMN correct_streak INTEGER NOT NULL DEFAULT 0"))
    evidence_columns = {c["name"] for c in inspect(conn).get_columns("weakpoint_evidence")}
    for name in (
        "evidence_stage", "assessment_fingerprint", "parent_evidence_key", "eligible_at", "occurred_at",
    ):
        if name not in evidence_columns:
            conn.execute(text(f"ALTER TABLE weakpoint_evidence ADD COLUMN {name} TEXT"))
    conn.execute(text("""CREATE INDEX IF NOT EXISTS idx_weakpoint_evidence_chain
          ON weakpoint_evidence(student_id, knowledge_tag, evidence_stage, assessment_fingerprint, occurred_at)"""))


def _record_weakpoint_with_connection(conn: Any, student_id: str, knowledge_tag: str, source: str) -> None:
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


def _record_correct_evidence_with_connection(
    conn: Any,
    student_id: str,
    knowledge_tag: str,
    *,
    mastery_threshold: int = _MASTERY_THRESHOLD,
) -> dict[str, Any]:
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


def apply_weakpoint_evidence_with_connection(
    conn: Any,
    *,
    evidence_key: str,
    student_id: str,
    knowledge_tag: str,
    evidence_type: str,
    source_feature: str,
    source_session_id: str | None,
    assessment_id: str | None,
    evidence_stage: str | None = None,
    assessment_fingerprint: str | None = None,
    parent_evidence_key: str | None = None,
    eligible_at: str | None = None,
    occurred_at: str | None = None,
    mastery_eligible: bool = False,
) -> dict[str, Any]:
    """Record the evidence fact and update its aggregate at most once."""
    _ensure_tables_with_connection(conn)
    if evidence_type not in {
        "wrong", "verified_correct", "retrieval_correct", "independent_correct", "retention_correct",
    }:
        raise ValueError("invalid weakpoint evidence type")
    timestamp = occurred_at or now_iso()
    inserted = conn.execute(
        text("""INSERT INTO weakpoint_evidence (
            evidence_key, student_id, knowledge_tag, evidence_type, source_feature,
            source_session_id, assessment_id, evidence_stage, assessment_fingerprint,
            parent_evidence_key, eligible_at, occurred_at, created_at
        ) VALUES (
            :evidence_key, :student_id, :knowledge_tag, :evidence_type, :source_feature,
            :source_session_id, :assessment_id, :evidence_stage, :assessment_fingerprint,
            :parent_evidence_key, :eligible_at, :occurred_at, :created_at
        ) ON CONFLICT(evidence_key) DO NOTHING"""),
        {
            "evidence_key": evidence_key,
            "student_id": student_id,
            "knowledge_tag": knowledge_tag,
            "evidence_type": evidence_type,
            "source_feature": source_feature,
            "source_session_id": source_session_id,
            "assessment_id": assessment_id,
            "evidence_stage": evidence_stage,
            "assessment_fingerprint": assessment_fingerprint,
            "parent_evidence_key": parent_evidence_key,
            "eligible_at": eligible_at,
            "occurred_at": timestamp,
            "created_at": timestamp,
        },
    )
    if inserted.rowcount != 1:
        return {"applied": False, "reason": "duplicate_evidence"}
    if evidence_type == "wrong":
        _record_weakpoint_with_connection(conn, student_id, knowledge_tag, source_feature)
        return {"applied": True, "action": "weakpoint_recorded"}
    if evidence_type == "retention_correct" and mastery_eligible:
        row = conn.execute(
            text("SELECT 1 FROM weakpoints WHERE student_id=:sid AND knowledge_tag=:tag"),
            {"sid": student_id, "tag": knowledge_tag},
        ).first()
        if row:
            conn.execute(
                text("DELETE FROM weakpoints WHERE student_id=:sid AND knowledge_tag=:tag"),
                {"sid": student_id, "tag": knowledge_tag},
            )
            return {"applied": True, "action": "retention_mastery_recorded", "removed": True}
        return {"applied": True, "action": "retention_mastery_recorded", "removed": False}
    # Immediate correct answers are useful evidence, but they cannot establish
    # retained mastery or increment the legacy consecutive-correct aggregate.
    return {"applied": True, "action": f"{evidence_type}_recorded", "removed": False}


def record_weakpoint(student_id: str, knowledge_tag: str, source: str) -> None:
    """记录/强化一个薄弱点（答错）。答错说明未掌握，连对计数清零。"""
    _ensure_table()
    with get_connection() as conn:
        _record_weakpoint_with_connection(conn, student_id, knowledge_tag, source)


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
        return _record_correct_evidence_with_connection(
            conn,
            student_id,
            knowledge_tag,
            mastery_threshold=mastery_threshold,
        )


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
