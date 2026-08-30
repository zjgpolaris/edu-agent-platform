from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-production-auth-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "auth.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_ENVIRONMENT"] = "production"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
os.environ["EDU_AGENT_AUTH_DB_AUTHORITY"] = "true"
os.environ["JWT_SECRET"] = "production-auth-smoke-7f92c1e4-a8d3-4b5f-91a7"
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "d" * 40
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "v1.43-history-control"
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "false"
os.environ["EDU_AGENT_RUNTIME_V2_SHADOW_MODE"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "0"
os.environ["EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_runtime.context import RuntimeV2Settings, rollout_eligibility  # noqa: E402
from agent_runtime.event_store import ensure_runtime_tables  # noqa: E402
from agent_runtime.rollout_observations import control_observation_progress, record_rollout_observation  # noqa: E402
from api.main import app  # noqa: E402
from db.engine import get_connection  # noqa: E402
from deployment import auth_configuration_status  # noqa: E402
from security.accounts import create_account  # noqa: E402
from security.auth import Actor, create_token  # noqa: E402
from start_backend import validate_auth_preflight  # noqa: E402


def _headers(actor_id: str, claimed_role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(actor_id, claimed_role)}"}


def main() -> None:
    ensure_runtime_tables()
    create_account("verified-a", "verified-a", "verified-pass", "student", traffic_cohort="verified")
    create_account("student-a", "student-a", "student-pass", "student", traffic_cohort="unverified")
    create_account("demo-a", "demo-a", "demo-password", "student", traffic_cohort="demo")
    create_account("teacher-a", "teacher-a", "teacher-pass", "teacher", traffic_cohort="unverified")
    create_account("admin-a", "admin-a", "admin-password", "admin", traffic_cohort="operator")
    create_account("disabled-a", "disabled-a", "disabled-pass", "admin", traffic_cohort="operator")
    with get_connection() as conn:
        conn.execute(text("UPDATE accounts SET account_status='disabled' WHERE actor_id='disabled-a'"))

    with TestClient(app) as client:
        anonymous = client.get("/api/admin/agent-runtime/rollout-status", params={"agent_type": "history_character"})
        assert anonymous.status_code == 401, anonymous.text
        teacher = client.get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character"},
            headers=_headers("teacher-a", "admin"),
        )
        assert teacher.status_code == 403, teacher.text
        student = client.get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character"},
            headers=_headers("student-a", "admin"),
        )
        assert student.status_code == 403, student.text
        teacher_agent_ops = client.get(
            "/api/agent-ops/summary",
            headers=_headers("teacher-a", "teacher"),
        )
        assert teacher_agent_ops.status_code == 403, teacher_agent_ops.text
        disabled = client.get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character"},
            headers=_headers("disabled-a", "admin"),
        )
        assert disabled.status_code == 401, disabled.text
        admin = client.get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character"},
            headers=_headers("admin-a", "admin"),
        )
        assert admin.status_code == 200, admin.text
        assert all(secret not in admin.text for secret in ("verified-a", "demo-a", "admin-a", os.environ["JWT_SECRET"]))

    verified_actor = Actor(actor_id="verified-a", role="student", traffic_cohort="verified")
    demo_actor = Actor(actor_id="demo-a", role="student", traffic_cohort="demo")
    eligible, reason = rollout_eligibility(verified_actor, "runtime")
    assert eligible and reason == "verified_runtime_actor"
    excluded, reason = rollout_eligibility(demo_actor, "runtime")
    assert not excluded and reason == "demo_actor"

    for actor, latency in ((verified_actor, 100), (demo_actor, 200)):
        is_eligible, eligibility_reason = rollout_eligibility(actor, "runtime")
        record_rollout_observation(
            agent_type="history_character",
            runtime_mode="control",
            status="completed",
            latency_ms=latency,
            trace_id=None,
            data_scope="runtime",
            traffic_cohort=actor.traffic_cohort,
            rollout_eligible=is_eligible,
            eligibility_reason=eligibility_reason,
        )
    progress = control_observation_progress(
        agent_type="history_character",
        config_version="v1.43-history-control",
        deployed_commit="d" * 40,
        environment="production",
        minimum_samples=100,
    )
    assert progress["terminal_samples"] == 1, progress
    assert progress["excluded_samples"] == 1, progress
    assert progress["excluded_by_reason"] == {"demo_actor": 1}, progress

    shadow_env = {
        **os.environ,
        "EDU_AGENT_RUNTIME_V2_ENABLED": "true",
        "EDU_AGENT_RUNTIME_V2_SHADOW_MODE": "true",
        "EDU_AGENT_RUNTIME_V2_CONFIG_VERSION": "v1.43-history-shadow",
        "EDU_AGENT_RUNTIME_V2_PERCENT_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS": "true",
        "EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED": "true",
    }
    with patch.dict(os.environ, shadow_env, clear=True):
        settings = RuntimeV2Settings.from_env()
        assert settings.rollout_decision("history_character", "verified-a", rollout_eligible=True)[0] is True
        assert settings.rollout_decision("history_character", "demo-a", rollout_eligible=False)[0] is False

    with patch.dict(os.environ, {**os.environ, "EDU_AGENT_AUTH_REQUIRED": "false"}, clear=True):
        assert "production_auth_not_enabled" in auth_configuration_status()["errors"]
        try:
            validate_auth_preflight()
        except RuntimeError:
            pass
        else:
            raise AssertionError("production auth preflight accepted disabled authentication")
    with patch.dict(os.environ, {**os.environ, "JWT_SECRET": "short"}, clear=True):
        assert "jwt_secret_too_short" in auth_configuration_status()["errors"]
    with patch.dict(os.environ, {**os.environ, "EDU_AGENT_AUTH_REQUIRED": "true"}, clear=True):
        assert validate_auth_preflight()["ok"] is True

    print("production_auth_trusted_rollout_smoke=PASS")


if __name__ == "__main__":
    main()
