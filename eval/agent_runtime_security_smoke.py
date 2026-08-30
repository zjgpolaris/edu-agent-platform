from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-security-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
os.environ["JWT_SECRET"] = "runtime-security-smoke-secret-at-least-32-bytes"

from fastapi.testclient import TestClient  # noqa: E402
from agent_runtime.artifact_store import create_artifact  # noqa: E402
from agent_runtime.event_store import append_run_event, create_run, get_run  # noqa: E402
from agent_runtime.models import AgentContext, AgentPlan, AgentStep  # noqa: E402
from api.main import app  # noqa: E402
from db.engine import get_connection  # noqa: E402
from db.schema import assignments  # noqa: E402
from security.auth import create_token  # noqa: E402
from sqlalchemy import text  # noqa: E402


def headers(actor_id: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(actor_id, role)}"}


def main() -> None:
    context = AgentContext(
        run_id="run_security",
        agent_type="essay_grader",
        actor_id="student-owner",
        actor_role="student",
        student_id="student-owner",
        session_id="run_security",
        trace_id="trace-security",
        durability_mode="resumable",
        config_version="security-test",
    )
    create_run(context, objective="owner protected")
    create_artifact(
        "run_security",
        owner_actor_id="student-owner",
        student_id="student-owner",
        artifact_type="input",
        sensitivity="student_content",
        content={"essay": "must remain private"},
    )
    create_artifact(
        "run_security",
        owner_actor_id="student-owner",
        student_id="student-owner",
        artifact_type="structured_output",
        sensitivity="student_content",
        content={"draft_score": {"total_score": 80}, "draft_comments": "待教师复核"},
    )
    append_run_event("run_security", expected_revision=0, event_type="route_decided", next_status="routed")
    plan = AgentPlan(
        plan_id="plan-security",
        objective="security review",
        strategy="subgraph",
        steps=[AgentStep(step_id="finalize", kind="control", operation="essay.finalize")],
        generated_by="template",
        planner_version="security-test",
    )
    append_run_event("run_security", expected_revision=1, event_type="plan_created", next_status="planned", plan=plan.model_dump())
    append_run_event("run_security", expected_revision=2, event_type="step_started", next_status="running")
    append_run_event("run_security", expected_revision=3, event_type="waiting_input", next_status="waiting_input")
    with get_connection() as conn:
        assignments.create(bind=conn, checkfirst=True)
        conn.execute(text("""INSERT INTO assignments (
            id, teacher_id, title, subject, grade, questions_json,
            assignee_ids_json, due_date, created_at
        ) VALUES (
            'assignment-security', 'teacher-a', '安全测试', '语文', NULL,
            '[]', '[\"student-owner\"]', NULL, '2026-08-20T00:00:00+00:00'
        )"""))
    with TestClient(app) as client:
        denied = client.get("/api/agent-runs/run_security", headers=headers("student-other", "student"))
        assert denied.status_code == 403, denied.text
        allowed = client.get("/api/agent-runs/run_security", headers=headers("student-owner", "student"))
        assert allowed.status_code == 200, allowed.text
        assert "must remain private" not in allowed.text
        events_denied = client.get("/api/agent-runs/run_security/events", headers=headers("student-other", "student"))
        assert events_denied.status_code == 403
        teacher = client.get("/api/agent-runs/run_security", headers=headers("teacher-a", "teacher"))
        assert teacher.status_code == 200
        unrelated_teacher = client.get("/api/agent-runs/run_security", headers=headers("teacher-other", "teacher"))
        assert unrelated_teacher.status_code == 403
        rollout_teacher_denied = client.get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character"},
            headers=headers("teacher-a", "teacher"),
        )
        assert rollout_teacher_denied.status_code == 403
        rollout_admin = client.get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character"},
            headers=headers("admin-a", "admin"),
        )
        assert rollout_admin.status_code == 200, rollout_admin.text
        assert "student_id" not in rollout_admin.text
        assert "session_id" not in rollout_admin.text
        history_denied = client.post(
            "/api/history/character/recommend",
            json={"message": "推荐一位人物", "student_id": "student-owner"},
            headers=headers("teacher-other", "teacher"),
        )
        assert history_denied.status_code == 403, history_denied.text
        essay_start_denied = client.post(
            "/api/chinese/essay/grade",
            json={"essay": "这是一篇安全边界测试作文。", "student_id": "student-owner"},
            headers=headers("teacher-other", "teacher"),
        )
        assert essay_start_denied.status_code == 403, essay_start_denied.text
        essay_owner_denied = client.post(
            "/api/chinese/essay/grade",
            json={"essay": "这是一篇安全边界测试作文。", "student_id": "student-owner"},
            headers=headers("student-other", "student"),
        )
        assert essay_owner_denied.status_code == 403, essay_owner_denied.text
        student_review = client.post(
            "/api/chinese/essay/review-result",
            json={"session_id": "run_security", "approved": True},
            headers=headers("student-owner", "student"),
        )
        assert student_review.status_code == 403
        student_resume = client.post(
            "/api/agent-runs/run_security/resume",
            json={
                "expected_revision": 4,
                "correlation_key": "essay-review-student-denied",
                "input_patch": {"approved": True},
            },
            headers=headers("student-owner", "student"),
        )
        assert student_resume.status_code == 403, student_resume.text
        teacher_resume = client.post(
            "/api/agent-runs/run_security/resume",
            json={
                "expected_revision": 4,
                "correlation_key": "essay-review-teacher-approved",
                "input_patch": {"approved": True, "decision": "approved", "teacher_comments": "通过"},
            },
            headers=headers("teacher-a", "teacher"),
        )
        assert teacher_resume.status_code == 200, teacher_resume.text
        assert get_run("run_security")["status"] == "completed"
    print("agent_runtime_security_smoke=PASS")


if __name__ == "__main__":
    main()
