"""
学习偏好配置服务 — 存储并读取学生的 AI 教学风格偏好
"""
from __future__ import annotations

import json

from sqlalchemy import text

from db.engine import DATABASE_URL, get_connection

# ── 数据库方言检测 ──────────────────────────────────────────────────────
_IS_POSTGRES = DATABASE_URL.startswith(("postgresql://", "postgres://"))

# 偏好维度定义
PREFERENCE_DIMS = {
    "pace": {
        "label": "学习速度",
        "options": {"fast": "快速模式（简洁讲解）", "normal": "标准模式", "deep": "深度模式（详细展开）"},
        "default": "normal",
    },
    "style": {
        "label": "讲解风格",
        "options": {"example": "偏举例（多实例）", "logic": "偏逻辑（多推导）", "story": "偏故事（多叙事）"},
        "default": "example",
    },
    "interaction": {
        "label": "互动频率",
        "options": {"high": "频繁提问（每步追问）", "medium": "适中（关键点提问）", "low": "少提问（专注学习）"},
        "default": "medium",
    },
    "difficulty": {
        "label": "难度偏好",
        "options": {"easy": "先简后难", "match": "匹配当前水平", "challenge": "挑战模式（适当拔高）"},
        "default": "match",
    },
}

# prompt 注入片段
PACE_PROMPTS = {
    "fast": "讲解力求简洁，每个知识点控制在80字以内，直接给出结论。",
    "normal": "讲解详略适中，关键点充分说明。",
    "deep": "讲解要详尽，展开背景、过程、影响，每个知识点不少于150字。",
}
STYLE_PROMPTS = {
    "example": "每个概念都要举至少2个具体历史例子来辅助说明。",
    "logic": "优先用逻辑推导和因果链解释，少举例，多分析。",
    "story": "用叙事和故事化方式呈现，让知识有画面感。",
}
INTERACTION_PROMPTS = {
    "high": "每讲一个要点后，都要向学生提一个追问，引导其主动思考。",
    "medium": "在关键知识节点（约每2-3个要点）提一次追问。",
    "low": "以讲授为主，减少提问，让学生专注接收。",
}
DIFFICULTY_PROMPTS = {
    "easy": "从最基础的层面开始，确保打好基础再逐步加深。",
    "match": "根据学生当前掌握情况匹配合适难度。",
    "challenge": "在学生已掌握的基础上适当拔高，提出有一定挑战性的问题。",
}


def _ensure_table():
    with get_connection() as conn:
        if _IS_POSTGRES:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS learning_preferences (
                    id BIGSERIAL PRIMARY KEY,
                    student_id TEXT NOT NULL UNIQUE,
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS learning_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL UNIQUE,
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """))
        conn.commit()


def get_preferences(student_id: str) -> dict:
    """
    获取学生偏好配置，未设置的维度返回默认值

    Returns:
        {
            "pace": "normal",
            "style": "example",
            "interaction": "medium",
            "difficulty": "match"
        }
    """
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT preferences_json FROM learning_preferences WHERE student_id = :sid"),
            {"sid": student_id},
        ).fetchone()

    stored = json.loads(row[0]) if row else {}
    # 合并默认值
    return {k: stored.get(k, v["default"]) for k, v in PREFERENCE_DIMS.items()}


def set_preferences(student_id: str, updates: dict) -> dict:
    """
    保存学生偏好配置（只更新传入的维度）

    Args:
        updates: 要更新的偏好项，例如 {"pace": "fast", "style": "logic"}

    Returns:
        更新后的完整偏好配置
    """
    _ensure_table()
    # 校验传入的 key 和 value
    validated = {}
    for k, v in updates.items():
        if k in PREFERENCE_DIMS and v in PREFERENCE_DIMS[k]["options"]:
            validated[k] = v

    current = get_preferences(student_id)
    merged = {**current, **validated}

    with get_connection() as conn:
        conn.execute(
            text("""
                INSERT INTO learning_preferences (student_id, preferences_json, updated_at)
                VALUES (:sid, :pref, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id) DO UPDATE SET
                    preferences_json = excluded.preferences_json,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {"sid": student_id, "pref": json.dumps(merged, ensure_ascii=False)},
        )
        conn.commit()

    return merged


def build_preference_prompt(student_id: str) -> str:
    """
    根据学生偏好生成注入到 AutoTutor 的 prompt 片段

    Returns:
        可直接插入 system prompt 的字符串，若全部为默认值则返回空字符串
    """
    prefs = get_preferences(student_id)
    parts = []

    pace_prompt = PACE_PROMPTS.get(prefs["pace"], "")
    if pace_prompt and prefs["pace"] != "normal":
        parts.append(pace_prompt)

    style_prompt = STYLE_PROMPTS.get(prefs["style"], "")
    if style_prompt and prefs["style"] != "example":
        parts.append(style_prompt)

    interaction_prompt = INTERACTION_PROMPTS.get(prefs["interaction"], "")
    if interaction_prompt and prefs["interaction"] != "medium":
        parts.append(interaction_prompt)

    difficulty_prompt = DIFFICULTY_PROMPTS.get(prefs["difficulty"], "")
    if difficulty_prompt and prefs["difficulty"] != "match":
        parts.append(difficulty_prompt)

    if not parts:
        return ""
    return "\n\n【学生偏好设置】\n" + "\n".join(f"- {p}" for p in parts)


def get_preference_schema() -> dict:
    """返回偏好维度定义，供前端渲染表单使用"""
    return PREFERENCE_DIMS
