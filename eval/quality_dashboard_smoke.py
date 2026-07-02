"""Smoke test: 命题质量看板跨作业聚合（真实 DB，离线）

覆盖 get_teacher_quality_dashboard：质检分布、有效性(漏检/误报)、复核结论、
高频问题类型、最难题排行、few-shot 反例、teacher 隔离与新教师冷启动。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-quality-dashboard-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.assignment_service import (
    create_assignment,
    record_question_review_flag,
    submit_assignment,
)
from services.quality_dashboard import get_teacher_quality_dashboard

TEACHER = "qd-teacher"
STUDENTS = [f"qd-stu-{i}" for i in range(5)]

# 三道单选题，携带 AI 质检结论：
#   Q0 判 ok，但真实正确率 20% → 质检盲区（会被标 bad_question）
#   Q1 判 warn（含语义质检），真实正确率 100% → 疑似误报
#   Q2 判 error，真实正确率 40% → 仅计入分布/主动预警
QUESTIONS = [
    {"type": "single_choice", "prompt": "秦朝统一六国是在公元前哪一年？",
     "options": ["前221", "前202", "前207", "前209"], "answer": "A", "knowledge_tag": "秦朝",
     "quality": {"level": "ok", "issues": []}},
    {"type": "single_choice", "prompt": "西汉的建立者是谁？",
     "options": ["刘邦", "项羽", "刘秀", "刘彻"], "answer": "A", "knowledge_tag": "西汉",
     "quality": {"level": "warn", "issues": ["存在重复选项"], "semantic_checked": True}},
    {"type": "single_choice", "prompt": "东汉都城在哪里？",
     "options": ["洛阳", "长安", "咸阳", "开封"], "answer": "A", "knowledge_tag": "东汉",
     "quality": {"level": "error", "issues": ["正确答案字母无效"]}},
]

# 每名学生 [q0, q1, q2] 的作答，制造确定的正确率分布
ANSWERS = {
    STUDENTS[0]: ["A", "A", "A"],  # Q0✓ Q1✓ Q2✓
    STUDENTS[1]: ["B", "A", "A"],  # Q0✗ Q1✓ Q2✓
    STUDENTS[2]: ["B", "A", "B"],  # Q0✗ Q1✓ Q2✗
    STUDENTS[3]: ["B", "A", "B"],  # Q0✗ Q1✓ Q2✗
    STUDENTS[4]: ["B", "A", "B"],  # Q0✗ Q1✓ Q2✗
}
# → Q0 20% / Q1 100% / Q2 40%

_state: dict = {}


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def build_fixture() -> None:
    a = create_assignment(TEACHER, "秦汉随堂测", QUESTIONS, STUDENTS, subject="历史", grade="初一")
    _state["aid"] = a["id"]
    for sid, ans in ANSWERS.items():
        submit_assignment(sid, a["id"], ans)
    # Q0 是盲区 → 教师复核判定为 bad_question
    record_question_review_flag(TEACHER, a["id"], 0, "bad_question", note="正确答案存疑")


def dashboard_totals_and_distribution() -> None:
    d = get_teacher_quality_dashboard(TEACHER)
    t = d["totals"]
    assert t["assignment_count"] == 1, t
    assert t["question_count"] == 3, t
    assert t["objective_count"] == 3, t
    assert t["quality_checked_count"] == 3, t
    assert t["semantic_checked_count"] == 1, t   # 仅 Q1 带 semantic_checked
    dist = d["quality_distribution"]
    assert dist == {"error": 1, "warn": 1, "ok": 1, "unchecked": 0}, dist


def dashboard_effectiveness() -> None:
    eff = get_teacher_quality_dashboard(TEACHER)["effectiveness"]
    assert eff["proactive_flagged"] == 2, eff          # Q1 warn + Q2 error
    assert eff["suspected_false_alarm"] == 1, eff       # Q1 warn 但 100%
    assert eff["blind_spots_total"] == 1, eff           # 仅 Q0
    assert eff["blind_spots_open"] == 0, eff            # 已复核
    assert eff["blind_spots_confirmed_bad"] == 1, eff   # 复核为 bad_question
    assert eff["blind_spots_not_mastered"] == 0, eff


def dashboard_verdicts_and_issues() -> None:
    d = get_teacher_quality_dashboard(TEACHER)
    assert d["review_verdicts"] == {"bad_question": 1, "not_mastered": 0}, d["review_verdicts"]
    issues = {it["issue"] for it in d["top_issue_types"]}
    assert "存在重复选项" in issues, issues
    assert "正确答案字母无效" in issues, issues


def dashboard_hardest_questions_sorted() -> None:
    hardest = get_teacher_quality_dashboard(TEACHER)["hardest_questions"]
    assert len(hardest) == 3, hardest
    # 按真实正确率升序：Q0(20) → Q2(40) → Q1(100)
    assert [h["accuracy"] for h in hardest] == [20, 40, 100], hardest
    assert hardest[0]["question_index"] == 0
    assert hardest[0]["assignment_title"] == "秦汉随堂测"


def dashboard_recent_bad_examples() -> None:
    ex = get_teacher_quality_dashboard(TEACHER)["recent_bad_examples"]
    assert len(ex) == 1, ex
    assert ex[0]["prompt"] == "秦朝统一六国是在公元前哪一年？", ex


def dashboard_teacher_isolation() -> None:
    d = get_teacher_quality_dashboard("qd-teacher-other")
    assert d["totals"]["assignment_count"] == 0, d
    assert d["quality_distribution"] == {"error": 0, "warn": 0, "ok": 0, "unchecked": 0}, d
    assert d["hardest_questions"] == [], d
    assert d["recent_bad_examples"] == [], d
    assert d["effectiveness"]["blind_spots_total"] == 0, d


if __name__ == "__main__":
    cases = [
        ("build_fixture", build_fixture),
        ("dashboard_totals_and_distribution", dashboard_totals_and_distribution),
        ("dashboard_effectiveness", dashboard_effectiveness),
        ("dashboard_verdicts_and_issues", dashboard_verdicts_and_issues),
        ("dashboard_hardest_questions_sorted", dashboard_hardest_questions_sorted),
        ("dashboard_recent_bad_examples", dashboard_recent_bad_examples),
        ("dashboard_teacher_isolation", dashboard_teacher_isolation),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"quality_dashboard_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
