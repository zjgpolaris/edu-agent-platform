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
    compute_assignment_insights,
    create_assignment,
    get_assignment_submissions,
    list_student_assignments,
    list_teacher_assignments,
    review_assignment_submission,
    submit_assignment,
)

TEACHER = "smoke-teacher"
STUDENT_A = "smoke-stu-a"
STUDENT_B = "smoke-stu-b"

QUESTIONS = [
    {"type": "single_choice", "prompt": "鸦片战争爆发于哪一年？",
     "options": ["1840", "1842", "1856", "1860"], "answer": "A", "knowledge_tag": "鸦片战争"},
    {"type": "true_false", "prompt": "《南京条约》割让了香港岛。", "answer": "正确", "knowledge_tag": "南京条约"},
    {"type": "subjective", "prompt": "简述鸦片战争的历史影响。", "answer": None, "knowledge_tag": "鸦片战争影响", "reference_answer": "中国开始沦为半殖民地半封建社会。"},
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
    assert "insights" in data
    # 完成率更新
    lst = list_teacher_assignments(TEACHER)
    assert lst[0]["completion_rate"] == 100
    assert lst[0]["submitted_count"] == 2


def assignment_insights_detects_weak_tags() -> None:
    data = get_assignment_submissions(TEACHER, _state["aid"])
    tags = data["insights"]["top_weak_tags"]
    assert tags[0]["knowledge_tag"] == "鸦片战争"
    assert tags[0]["student_count"] == 1


def assignment_insights_detects_low_accuracy_questions() -> None:
    data = get_assignment_submissions(TEACHER, _state["aid"])
    q = data["insights"]["lowest_accuracy_questions"][0]
    assert q["question_index"] == 0
    assert q["accuracy"] == 50


def assignment_insights_tracks_pending_review_count() -> None:
    data = get_assignment_submissions(TEACHER, _state["aid"])
    assert data["insights"]["pending_review_count"] == 2
    review = review_assignment_submission(TEACHER, _state["aid"], STUDENT_A, 88, "回答较完整")
    assert review["status"] == "graded"
    data = get_assignment_submissions(TEACHER, _state["aid"])
    assert data["insights"]["pending_review_count"] == 1
    sub_a = next(s for s in data["submissions"] if s["student_id"] == STUDENT_A)
    assert sub_a["teacher_feedback"] == "回答较完整"
    assert sub_a["reviewed_at"]


def assignment_insights_detects_below_threshold_students() -> None:
    review_assignment_submission(TEACHER, _state["aid"], STUDENT_B, 45, "需补充影响分析")
    data = get_assignment_submissions(TEACHER, _state["aid"])
    low = data["insights"]["below_threshold_students"]
    assert low[0]["student_id"] == STUDENT_B
    assert "鸦片战争" in low[0]["missed_tags"]
    assert "鸦片战争影响" in low[0]["missed_tags"]
    lst = list_teacher_assignments(TEACHER)
    assert lst[0]["pending_review_count"] == 0
    assert lst[0]["below_threshold_count"] == 1


def permission_guard() -> None:
    try:
        get_assignment_submissions("other-teacher", _state["aid"])
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


def _blind_spot_fixture(predicted_level):
    """构造一份 1 题客观题作业 + 5 份多数答错的提交，用于纯函数测 insights。"""
    q = {"type": "single_choice", "prompt": "测试题", "options": ["A", "B", "C", "D"],
         "answer": "A", "knowledge_tag": "测试点"}
    if predicted_level is not None:
        q["quality"] = {"level": predicted_level, "issues": []}
    assignment = {"questions": [q], "assignee_ids": [f"s{i}" for i in range(5)]}
    # 5 人作答，仅 1 人答对 → accuracy 20%，attempts 5
    submissions = []
    for i in range(5):
        correct = (i == 0)
        submissions.append({
            "student_id": f"s{i}", "score": 100 if correct else 0, "status": "graded",
            "answers": [{"question_index": 0, "is_correct": correct, "student_answer": "A" if correct else "C"}],
        })
    return assignment, submissions


def insights_flags_quality_blind_spot() -> None:
    # AI 判为 ok，但真实正确率 20%（<40）且 5 人作答（≥3）→ 命中盲区
    assignment, submissions = _blind_spot_fixture("ok")
    ins = compute_assignment_insights(assignment, submissions)
    spots = ins["quality_blind_spots"]
    assert len(spots) == 1, spots
    assert spots[0]["question_index"] == 0
    assert spots[0]["accuracy"] == 20
    assert spots[0]["predicted_level"] == "ok"


def insights_excludes_prewarned_and_underanswered() -> None:
    # 已被质检预警（error）→ 不算盲区（并非质检没查出来）
    a_err, subs_err = _blind_spot_fixture("error")
    assert compute_assignment_insights(a_err, subs_err)["quality_blind_spots"] == []
    # 样本不足（仅 2 人作答）→ 不算盲区（统计不可信）
    a_ok, subs_ok = _blind_spot_fixture("ok")
    ins = compute_assignment_insights(a_ok, subs_ok[:2])
    assert ins["quality_blind_spots"] == [], ins["quality_blind_spots"]


if __name__ == "__main__":
    cases = [
        ("create_and_list", create_and_list),
        ("validation_guards", validation_guards),
        ("student_sees_assignment", student_sees_assignment),
        ("submit_autogrades_objective", submit_autogrades_objective),
        ("submit_partial_wrong", submit_partial_wrong),
        ("duplicate_submit_blocked", duplicate_submit_blocked),
        ("teacher_sees_submissions", teacher_sees_submissions),
        ("assignment_insights_detects_weak_tags", assignment_insights_detects_weak_tags),
        ("assignment_insights_detects_low_accuracy_questions", assignment_insights_detects_low_accuracy_questions),
        ("assignment_insights_tracks_pending_review_count", assignment_insights_tracks_pending_review_count),
        ("assignment_insights_detects_below_threshold_students", assignment_insights_detects_below_threshold_students),
        ("insights_flags_quality_blind_spot", insights_flags_quality_blind_spot),
        ("insights_excludes_prewarned_and_underanswered", insights_excludes_prewarned_and_underanswered),
        ("permission_guard", permission_guard),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"assignment_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
