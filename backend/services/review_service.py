"""自适应复习调度服务"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso
from services.weakpoint_service import get_weakpoints


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS review_sessions (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            date TEXT NOT NULL,
            tasks_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(student_id, date))"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_review_sessions_student ON review_sessions(student_id)"))


def _decay_weight(last_wrong_at: str) -> float:
    """Returns 0.1–1.0 based on how many days since last wrong answer."""
    try:
        ts = time.strptime(last_wrong_at[:19], "%Y-%m-%dT%H:%M:%S")
        days = (time.time() - time.mktime(ts)) / 86400
    except Exception:
        return 1.0
    if days < 1: return 0.1
    if days < 3: return 0.4
    if days < 7: return 0.7
    return 1.0


def _generate_question(tag: str) -> dict[str, Any]:
    from llm_config import llm_fast
    prompt = (
        f"为历史知识点「{tag}」出一道选择题，严格返回JSON，不要其他内容：\n"
        '{"question":"题目内容","options":["A.选项一","B.选项二","C.选项三","D.选项四"],'
        '"answer":"A","explanation":"简短解析（1-2句）"}'
    )
    try:
        raw = llm_fast.invoke([{"role": "user", "content": prompt}]).content
        start, end = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[start:end])
    except Exception:
        data = {
            "question": f"关于「{tag}」，以下说法正确的是？",
            "options": ["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"],
            "answer": "A",
            "explanation": f"请复习{tag}相关内容。",
        }
    return {**data, "tag": tag, "done": False, "correct": None}


def get_today_session(student_id: str, today: str) -> dict | None:
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT tasks_json, completed, total FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
    if not row:
        return None
    return {"date": today, "completed": row["completed"], "total": row["total"], "tasks": json.loads(row["tasks_json"])}


def create_today_session(student_id: str, today: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    top = sorted(weakpoints, key=lambda w: w["wrong_count"] * _decay_weight(w["last_wrong_at"]), reverse=True)[:8]
    tasks = [_generate_question(w["knowledge_tag"]) for w in top]
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions (id, student_id, date, tasks_json, completed, total, created_at)
                 VALUES (:id, :sid, :date, :tasks, 0, :total, :ts)
                 ON CONFLICT(student_id, date) DO NOTHING"""),
            {"id": str(uuid.uuid4()), "sid": student_id, "date": today,
             "tasks": json.dumps(tasks, ensure_ascii=False), "total": len(tasks), "ts": now_iso()},
        )
    return {"date": today, "completed": 0, "total": len(tasks), "tasks": tasks}


def submit_answer(student_id: str, today: str, task_idx: int, is_correct: bool) -> dict:
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT tasks_json FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
        if not row:
            raise ValueError("review session not found")
        tasks = json.loads(row["tasks_json"])
        if not 0 <= task_idx < len(tasks):
            raise ValueError("invalid task_index")
        tasks[task_idx].update(done=True, correct=is_correct)
        completed = sum(1 for t in tasks if t["done"])
        conn.execute(
            text("UPDATE review_sessions SET tasks_json=:tasks, completed=:c WHERE student_id=:sid AND date=:date"),
            {"tasks": json.dumps(tasks, ensure_ascii=False), "c": completed, "sid": student_id, "date": today},
        )
    return {"completed": completed, "total": len(tasks), "task": tasks[task_idx]}


def get_mastery_overview(student_id: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    heatmap = [
        {"tag": w["knowledge_tag"],
         "strength": round(max(0.1, 1.0 - min(w["wrong_count"] * 0.15, 0.9)), 2),
         "wrong_count": w["wrong_count"],
         "last_reviewed": w["last_wrong_at"]}
        for w in weakpoints
    ]
    mastered = sum(1 for h in heatmap if h["strength"] >= 0.7)
    learning = sum(1 for h in heatmap if 0.4 <= h["strength"] < 0.7)
    weak = len(heatmap) - mastered - learning

    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT date FROM review_sessions WHERE student_id=:sid AND completed >= total AND total > 0 ORDER BY date DESC LIMIT 30"),
            {"sid": student_id},
        ).mappings().fetchall()
    streak = 0
    for i, row in enumerate(rows):
        if row["date"] == (date.today() - timedelta(days=i)).isoformat():
            streak += 1
        else:
            break

    return {"total_tags": len(heatmap), "mastered": mastered, "learning": learning, "weak": weak,
            "streak_days": streak, "heatmap": heatmap}
