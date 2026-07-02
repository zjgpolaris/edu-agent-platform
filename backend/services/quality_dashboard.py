"""命题质量看板：跨作业聚合教师的 AI 出题质检画像（只读、确定性）。

在单份作业洞察（compute_assignment_insights）之上再升一层，把一位教师所有作业
的质检结论、有效性（漏检/误报）、复核结论、高频问题类型与最难题汇总成一个视图，
让教师看清"我出的题整体质量如何、AI 质检准不准"。

数据来源全部已持久化：assignments.questions_json 里每题的 quality 字段、
学生真实作答（assignment_submissions）、教师复核（question_review_flags）。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from services.assignment_service import (
    BLIND_SPOT_MIN_ATTEMPTS,
    OBJECTIVE_TYPES,
    _ensure_tables,
    _row_to_assignment,
    _submission_from_row,
    compute_assignment_insights,
    get_bad_question_examples,
)

# AI 预警(error/warn)但真实正确率仍≥此值 → 疑似误报（AI 过度标注）
FALSE_ALARM_ACCURACY = 80


def get_teacher_quality_dashboard(teacher_id: str) -> dict[str, Any]:
    """聚合一位教师全部作业的命题质量画像。

    返回：
      - totals：作业/题目/客观题/已质检/含语义质检 计数
      - quality_distribution：error/warn/ok/unchecked 分布
      - effectiveness：主动预警、疑似误报、盲区(待复核/确认漏检/其实没掌握)
      - review_verdicts：教师复核结论分布
      - top_issue_types：高频问题类型（来自 quality.issues）
      - hardest_questions：跨作业真实正确率最低的题（含所属作业）
      - recent_bad_examples：近期回流的 few-shot 反例
    """
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM assignments WHERE teacher_id = :tid ORDER BY created_at DESC"),
            {"tid": teacher_id},
        ).mappings().fetchall()
        bundles: list[tuple[dict[str, Any], list[dict[str, Any]], dict[int, str]]] = []
        for row in rows:
            full = _row_to_assignment(row, include_questions=True)
            subs = conn.execute(
                text("SELECT * FROM assignment_submissions WHERE assignment_id = :aid"),
                {"aid": full["id"]},
            ).mappings().fetchall()
            submissions = [_submission_from_row(s) for s in subs]
            flag_rows = conn.execute(
                text("SELECT question_index, verdict FROM question_review_flags WHERE assignment_id = :aid"),
                {"aid": full["id"]},
            ).mappings().fetchall()
            flags = {int(r["question_index"]): str(r["verdict"]) for r in flag_rows}
            bundles.append((full, submissions, flags))

    dist = {"error": 0, "warn": 0, "ok": 0, "unchecked": 0}
    question_count = objective_count = quality_checked = semantic_checked = 0
    proactive_flagged = suspected_false_alarm = 0
    blind_total = blind_open = blind_confirmed_bad = blind_not_mastered = 0
    verdicts = {"bad_question": 0, "not_mastered": 0}
    issue_counter: Counter[str] = Counter()
    hardest: list[dict[str, Any]] = []

    for full, submissions, flags in bundles:
        questions = full.get("questions") or []
        question_count += len(questions)
        for q in questions:
            if q.get("type") in OBJECTIVE_TYPES:
                objective_count += 1
            quality = q.get("quality") if isinstance(q.get("quality"), dict) else None
            level = (quality or {}).get("level")
            if quality is None or level is None:
                dist["unchecked"] += 1
                continue
            quality_checked += 1
            dist[level] = dist.get(level, 0) + 1
            if level in ("error", "warn"):
                proactive_flagged += 1
            if quality.get("semantic_checked"):
                semantic_checked += 1
            for issue in quality.get("issues") or []:
                txt = str(issue).replace("语义：", "").strip()
                if txt:
                    issue_counter[txt] += 1

        insights = compute_assignment_insights(full, submissions)
        for q in insights.get("lowest_accuracy_questions") or []:
            if q["attempts"] < BLIND_SPOT_MIN_ATTEMPTS:
                continue
            hardest.append({
                "assignment_id": full["id"], "assignment_title": full["title"],
                "question_index": q["question_index"], "prompt": q["prompt"],
                "accuracy": q["accuracy"], "attempts": q["attempts"],
                "predicted_level": q["predicted_level"],
            })
            if q["predicted_level"] in ("error", "warn") and q["accuracy"] >= FALSE_ALARM_ACCURACY:
                suspected_false_alarm += 1

        for b in insights.get("quality_blind_spots") or []:
            blind_total += 1
            verdict = flags.get(b["question_index"])
            if verdict is None:
                blind_open += 1
            elif verdict == "bad_question":
                blind_confirmed_bad += 1
            elif verdict == "not_mastered":
                blind_not_mastered += 1

        for v in flags.values():
            if v in verdicts:
                verdicts[v] += 1

    hardest.sort(key=lambda x: (x["accuracy"], -x["attempts"]))

    return {
        "totals": {
            "assignment_count": len(bundles),
            "question_count": question_count,
            "objective_count": objective_count,
            "quality_checked_count": quality_checked,
            "semantic_checked_count": semantic_checked,
        },
        "quality_distribution": dist,
        "effectiveness": {
            "proactive_flagged": proactive_flagged,
            "suspected_false_alarm": suspected_false_alarm,
            "blind_spots_total": blind_total,
            "blind_spots_open": blind_open,
            "blind_spots_confirmed_bad": blind_confirmed_bad,
            "blind_spots_not_mastered": blind_not_mastered,
        },
        "review_verdicts": verdicts,
        "top_issue_types": [{"issue": k, "count": v} for k, v in issue_counter.most_common(6)],
        "hardest_questions": hardest[:8],
        "recent_bad_examples": get_bad_question_examples(teacher_id, limit=5),
    }
