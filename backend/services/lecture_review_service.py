"""讲评课 AI 辅助服务

基于教师近期作业的实际答题数据（而非泛化学情画像），
跨作业聚合每个知识点的错误分布，再由 LLM 生成：
- lecture_tip：2 句针对该错误模式的讲解提示（教师可直接念）
- board_keywords：3-5 个板书关键词
- sample_exercise：1 句描述适合即时巩固的练习形式

对外接口
--------
aggregate_teacher_errors(teacher_id, limit_assignments=5) -> list[dict]
    读最近 N 份作业的答题记录，按知识点聚合错误数据，返回按错误人数降序的列表。

generate_lecture_review(teacher_id, *, limit_assignments=5) -> dict
    在 aggregate 基础上，批量调 LLM 生成每个高频错误知识点的讲评材料。
    返回 {"topics": [...], "generated_at": "..."}
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso

_log = logging.getLogger(__name__)

# 每次最多处理的知识点数量（太多会超 LLM token）
_MAX_TOPICS = 6
# 纳入聚合的最近作业数
_DEFAULT_LIMIT_ASSIGNMENTS = 5


# ── 数据聚合层 ─────────────────────────────────────────────────────────────────

def aggregate_teacher_errors(
    teacher_id: str,
    limit_assignments: int = _DEFAULT_LIMIT_ASSIGNMENTS,
) -> list[dict[str, Any]]:
    """读取教师最近 N 份作业的答题记录，按知识点聚合错误分布。

    Returns list of:
    {
        "tag": str,           # 知识点标签
        "error_count": int,   # 总答错次数（可重复同一学生）
        "student_count": int, # 答错该知识点的不同学生数
        "accuracy": float,    # 正确率 0-100
        "wrong_options": list[{"option": str, "count": int}],  # 高频错误选项
        "question_prompts": list[str],  # 该 tag 关联的题干（去重，最多3道）
    }
    按 student_count 降序，取前 _MAX_TOPICS 条。
    """
    limit_assignments = max(1, min(int(limit_assignments), 20))
    # 确保表存在（跨服务调用时表可能尚未创建）
    from services.assignment_service import _ensure_tables as _ensure_asgn_tables
    _ensure_asgn_tables()
    with get_connection() as conn:
        # 取最近 N 份已有提交的作业
        asgn_rows = conn.execute(
            text("""SELECT a.id, a.questions_json
                 FROM assignments a
                 WHERE a.teacher_id = :tid
                   AND EXISTS (SELECT 1 FROM assignment_submissions s WHERE s.assignment_id = a.id)
                 ORDER BY a.created_at DESC
                 LIMIT :lim"""),
            {"tid": teacher_id, "lim": limit_assignments},
        ).mappings().fetchall()
        if not asgn_rows:
            return []

        assignment_ids = [r["id"] for r in asgn_rows]
        questions_by_asgn: dict[str, list[dict]] = {
            r["id"]: json.loads(r["questions_json"] or "[]") for r in asgn_rows
        }

        # 取这些作业的所有提交记录
        placeholders = ", ".join(f":aid_{i}" for i in range(len(assignment_ids)))
        sub_rows = conn.execute(
            text(f"""SELECT assignment_id, student_id, answers_json
                 FROM assignment_submissions
                 WHERE assignment_id IN ({placeholders})"""),
            {f"aid_{i}": aid for i, aid in enumerate(assignment_ids)},
        ).mappings().fetchall()

    # 按 tag 聚合
    tag_stats: dict[str, dict[str, Any]] = {}

    for sub in sub_rows:
        answers: list[dict] = json.loads(sub["answers_json"] or "[]")
        questions = questions_by_asgn.get(sub["assignment_id"], [])
        for ans in answers:
            q_idx = int(ans.get("question_index", -1))
            if q_idx < 0 or q_idx >= len(questions):
                continue
            q = questions[q_idx]
            tag = str(q.get("knowledge_tag") or "").strip()
            if not tag:
                continue
            is_correct = ans.get("is_correct")
            if is_correct is None:
                continue  # 主观题跳过

            if tag not in tag_stats:
                tag_stats[tag] = {
                    "tag": tag,
                    "attempts": 0,
                    "errors": 0,
                    "wrong_students": set(),
                    "wrong_option_counter": {},
                    "prompts": set(),
                }
            stat = tag_stats[tag]
            stat["attempts"] += 1
            prompt = str(q.get("prompt") or "").strip()
            if prompt:
                stat["prompts"].add(prompt)
            if not is_correct:
                stat["errors"] += 1
                stat["wrong_students"].add(sub["student_id"])
                raw_answer = str(ans.get("student_answer") or "").strip()
                if raw_answer:
                    stat["wrong_option_counter"][raw_answer] = (
                        stat["wrong_option_counter"].get(raw_answer, 0) + 1
                    )

    # 整理输出
    result: list[dict[str, Any]] = []
    for stat in tag_stats.values():
        attempts = stat["attempts"]
        errors = stat["errors"]
        accuracy = round((attempts - errors) / attempts * 100, 1) if attempts else 100.0
        wrong_options = sorted(
            [{"option": k, "count": v} for k, v in stat["wrong_option_counter"].items()],
            key=lambda x: -x["count"],
        )[:3]
        result.append({
            "tag": stat["tag"],
            "error_count": errors,
            "student_count": len(stat["wrong_students"]),
            "attempts": attempts,
            "accuracy": accuracy,
            "wrong_options": wrong_options,
            "question_prompts": list(stat["prompts"])[:3],
        })

    result.sort(key=lambda x: (-x["student_count"], -x["error_count"]))
    return result[:_MAX_TOPICS]


# ── LLM 生成层 ─────────────────────────────────────────────────────────────────

def _build_topic_prompt(topic: dict[str, Any]) -> str:
    """为单个知识点构建 LLM 提示。"""
    tag = topic["tag"]
    acc = topic["accuracy"]
    student_count = topic["student_count"]
    wrong_opts = topic.get("wrong_options", [])
    prompts = topic.get("question_prompts", [])

    wrong_opt_text = ""
    if wrong_opts:
        top = wrong_opts[0]
        wrong_opt_text = f"最常见错误答案：{top['option']}（{top['count']} 人选）"

    prompt_text = ""
    if prompts:
        prompt_text = f"代表性题干：「{prompts[0][:60]}」"

    return (
        f"知识点：【{tag}】\n"
        f"有 {student_count} 名学生在此知识点答错，正确率 {acc}%。\n"
        f"{wrong_opt_text}\n{prompt_text}\n"
        "请生成：\n"
        "1. lecture_tip：2 句针对此错误模式的讲解提示，语气面向中学历史教师，可直接朗读。\n"
        "2. board_keywords：3-5 个板书关键词，逗号分隔。\n"
        "3. sample_exercise：1 句描述适合课堂即时巩固的练习形式（不要写具体题目，写形式即可）。\n"
        '只输出 JSON，不要其他内容：{"lecture_tip":"...","board_keywords":"...","sample_exercise":"..."}'
    )


def _parse_topic_llm(raw: str, tag: str) -> dict[str, str]:
    try:
        start, end = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        return {
            "lecture_tip": str(data.get("lecture_tip") or "").strip(),
            "board_keywords": str(data.get("board_keywords") or "").strip(),
            "sample_exercise": str(data.get("sample_exercise") or "").strip(),
        }
    except Exception:
        return {
            "lecture_tip": f"请重点讲解「{tag}」的核心考点，结合典型错误分析。",
            "board_keywords": tag,
            "sample_exercise": "即时选择题巩固练习",
        }


def generate_lecture_review(
    teacher_id: str,
    *,
    limit_assignments: int = _DEFAULT_LIMIT_ASSIGNMENTS,
) -> dict[str, Any]:
    """生成讲评课 AI 辅助材料。

    Returns:
    {
        "topics": [
            {
                "tag": str,
                "error_count": int,
                "student_count": int,
                "accuracy": float,
                "wrong_options": [...],
                "question_prompts": [...],
                "lecture_tip": str,
                "board_keywords": str,
                "sample_exercise": str,
            },
            ...
        ],
        "generated_at": str,
        "assignments_analyzed": int,
    }
    """
    from llm_config import llm_fast  # 延迟导入避免循环依赖

    topics = aggregate_teacher_errors(teacher_id, limit_assignments=limit_assignments)
    if not topics:
        return {"topics": [], "generated_at": now_iso(), "assignments_analyzed": 0}

    enriched: list[dict[str, Any]] = []
    for topic in topics:
        prompt = _build_topic_prompt(topic)
        try:
            raw = llm_fast.invoke([{"role": "user", "content": prompt}]).content
            llm_out = _parse_topic_llm(raw, topic["tag"])
        except Exception as exc:
            _log.warning("lecture_review: LLM 失败 tag=%s: %s", topic["tag"], exc)
            llm_out = _parse_topic_llm("", topic["tag"])

        enriched.append({**topic, **llm_out})

    return {
        "topics": enriched,
        "generated_at": now_iso(),
        "assignments_analyzed": min(limit_assignments, _DEFAULT_LIMIT_ASSIGNMENTS),
    }
