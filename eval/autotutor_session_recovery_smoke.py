from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-recovery-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass

from agents.auto_tutor import get_latest_session, get_session, start_session


def main() -> None:
    started = start_session("demo-student", grade="八年级上册")
    session_id = started["session_id"]

    latest = get_latest_session("demo-student")
    assert latest["session_id"] == session_id
    assert latest["status"] == "awaiting_answer"
    assert latest["current_question"] is not None

    loaded = get_session(session_id)
    assert loaded["session_id"] == session_id
    assert loaded["current_question"] is not None
    print("autotutor_session_recovery_smoke=PASS")


if __name__ == "__main__":
    main()
