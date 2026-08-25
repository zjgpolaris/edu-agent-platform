"""Deterministic clock gate for review retention scheduling."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-review-retention-scheduler.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from services.review_service import (
    advance_after_feedback,
    create_today_session,
    get_today_session,
    public_review_session,
    submit_answer,
)
from services.weakpoint_service import record_weakpoint

TODAY = "2026-08-25"
NOW = "2026-08-25T03:00:00Z"


def main() -> None:
    student = "v138-scheduler"
    tag = "辛亥革命历史意义"
    record_weakpoint(student, tag, source="assignment")
    record_weakpoint(student, "鸦片战争的影响", source="assignment")
    session = create_today_session(student, TODAY)
    retrieval_index = next(index for index, task in enumerate(session["tasks"]) if task["tag"] == tag)
    retrieval = session["tasks"][retrieval_index]
    first = submit_answer(
        student, TODAY, retrieval_index, retrieval["answer"], 0, "scheduler-retrieval", occurred_at=NOW,
    )
    advanced = advance_after_feedback(
        student, TODAY, retrieval_index, first["session_revision"], "scheduler-feedback",
    )
    internal = get_today_session(student, TODAY, at=NOW)
    assert internal
    verification = internal["tasks"][advanced["task_index"]]
    verified = submit_answer(
        student,
        TODAY,
        advanced["task_index"],
        verification["answer"],
        advanced["session_revision"],
        "scheduler-verification",
        occurred_at=NOW,
    )
    due_at = verified["available_at"]

    before_due = get_today_session(student, TODAY, at=NOW)
    assert before_due
    before_public = public_review_session(before_due)
    assert not any(task.get("task_role") == "retention" for task in before_due["tasks"]), before_due
    assert before_public["scheduled_reviews"] == [{
        "knowledge_tag": tag,
        "available_at": due_at,
        "message": "明天再确认一次，看看是否真正记住。",
    }], before_public
    assert all("question" not in item and "options" not in item for item in before_public["scheduled_reviews"])

    after_due = (
        datetime.fromisoformat(due_at.replace("Z", "+00:00")) + timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    due_session = get_today_session(student, TODAY, at=after_due)
    assert due_session and due_session["tasks"][0]["task_role"] == "retention", due_session
    assert due_session["tasks"][0]["tag"] == tag, due_session["tasks"][0]
    due_revision = due_session["revision"]
    repeated = get_today_session(student, TODAY, at=after_due)
    assert repeated
    retention_tasks = [task for task in repeated["tasks"] if task.get("task_role") == "retention"]
    assert len(retention_tasks) == 1 and repeated["revision"] == due_revision, repeated
    print("review_retention_scheduler_smoke=PASS")


if __name__ == "__main__":
    main()
