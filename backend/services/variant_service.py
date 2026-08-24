"""错题变式选题与缓存服务

当学生在某个知识点上反复答错（wrong_count >= VARIANT_THRESHOLD），
复习时不再重复原题，而是从课程审定内容包选择一道带新材料/情境的迁移题。
没有审定题时阻断，不把一次模型生成直接发布给学生。

对外接口
--------
generate_variant(tag, seed_question=None) -> dict
    选择一道审定变式题；seed_question 用于避开上一道 assessment。

get_or_create_variant(student_id, tag, seed_question=None) -> dict
    先查本地缓存（当天已选择），命中则直接返回；否则调 generate_variant
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
from services.history_review_question import (
    build_curated_review_question,
    build_grounded_review_question,
    is_usable_choice_question,
)

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


def generate_variant(
    tag: str,
    seed_question: dict | None = None,
    *,
    target_difficulty: str = "medium",
    selection_seed: str = "",
) -> dict[str, Any]:
    """选择审定变式题。seed_question 为本 tag 上次出现的题目（可 None）。"""
    curated = build_curated_review_question(
        tag,
        is_variant=True,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
    )
    if curated is not None:
        return curated

    _log.info("variant_service: reviewed assessment missing; blocked tag=%s", tag)
    return build_grounded_review_question(
        tag,
        is_variant=True,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
    )


def get_or_create_variant(
    student_id: str,
    tag: str,
    seed_question: dict | None = None,
    *,
    today: str | None = None,
    target_difficulty: str = "medium",
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
    if cached and is_usable_choice_question(cached) and cached.get("difficulty") == target_difficulty:
        return cached

    # 2. 生成新变式题
    variant = generate_variant(
        tag,
        seed_question,
        target_difficulty=target_difficulty,
        selection_seed=f"{student_id}:{today}:{tag}",
    )

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
