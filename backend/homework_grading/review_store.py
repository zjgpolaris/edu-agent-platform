from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso


def save_review(
    *,
    actor_id: str,
    student_id: str | None,
    grade_request: dict[str, Any],
    grade_result: dict[str, Any],
) -> str:
    review_id = uuid4().hex
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO homework_reviews
               (id, student_id, actor_id, grade_request_json, grade_result_json,
                needs_human_review, decision, created_at)
               VALUES (:id, :student_id, :actor_id, :grade_request, :grade_result,
                :needs_review, 'pending', :created_at)"""),
            {
                "id": review_id,
                "student_id": student_id,
                "actor_id": actor_id,
                "grade_request": json.dumps(grade_request),
                "grade_result": json.dumps(grade_result),
                "needs_review": int(bool(grade_result.get("needs_human_review"))),
                "created_at": now_iso(),
            },
        )
    return review_id


def _review_from_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["grade_request"] = json.loads(item.pop("grade_request_json") or "{}")
    item["grade_result"] = json.loads(item.pop("grade_result_json") or "{}")
    item["needs_human_review"] = bool(item["needs_human_review"])
    return item


def list_reviews(
    *,
    decision: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    where = ""
    if decision:
        where = "WHERE decision = :decision"
        params["decision"] = decision
    with get_connection() as conn:
        rows = conn.execute(
            text(f"SELECT * FROM homework_reviews {where} ORDER BY created_at DESC LIMIT :limit"),
            params,
        ).mappings().fetchall()
    return [_review_from_row(row) for row in rows]


def get_review(review_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM homework_reviews WHERE id = :id"),
            {"id": review_id},
        ).mappings().fetchone()
    return _review_from_row(row) if row else None


def apply_decision(
    review_id: str,
    *,
    teacher_id: str,
    decision: str,
    teacher_note: str | None = None,
    teacher_score: float | None = None,
) -> bool:
    with get_connection() as conn:
        result = conn.execute(
            text("""UPDATE homework_reviews
               SET decision=:decision, teacher_id=:teacher_id, teacher_note=:note,
                   teacher_score=:score, reviewed_at=:reviewed_at
               WHERE id=:id"""),
            {
                "decision": decision,
                "teacher_id": teacher_id,
                "note": teacher_note,
                "score": teacher_score,
                "reviewed_at": now_iso(),
                "id": review_id,
            },
        )
    return result.rowcount > 0
