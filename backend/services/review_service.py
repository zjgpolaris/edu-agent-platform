"""自适应复习调度服务"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import (
    LearningEvent,
    init_db as init_profile_db,
    now_iso,
    record_learning_event_with_connection,
)
from services.history_review_question import (
    QUALITY_CONTRACT_VERSION,
    build_curated_review_question,
    build_grounded_review_question,
    is_usable_choice_question,
    public_review_question,
)
from services.weakpoint_service import apply_weakpoint_evidence_with_connection, get_weakpoints
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


class ReviewConflictError(ValueError):
    """The same review task was already answered with another option."""


def _generate_question(
    tag: str,
    *,
    is_variant: bool = False,
    seed_question: dict[str, Any] | None = None,
    target_difficulty: str = "easy",
    selection_seed: str = "",
) -> dict[str, Any]:
    curated = build_curated_review_question(
        tag,
        is_variant=is_variant,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
    )
    if curated is not None:
        return curated
    # 当前只有审定内容包能同时证明题干、答案和干扰项质量。教材段落可用于
    # 讲解或后续出题草稿，但不能自动证明一道选择题达到学生发布标准。
    return build_grounded_review_question(
        tag,
        is_variant=is_variant,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
    )


def get_today_session(student_id: str, today: str, *, hydrate: bool = True) -> dict | None:
    """读取今日复习 session。

    hydrate=True（默认，复习页）：从审定题包补齐占位题并升级不合格旧题。
    hydrate=False（徽标轮询等只需计数的场景）：不做题目升级，直接返回已有任务。
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


def is_unusable_question(task: dict[str, Any]) -> bool:
    """判断一道已落库的复习题是否无法作答（占位、生成失败或选项残缺）。

    历史上生成失败的题目会被直接写库，因此读取时必须重新判定，
    不能只信任写入时的标记。
    """
    if task.get("pending_generate") or task.get("_generation_failed"):
        return True
    if int(task.get("quality_contract_version") or 0) != QUALITY_CONTRACT_VERSION:
        return True
    if task.get("quality_status") != "verified":
        return True
    return not is_usable_choice_question(task)


def _adaptive_profile(wp: dict[str, Any]) -> tuple[bool, str, str]:
    wrong_count = int(wp.get("wrong_count") or 0)
    correct_streak = int(wp.get("correct_streak") or 0)
    if wrong_count < 4 and (should_use_variant(wrong_count) or correct_streak >= 1):
        message = (
            "已完成一次基础辨析，先独立作答，再用对照材料确认是否真正理解。"
            if correct_streak >= 1
            else "这个知识点近期反复出错，先独立作答，再用对照材料检查理解。"
        )
        return True, "medium", message
    message = (
        "这个知识点错误较多，先用基础辨析稳住核心史实。"
        if wrong_count >= 4
        else "根据近期错题安排一道基础辨析。"
    )
    return False, "easy", message


def _hydrate_pending_tasks(student_id: str, today: str, tasks: list[dict]) -> list[dict]:
    """为无法作答的未答题目按需生成真实题目并落库。

    覆盖两类：作业错题追加的 pending_generate 占位题，以及早先已写库但
    不满足质量合同的题。缺少审定题时保留 blocked 状态，不向学生发布。
    """
    weakpoints = {item["knowledge_tag"]: item for item in get_weakpoints(student_id)}
    changed = False
    for index, task in enumerate(tasks):
        if task.get("done"):
            continue
        wp = weakpoints.get(str(task.get("tag") or ""))
        if wp:
            is_variant, target_difficulty, adaptive_message = _adaptive_profile(wp)
        else:
            is_variant = bool(task.get("is_variant"))
            target_difficulty = str(task.get("target_difficulty") or task.get("difficulty") or ("medium" if is_variant else "easy"))
            adaptive_message = str(task.get("adaptive_message") or "")
        adaptive_mismatch = bool(wp) and (
            bool(task.get("is_variant")) != is_variant
            or str(task.get("difficulty") or "") != target_difficulty
        )
        if not is_unusable_question(task) and not adaptive_mismatch:
            continue
        generated = _generate_question(
            str(task.get("tag") or ""),
            is_variant=is_variant,
            seed_question=task,
            target_difficulty=target_difficulty,
            selection_seed=f"{student_id}:{today}:{index}",
        )
        replacement = {
            **generated,
            **({"adaptive_message": adaptive_message} if adaptive_message else {}),
        }
        if replacement != task:
            task.clear()
            task.update(replacement)
            changed = True
    if changed:
        with get_connection() as conn:
            conn.execute(
                text("UPDATE review_sessions SET tasks_json=:tasks WHERE student_id=:sid AND date=:date"),
                {"tasks": json.dumps(tasks, ensure_ascii=False), "sid": student_id, "date": today},
            )
    return tasks


def _pick_question(student_id: str, today: str, wp: dict[str, Any]) -> dict[str, Any]:
    """Pick a reviewed assessment using the student's current evidence state."""
    import logging
    tag = wp["knowledge_tag"]
    is_variant, target_difficulty, adaptive_message = _adaptive_profile(wp)
    try:
        if is_variant:
            task = get_or_create_variant(
                student_id,
                tag,
                today=today,
                target_difficulty=target_difficulty,
            )
            task["adaptive_message"] = adaptive_message
            return task
    except Exception as exc:
        logging.getLogger(__name__).warning("review: 变式题生成失败 tag=%s: %s", tag, exc)
    task = _generate_question(
        tag,
        target_difficulty=target_difficulty,
        selection_seed=f"{student_id}:{today}:{tag}",
    )
    task["adaptive_message"] = adaptive_message
    return task


def create_today_session(student_id: str, today: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    top = sorted(weakpoints, key=lambda w: w["wrong_count"] * _decay_weight(w["last_wrong_at"]), reverse=True)[:8]
    tasks = [_pick_question(student_id, today, w) for w in top]
    # 生成失败的题标记为待重试，下次打开复习页会重新生成，而不是固化成占位题
    for t in tasks:
        if is_unusable_question(t):
            t["pending_generate"] = True
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions (id, student_id, date, tasks_json, completed, total, created_at)
                 VALUES (:id, :sid, :date, :tasks, 0, :total, :ts)
                 ON CONFLICT(student_id, date) DO NOTHING"""),
            {"id": str(uuid.uuid4()), "sid": student_id, "date": today,
             "tasks": json.dumps(tasks, ensure_ascii=False), "total": len(tasks), "ts": now_iso()},
        )
    return {"date": today, "completed": 0, "total": len(tasks), "tasks": tasks}


def public_review_session(session: dict[str, Any]) -> dict[str, Any]:
    """Serialize a review session without pre-disclosing answers or feedback."""
    public_tasks: list[dict[str, Any]] = []
    blocked_tags: list[str] = []
    for task_index, task in enumerate(session.get("tasks") or []):
        if is_unusable_question(task):
            blocked_tags.append(str(task.get("tag") or "历史知识点"))
            continue
        public = public_review_question(task)
        public["task_index"] = task_index
        public_tasks.append(public)
    return {
        "date": session.get("date"),
        "completed": sum(1 for task in public_tasks if task.get("done")),
        "total": len(public_tasks),
        "tasks": public_tasks,
        "blocked_count": len(blocked_tags),
        "blocked_tags": blocked_tags,
    }


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


def submit_answer(student_id: str, today: str, task_idx: int, selected_answer: str) -> dict:
    selected = str(selected_answer or "").strip().upper()[:1]
    if selected not in "ABCD":
        raise ValueError("selected_answer must be A, B, C or D")
    _ensure_table()
    init_profile_db()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT tasks_json, completed, total FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
        if not row:
            raise ValueError("review session not found")
        original_tasks_json = row["tasks_json"]
        tasks = json.loads(original_tasks_json)
        if not 0 <= task_idx < len(tasks):
            raise ValueError("invalid task_index")
        task = tasks[task_idx]
        if is_unusable_question(task):
            raise ValueError("review question is not answerable")
        if task.get("done"):
            if task.get("selected_answer") != selected:
                raise ReviewConflictError("review task already answered with another option")
            scoreable = [item for item in tasks if not is_unusable_question(item)]
            return {
                "completed": sum(1 for item in scoreable if item.get("done")),
                "total": len(scoreable),
                "is_correct": bool(task.get("correct")),
                "replayed": True,
                "task": public_review_question(task, reveal_answer=True),
            }

        answer = str(task.get("answer") or "").strip().upper()[:1]
        is_correct = selected == answer
        feedback = task.get("option_feedback") if isinstance(task.get("option_feedback"), dict) else {}
        task.update(
            done=True,
            correct=is_correct,
            selected_answer=selected,
            selected_feedback=str(feedback.get(selected) or task.get("explanation") or "").strip(),
        )
        completed = sum(1 for t in tasks if t.get("done"))
        updated = conn.execute(
            text("""UPDATE review_sessions SET tasks_json=:tasks, completed=:c
                  WHERE student_id=:sid AND date=:date AND tasks_json=:expected"""),
            {
                "tasks": json.dumps(tasks, ensure_ascii=False),
                "c": completed,
                "sid": student_id,
                "date": today,
                "expected": original_tasks_json,
            },
        )
        if updated.rowcount != 1:
            raise ReviewConflictError("review task changed while submitting")

        tag = str(task.get("tag") or "").strip()
        question_id = str(task.get("question_id") or f"task-{task_idx}")
        effect_key = f"review:{student_id}:{today}:{task_idx}:{question_id}"
        if tag:
            apply_weakpoint_evidence_with_connection(
                conn,
                evidence_key=effect_key,
                student_id=student_id,
                knowledge_tag=tag,
                evidence_type="verified_correct" if is_correct else "wrong",
                source_feature="review",
                source_session_id=f"review:{today}",
                assessment_id=question_id,
            )
            record_learning_event_with_connection(
                conn,
                LearningEvent(
                    student_id=student_id,
                    session_id=f"review:{today}",
                    feature="review",
                    event_type="review_answered",
                    topic=tag,
                    score=1.0 if is_correct else 0.0,
                    success=is_correct,
                    metadata={
                        "assessment_id": question_id,
                        "difficulty": task.get("difficulty"),
                        "cognitive_action": task.get("cognitive_action"),
                        "is_variant": bool(task.get("is_variant")),
                    },
                ),
                effect_key=f"{effect_key}:event",
            )
    scoreable = [item for item in tasks if not is_unusable_question(item)]
    return {
        "completed": sum(1 for item in scoreable if item.get("done")),
        "total": len(scoreable),
        "is_correct": is_correct,
        "replayed": False,
        "task": public_review_question(task, reveal_answer=True),
    }


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
