"""错题变式生成服务

当学生在某个知识点上反复答错（wrong_count >= VARIANT_THRESHOLD），
复习时不再重复出原题，而是 LLM 生成一道"换汤不换药"的变式题：
同一知识点、不同题面/情境/干扰项，帮助学生真正理解而非靠记忆蒙对。

对外接口
--------
generate_variant(tag, seed_question=None) -> dict
    无论如何都调 LLM 生成一道新变式题。seed_question 用于提示 LLM
    "不要和这道题一样"，可为 None（首次或无历史题目时）。

get_or_create_variant(student_id, tag, seed_question=None) -> dict
    先查本地缓存（当天已生成），命中则直接返回；否则调 generate_variant
    落库后返回。调用方无需关心是否命中缓存。

get_cached_variant(student_id, tag, today) -> dict | None
    只读查询，不触发生成。供批量读取时使用。
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso

_log = logging.getLogger(__name__)

# wrong_count 达到此阈值，复习时改用变式题
VARIANT_THRESHOLD = 2


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS variant_questions (
            id          TEXT PRIMARY KEY,
            student_id  TEXT NOT NULL,
            knowledge_tag TEXT NOT NULL,
            variant_json  TEXT NOT NULL,
            seed_hash   TEXT,          -- sha1(seed_question_prompt)，用于去重
            created_at  TEXT NOT NULL,
            date        TEXT NOT NULL  -- 生成日期（YYYY-MM-DD），每天最多复用一次
        )"""))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_vq_student_tag_date "
            "ON variant_questions(student_id, knowledge_tag, date)"
        ))


def _seed_hash(seed_question: dict | None) -> str | None:
    if not seed_question:
        return None
    prompt = str(seed_question.get("question") or seed_question.get("prompt") or "")
    return hashlib.sha1(prompt.encode()).hexdigest()[:16] if prompt else None


def generate_variant(tag: str, seed_question: dict | None = None) -> dict[str, Any]:
    """调 LLM 生成变式题。seed_question 为本 tag 上次出现的题目（可 None）。"""
    from llm_config import llm_fast  # 延迟导入避免循环依赖

    avoid_block = ""
    if seed_question:
        original = str(seed_question.get("question") or seed_question.get("prompt") or "").strip()
        if original:
            avoid_block = f"\n【原题（请勿重复相同题面）】\n{original}\n"

    prompt = (
        f"为初中历史知识点「{tag}」出一道选择题变式题。"
        f"{avoid_block}"
        "要求：考查相同知识点，但题面情境、问法或干扰项与原题明显不同，"
        "让学生需要真正理解才能作答，而非靠记忆套答。\n"
        "严格返回 JSON，不要其他内容：\n"
        '{"question":"题目内容","options":["A.选项一","B.选项二","C.选项三","D.选项四"],'
        '"answer":"A","explanation":"简短解析（1-2句）","is_variant":true}'
    )

    try:
        raw = llm_fast.invoke([{"role": "user", "content": prompt}]).content
        start, end = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        data["is_variant"] = True
        data["tag"] = tag
        data.setdefault("done", False)
        data.setdefault("correct", None)
    except Exception as exc:
        _log.warning("variant_service: LLM 生成失败 tag=%s: %s", tag, exc)
        # 降级：生成占位变式题，与原题有所区别
        data = {
            "question": f"下列关于「{tag}」的说法，正确的是？",
            "options": ["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"],
            "answer": "A",
            "explanation": f"请结合课本复习「{tag}」的核心内容。",
            "is_variant": True,
            "tag": tag,
            "done": False,
            "correct": None,
        }

    return data


def get_or_create_variant(
    student_id: str,
    tag: str,
    seed_question: dict | None = None,
    *,
    today: str | None = None,
) -> dict[str, Any]:
    """查缓存；当天已有变式题则直接返回，否则生成并落库。

    Parameters
    ----------
    student_id : 学生 ID
    tag        : 知识点标签
    seed_question : 原题 dict（用于去重提示），可 None
    today      : YYYY-MM-DD，默认取当天
    """
    import datetime
    _ensure_table()
    if today is None:
        today = datetime.date.today().isoformat()

    # 1. 先查今日缓存
    cached = get_cached_variant(student_id, tag, today)
    if cached:
        return cached

    # 2. 生成新变式题
    variant = generate_variant(tag, seed_question)

    # 3. 落库
    try:
        with get_connection() as conn:
            conn.execute(
                text("""INSERT INTO variant_questions
                    (id, student_id, knowledge_tag, variant_json, seed_hash, created_at, date)
                    VALUES (:id, :sid, :tag, :vj, :sh, :ts, :date)"""),
                {
                    "id": str(uuid.uuid4()),
                    "sid": student_id,
                    "tag": tag,
                    "vj": json.dumps(variant, ensure_ascii=False),
                    "sh": _seed_hash(seed_question),
                    "ts": now_iso(),
                    "date": today,
                },
            )
    except Exception as exc:
        _log.warning("variant_service: 落库失败 tag=%s: %s", tag, exc)

    return variant


def get_cached_variant(student_id: str, tag: str, today: str) -> dict[str, Any] | None:
    """只读查询今日已缓存的变式题，无缓存返回 None。"""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("""SELECT variant_json FROM variant_questions
                 WHERE student_id=:sid AND knowledge_tag=:tag AND date=:date
                 ORDER BY created_at DESC LIMIT 1"""),
            {"sid": student_id, "tag": tag, "date": today},
        ).mappings().fetchone()
    if not row:
        return None
    try:
        return json.loads(row["variant_json"])
    except Exception:
        return None


def should_use_variant(wrong_count: int) -> bool:
    """根据答错次数判断是否应使用变式题（取代重复原题）。"""
    return int(wrong_count or 0) >= VARIANT_THRESHOLD
