"""Smoke test: 学生今日计划聚合（纯函数为主，离线）

覆盖 build_today_plan 的优先级排序与摘要，并做一次真实 DB 集成校验。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-today-plan-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.today_plan import build_today_plan, get_student_today_plan

TODAY = "2026-07-02"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def _asg(aid, due=None, submitted=False, title=None):
    return {
        "id": aid, "title": title or aid, "due_date": due,
        "submission": {"score": 100, "status": "graded"} if submitted else None,
    }


def empty_plan_is_all_clear() -> None:
    plan = build_today_plan([], 0, [], TODAY)
    assert plan["tasks"] == [], plan
    assert plan["summary"]["all_clear"] is True, plan
    assert plan["date"] == TODAY


def submitted_assignments_excluded() -> None:
    plan = build_today_plan([_asg("a1", due="2026-06-01", submitted=True)], 0, [], TODAY)
    assert plan["summary"]["pending_assignments"] == 0, plan
    assert plan["tasks"] == [], plan


def overdue_assignment_is_urgent_and_first() -> None:
    plan = build_today_plan([_asg("a1", due="2026-06-30", title="鸦片战争测")], 0, [], TODAY)
    t = plan["tasks"][0]
    assert t["kind"] == "assignment" and t["priority"] == "urgent", t
    assert "逾期" in t["detail"] and "2026-06-30" in t["detail"], t
    assert plan["summary"]["overdue_assignments"] == 1, plan


def priority_ordering_across_kinds() -> None:
    # 逾期作业 > 今天截止 > 今日复习 > 未来作业 > 薄弱点
    assignments = [
        _asg("future", due="2026-12-01", title="期末"),
        _asg("today", due=TODAY, title="今日卷"),
        _asg("late", due="2026-06-01", title="补交卷"),
    ]
    weak = [{"knowledge_tag": "太平天国", "wrong_count": 3}]
    plan = build_today_plan(assignments, 5, weak, TODAY, review_total=8)
    kinds = [(t["kind"], t.get("ref_id"), t["priority"]) for t in plan["tasks"]]
    assert kinds == [
        ("assignment", "late", "urgent"),
        ("assignment", "today", "high"),
        ("review", None, "high"),
        ("assignment", "future", "normal"),
        ("weakpoint", "太平天国", "normal"),
    ], kinds


def review_task_only_when_remaining() -> None:
    assert build_today_plan([], 0, [], TODAY)["tasks"] == []
    plan = build_today_plan([], 3, [], TODAY, review_total=3)
    assert len(plan["tasks"]) == 1 and plan["tasks"][0]["kind"] == "review", plan
    assert plan["tasks"][0]["count"] == 3, plan
    assert plan["summary"]["review_remaining"] == 3


def weakpoint_task_encodes_focus() -> None:
    plan = build_today_plan([], 0, [{"knowledge_tag": "戊戌变法", "wrong_count": 2}], TODAY)
    t = plan["tasks"][0]
    assert t["kind"] == "weakpoint", t
    # 单 tag 透传到 AutoTutor（URL 编码）
    assert t["href"].startswith("/student/auto-tutor?focus="), t
    assert "%" in t["href"], t  # 中文被编码


def no_due_date_is_upcoming_not_overdue() -> None:
    plan = build_today_plan([_asg("nodue", due=None)], 0, [], TODAY)
    t = plan["tasks"][0]
    assert t["priority"] == "normal", t
    assert plan["summary"]["overdue_assignments"] == 0, plan


def integration_reads_real_assignment() -> None:
    from services.assignment_service import create_assignment
    q = [{"type": "single_choice", "prompt": "唐朝建立于？", "options": ["618", "626", "907", "960"],
          "answer": "A", "knowledge_tag": "唐朝"}]
    create_assignment("tp-teacher", "唐朝测", q, ["tp-stu"], due_date="2026-06-01")
    plan = get_student_today_plan("tp-stu", TODAY)
    # 未提交 + 已逾期 → urgent 作业任务
    assert plan["summary"]["pending_assignments"] == 1, plan
    assert plan["tasks"][0]["kind"] == "assignment", plan
    assert plan["tasks"][0]["priority"] == "urgent", plan
    # 别的学生看不到
    other = get_student_today_plan("tp-stu-other", TODAY)
    assert other["summary"]["pending_assignments"] == 0, other


if __name__ == "__main__":
    cases = [
        ("empty_plan_is_all_clear", empty_plan_is_all_clear),
        ("submitted_assignments_excluded", submitted_assignments_excluded),
        ("overdue_assignment_is_urgent_and_first", overdue_assignment_is_urgent_and_first),
        ("priority_ordering_across_kinds", priority_ordering_across_kinds),
        ("review_task_only_when_remaining", review_task_only_when_remaining),
        ("weakpoint_task_encodes_focus", weakpoint_task_encodes_focus),
        ("no_due_date_is_upcoming_not_overdue", no_due_date_is_upcoming_not_overdue),
        ("integration_reads_real_assignment", integration_reads_real_assignment),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"today_plan_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
