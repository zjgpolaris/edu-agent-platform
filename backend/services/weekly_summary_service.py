"""学生周报服务 — 聚合本周学习数据，生成自然语言小结与下周建议。

设计：数据聚合走确定性 SQL，自然语言小结优先调 LLM（失败或无凭证时降级为规则模板），
因此离线也能稳定产出，可被 smoke 覆盖。
"""
from __future__ import annotations

import json
from datetime import date as _date, timedelta

from sqlalchemy import text

from db.engine import get_connection
from services.weakpoint_service import get_weakpoints


def _collect_metrics(student_id: str, today: _date) -> dict:
    """聚合最近 7 天的学习数据（今天为第 7 天）。"""
    week_start = today - timedelta(days=6)
    since = week_start.isoformat()

    metrics: dict = {
        "active_days": 0,
        "streak_days": 0,
        "reviews_done": 0,
        "reviews_total": 0,
        "review_completion_rate": None,
        "homework_count": 0,
        "homework_avg_score": None,
        "autotutor_sessions": 0,
        "weakpoint_count": 0,
        "top_weakpoints": [],
    }

    with get_connection() as conn:
        # 活跃天数 + 连续打卡（learning_events）
        ev_rows = conn.execute(
            text(
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS cnt "
                "FROM learning_events WHERE student_id = :sid AND created_at >= :since "
                "GROUP BY day"
            ),
            {"sid": student_id, "since": since},
        ).mappings().fetchall()
        activity_days = {r["day"] for r in ev_rows}
        metrics["active_days"] = len(activity_days)

        # 连续打卡：从今天往回数（不限本周窗口，反映真实 streak）
        all_days_rows = conn.execute(
            text(
                "SELECT DISTINCT substr(created_at, 1, 10) AS day "
                "FROM learning_events WHERE student_id = :sid"
            ),
            {"sid": student_id},
        ).mappings().fetchall()
        all_days = {r["day"] for r in all_days_rows}
        streak, check = 0, today
        while check.isoformat() in all_days:
            streak += 1
            check -= timedelta(days=1)
        metrics["streak_days"] = streak

        # 本周复习完成情况（review_sessions）
        rv_rows = conn.execute(
            text(
                "SELECT completed, total FROM review_sessions "
                "WHERE student_id = :sid AND date >= :since"
            ),
            {"sid": student_id, "since": since},
        ).mappings().fetchall()
        done = sum(r["completed"] for r in rv_rows)
        total = sum(r["total"] for r in rv_rows)
        metrics["reviews_done"] = done
        metrics["reviews_total"] = total
        metrics["review_completion_rate"] = round(done / total * 100) if total else None

        # 本周作业均分（homework_reviews）
        hw_rows = conn.execute(
            text(
                "SELECT teacher_score, grade_result_json FROM homework_reviews "
                "WHERE student_id = :sid AND created_at >= :since"
            ),
            {"sid": student_id, "since": since},
        ).mappings().fetchall()
        scores: list[float] = []
        for r in hw_rows:
            score = r["teacher_score"]
            if score is None:
                try:
                    result = json.loads(r["grade_result_json"] or "{}")
                    score = result.get("total_score") or result.get("score")
                except Exception:
                    score = None
            if score is not None:
                try:
                    scores.append(float(score))
                except (TypeError, ValueError):
                    pass
        metrics["homework_count"] = len(hw_rows)
        metrics["homework_avg_score"] = round(sum(scores) / len(scores), 1) if scores else None

        # 本周 AutoTutor 完成会话
        t_row = conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM learning_events "
                "WHERE student_id = :sid AND feature = 'auto_tutor' "
                "AND event_type = 'session_complete' AND created_at >= :since"
            ),
            {"sid": student_id, "since": since},
        ).mappings().fetchone()
        metrics["autotutor_sessions"] = int(t_row["cnt"]) if t_row else 0

    # 错题本（在连接块外，避免嵌套连接）
    wps = get_weakpoints(student_id)
    metrics["weakpoint_count"] = len(wps)
    metrics["top_weakpoints"] = [
        {"tag": w["knowledge_tag"], "count": w["wrong_count"]} for w in wps[:3]
    ]
    return metrics


def _rule_based_narrative(metrics: dict) -> tuple[str, list[str]]:
    """无 LLM 时的规则降级：拼接鼓励性小结 + 下周建议。"""
    active = metrics["active_days"]
    streak = metrics["streak_days"]
    rate = metrics["review_completion_rate"]
    hw_avg = metrics["homework_avg_score"]
    tutor = metrics["autotutor_sessions"]
    weak = metrics["weakpoint_count"]
    tops = metrics["top_weakpoints"]

    # 小结
    if active == 0:
        summary = "本周还没有学习记录哦，新的一周从今天开始，先完成一次复习吧！"
    else:
        parts = [f"本周你学习了 {active} 天"]
        if streak >= 2:
            parts.append(f"已连续打卡 {streak} 天，坚持得很棒")
        if rate is not None:
            parts.append(f"复习完成率 {rate}%")
        if hw_avg is not None:
            parts.append(f"作业平均分 {hw_avg}")
        if tutor > 0:
            parts.append(f"完成了 {tutor} 次 AutoTutor 辅导")
        summary = "，".join(parts) + "。"

    # 下周建议
    suggestions: list[str] = []
    if rate is not None and rate < 60:
        suggestions.append("每天留 10 分钟完成当天的复习任务，把完成率提到 80% 以上。")
    if weak > 0 and tops:
        tag = tops[0]["tag"]
        suggestions.append(f"重点攻克错得最多的「{tag}」，可以用 AutoTutor 精讲一节。")
    if active < 5:
        suggestions.append("尽量保持每天都来学一会儿，连续打卡更容易形成习惯。")
    if not suggestions:
        suggestions.append("保持当前节奏，挑战一下更高难度的练习题吧！")
    return summary, suggestions[:3]


def _llm_narrative(metrics: dict) -> tuple[str, list[str]] | None:
    """调用 LLM 生成温暖、具体的周报小结与建议，失败返回 None。"""
    try:
        from pydantic import BaseModel

        from llm_config import llm_fast
        from structured_output import invoke_structured

        class _Narrative(BaseModel):
            summary: str
            suggestions: list[str]

        tops = "、".join(f"{t['tag']}(错{t['count']}次)" for t in metrics["top_weakpoints"]) or "无"
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是初中生的学习教练，根据本周学习数据写一份简短周报。\n"
                    "要求：summary 为 2-3 句温暖、具体、有鼓励性的小结（引用真实数字，避免空话）；"
                    "suggestions 为 2-3 条可执行的下周建议。\n"
                    "只输出 JSON：{\"summary\":\"\",\"suggestions\":[\"\",\"\"]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"活跃天数：{metrics['active_days']}/7\n"
                    f"连续打卡：{metrics['streak_days']} 天\n"
                    f"复习完成率：{metrics['review_completion_rate'] if metrics['review_completion_rate'] is not None else '无'}%\n"
                    f"作业平均分：{metrics['homework_avg_score'] if metrics['homework_avg_score'] is not None else '无'}\n"
                    f"AutoTutor 辅导次数：{metrics['autotutor_sessions']}\n"
                    f"当前错题数：{metrics['weakpoint_count']}\n"
                    f"高频错题：{tops}\n"
                    "请生成本周小结与下周建议。"
                ),
            },
        ]
        result = invoke_structured(llm_fast, prompt, model=_Narrative, fallback=None)
        if result and result.summary and result.suggestions:
            return result.summary.strip(), [s.strip() for s in result.suggestions if s.strip()][:3]
    except Exception:
        pass
    return None


def build_weekly_summary(student_id: str, today: _date | None = None) -> dict:
    """构建学生周报：本周指标 + 自然语言小结 + 下周建议。"""
    today = today or _date.today()
    week_start = today - timedelta(days=6)
    metrics = _collect_metrics(student_id, today)

    narrative = _llm_narrative(metrics)
    if narrative:
        summary, suggestions = narrative
        generated_by = "llm"
    else:
        summary, suggestions = _rule_based_narrative(metrics)
        generated_by = "rule"

    return {
        "student_id": student_id,
        "week_start": week_start.isoformat(),
        "week_end": today.isoformat(),
        "metrics": metrics,
        "summary": summary,
        "suggestions": suggestions,
        "generated_by": generated_by,
    }
