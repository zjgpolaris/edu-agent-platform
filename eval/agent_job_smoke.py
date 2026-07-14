from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

db_path = Path(tempfile.gettempdir()) / "edu-agent-job-smoke.sqlite3"
for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
    candidate.unlink(missing_ok=True)
os.environ["EDU_AGENT_DB_PATH"] = str(db_path)

from db.engine import get_connection  # noqa: E402
from services.agent_job_service import (  # noqa: E402
    claim_job,
    create_job,
    execute_job,
    get_job,
    recover_stale_jobs,
    request_cancel,
)
from sqlalchemy import text  # noqa: E402


def main() -> None:
    created = create_job(
        "report.generate",
        {"student_id": "student-a"},
        actor_id="teacher-a",
        idempotency_key="report-student-a-v1",
        trace_id="trace-job-1",
    )
    duplicate = create_job(
        "report.generate",
        {"student_id": "student-a", "ignored": True},
        actor_id="teacher-a",
        idempotency_key="report-student-a-v1",
    )
    assert duplicate["id"] == created["id"]

    completed = execute_job(created["id"], lambda payload: {"student_id": payload["student_id"], "ready": True})
    assert completed["status"] == "succeeded"
    assert completed["attempts"] == 1
    assert completed["result"]["ready"] is True
    assert completed["trace_id"] == "trace-job-1"

    retrying = create_job("unstable", {}, max_attempts=2)

    def fail(_: dict) -> None:
        raise RuntimeError("temporary provider failure")

    first_failure = execute_job(retrying["id"], fail)
    assert first_failure["status"] == "pending"
    assert first_failure["attempts"] == 1
    final_failure = execute_job(retrying["id"], fail)
    assert final_failure["status"] == "failed"
    assert final_failure["attempts"] == 2
    assert "temporary provider failure" in final_failure["error"]

    pending = create_job("cancel-me", {})
    cancelled = request_cancel(pending["id"])
    assert cancelled and cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True

    stale = create_job("recover-me", {}, max_attempts=2)
    assert claim_job(stale["id"])["status"] == "running"
    with get_connection() as conn:
        conn.execute(
            text("UPDATE agent_jobs SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=:id"),
            {"id": stale["id"]},
        )
    recovered = recover_stale_jobs("2001-01-01T00:00:00+00:00")
    assert recovered == {"retried": 1, "failed": 0, "cancelled": 0}
    assert get_job(stale["id"])["status"] == "pending"
    request_cancel(stale["id"])

    from fastapi.testclient import TestClient
    from api.main import app
    from services.review_service import _ensure_table as ensure_review_table
    from student_profile import init_db as init_student_db

    init_student_db()
    ensure_review_table()

    with TestClient(app) as client:
        queued_response = client.post(
            "/api/agent-jobs/weekly-summary",
            json={"student_id": "student-api", "idempotency_key": "weekly-student-api"},
        )
        assert queued_response.status_code == 202, queued_response.text
        queued = queued_response.json()
        status_response = client.get(f"/api/agent-jobs/{queued['id']}")
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["status"] in {"pending", "running", "succeeded"}, status_payload

        cancel_response = client.delete(f"/api/agent-jobs/{queued['id']}")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] in {"running", "succeeded", "cancelled"}

    print("agent_job_smoke=PASS")


if __name__ == "__main__":
    main()
