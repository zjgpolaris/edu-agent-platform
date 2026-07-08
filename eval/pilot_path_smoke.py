"""Smoke test: v1.25 pilot demo 主路径

覆盖：
1. pilot seed 可重复执行且不重复作业/通知
2. demo 教师/学生账号可登录
3. 学生今日计划有可执行下一步，且不触发 LLM
4. 教师端待复核、欠交/逾期、质检盲区信号存在
5. weakpoints 与 review placeholder 已连接
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-pilot-path-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.seed_pilot_demo import (  # noqa: E402
    ASSIGNMENT_TITLE,
    MAIN_STUDENT,
    NOTIFICATION_MESSAGE,
    PASSWORD,
    TEACHER_ID,
    seed,
)
from security.accounts import authenticate  # noqa: E402
from services.assignment_service import get_teacher_badges, list_teacher_assignments  # noqa: E402
from services.completion_overview import get_class_completion_overview  # noqa: E402
from services.notification_service import get_student_notifications  # noqa: E402
from services.quality_dashboard import get_teacher_quality_dashboard  # noqa: E402
from services.review_service import get_today_session  # noqa: E402
from services.teacher_today_queue import get_teacher_today_queue  # noqa: E402
from services.today_plan import get_student_today_plan  # noqa: E402
from services.weakpoint_service import get_weakpoints  # noqa: E402

TODAY = date.today().isoformat()
_state: dict = {}


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def seed_is_idempotent() -> None:
    first = seed(TODAY, verbose=False)
    second = seed(TODAY, verbose=False)
    assert first["assignment_id"] == second["assignment_id"], (first, second)
    assignments = [a for a in list_teacher_assignments(TEACHER_ID) if a.get("title") == ASSIGNMENT_TITLE]
    assert len(assignments) == 1, assignments
    notes = [n for n in get_student_notifications(MAIN_STUDENT, limit=50, unread_only=False) if n.get("message") == NOTIFICATION_MESSAGE]
    assert len(notes) == 1, notes
    _state["assignment_id"] = first["assignment_id"]


def pilot_accounts_authenticate() -> None:
    teacher = authenticate(TEACHER_ID, PASSWORD)
    student = authenticate(MAIN_STUDENT, PASSWORD)
    assert teacher and teacher["role"] == "teacher", teacher
    assert student and student["role"] == "student", student


def student_today_plan_has_next_step_without_llm() -> None:
    plan = get_student_today_plan(MAIN_STUDENT, TODAY)
    assert plan["tasks"], plan
    summary = plan["summary"]
    assert summary["review_remaining"] > 0, summary
    assert summary["weakpoint_count"] > 0, summary
    weak_tasks = [t for t in plan["tasks"] if t.get("kind") == "weakpoint"]
    assert weak_tasks, plan["tasks"]
    assert weak_tasks[0]["href"].startswith("/student/auto-tutor?focus="), weak_tasks[0]
    # 不调用 AutoTutor start，不 hydrate review；只验证今日计划的确定性聚合。


def teacher_queue_backend_signals_exist() -> None:
    badges = get_teacher_badges(TEACHER_ID)
    assert badges["pending_review"] > 0, badges
    assert badges["blind_spots_to_review"] > 0, badges

    completion = get_class_completion_overview(TEACHER_ID, TODAY)
    assert completion["summary"]["students_with_overdue"] > 0, completion
    assert any(s["pending"] > 0 for s in completion["students"]), completion["students"]

    quality = get_teacher_quality_dashboard(TEACHER_ID)
    eff = quality["effectiveness"]
    assert eff["blind_spots_open"] > 0, eff
    assert quality["hardest_questions"], quality


def teacher_today_queue_api_matches_pilot_signals() -> None:
    queue = get_teacher_today_queue(TEACHER_ID, TODAY)
    items = queue.get("items") or []
    keys = {item.get("key") for item in items}
    summary = queue.get("summary") or {}
    assert items, queue
    assert len(items) <= 4, items
    assert {"reviews", "quality-blind-spots", "completion"}.issubset(keys), queue
    assert int(summary.get("pending_reviews") or 0) > 0, summary
    assert int(summary.get("blind_spots_open") or 0) > 0, summary
    assert int(summary.get("students_with_overdue") or 0) > 0, summary
    priorities = {item["key"]: int(item.get("priority") or 999) for item in items}
    assert priorities["reviews"] < priorities.get("completion", 999), priorities


def notification_banner_seeded_once() -> None:
    unread = [n for n in get_student_notifications(MAIN_STUDENT, limit=50, unread_only=True) if n.get("message") == NOTIFICATION_MESSAGE]
    assert len(unread) == 1, unread
    assert _state.get("assignment_id") in unread[0].get("assignment_ids", []), unread[0]


def weakpoints_and_review_are_connected() -> None:
    weakpoints = get_weakpoints(MAIN_STUDENT)
    tags = {w["knowledge_tag"] for w in weakpoints}
    assert "辛亥革命历史意义" in tags, weakpoints
    session = get_today_session(MAIN_STUDENT, TODAY, hydrate=False)
    assert session is not None, session
    assert session["total"] >= 2, session
    pending = [t for t in session["tasks"] if t.get("pending_generate")]
    assert pending, session
    assert {t.get("tag") for t in pending} & tags, (pending, tags)


if __name__ == "__main__":
    cases = [
        ("seed_is_idempotent", seed_is_idempotent),
        ("pilot_accounts_authenticate", pilot_accounts_authenticate),
        ("student_today_plan_has_next_step_without_llm", student_today_plan_has_next_step_without_llm),
        ("teacher_queue_backend_signals_exist", teacher_queue_backend_signals_exist),
        ("teacher_today_queue_api_matches_pilot_signals", teacher_today_queue_api_matches_pilot_signals),
        ("notification_banner_seeded_once", notification_banner_seeded_once),
        ("weakpoints_and_review_are_connected", weakpoints_and_review_are_connected),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"pilot_path_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
