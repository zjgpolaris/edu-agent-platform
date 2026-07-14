"""预置 v1.25 试点主路径 demo 数据。

这套数据用于稳定演示：学生登录后看到明确今日任务，教师登录后看到待复核、
欠交/逾期、质检盲区等今日行动队列。

用法：
    PYTHONPATH=backend python3 scripts/seed_pilot_demo.py

默认账号：
  教师：pilot-teacher / pilot123
  学生：pilot-student / pilot123
        pilot-student-b / pilot123
        pilot-student-c / pilot123
        pilot-student-d / pilot123
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from db.engine import get_connection  # noqa: E402
from security.accounts import create_account  # noqa: E402
from security.auth import hash_password  # noqa: E402
from services.assignment_service import (  # noqa: E402
    create_assignment,
    get_assignment_submissions,
    list_teacher_assignments,
    review_assignment_submission,
    submit_assignment,
)
from services.notification_service import get_student_notifications, send_urge_notification  # noqa: E402
from services.review_service import _ensure_table as ensure_review_table  # noqa: E402
from services.weakpoint_service import get_weakpoints, record_weakpoint  # noqa: E402
from sqlalchemy import text  # noqa: E402
from student_profile import LearningEvent, now_iso, try_record_learning_event  # noqa: E402

TEACHER_ID = "pilot-teacher"
PASSWORD = "pilot123"
STUDENTS = ["pilot-student", "pilot-student-b", "pilot-student-c", "pilot-student-d"]
DISPLAY_NAMES = {
    TEACHER_ID: "Pilot 张老师",
    "pilot-student": "Pilot 学生A",
    "pilot-student-b": "Pilot 学生B",
    "pilot-student-c": "Pilot 学生C",
    "pilot-student-d": "Pilot 学生D",
}
MAIN_STUDENT = "pilot-student"
ASSIGNMENT_TITLE = "【Pilot Demo】辛亥革命随堂诊断"
NOTIFICATION_MESSAGE = "Pilot 演示：请先完成辛亥革命随堂诊断，错题会自动进入今日复习。"
REVIEW_DATE_DEFAULT = date.today().isoformat()
PILOT_AUTOTUTOR_SESSION_PREFIX = "pilot-autotutor-evidence"

QUESTIONS: list[dict[str, Any]] = [
    {
        "type": "single_choice",
        "prompt": "辛亥革命后建立的临时政府定都在哪里？",
        "options": ["A. 南京", "B. 北京", "C. 武昌", "D. 上海"],
        "answer": "A",
        "knowledge_tag": "辛亥革命历史意义",
        "difficulty": "medium",
        "quality": {"level": "ok", "issues": []},
    },
    {
        "type": "single_choice",
        "prompt": "洋务运动提出的核心口号之一是？",
        "options": ["A. 自强", "B. 民主", "C. 科学", "D. 平等"],
        "answer": "A",
        "knowledge_tag": "洋务运动目的",
        "difficulty": "easy",
        "quality": {"level": "warn", "issues": ["干扰项区分度可继续优化"]},
    },
    {
        "type": "true_false",
        "prompt": "戊戌变法失败的重要原因之一是维新派力量弱小。",
        "answer": "正确",
        "knowledge_tag": "戊戌变法失败原因",
        "difficulty": "medium",
        "quality": {"level": "ok", "issues": []},
    },
    {
        "type": "subjective",
        "prompt": "请简述辛亥革命的历史意义。",
        "reference_answer": "推翻清王朝统治，结束君主专制制度，推动民主共和观念传播。",
        "knowledge_tag": "辛亥革命历史意义",
        "difficulty": "hard",
    },
]

SUBMISSIONS: dict[str, list[Any]] = {
    # Q0 三人均答错，且 Q0 quality=ok、attempts=3、accuracy=0 → 质检盲区。
    MAIN_STUDENT: ["B", "A", "错误", "只推翻了清朝。"],
    "pilot-student-b": ["B", "A", "正确", "结束了封建帝制。"],
    "pilot-student-c": ["B", "C", "错误", "推动民主共和。"],
    # pilot-student-d 不提交，用于教师端欠交/逾期队列。
}

WEAKPOINT_TARGETS = {
    "辛亥革命历史意义": 2,
    "洋务运动目的": 1,
    "戊戌变法失败原因": 1,
}


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def ensure_account(actor_id: str, role: str, password: str = PASSWORD, *, verbose: bool = True) -> None:
    """创建或重置 pilot 账号，保证 demo 口令稳定。"""
    try:
        create_account(actor_id, actor_id, password, role, DISPLAY_NAMES.get(actor_id, actor_id))
        _log(verbose, f"[account] created {actor_id} / {password}")
    except Exception:
        with get_connection() as conn:
            conn.execute(
                text("""UPDATE accounts
                     SET password_hash=:password_hash, role=:role, display_name=:display_name
                     WHERE actor_id=:actor_id"""),
                {
                    "password_hash": hash_password(password),
                    "role": role,
                    "display_name": DISPLAY_NAMES.get(actor_id, actor_id),
                    "actor_id": actor_id,
                },
            )
        _log(verbose, f"[account] reset {actor_id} / {password}")


def _find_assignment_by_title(title: str) -> dict[str, Any] | None:
    for item in list_teacher_assignments(TEACHER_ID):
        if item.get("title") == title:
            return item
    return None


def ensure_assignment(today: str, *, verbose: bool = True) -> dict[str, Any]:
    due_date = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    existing = _find_assignment_by_title(ASSIGNMENT_TITLE)
    if existing:
        with get_connection() as conn:
            conn.execute(
                text("""UPDATE assignments
                     SET questions_json=:questions, assignee_ids_json=:assignees,
                         due_date=:due_date, subject=:subject, grade=:grade
                     WHERE id=:id"""),
                {
                    "questions": json.dumps(QUESTIONS, ensure_ascii=False),
                    "assignees": json.dumps(STUDENTS, ensure_ascii=False),
                    "due_date": due_date,
                    "subject": "历史",
                    "grade": "八年级上册",
                    "id": existing["id"],
                },
            )
        _log(verbose, f"[assignment] reused {ASSIGNMENT_TITLE} ({existing['id']})")
        return existing

    created = create_assignment(
        TEACHER_ID,
        ASSIGNMENT_TITLE,
        QUESTIONS,
        STUDENTS,
        subject="历史",
        grade="八年级上册",
        due_date=due_date,
    )
    _log(verbose, f"[assignment] created {ASSIGNMENT_TITLE} ({created['id']})")
    return created


def _submitted_students(assignment_id: str) -> set[str]:
    try:
        bundle = get_assignment_submissions(TEACHER_ID, assignment_id)
    except Exception:
        return set()
    return {str(s.get("student_id")) for s in bundle.get("submissions") or []}


def ensure_submissions(assignment_id: str, *, verbose: bool = True) -> None:
    submitted = _submitted_students(assignment_id)
    for student_id, answers in SUBMISSIONS.items():
        if student_id in submitted:
            _log(verbose, f"[submission] reused {student_id}")
            continue
        try:
            submit_assignment(student_id, assignment_id, answers)
            _log(verbose, f"[submission] created {student_id}")
        except ValueError as exc:
            if "已提交" in str(exc):
                _log(verbose, f"[submission] skipped duplicate {student_id}")
            else:
                raise


def ensure_reviewed_submission(assignment_id: str, *, verbose: bool = True) -> None:
    """保留 pilot-student 的 partial 待评阅；评阅 B 学生制造 graded 样本。"""
    try:
        review_assignment_submission(
            TEACHER_ID,
            assignment_id,
            "pilot-student-b",
            78,
            "能答出部分意义，但还要补充民主共和观念传播。",
        )
        _log(verbose, "[review] graded pilot-student-b")
    except Exception as exc:
        _log(verbose, f"[review] skipped ({exc})")


def ensure_weakpoints(student_id: str = MAIN_STUDENT, *, verbose: bool = True) -> None:
    current = {w["knowledge_tag"]: int(w.get("wrong_count") or 0) for w in get_weakpoints(student_id)}
    for tag, target in WEAKPOINT_TARGETS.items():
        missing = max(0, target - current.get(tag, 0))
        for _ in range(missing):
            record_weakpoint(student_id, tag, source="pilot_seed")
        if missing:
            _log(verbose, f"[weakpoint] {student_id} +{missing} {tag}")


def ensure_review_placeholders(student_id: str, today: str, *, verbose: bool = True) -> None:
    ensure_review_table()
    tasks = [
        {
            "tag": "辛亥革命历史意义",
            "question": "关于「辛亥革命历史意义」的复习题",
            "options": [],
            "answer": "",
            "explanation": "",
            "done": False,
            "correct": None,
            "pending_generate": True,
        },
        {
            "tag": "洋务运动目的",
            "question": "关于「洋务运动目的」的复习题",
            "options": [],
            "answer": "",
            "explanation": "",
            "done": False,
            "correct": None,
            "pending_generate": True,
        },
    ]
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions (id, student_id, date, tasks_json, completed, total, created_at)
                 VALUES (:id, :sid, :date, :tasks, 0, :total, :ts)
                 ON CONFLICT(student_id, date) DO UPDATE SET
                   tasks_json=excluded.tasks_json,
                   completed=0,
                   total=excluded.total"""),
            {
                "id": str(uuid.uuid4()),
                "sid": student_id,
                "date": today,
                "tasks": json.dumps(tasks, ensure_ascii=False),
                "total": len(tasks),
                "ts": now_iso(),
            },
        )
    _log(verbose, f"[review] placeholders ready {student_id} {today}")


def ensure_notification_once(assignment_id: str, *, verbose: bool = True) -> None:
    existing = get_student_notifications(MAIN_STUDENT, limit=50, unread_only=False)
    found = any(
        n.get("teacher_id") == TEACHER_ID
        and n.get("message") == NOTIFICATION_MESSAGE
        and assignment_id in (n.get("assignment_ids") or [])
        for n in existing
    )
    if found:
        _log(verbose, "[notification] reused pilot message")
        return
    send_urge_notification(TEACHER_ID, [MAIN_STUDENT], NOTIFICATION_MESSAGE, [assignment_id])
    _log(verbose, "[notification] created pilot message")


def ensure_profile_events(today: str, *, verbose: bool = True) -> None:
    with get_connection() as conn:
        conn.execute(
            text("DELETE FROM learning_events WHERE student_id=:sid AND feature='pilot_seed'"),
            {"sid": MAIN_STUDENT},
        )
    for topic in ["辛亥革命历史意义", "洋务运动目的", "戊戌变法失败原因"]:
        try_record_learning_event(
            LearningEvent(
                student_id=MAIN_STUDENT,
                feature="pilot_seed",
                event_type="history_review",
                grade="八年级上册",
                topic=topic,
                success=True,
                metadata={"source": "pilot_seed", "date": today},
            )
        )
    _log(verbose, "[profile] pilot learning events reset")


def ensure_autotutor_evidence(today: str, *, verbose: bool = True) -> None:
    rows = [
        ("pilot-student", "辛亥革命历史意义", True),
        ("pilot-student-b", "辛亥革命历史意义", False),
        ("pilot-student-c", "洋务运动目的", True),
    ]
    with get_connection() as conn:
        for student_id in STUDENTS:
            conn.execute(
                text("""DELETE FROM learning_events
                     WHERE student_id=:sid AND feature='auto_tutor' AND session_id LIKE :prefix"""),
                {"sid": student_id, "prefix": f"{PILOT_AUTOTUTOR_SESSION_PREFIX}%"},
            )
    for index, (student_id, topic, success) in enumerate(rows, start=1):
        session_id = f"{PILOT_AUTOTUTOR_SESSION_PREFIX}-{index}"
        try_record_learning_event(
            LearningEvent(
                student_id=student_id,
                session_id=session_id,
                feature="auto_tutor",
                event_type="auto_tutor_step",
                grade="八年级上册",
                topic=topic,
                success=success,
                score=1.0 if success else 0.0,
                metadata={"source": "pilot_seed", "date": today},
            )
        )
        try_record_learning_event(
            LearningEvent(
                student_id=student_id,
                session_id=session_id,
                feature="auto_tutor",
                event_type="auto_tutor_exit_ticket",
                grade="八年级上册",
                topic=topic,
                success=success,
                score=1.0 if success else 0.0,
                metadata={"source": "pilot_seed", "date": today, "session_phase": "exit_ticket"},
            )
        )
    _log(verbose, "[autotutor] pilot exit ticket evidence reset")


def seed(today: str | None = None, *, verbose: bool = True) -> dict[str, Any]:
    today = today or REVIEW_DATE_DEFAULT
    ensure_account(TEACHER_ID, "teacher", verbose=verbose)
    for sid in STUDENTS:
        ensure_account(sid, "student", verbose=verbose)

    assignment = ensure_assignment(today, verbose=verbose)
    assignment_id = str(assignment["id"])
    ensure_review_placeholders(MAIN_STUDENT, today, verbose=verbose)
    ensure_submissions(assignment_id, verbose=verbose)
    ensure_reviewed_submission(assignment_id, verbose=verbose)
    ensure_weakpoints(MAIN_STUDENT, verbose=verbose)
    ensure_notification_once(assignment_id, verbose=verbose)
    ensure_profile_events(today, verbose=verbose)
    ensure_autotutor_evidence(today, verbose=verbose)

    summary = {
        "teacher": TEACHER_ID,
        "students": STUDENTS,
        "password": PASSWORD,
        "assignment_id": assignment_id,
        "today": today,
    }
    _log(verbose, "\nPilot demo 就绪：")
    _log(verbose, f"  教师登录：{TEACHER_ID} / {PASSWORD} → /teacher")
    _log(verbose, f"  学生登录：{MAIN_STUDENT} / {PASSWORD} → /student")
    _log(verbose, f"  作业：{ASSIGNMENT_TITLE} ({assignment_id})")
    return summary


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else None
    seed(day)
