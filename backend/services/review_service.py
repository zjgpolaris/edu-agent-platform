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
from services.variant_service import get_or_create_variant, should_use_variant


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


def get_today_session(student_id: str, today: str, *, hydrate: bool = True) -> dict | None:
    """读取今日复习 session。

    hydrate=True（默认，复习页）：把作业错题追加的 pending_generate 占位题按需生成真题。
    hydrate=False（徽标轮询等只需计数的场景）：不触发 LLM 生成，直接返回占位题。
    """
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT tasks_json, completed, total FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
    if not row:
        return None
    tasks = json.loads(row["tasks_json"])
    if hydrate:
        tasks = _hydrate_pending_tasks(student_id, today, tasks)
    return {"date": today, "completed": row["completed"], "total": row["total"], "tasks": tasks}


def _hydrate_pending_tasks(student_id: str, today: str, tasks: list[dict]) -> list[dict]:
    """为标了 pending_generate 的占位任务（来自作业错题追加）按需生成真实题目并落库。

    只对未作答的占位题生成，避免每次读取都重复调用 LLM。
    """
    pending = [t for t in tasks if t.get("pending_generate") and not t.get("done")]
    if not pending:
        return tasks
    for t in pending:
        generated = _generate_question(t.get("tag", ""))
        t.update(
            question=generated.get("question", t.get("question", "")),
            options=generated.get("options", []),
            answer=generated.get("answer", ""),
            explanation=generated.get("explanation", ""),
        )
        t.pop("pending_generate", None)
    with get_connection() as conn:
        conn.execute(
            text("UPDATE review_sessions SET tasks_json=:tasks WHERE student_id=:sid AND date=:date"),
            {"tasks": json.dumps(tasks, ensure_ascii=False), "sid": student_id, "date": today},
        )
    return tasks


def _pick_question(student_id: str, today: str, wp: dict[str, Any]) -> dict[str, Any]:
    """为单个薄弱点选题策略：答错次数达阈值则生成变式题，否则普通出题。"""
    import logging
    tag = wp["knowledge_tag"]
    try:
        if should_use_variant(wp.get("wrong_count", 0)):
            return get_or_create_variant(student_id, tag, today=today)
    except Exception as exc:
        logging.getLogger(__name__).warning("review: 变式题生成失败 tag=%s: %s", tag, exc)
    return _generate_question(tag)


def create_today_session(student_id: str, today: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    top = sorted(weakpoints, key=lambda w: w["wrong_count"] * _decay_weight(w["last_wrong_at"]), reverse=True)[:8]
    tasks = [_pick_question(student_id, today, w) for w in top]
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions (id, student_id, date, tasks_json, completed, total, created_at)
                 VALUES (:id, :sid, :date, :tasks, 0, :total, :ts)
                 ON CONFLICT(student_id, date) DO NOTHING"""),
            {"id": str(uuid.uuid4()), "sid": student_id, "date": today,
             "tasks": json.dumps(tasks, ensure_ascii=False), "total": len(tasks), "ts": now_iso()},
        )
    return {"date": today, "completed": 0, "total": len(tasks), "tasks": tasks}


def merge_new_weakpoints_to_today(student_id: str, new_tags: list[str], today: str) -> None:
    """作业提交后，将新增错误知识点追加到今日复习 session（若 session 已存在）。

    - 若今日 session 不存在：忽略（用户主动打开复习页时会创建）。
    - 若 session 已存在：只追加尚未在 session 中的 tag，避免重复。
    - 不调用 LLM，只生成占位任务；题目在用户打开复习页时按需生成即可。
    """
    if not new_tags:
        return
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT tasks_json, total FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
        if not row:
            return  # 今日 session 尚未创建，跳过
        tasks: list[dict] = json.loads(row["tasks_json"])
        existing_tags = {t.get("tag") for t in tasks}
        additions = [
            {"tag": tag, "question": f"关于「{tag}」的复习题", "options": [], "answer": "", "explanation": "", "done": False, "correct": None, "pending_generate": True}
            for tag in new_tags if tag not in existing_tags
        ]
        if not additions:
            return
        merged = tasks + additions
        conn.execute(
            text("UPDATE review_sessions SET tasks_json=:tasks, total=:total WHERE student_id=:sid AND date=:date"),
            {"tasks": json.dumps(merged, ensure_ascii=False), "total": len(merged), "sid": student_id, "date": today},
        )


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
    # 复习作答回写错题本：答对累积掌握证据，答错强化薄弱点，让复习真正影响掌握度
    tag = str(tasks[task_idx].get("tag") or "").strip()
    if tag:
        try:
            from services.weakpoint_service import record_correct_evidence, record_weakpoint
            if is_correct:
                record_correct_evidence(student_id, tag)
            else:
                record_weakpoint(student_id, tag, source="review")
        except Exception:
            pass
    return {"completed": completed, "total": len(tasks), "task": tasks[task_idx]}


def get_mastery_overview(student_id: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    heatmap = [
        {"tag": w["knowledge_tag"],
         # 强度 = 错误次数惩罚 + 近期连续答对加成（掌握度证据），钳制在 0.1–1.0
         "strength": round(min(1.0, max(0.1, 1.0 - min(w["wrong_count"] * 0.15, 0.9) + int(w.get("correct_streak") or 0) * 0.2)), 2),
         "wrong_count": w["wrong_count"],
         "correct_streak": int(w.get("correct_streak") or 0),
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
