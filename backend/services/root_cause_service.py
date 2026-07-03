"""
薄弱点根因诊断服务 — 分析答错原因并推荐补救题
"""
from __future__ import annotations

import json
from enum import Enum

from sqlalchemy import text

from db.engine import get_connection

# 错误根因分类
class RootCause(str, Enum):
    CONCEPT = "concept"        # 概念模糊：知识点理解不透彻
    MEMORY = "memory"          # 知识遗忘：背诵内容遗忘
    COMPREHENSION = "comprehension"  # 题目理解：审题/理解题意有误
    CARELESS = "careless"      # 粗心大意：知道但填/选错了

ROOT_CAUSE_LABELS = {
    RootCause.CONCEPT: ("概念模糊", "💡", "对这个知识点的理解还不到位，需要重新理解核心概念。"),
    RootCause.MEMORY: ("知识遗忘", "🧠", "这个知识点曾经学过，但记忆模糊了，需要加强复习。"),
    RootCause.COMPREHENSION: ("审题失误", "🔍", "知识掌握了，但读题时理解有偏差，注意仔细审题。"),
    RootCause.CARELESS: ("粗心大意", "✏️", "知道正确答案，但做题时选错了，注意检查。"),
}

# 每种根因的补救建议
REMEDIAL_TIPS = {
    RootCause.CONCEPT: "建议：重新阅读教材相关章节，理解核心概念，再做1-2道基础题巩固。",
    RootCause.MEMORY: "建议：用记忆卡片反复背诵，间隔复习强化记忆。",
    RootCause.COMPREHENSION: "建议：做题前先圈出题目中的关键词（时间/地点/事件），再作答。",
    RootCause.CARELESS: "建议：答完后检查一遍，特别注意否定词（「不是」「错误的」）。",
}


def _ensure_table():
    with get_connection() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS root_cause_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                knowledge_tag TEXT NOT NULL,
                question_text TEXT,
                student_answer TEXT,
                correct_answer TEXT,
                root_cause TEXT NOT NULL,
                confidence REAL DEFAULT 0.8,
                analyzed_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        conn.commit()


def analyze_root_cause(
    student_id: str,
    knowledge_tag: str,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    wrong_count: int = 1,
) -> dict:
    """
    分析答错原因，调用 LLM 分类，并存储结果

    Returns:
        {
            "root_cause": "concept",
            "label": "概念模糊",
            "icon": "💡",
            "description": "...",
            "tip": "...",
            "confidence": 0.85
        }
    """
    _ensure_table()

    # 先调用 LLM 分析
    root_cause, confidence = _classify_with_llm(
        knowledge_tag, question_text, student_answer, correct_answer, wrong_count
    )

    # 存储结果
    with get_connection() as conn:
        conn.execute(
            text("""
                INSERT INTO root_cause_records
                    (student_id, knowledge_tag, question_text, student_answer,
                     correct_answer, root_cause, confidence)
                VALUES (:sid, :tag, :q, :sa, :ca, :rc, :conf)
            """),
            {
                "sid": student_id, "tag": knowledge_tag,
                "q": question_text[:500] if question_text else "",
                "sa": student_answer, "ca": correct_answer,
                "rc": root_cause.value, "conf": confidence,
            },
        )
        conn.commit()

    label, icon, description = ROOT_CAUSE_LABELS[root_cause]
    return {
        "root_cause": root_cause.value,
        "label": label,
        "icon": icon,
        "description": description,
        "tip": REMEDIAL_TIPS[root_cause],
        "confidence": confidence,
    }


def _classify_with_llm(
    knowledge_tag: str,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    wrong_count: int,
) -> tuple[RootCause, float]:
    """调用 LLM 分类错误根因，失败时降级为规则推断"""
    try:
        from llm_config import llm_fast
        from structured_output import invoke_structured
        from pydantic import BaseModel

        class _Classification(BaseModel):
            root_cause: str
            reasoning: str
            confidence: float

        prompt = [
            {
                "role": "system",
                "content": (
                    "你是教学诊断专家，分析学生答错题的根本原因。\n"
                    "根因分类：\n"
                    "- concept: 对知识点理解有误（概念模糊）\n"
                    "- memory: 背诵内容遗忘（知识遗忘）\n"
                    "- comprehension: 审题不仔细，理解题意有偏差（审题失误）\n"
                    "- careless: 知道答案但填错了（粗心大意）\n"
                    "只输出 JSON：{\"root_cause\":\"concept\",\"reasoning\":\"一句话解释\",\"confidence\":0.85}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"知识点：{knowledge_tag}\n"
                    f"题目：{(question_text or '（题目未知）')[:200]}\n"
                    f"学生答案：{student_answer or '（未作答）'}\n"
                    f"正确答案：{correct_answer or '（未知）'}\n"
                    f"该知识点累计错{wrong_count}次\n"
                    "分析根本原因："
                ),
            },
        ]
        result = invoke_structured(llm_fast, prompt, model=_Classification, fallback=None)
        if result and result.root_cause in [e.value for e in RootCause]:
            return RootCause(result.root_cause), min(1.0, max(0.0, result.confidence))
    except Exception:
        pass

    # 降级规则推断
    return _rule_based_fallback(wrong_count, student_answer, correct_answer)


def _rule_based_fallback(wrong_count: int, student_answer: str, correct_answer: str) -> tuple[RootCause, float]:
    """无 LLM 时的规则降级推断"""
    # 答案很接近（只差一个字母/数字）→ 粗心
    if (student_answer and correct_answer
            and len(student_answer) == len(correct_answer)
            and sum(a != b for a, b in zip(student_answer, correct_answer)) == 1):
        return RootCause.CARELESS, 0.6

    # 错误超过3次 → 概念模糊
    if wrong_count >= 3:
        return RootCause.CONCEPT, 0.65

    # 错误1-2次 → 知识遗忘
    if wrong_count <= 2:
        return RootCause.MEMORY, 0.6

    return RootCause.CONCEPT, 0.5


def get_latest_root_cause(student_id: str, knowledge_tag: str) -> dict | None:
    """获取某知识点最新的根因诊断结果"""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("""
                SELECT root_cause, confidence, analyzed_at
                FROM root_cause_records
                WHERE student_id = :sid AND knowledge_tag = :tag
                ORDER BY analyzed_at DESC LIMIT 1
            """),
            {"sid": student_id, "tag": knowledge_tag},
        ).fetchone()

    if not row:
        return None

    root_cause = RootCause(row[0])
    label, icon, description = ROOT_CAUSE_LABELS[root_cause]
    return {
        "root_cause": root_cause.value,
        "label": label,
        "icon": icon,
        "description": description,
        "tip": REMEDIAL_TIPS[root_cause],
        "confidence": row[1],
        "analyzed_at": row[2],
    }


def get_root_cause_summary(student_id: str) -> dict:
    """
    获取学生所有知识点的根因分布（用于分析最常见的错误类型）

    Returns:
        {"concept": 5, "memory": 3, "comprehension": 2, "careless": 1}
    """
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            text("""
                SELECT root_cause, COUNT(*) AS cnt
                FROM root_cause_records
                WHERE student_id = :sid
                GROUP BY root_cause
            """),
            {"sid": student_id},
        ).fetchall()

    result = {e.value: 0 for e in RootCause}
    for rc, cnt in rows:
        if rc in result:
            result[rc] = cnt
    return result
