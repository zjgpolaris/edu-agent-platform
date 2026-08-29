from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-learning-api-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
os.environ["JWT_SECRET"] = "runtime-learning-api-secret-at-least-32-bytes"
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "learning-assistant-api-test"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS"] = "10000"

from fastapi.testclient import TestClient  # noqa: E402
from agent_runtime.event_store import get_run  # noqa: E402
from api.main import app  # noqa: E402
from security.auth import create_token  # noqa: E402


def headers(student_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(student_id, 'student')}"}


def create_session(client: TestClient, student_id: str) -> str:
    response = client.post(
        "/api/learning/assistant/sessions",
        json={"student_id": student_id, "source_feature": "standalone"},
        headers=headers(student_id),
    )
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


def start_waiting_run(client: TestClient, student_id: str, session_id: str, key: str) -> dict:
    response = client.post(
        "/api/learning/assistant/chat",
        json={
            "message": "演示高风险工具，删除演示记忆",
            "student_id": student_id,
            "session_id": session_id,
            "stream": False,
            "idempotency_key": key,
        },
        headers=headers(student_id),
    )
    assert response.status_code == 200, response.text
    final = response.json()["final"]
    assert final["completion_status"] == "waiting_confirmation", final
    assert str(final["run_id"]).startswith("run_")
    return final


def main() -> None:
    student_id = "student-learning-api"
    with TestClient(app) as client:
        session_id = create_session(client, student_id)
        final = start_waiting_run(client, student_id, session_id, "learning-api-confirm-0001")
        run_id = str(final["run_id"])
        run = get_run(run_id)
        assert run["status"] == "waiting_confirmation"

        replay = client.get(f"/api/agent-runs/{run_id}/events", headers=headers(student_id))
        assert replay.status_code == 200, replay.text
        assert replay.json()["run_revision"] == run["revision"]
        assert replay.json()["status"] == "waiting_confirmation"
        assert "confirm_" not in replay.text

        session_before = client.get(
            f"/api/learning/assistant/sessions/{session_id}",
            headers=headers(student_id),
        ).json()
        assert "confirm_" not in str(session_before)
        messages_before = list(session_before["messages"])
        assert messages_before[-1]["metadata"]["run_id"] == run_id

        refreshed = client.post(
            f"/api/agent-runs/{run_id}/confirmation-token",
            json={"expected_revision": run["revision"]},
            headers=headers(student_id),
        )
        assert refreshed.status_code == 200, refreshed.text
        token = str(refreshed.json()["confirmation_token"])
        assert token.startswith("confirm_")

        confirmed = client.post(
            f"/api/agent-runs/{run_id}/confirm",
            json={
                "expected_revision": run["revision"],
                "correlation_key": f"confirm:{run_id}:{run['revision']}",
                "confirmation_token": token,
            },
            headers=headers(student_id),
        )
        assert confirmed.status_code == 200, confirmed.text
        confirmed_data = confirmed.json()
        assert confirmed_data["ok"] is True
        assert confirmed_data["run_id"] == run_id
        assert confirmed_data["status"] == "completed"
        assert confirmed_data["event_cursor"] > final["event_cursor"]
        assert get_run(run_id)["status"] == "completed"

        session_after = client.get(
            f"/api/learning/assistant/sessions/{session_id}",
            headers=headers(student_id),
        ).json()
        assert session_after["messages"][-1]["metadata"]["completion_status"] == "completed"
        assert session_after["messages"][-1]["tool_results"][-1]["ok"] is True
        assert "confirm_" not in str(session_after)

        replay_chat = client.post(
            "/api/learning/assistant/chat",
            json={
                "message": "演示高风险工具，删除演示记忆",
                "student_id": student_id,
                "session_id": session_id,
                "stream": False,
                "idempotency_key": "learning-api-confirm-0001",
            },
            headers=headers(student_id),
        )
        assert replay_chat.status_code == 200, replay_chat.text
        assert replay_chat.json()["final"]["run_id"] == run_id
        assert replay_chat.json()["final"]["idempotent_replay"] is True
        session_replayed = client.get(
            f"/api/learning/assistant/sessions/{session_id}",
            headers=headers(student_id),
        ).json()
        assert len(session_replayed["messages"]) == len(session_after["messages"])

        conflicting_replay = client.post(
            "/api/learning/assistant/chat",
            json={
                "message": "用同一个幂等键发送另一条问题",
                "student_id": student_id,
                "session_id": session_id,
                "stream": False,
                "idempotency_key": "learning-api-confirm-0001",
            },
            headers=headers(student_id),
        )
        assert conflicting_replay.status_code == 409, conflicting_replay.text

        cancel_session = create_session(client, student_id)
        cancel_final = start_waiting_run(client, student_id, cancel_session, "learning-api-cancel-0001")
        cancelled = client.post(
            f"/api/agent-runs/{cancel_final['run_id']}/cancel",
            json={"expected_revision": cancel_final["run_revision"]},
            headers=headers(student_id),
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["event_cursor"] > cancel_final["event_cursor"]
        cancel_messages = client.get(
            f"/api/learning/assistant/sessions/{cancel_session}",
            headers=headers(student_id),
        ).json()["messages"]
        assert cancel_messages[-1]["metadata"]["completion_status"] == "cancelled"

    print("agent_runtime_learning_assistant_api_smoke=PASS")


if __name__ == "__main__":
    main()
