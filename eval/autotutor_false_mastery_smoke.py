"""P0 smoke: invalid content never masters; valid mastery needs independent exit evidence."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-false-mastery.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents import auto_tutor as at
from services.weakpoint_service import clear_weakpoints, get_weakpoints, record_weakpoint
from student_profile import list_learning_events


def _correct(session_id: str) -> str:
    state = at._store.get(session_id)
    if state.phase == "exit_ticket":
        return str(state.exit_ticket.question["answer"])
    return str(state.lesson_plan[state.current_step_index].question["answer"])


def main() -> None:
    blocked_id = "false-mastery-blocked"
    clear_weakpoints(blocked_id)
    before = get_weakpoints(blocked_id)
    blocked = at.start_session(blocked_id, grade="八年级上册", focus_tags=["长平之战逐日行军路线"])
    assert blocked["status"] == "needs_content"
    assert blocked["phase"] == "content_blocked"
    assert blocked["current_question"] is None
    replay = at.submit_answer(blocked["session_id"], "A")
    assert replay["status"] == "needs_content"
    assert not replay["mastery"]["practice_correct"]
    assert get_weakpoints(blocked_id) == before
    assert not list_learning_events(student_id=blocked_id, feature="auto_tutor", event_type="auto_tutor_verified_mastery")

    student_id = "verified-mastery-valid"
    clear_weakpoints(student_id)
    record_weakpoint(student_id, "戊戌变法失败原因", source="false_mastery_smoke")
    started = at.start_session(student_id, grade="八年级上册", focus_tags=["戊戌变法失败原因"])
    session_id = started["session_id"]
    assert "answer" not in started["current_question"]
    assert "strategy" not in started["current_question"]
    assert "source_ids" not in str(started["current_question"])
    assert "strategy" not in started["lesson_plan"][0]
    assert "rationale" not in started["lesson_plan"][0]
    practice_id = started["current_question"]["assessment_id"]
    practiced = at.submit_answer(session_id, _correct(session_id))
    assert practiced["lesson_plan"][0]["status"] == "practiced"
    assert practiced["mastery"]["status"] == "not_yet_verified"
    assert not list_learning_events(student_id=student_id, feature="auto_tutor", event_type="auto_tutor_verified_mastery")
    exit_id = practiced["current_question"]["assessment_id"]
    assert practice_id != exit_id
    completed = at.submit_answer(session_id, _correct(session_id))
    assert completed["lesson_plan"][0]["status"] == "mastered"
    assert completed["mastery"]["status"] == "verified"
    verified = list_learning_events(student_id=student_id, feature="auto_tutor", event_type="auto_tutor_verified_mastery")
    assert len(verified) == 1
    print("autotutor_false_mastery_smoke=PASS")


if __name__ == "__main__":
    main()
