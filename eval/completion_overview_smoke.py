"""Smoke test: 教师班级作业完成情况聚合（纯函数 + 真实 DB 集成，离线）"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-completion-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.completion_overview import compute_class_completion, get_class_completion_overview

TODAY = "2026-07-02"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def empty_class() -> None:
    out = compute_class_completion([], TODAY)
    assert out["students"] == [], out
    assert out["summary"]["student_count"] == 0
    assert out["summary"]["overall_submission_rate"] == 0


def per_student_counts() -> None:
    records = [
        {"id": "a1", "title": "卷一", "due_date": "2026-06-01", "assignee_ids": ["s1", "s2"], "submitted_ids": ["s1"]},
        {"id": "a2", "title": "卷二", "due_date": "2026-12-01", "assignee_ids": ["s1", "s2"], "submitted_ids": []},
    ]
    out = compute_class_completion(records, TODAY)
    by = {s["student_id"]: s for s in out["students"]}
    # s1：a1 已交、a2 未交且未逾期 → assigned2 submitted1 pending1 overdue0
    assert by["s1"]["assigned"] == 2 and by["s1"]["submitted"] == 1 and by["s1"]["pending"] == 1 and by["s1"]["overdue"] == 0, by["s1"]
    # s2：a1 未交且逾期(2026-06-01<today)、a2 未交未逾期 → pending2 overdue1
    assert by["s2"]["pending"] == 2 and by["s2"]["overdue"] == 1, by["s2"]
    assert by["s2"]["overdue_titles"] == ["卷一"], by["s2"]


def overdue_needs_due_in_past() -> None:
    # due 为今天 → 未逾期
    records = [{"id": "a", "title": "t", "due_date": TODAY, "assignee_ids": ["s1"], "submitted_ids": []}]
    out = compute_class_completion(records, TODAY)
    assert out["students"][0]["overdue"] == 0, out
    assert out["students"][0]["pending"] == 1
    # 无 due → 不算逾期
    records2 = [{"id": "a", "title": "t", "due_date": None, "assignee_ids": ["s1"], "submitted_ids": []}]
    assert compute_class_completion(records2, TODAY)["students"][0]["overdue"] == 0


def sorted_behind_first() -> None:
    records = [
        {"id": "a1", "title": "卷一", "due_date": "2026-06-01", "assignee_ids": ["good", "bad", "mid"], "submitted_ids": ["good", "mid"]},
        {"id": "a2", "title": "卷二", "due_date": "2026-06-01", "assignee_ids": ["good", "bad", "mid"], "submitted_ids": ["good"]},
    ]
    out = compute_class_completion(records, TODAY)
    order = [s["student_id"] for s in out["students"]]
    # bad 逾期2 > mid 逾期1 > good 逾期0
    assert order == ["bad", "mid", "good"], order


def summary_metrics() -> None:
    records = [
        {"id": "a1", "title": "t", "due_date": "2026-06-01", "assignee_ids": ["s1", "s2"], "submitted_ids": ["s1"]},
    ]
    out = compute_class_completion(records, TODAY)
    s = out["summary"]
    assert s["student_count"] == 2 and s["assignment_count"] == 1
    assert s["students_with_overdue"] == 1  # s2 逾期
    assert s["students_all_done"] == 1      # s1 全交
    assert s["overall_submission_rate"] == 50  # 1/2


def integration_real_db() -> None:
    from services.assignment_service import create_assignment, submit_assignment
    q = [{"type": "single_choice", "prompt": "唐都在哪？", "options": ["长安", "洛阳", "开封", "北京"], "answer": "A", "knowledge_tag": "唐"}]
    a = create_assignment("co-teacher", "唐卷", q, ["co-s1", "co-s2"], due_date="2026-06-01")
    submit_assignment("co-s1", a["id"], ["A"])
    out = get_class_completion_overview("co-teacher", TODAY)
    by = {s["student_id"]: s for s in out["students"]}
    assert by["co-s1"]["submitted"] == 1 and by["co-s1"]["overdue"] == 0, by
    assert by["co-s2"]["overdue"] == 1, by
    # teacher 隔离
    assert get_class_completion_overview("co-teacher-other", TODAY)["summary"]["student_count"] == 0


if __name__ == "__main__":
    cases = [
        ("empty_class", empty_class),
        ("per_student_counts", per_student_counts),
        ("overdue_needs_due_in_past", overdue_needs_due_in_past),
        ("sorted_behind_first", sorted_behind_first),
        ("summary_metrics", summary_metrics),
        ("integration_real_db", integration_real_db),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"completion_overview_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
