"""Smoke test: 学生分层作业

覆盖场景：
1. _parse_difficulty_groups 解析正常和异常输入
2. set_difficulty_groups 正常写入、权限校验、学生过滤
3. get_questions_for_student 无分组时返回全部题目
4. get_questions_for_student 有分组时只返回匹配难度题目
5. get_questions_for_student 分组学生无对应难度题时降级返回全部
6. list_student_assignments 包含 my_difficulty 字段
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-tiered-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

TEACHER = "smoke-tiered-teacher"
STUDENT_EASY = "smoke-tiered-easy"
STUDENT_HARD = "smoke-tiered-hard"
STUDENT_NONE = "smoke-tiered-none"  # 无分层


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


def _make_tiered_assignment() -> str:
    """创建含 easy+medium+hard+无标注 题目的作业，返回 assignment_id。"""
    from services.assignment_service import create_assignment, _ensure_tables
    _ensure_tables()
    questions = [
        {"type": "single_choice", "prompt": "基础题1", "options": ["A","B","C","D"], "answer": "A",
         "knowledge_tag": "鸦片战争", "difficulty": "easy"},
        {"type": "single_choice", "prompt": "中等题1", "options": ["A","B","C","D"], "answer": "B",
         "knowledge_tag": "洋务运动", "difficulty": "medium"},
        {"type": "single_choice", "prompt": "提高题1", "options": ["A","B","C","D"], "answer": "C",
         "knowledge_tag": "甲午战争", "difficulty": "hard"},
        {"type": "single_choice", "prompt": "无标注题", "options": ["A","B","C","D"], "answer": "A",
         "knowledge_tag": "变法运动"},
    ]
    return create_assignment(TEACHER, "分层测试作业",
                             questions, [STUDENT_EASY, STUDENT_HARD, STUDENT_NONE])["id"]


# ── Case 1: _parse_difficulty_groups 解析 ─────────────────────────────────────
def c1_parse_groups():
    from services.assignment_service import _parse_difficulty_groups
    # 正常解析
    g = _parse_difficulty_groups('{"s1":"easy","s2":"hard","s3":"medium"}')
    assert g == {"s1": "easy", "s2": "hard", "s3": "medium"}, f"解析结果不符: {g}"
    # 过滤非法难度
    g2 = _parse_difficulty_groups('{"s1":"veryhard","s2":"easy"}')
    assert "s1" not in g2, "非法难度应被过滤"
    assert g2["s2"] == "easy"
    # 空/None
    assert _parse_difficulty_groups(None) == {}
    assert _parse_difficulty_groups("") == {}
    assert _parse_difficulty_groups("not-json") == {}


# ── Case 2: set_difficulty_groups 写入 + 权限校验 ─────────────────────────────
def c2_set_groups():
    from services.assignment_service import set_difficulty_groups
    aid = _make_tiered_assignment()
    # 正常设置
    set_difficulty_groups(TEACHER, aid, {STUDENT_EASY: "easy", STUDENT_HARD: "hard"})
    # 非法教师 → PermissionError
    try:
        set_difficulty_groups("other-teacher", aid, {STUDENT_EASY: "easy"})
        assert False, "应抛 PermissionError"
    except PermissionError:
        pass
    # 不存在的作业 → LookupError
    try:
        set_difficulty_groups(TEACHER, "non-exist-id", {})
        assert False, "应抛 LookupError"
    except LookupError:
        pass


# ── Case 3: 无分组时返回全部题目 ──────────────────────────────────────────────
def c3_no_group_all_questions():
    from services.assignment_service import create_assignment, get_questions_for_student, _ensure_tables
    _ensure_tables()
    questions = [
        {"type": "single_choice", "prompt": "Q1", "options": ["A","B","C","D"], "answer": "A", "difficulty": "easy"},
        {"type": "single_choice", "prompt": "Q2", "options": ["A","B","C","D"], "answer": "B", "difficulty": "hard"},
    ]
    asgn = create_assignment(TEACHER, "无分层", questions, [STUDENT_NONE])
    aid = asgn["id"]
    qs = get_questions_for_student(STUDENT_NONE, aid)
    assert len(qs) == 2, f"无分层应返回全部2题，实际 {len(qs)}"


# ── Case 4: 有分组时只返回匹配难度题目 ────────────────────────────────────────
def c4_filter_by_difficulty():
    from services.assignment_service import create_assignment, set_difficulty_groups, get_questions_for_student, _ensure_tables
    _ensure_tables()
    questions = [
        {"type": "single_choice", "prompt": "Easy Q", "options": ["A","B","C","D"], "answer": "A", "difficulty": "easy"},
        {"type": "single_choice", "prompt": "Medium Q", "options": ["A","B","C","D"], "answer": "B", "difficulty": "medium"},
        {"type": "single_choice", "prompt": "Hard Q", "options": ["A","B","C","D"], "answer": "C", "difficulty": "hard"},
    ]
    asgn = create_assignment(TEACHER, "分层过滤", questions, [STUDENT_EASY, STUDENT_HARD])
    aid = asgn["id"]
    set_difficulty_groups(TEACHER, aid, {STUDENT_EASY: "easy", STUDENT_HARD: "hard"})

    easy_qs = get_questions_for_student(STUDENT_EASY, aid)
    assert len(easy_qs) == 1 and easy_qs[0]["difficulty"] == "easy", f"基础组应只有1道 easy 题，实际: {easy_qs}"

    hard_qs = get_questions_for_student(STUDENT_HARD, aid)
    assert len(hard_qs) == 1 and hard_qs[0]["difficulty"] == "hard", f"提高组应只有1道 hard 题，实际: {hard_qs}"


# ── Case 5: 分组中无对应难度题时降级 ──────────────────────────────────────────
def c5_fallback_when_no_matching():
    from services.assignment_service import create_assignment, set_difficulty_groups, get_questions_for_student, _ensure_tables
    _ensure_tables()
    questions = [
        {"type": "single_choice", "prompt": "Easy1", "options": ["A","B","C","D"], "answer": "A", "difficulty": "easy"},
        {"type": "single_choice", "prompt": "Easy2", "options": ["A","B","C","D"], "answer": "B", "difficulty": "easy"},
    ]
    asgn = create_assignment(TEACHER, "降级测试", questions, [STUDENT_HARD])
    aid = asgn["id"]
    set_difficulty_groups(TEACHER, aid, {STUDENT_HARD: "hard"})  # 但题目全是 easy
    # 过滤后为空，应降级返回全部题目
    qs = get_questions_for_student(STUDENT_HARD, aid)
    assert len(qs) == 2, f"无匹配难度时应降级返回全部2题，实际 {len(qs)}"


# ── Case 6: list_student_assignments 含 my_difficulty ─────────────────────────
def c6_list_includes_my_difficulty():
    from services.assignment_service import create_assignment, set_difficulty_groups, list_student_assignments, _ensure_tables
    _ensure_tables()
    questions = [{"type": "single_choice", "prompt": "Q", "options": ["A","B","C","D"], "answer": "A", "difficulty": "easy"}]
    asgn = create_assignment(TEACHER, "列表分层测试", questions, [STUDENT_EASY])
    aid = asgn["id"]
    set_difficulty_groups(TEACHER, aid, {STUDENT_EASY: "easy"})
    assignments = list_student_assignments(STUDENT_EASY)
    target = next((a for a in assignments if a["id"] == aid), None)
    assert target is not None, f"作业应在学生列表中"
    assert target.get("my_difficulty") == "easy", f"my_difficulty 期望 'easy'，实际 {target.get('my_difficulty')}"


if __name__ == "__main__":
    cases = [
        ("C1 _parse_difficulty_groups 解析", c1_parse_groups),
        ("C2 set_difficulty_groups 写入+权限", c2_set_groups),
        ("C3 无分组时返回全部题目", c3_no_group_all_questions),
        ("C4 有分组时只返回匹配难度", c4_filter_by_difficulty),
        ("C5 无匹配难度时降级返回全部", c5_fallback_when_no_matching),
        ("C6 list_student_assignments 含 my_difficulty", c6_list_includes_my_difficulty),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
