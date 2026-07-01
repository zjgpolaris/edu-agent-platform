"""Smoke test: 教师布置作业工作流"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-assignment-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.assignment_service import (
    create_assignment,
    get_assignment_submissions,
    list_student_assignments,
    list_teacher_assignments,
    submit_assignment,
)

TEACHER = "smoke-teacher"
STUDENT_A = "smoke-stu-a"
STUDENT_B = "smoke-stu-b"

QUESTIONS = [
    {"type": "single_choice", "prompt": "鸦片战争爆发于哪一年？",
     "options": ["1840", "1842", "1856", "1860"], "answer": "A", "knowledge_tag": "鸦片战争"},
    {"type": "true_false", "prompt": "《南京条约》割让了香港岛。", "answer": "正确"},
    {"type": "subjective", "prompt": "简述鸦片战争的历史影响。", "answer": None},
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


def create_and_list() -> None:
    a = create_assignment(TEACHER, "鸦片战争随堂测", QUESTIONS, [STUDENT_A, STUDENT_B], subject="历史", grade="初二")
    assert a["id"].startswith("asg_")
    _state["aid"] = a["id"]
    lst = list_teacher_assignments(TEACHER)
    assert len(lst) == 1
    assert lst[0]["assignee_count"] == 2
    assert lst[0]["completion_rate"] == 0
    assert lst[0]["submitted_count"] == 0


def validation_guards() -> None:
    for bad in [
        lambda: create_assignment(TEACHER, "", QUESTIONS, [STUDENT_A]),
        lambda: create_assignment(TEACHER, "t", [], [STUDENT_A]),
        lambda: create_assignment(TEACHER, "t", QUESTIONS, []),
    ]:
        try:
            bad()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def student_sees_assignment() -> None:
    lst = list_student_assignments(STUDENT_A)
    assert len(lst) == 1
    assert lst[0]["id"] == _state["aid"]
    assert lst[0]["submission"] is None
    # 未分配的学生看不到
    assert list_student_assignments("random-student") == []


def submit_autogrades_objective() -> None:
    # A 全对客观题（含 1 道主观题 → status=partial）
    result = submit_assignment(STUDENT_A, _state["aid"], ["A", "正确", "影响深远"])
    assert result["objective_total"] == 2
    assert result["objective_correct"] == 2
    assert result["score"] == 100.0
    assert result["status"] == "partial"  # 有主观题
    assert result["has_subjective"] is True


def submit_partial_wrong() -> None:
    # B 客观题错一半
    result = submit_assignment(STUDENT_B, _state["aid"], ["B", "正确", ""])
    assert result["objective_correct"] == 1
    assert result["score"] == 50.0


def duplicate_submit_blocked() -> None:
    try:
        submit_assignment(STUDENT_A, _state["aid"], ["A", "正确", "x"])
        raise AssertionError("expected ValueError on duplicate")
    except ValueError:
        pass


def teacher_sees_submissions() -> None:
    data = get_assignment_submissions(TEACHER, _state["aid"])
    assert len(data["submissions"]) == 2
    scores = sorted(s["score"] for s in data["submissions"])
    assert scores == [50.0, 100.0]
    # 完成率更新
    lst = list_teacher_assignments(TEACHER)
    assert lst[0]["completion_rate"] == 100
    assert lst[0]["submitted_count"] == 2


def permission_guard() -> None:
    try:
        get_assignment_submissions("other-teacher", _state["aid"])
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


if __name__ == "__main__":
    cases = [
        ("create_and_list", create_and_list),
        ("validation_guards", validation_guards),
        ("student_sees_assignment", student_sees_assignment),
        ("submit_autogrades_objective", submit_autogrades_objective),
        ("submit_partial_wrong", submit_partial_wrong),
        ("duplicate_submit_blocked", duplicate_submit_blocked),
        ("teacher_sees_submissions", teacher_sees_submissions),
        ("permission_guard", permission_guard),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"assignment_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
