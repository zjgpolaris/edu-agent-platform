"""预置 AutoTutor demo 学生 + 教师种子数据。

灌一个带预置错题本的 demo 学生和一个 demo 教师，让 AutoTutor 一进去就有东西可规划。
（参见 docs/202606291030-autotutor-autonomous-loop-dev.md 第 4.2 节）

用法：
    PYTHONPATH=backend python3 scripts/seed_demo_student.py
    # 自定义学生账号：
    PYTHONPATH=backend python3 scripts/seed_demo_student.py demo-student demo123

默认账号：
  学生：demo-student / demo123（年级：八年级上册）
  教师：teacher_zhang / teacher123
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from security.accounts import create_account  # noqa: E402
from services.weakpoint_service import clear_weakpoints, get_weakpoints, record_weakpoint  # noqa: E402
from student_profile import LearningEvent, try_record_learning_event  # noqa: E402

# (知识点, 错误次数) —— 错得多的会被 AutoTutor 排在前面、从更低难度起步
DEMO_WEAKPOINTS = [
    ("鸦片战争", 3),
    ("洋务运动", 2),
    ("戊戌变法", 2),
    ("辛亥革命", 1),
]
DEMO_RECENT_TOPICS = ["第二次鸦片战争", "甲午中日战争"]


def seed(student_id: str, password: str, grade: str = "八年级上册") -> None:
    try:
        create_account(student_id, student_id, password, "student", "Demo 学生")
        print(f"[account] created {student_id} / {password}")
    except Exception as exc:  # 已存在则跳过
        print(f"[account] skipped ({exc})")

    clear_weakpoints(student_id)
    for tag, count in DEMO_WEAKPOINTS:
        for _ in range(count):
            record_weakpoint(student_id, tag, source="demo_seed")
    print(f"[weakpoints] seeded: {[t for t, _ in DEMO_WEAKPOINTS]}")

    for topic in DEMO_RECENT_TOPICS:
        try_record_learning_event(
            LearningEvent(
                student_id=student_id,
                feature="demo_seed",
                event_type="history_search",
                grade=grade,
                topic=topic,
                success=True,
                metadata={"source": "demo_seed"},
            )
        )
    print(f"[profile] recent topics + grade={grade} seeded")

    print("\nDemo 学生就绪：")
    print(f"  登录：{student_id} / {password}")
    print(f"  错题本：{[w['knowledge_tag'] for w in get_weakpoints(student_id)]}")
    print("  打开 /student/auto-tutor 即可让 AutoTutor 现场规划本节课。")


if __name__ == "__main__":
    # 学生 demo 账号
    sid = sys.argv[1] if len(sys.argv) > 1 else "demo-student"
    pwd = sys.argv[2] if len(sys.argv) > 2 else "demo123"
    seed(sid, pwd)

    # 教师 demo 账号（确保每次 seed 都存在且密码已知）
    try:
        create_account("teacher_zhang", "teacher_zhang", "teacher123", "teacher", "张老师")
        print("\n[account] teacher_zhang created")
    except Exception:
        # 已存在时更新密码，保证密码始终是 teacher123
        from security.auth import hash_password
        from db.engine import get_connection
        from sqlalchemy import text
        with get_connection() as conn:
            conn.execute(
                text("UPDATE accounts SET password_hash=:h WHERE actor_id='teacher_zhang'"),
                {"h": hash_password("teacher123")},
            )
        print("\n[account] teacher_zhang password reset to teacher123")

    print("\nDemo 教师就绪：")
    print("  登录：teacher_zhang / teacher123")
    print("  打开 /teacher/assignments 可布置作业（支持 AI 出题）。")
