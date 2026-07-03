"""Smoke test: 出题难度维度

覆盖场景：
1. 创建带 difficulty 字段的作业，洞察报告包含 difficulty_distribution
2. difficulty_distribution 统计正确（easy/medium/hard 各计）
3. 无 difficulty 字段的旧题目：difficulty_distribution 全为 0
4. difficulty 仅统计 objective 类型（不含 subjective 的暂按 review_score 路径走）
5. 题目 JSON 中保留 difficulty 字段（序列化不丢失）
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-difficulty-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

TEACHER = "smoke-difficulty-teacher"
STUDENT = "smoke-difficulty-student"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


def _make_questions(easy=1, medium=1, hard=1, no_diff=0) -> list[dict]:
    """构造测试题目，含 difficulty 标注。"""
    qs = []
    for _ in range(easy):
        qs.append({"type": "single_choice", "prompt": "基础题", "options": ["A", "B", "C", "D"],
                   "answer": "A", "knowledge_tag": "鸦片战争", "difficulty": "easy"})
    for _ in range(medium):
        qs.append({"type": "single_choice", "prompt": "中等题", "options": ["A", "B", "C", "D"],
                   "answer": "B", "knowledge_tag": "洋务运动", "difficulty": "medium"})
    for _ in range(hard):
        qs.append({"type": "single_choice", "prompt": "提高题", "options": ["A", "B", "C", "D"],
                   "answer": "C", "knowledge_tag": "甲午战争", "difficulty": "hard"})
    for _ in range(no_diff):
        qs.append({"type": "single_choice", "prompt": "无难度题", "options": ["A", "B", "C", "D"],
                   "answer": "A", "knowledge_tag": "变法"})
    return qs


# ── Case 1: difficulty_distribution 存在且结构正确 ─────────────────────────────
def c1_distribution_exists() -> None:
    from services.assignment_service import create_assignment, submit_assignment, get_assignment_submissions
    questions = _make_questions(easy=1, medium=2, hard=1)
    asgn = create_assignment(TEACHER, "难度分布测试", questions, [STUDENT])
    aid = asgn["id"]
    submit_assignment(STUDENT, aid, ["A", "B", "C", "A"])
    detail = get_assignment_submissions(TEACHER, aid)
    dist = (detail.get("insights") or {}).get("difficulty_distribution")
    assert dist is not None, "difficulty_distribution 字段缺失"
    assert "easy" in dist and "medium" in dist and "hard" in dist, f"缺少难度键: {dist}"


# ── Case 2: 统计数量正确 ──────────────────────────────────────────────────────
def c2_distribution_counts() -> None:
    from services.assignment_service import create_assignment, submit_assignment, get_assignment_submissions
    questions = _make_questions(easy=2, medium=3, hard=1)
    asgn = create_assignment(TEACHER, "难度计数测试", questions, [STUDENT])
    aid = asgn["id"]
    submit_assignment(STUDENT, aid, ["A"] * 6)
    detail = get_assignment_submissions(TEACHER, aid)
    dist = detail["insights"]["difficulty_distribution"]
    assert dist["easy"] == 2, f"easy 期望 2，实际 {dist['easy']}"
    assert dist["medium"] == 3, f"medium 期望 3，实际 {dist['medium']}"
    assert dist["hard"] == 1, f"hard 期望 1，实际 {dist['hard']}"


# ── Case 3: 无难度字段的旧题目 ────────────────────────────────────────────────
def c3_no_difficulty_field() -> None:
    from services.assignment_service import create_assignment, submit_assignment, get_assignment_submissions
    questions = _make_questions(easy=0, medium=0, hard=0, no_diff=3)
    asgn = create_assignment(TEACHER, "旧题无难度", questions, [STUDENT])
    aid = asgn["id"]
    submit_assignment(STUDENT, aid, ["A", "A", "A"])
    detail = get_assignment_submissions(TEACHER, aid)
    dist = detail["insights"]["difficulty_distribution"]
    assert dist["easy"] == 0 and dist["medium"] == 0 and dist["hard"] == 0, \
        f"无难度字段时应全 0，实际 {dist}"


# ── Case 4: 混合（有+无难度字段）统计正确 ─────────────────────────────────────
def c4_mixed_distribution() -> None:
    from services.assignment_service import create_assignment, submit_assignment, get_assignment_submissions
    questions = _make_questions(easy=1, medium=0, hard=0, no_diff=2)
    asgn = create_assignment(TEACHER, "混合难度测试", questions, [STUDENT])
    aid = asgn["id"]
    submit_assignment(STUDENT, aid, ["A", "A", "A"])
    detail = get_assignment_submissions(TEACHER, aid)
    dist = detail["insights"]["difficulty_distribution"]
    assert dist["easy"] == 1, f"easy 期望 1，实际 {dist['easy']}"
    assert dist["medium"] == 0 and dist["hard"] == 0


# ── Case 5: difficulty 字段在 questions_json 中持久化 ─────────────────────────
def c5_difficulty_persisted_in_json() -> None:
    from services.assignment_service import create_assignment, _ensure_tables
    from db.engine import get_connection
    from sqlalchemy import text
    _ensure_tables()
    questions = _make_questions(easy=1, medium=1, hard=1)
    asgn = create_assignment(TEACHER, "持久化测试", questions, [STUDENT])
    aid = asgn["id"]
    with get_connection() as conn:
        row = conn.execute(text("SELECT questions_json FROM assignments WHERE id=:id"), {"id": aid}).fetchone()
    stored = json.loads(row[0])
    diffs = [q.get("difficulty") for q in stored]
    assert "easy" in diffs, f"easy 未持久化，实际: {diffs}"
    assert "medium" in diffs, f"medium 未持久化，实际: {diffs}"
    assert "hard" in diffs, f"hard 未持久化，实际: {diffs}"


if __name__ == "__main__":
    cases = [
        ("C1 difficulty_distribution 存在且结构正确", c1_distribution_exists),
        ("C2 统计数量正确", c2_distribution_counts),
        ("C3 无难度字段的旧题目全为 0", c3_no_difficulty_field),
        ("C4 混合题目统计正确", c4_mixed_distribution),
        ("C5 difficulty 字段在 questions_json 中持久化", c5_difficulty_persisted_in_json),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
