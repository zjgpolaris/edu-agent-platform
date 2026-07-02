"""Smoke test: 通知徽标聚合（教师待评阅 / 学生未提交与到期）"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-badges-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.assignment_service import (
    create_assignment,
    get_student_badges,
    get_teacher_badges,
    review_assignment_submission,
    submit_assignment,
)

TEACHER = "badge-teacher"
STU_A = "badge-stu-a"
STU_B = "badge-stu-b"

SUBJECTIVE_Q = [
    {"type": "single_choice", "prompt": "鸦片战争爆发于哪一年？",
     "options": ["1840", "1842", "1856", "1860"], "answer": "A", "knowledge_tag": "鸦片战争"},
    {"type": "subjective", "prompt": "简述鸦片战争影响。", "answer": None, "knowledge_tag": "鸦片战争影响"},
]

_state: dict = {}


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def teacher_badges_zero_initially() -> None:
    b = get_teacher_badges(TEACHER)
    assert b == {"pending_review": 0, "below_threshold": 0}, b


def pending_review_counts_partial_submissions() -> None:
    a1 = create_assignment(TEACHER, "卷一", SUBJECTIVE_Q, [STU_A, STU_B])
    a2 = create_assignment(TEACHER, "卷二", SUBJECTIVE_Q, [STU_A])
    _state["a1"] = a1["id"]
    _state["a2"] = a2["id"]
    # 三次含主观题的提交 → 三个 partial 待评阅
    submit_assignment(STU_A, a1["id"], ["A", "影响"])
    submit_assignment(STU_B, a1["id"], ["B", "影响"])
    submit_assignment(STU_A, a2["id"], ["A", "影响"])
    b = get_teacher_badges(TEACHER)
    assert b["pending_review"] == 3, b


def review_reduces_pending_and_tracks_below_threshold() -> None:
    # 评阅一份并给低分 → pending_review -1，below_threshold +1
    review_assignment_submission(TEACHER, _state["a1"], STU_B, 40, "需补充")
    b = get_teacher_badges(TEACHER)
    assert b["pending_review"] == 2, b
    assert b["below_threshold"] == 1, b


def teacher_isolation() -> None:
    assert get_teacher_badges("other-teacher") == {"pending_review": 0, "below_threshold": 0}


def student_badges_pending_and_due_soon() -> None:
    # 未来到期一份、已过期一份、都未提交
    create_assignment(TEACHER, "未来卷", SUBJECTIVE_Q, [STU_C := "badge-stu-c"], due_date="2099-12-31")
    create_assignment(TEACHER, "逾期卷", SUBJECTIVE_Q, [STU_C], due_date="2000-01-01")
    b = get_student_badges(STU_C, today="2026-07-02")
    assert b["pending_assignments"] == 2, b
    assert b["due_soon"] == 1, b  # 仅逾期那份 due_date<=today


def student_badges_exclude_submitted() -> None:
    stu_d = "badge-stu-d"
    a = create_assignment(TEACHER, "D卷", SUBJECTIVE_Q, [stu_d], due_date="2000-01-01")
    b0 = get_student_badges(stu_d, today="2026-07-02")
    assert b0["pending_assignments"] == 1 and b0["due_soon"] == 1, b0
    submit_assignment(stu_d, a["id"], ["A", "影响"])
    b1 = get_student_badges(stu_d, today="2026-07-02")
    assert b1["pending_assignments"] == 0 and b1["due_soon"] == 0, b1


if __name__ == "__main__":
    cases = [
        ("teacher_badges_zero_initially", teacher_badges_zero_initially),
        ("pending_review_counts_partial_submissions", pending_review_counts_partial_submissions),
        ("review_reduces_pending_and_tracks_below_threshold", review_reduces_pending_and_tracks_below_threshold),
        ("teacher_isolation", teacher_isolation),
        ("student_badges_pending_and_due_soon", student_badges_pending_and_due_soon),
        ("student_badges_exclude_submitted", student_badges_exclude_submitted),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"notification_badges_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
