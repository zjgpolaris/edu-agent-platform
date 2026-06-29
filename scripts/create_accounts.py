"""Run once to seed initial accounts: PYTHONPATH=backend python3 scripts/create_accounts.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from security.accounts import create_account

accounts = [
    ("teacher_zhang", "teacher_zhang", "teacher123", "teacher", "张老师"),
    ("student_001",   "student_001",   "student123", "student", "李明"),
    ("demo-student",  "demo-student",  "demo123",    "student", "演示学生"),
]

for actor_id, username, password, role, display_name in accounts:
    try:
        create_account(actor_id, username, password, role, display_name)
        print(f"created: {username} ({role})")
    except Exception as e:
        print(f"skip {username}: {e}")
