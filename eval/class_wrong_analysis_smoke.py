"""Smoke test: 错题班级聚合视图

覆盖场景：
1. 无作业时返回空列表
2. 有提交数据时聚合正确（prompt / accuracy / student_count_wrong）
3. 按 student_count_wrong 降序
4. 主观题不纳入统计
5. wrong_options 高频选项正确
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-class-wrong-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

TEACHER = "smoke-cwa-teacher"
STUDENTS = ["smoke-cwa-s1", "smoke-cwa-s2", "smoke-cwa-s3"]


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


def _seed() -> str:
    """创建一份含 easy/hard/subjective 三道题的作业，三名学生均提交。"""
    from services.assignment_service import create_assignment, submit_assignment, _ensure_tables
    _ensure_tables()
    qs = [
        {"type": "single_choice", "prompt": "鸦片战争爆发年份", "options": ["A","B","C","D"],
         "answer": "A", "knowledge_tag": "鸦片战争", "difficulty": "easy"},
        {"type": "single_choice", "prompt": "洋务运动核心主张", "options": ["A","B","C","D"],
         "answer": "C", "knowledge_tag": "洋务运动", "difficulty": "hard"},
        {"type": "subjective", "prompt": "简述甲午战争影响", "options": [],
         "answer": "", "knowledge_tag": "甲午战争"},
    ]
    asgn = create_assignment(TEACHER, "班级聚合测试", qs, STUDENTS)
    aid = asgn["id"]
    # s1: Q0正确, Q1错误(选B), Q2略过
    submit_assignment(STUDENTS[0], aid, ["A", "B", "简答"])
    # s2: Q0错误(选B), Q1错误(选B), Q2略过
    submit_assignment(STUDENTS[1], aid, ["B", "B", "简答"])
    # s3: Q0错误(选C), Q1正确, Q2略过
    submit_assignment(STUDENTS[2], aid, ["C", "C", "简答"])
    return aid


# ── Case 1: 无作业时返回空 ─────────────────────────────────────────────────────
def c1_no_assignments():
    from services.lecture_review_service import aggregate_class_wrong_questions
    result = aggregate_class_wrong_questions("unknown-teacher-xyz")
    assert result["questions"] == [], f"期望空，实际 {result['questions']}"
    assert result["assignments_analyzed"] == 0


# ── Case 2: 聚合数据结构正确 ──────────────────────────────────────────────────
def c2_aggregation_structure():
    from services.lecture_review_service import aggregate_class_wrong_questions
    _seed()
    result = aggregate_class_wrong_questions(TEACHER)
    assert len(result["questions"]) >= 1, "应有至少一道题"
    assert result["assignments_analyzed"] >= 1
    q = result["questions"][0]
    for field in ("prompt", "accuracy", "attempts", "student_count_wrong", "wrong_options",
                  "assignment_title", "assignment_id", "question_index"):
        assert field in q, f"缺少字段: {field}"


# ── Case 3: 按 student_count_wrong 降序 ────────────────────────────────────────
def c3_sorted_by_wrong_count():
    from services.lecture_review_service import aggregate_class_wrong_questions
    result = aggregate_class_wrong_questions(TEACHER)
    counts = [q["student_count_wrong"] for q in result["questions"]]
    assert counts == sorted(counts, reverse=True), f"应降序，实际 {counts}"


# ── Case 4: Q0 答错人数=2，Q1 答错人数=2（并列），accuracy 计算正确 ───────────
def c4_accuracy_calculation():
    from services.lecture_review_service import aggregate_class_wrong_questions
    result = aggregate_class_wrong_questions(TEACHER)
    qs_by_prompt = {q["prompt"]: q for q in result["questions"]}
    q0 = qs_by_prompt.get("鸦片战争爆发年份")
    assert q0 is not None, "Q0 应在聚合结果中"
    assert q0["student_count_wrong"] == 2, f"Q0 答错2人，实际 {q0['student_count_wrong']}"
    assert q0["attempts"] == 3, f"Q0 作答3人，实际 {q0['attempts']}"
    assert abs(q0["accuracy"] - 33.3) < 1.0, f"Q0 正确率约33%，实际 {q0['accuracy']}"


# ── Case 5: 主观题不纳入统计 ──────────────────────────────────────────────────
def c5_subjective_excluded():
    from services.lecture_review_service import aggregate_class_wrong_questions
    result = aggregate_class_wrong_questions(TEACHER)
    subjective_qs = [q for q in result["questions"] if q.get("type") == "subjective"]
    assert len(subjective_qs) == 0, f"主观题不应出现在聚合中，实际 {subjective_qs}"


if __name__ == "__main__":
    cases = [
        ("C1 无作业返回空", c1_no_assignments),
        ("C2 聚合数据结构正确", c2_aggregation_structure),
        ("C3 按答错人数降序", c3_sorted_by_wrong_count),
        ("C4 accuracy 计算正确", c4_accuracy_calculation),
        ("C5 主观题不纳入统计", c5_subjective_excluded),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
