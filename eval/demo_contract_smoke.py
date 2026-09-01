"""Pilot demo seed and login contract."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-demo-contract.sqlite3"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
os.environ["EDU_AGENT_DB_PATH"] = str(DB_PATH)
os.environ["JWT_SECRET"] = "edu-agent-demo-contract-secret-at-least-32-bytes"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from api.routers.auth import LoginRequest, auth_login  # noqa: E402
from scripts.seed_pilot_demo import ASSIGNMENT_TITLE, seed  # noqa: E402
from security.accounts import get_account  # noqa: E402
from services.assignment_service import list_teacher_assignments  # noqa: E402


def main() -> None:
    first = seed(verbose=False)
    second = seed(verbose=False)
    assert first["assignment_id"] == second["assignment_id"], (first, second)
    assignments = [item for item in list_teacher_assignments("pilot-teacher") if item.get("title") == ASSIGNMENT_TITLE]
    assert len(assignments) == 1, assignments
    assert get_account("pilot-student")["traffic_cohort"] == "demo"
    assert get_account("pilot-teacher")["traffic_cohort"] == "demo"
    student = auth_login(LoginRequest(username="pilot-student", password="pilot123"))
    teacher = auth_login(LoginRequest(username="pilot-teacher", password="pilot123"))
    assert student["demo_mode"] is True and student["role"] == "student", student
    assert teacher["demo_mode"] is True and teacher["role"] == "teacher", teacher
    print("demo_contract_smoke=PASS")


if __name__ == "__main__":
    main()
