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
from services.history_review_question import build_grounded_review_question, is_usable_choice_question
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


_PLACEHOLDER_OPTS = {"选项一", "选项二", "选项三", "选项四", "选项文字", "题目内容", "题目"}

def _generate_question(tag: str) -> dict[str, Any]:
    import logging
    from llm_config import llm_fast

    _log = logging.getLogger(__name__)

    # 使用与目标 tag 无关的固定示例，防止模型照抄示例内容
    prompt = (
        f"你是历史老师，请为知识点「{tag}」出一道四选一选择题。\n"
        "只输出一个 JSON 对象，不要输出其他任何内容（不要 markdown、不要注释）。\n"
        "JSON 格式参考（下面是示例，请用「{tag}」的真实内容替换，不要照抄）：\n"
        '{"question":"武则天是哪个朝代的皇帝？",'
        '"options":["A.汉朝","B.唐朝","C.宋朝","D.明朝"],'
        '"answer":"B",'
        '"explanation":"武则天是中国历史上唯一的女皇帝，统治时期属于唐朝。"}\n'
        f"现在请针对「{tag}」出题："
    )

    def _try_parse(raw: str) -> dict[str, Any] | None:
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start:end])
        except json.JSONDecodeError:
            return None
        if not is_usable_choice_question(data):
            return None
        return data

    for attempt in range(2):
        try:
            raw = llm_fast.invoke([{"role": "user", "content": prompt}]).content
            data = _try_parse(raw)
            if data is not None:
                return {**data, "tag": tag, "done": False, "correct": None}
            _log.warning("review _generate_question placeholder_detected attempt=%s tag=%s raw_preview=%s",
                         attempt + 1, tag, raw[:120])
        except Exception as exc:
            _log.warning("review _generate_question failed attempt=%s tag=%s: %s", attempt + 1, tag, exc)

    # 模型不可用时仍必须给学生一道可作答、可判分、教材有据的题。
    fallback = build_grounded_review_question(tag)
    _log.info(
        "review _generate_question grounded_fallback tag=%s source=%s",
        tag,
        fallback.get("generation_source"),
    )
    return fallback


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


def is_unusable_question(task: dict[str, Any]) -> bool:
    """判断一道已落库的复习题是否无法作答（占位、生成失败或选项残缺）。

    历史上生成失败的题目会被直接写库，因此读取时必须重新判定，
    不能只信任写入时的标记。
    """
    if task.get("pending_generate") or task.get("_generation_failed"):
        return True
    options = task.get("options") or []
    if len(options) != 4 or not all(str(o).strip() for o in options):
        return True
    if not str(task.get("answer") or "").strip():
        return True
    combined = " ".join(str(o) for o in options) + " " + str(task.get("question") or "")
    return any(p in combined for p in _PLACEHOLDER_OPTS) or "暂无选项" in combined


def _hydrate_pending_tasks(student_id: str, today: str, tasks: list[dict]) -> list[dict]:
    """为无法作答的未答题目按需生成真实题目并落库。

    覆盖两类：作业错题追加的 pending_generate 占位题，以及早先生成失败
    被写库的坏题。生成再次失败时保留占位标记，下次打开复习页会重试，
    避免把"选项一/二/三/四"永久固化给学生。
    """
    pending = [t for t in tasks if not t.get("done") and is_unusable_question(t)]
    if not pending:
        return tasks
    changed = False
    for t in pending:
        generated = _generate_question(t.get("tag", ""))
        if generated.get("_generation_failed"):
            # 保留占位标记，下次读取时重试；本次不覆盖已有内容
            t["pending_generate"] = True
            continue
        t.update(
            question=generated.get("question", t.get("question", "")),
            options=generated.get("options", []),
            answer=generated.get("answer", ""),
            explanation=generated.get("explanation", ""),
        )
        t.pop("pending_generate", None)
        t.pop("_generation_failed", None)
        changed = True
    if changed:
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
