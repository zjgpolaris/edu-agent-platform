"""Smoke test: 作业错题 → 薄弱点 → 今日复习 → AutoTutor 数据闭环

验证 P1 数据闭环完整化：
1. 学生提交作业答错客观题 → submit 返回 wrong_tags
2. 答错知识点写入 weakpoints 表
3. 已存在的今日复习 session 会追加新弱点（merge_new_weakpoints_to_today）
4. AutoTutor start_session 接收 focus_tags 时，把该知识点提到教学计划最前
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-assignment-loop-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.assignment_service import create_assignment, submit_assignment
from services.review_service import (
    create_today_session,
    get_today_session,
    merge_new_weakpoints_to_today,
)
from services.weakpoint_service import get_weakpoints

TEACHER = "loop-teacher"
STUDENT = "loop-student"
TODAY = "2026-07-02"

QUESTIONS = [
    {"type": "single_choice", "prompt": "鸦片战争爆发于哪一年？",
     "options": ["1840", "1842", "1856", "1860"], "answer": "A", "knowledge_tag": "鸦片战争时间"},
    {"type": "true_false", "prompt": "《马关条约》割让台湾。", "answer": "正确", "knowledge_tag": "马关条约"},
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


def submit_returns_wrong_tags() -> None:
    a = create_assignment(TEACHER, "闭环测试卷", QUESTIONS, [STUDENT], subject="历史")
    _state["aid"] = a["id"]
    # 两题都答错
    result = submit_assignment(STUDENT, a["id"], ["B", "错误"])
    assert "wrong_tags" in result, "提交结果应包含 wrong_tags"
    assert set(result["wrong_tags"]) == {"鸦片战争时间", "马关条约"}, result["wrong_tags"]
    assert result["correct_tags"] == []


def wrong_tags_written_to_weakpoints() -> None:
    tags = {w["knowledge_tag"] for w in get_weakpoints(STUDENT)}
    assert "鸦片战争时间" in tags
    assert "马关条约" in tags


def merge_appends_to_existing_session() -> None:
    # 先造一个只含无关弱点的今日 session
    from services.review_service import _ensure_table  # noqa
    import json
    import uuid
    from db.engine import get_connection
    from sqlalchemy import text
    from student_profile import now_iso

    _ensure_table()
    seed_tasks = [{"tag": "无关知识点", "question": "?", "options": [], "answer": "", "explanation": "", "done": False, "correct": None}]
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions (id, student_id, date, tasks_json, completed, total, created_at)
                 VALUES (:id, :sid, :date, :tasks, 0, :total, :ts)
                 ON CONFLICT(student_id, date) DO UPDATE SET tasks_json=excluded.tasks_json, total=excluded.total"""),
            {"id": str(uuid.uuid4()), "sid": STUDENT, "date": TODAY,
             "tasks": json.dumps(seed_tasks, ensure_ascii=False), "total": 1, "ts": now_iso()},
        )
    # 追加作业新弱点
    merge_new_weakpoints_to_today(STUDENT, ["鸦片战争时间", "马关条约"], TODAY)
    session = get_today_session(STUDENT, TODAY, hydrate=False)
    tags = {t["tag"] for t in session["tasks"]}
    assert tags == {"无关知识点", "鸦片战争时间", "马关条约"}, tags
    assert session["total"] == 3


def merge_dedups_and_skips_missing_session() -> None:
    # 重复追加不产生重复项
    merge_new_weakpoints_to_today(STUDENT, ["鸦片战争时间"], TODAY)
    session = get_today_session(STUDENT, TODAY, hydrate=False)
    assert session["total"] == 3, "重复 tag 不应增加任务数"
    # 无 session 的日期直接跳过，不报错
    merge_new_weakpoints_to_today(STUDENT, ["鸦片战争时间"], "2099-01-01")
    assert get_today_session(STUDENT, "2099-01-01", hydrate=False) is None


def autotutor_prioritizes_focus_tags() -> None:
    # focus_tags 应把指定知识点排到教学计划最前。
    # 计划可能由 LLM 生成（知识点会被改写/扩展），故不做精确字符串相等，
    # 而是检查首步的 source_tag 或 knowledge_point 关联到 focus tag。
    from agents.auto_tutor import start_session
    session = start_session(STUDENT, focus_tags=["马关条约"])
    plan = session.get("lesson_plan") or []
    assert plan, "应生成教学计划"
    first = plan[0]
    hit = (first.get("source_tag") == "马关条约") or ("马关条约" in (first.get("knowledge_point") or ""))
    assert hit, f"首步应聚焦「马关条约」，实际：source_tag={first.get('source_tag')!r} kp={first.get('knowledge_point')!r}"


def hydrate_generates_pending_tasks() -> None:
    # hydrate=True 时把 pending_generate 占位题生成真题并清除标记（stub 掉 LLM）
    import services.review_service as rs
    orig = rs._generate_question
    rs._generate_question = lambda tag: {  # type: ignore
        "question": f"[生成]{tag}？", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"],
        "answer": "A", "explanation": "解析", "tag": tag, "done": False, "correct": None,
    }
    try:
        session = rs.get_today_session(STUDENT, TODAY, hydrate=True)
    finally:
        rs._generate_question = orig  # type: ignore
    hydrated = next(t for t in session["tasks"] if t["tag"] == "马关条约")
    assert hydrated["question"].startswith("[生成]"), hydrated
    assert len(hydrated["options"]) == 4
    assert "pending_generate" not in hydrated
    # 再次读取（hydrate=False）应已持久化，不再是占位
    again = next(t for t in rs.get_today_session(STUDENT, TODAY, hydrate=False)["tasks"] if t["tag"] == "马关条约")
    assert "pending_generate" not in again, again


if __name__ == "__main__":
    cases = [
        ("submit_returns_wrong_tags", submit_returns_wrong_tags),
        ("wrong_tags_written_to_weakpoints", wrong_tags_written_to_weakpoints),
        ("merge_appends_to_existing_session", merge_appends_to_existing_session),
        ("merge_dedups_and_skips_missing_session", merge_dedups_and_skips_missing_session),
        ("hydrate_generates_pending_tasks", hydrate_generates_pending_tasks),
        ("autotutor_prioritizes_focus_tags", autotutor_prioritizes_focus_tags),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"assignment_review_loop_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
