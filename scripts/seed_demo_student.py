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
from db.engine import get_connection  # noqa: E402
from security.auth import hash_password  # noqa: E402
from sqlalchemy import text  # noqa: E402

# (知识点, 错误次数) —— 错得多的会被 AutoTutor 排在前面、从更低难度起步
DEMO_WEAKPOINTS = [
    ("鸦片战争", 3),
    ("洋务运动", 2),
    ("戊戌变法", 2),
    ("辛亥革命", 1),
]
DEMO_RECENT_TOPICS = ["第二次鸦片战争", "甲午中日战争"]
DEMO_FOCUS_TAG = DEMO_WEAKPOINTS[0][0]


def ensure_account(actor_id: str, password: str, role: str, display_name: str) -> None:
    try:
        create_account(actor_id, actor_id, password, role, display_name)
        print(f"[account] created {actor_id} / {password}")
    except Exception:
        with get_connection() as conn:
            conn.execute(
                text("""UPDATE accounts
                     SET password_hash=:password_hash, role=:role, display_name=:display_name
                     WHERE actor_id=:actor_id"""),
                {
                    "password_hash": hash_password(password),
                    "role": role,
                    "display_name": display_name,
                    "actor_id": actor_id,
                },
            )
        print(f"[account] reset {actor_id} / {password}")


def seed(student_id: str, password: str, grade: str = "八年级上册") -> None:
    ensure_account(student_id, password, "student", "Demo 学生")

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
    print("  首页：/student")
    print("  复习路径：/student/learning-path")
    print(f"  针对性 AutoTutor：/student/auto-tutor?focus={DEMO_FOCUS_TAG}")
    print("  评测与 AgentOps：/eval")


if __name__ == "__main__":
    # 学生 demo 账号
    sid = sys.argv[1] if len(sys.argv) > 1 else "demo-student"
    pwd = sys.argv[2] if len(sys.argv) > 2 else "demo123"
    seed(sid, pwd)

    # 教师 demo 账号（确保每次 seed 都存在且密码已知）
    ensure_account("teacher_zhang", "teacher123", "teacher", "张老师")

    print("\nDemo 教师就绪：")
    print("  登录：teacher_zhang / teacher123")
    print("  教师首页：/teacher")
    print("  布置作业：/teacher/assignments")
