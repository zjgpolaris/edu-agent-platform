"""v1.49.7 scoped machine identity and route-boundary smoke."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_temp_dir = tempfile.TemporaryDirectory(prefix="autotutor-verifier-")
CURRENT_TOKEN = "current-autotutor-verification-token-0001"
NEXT_TOKEN = "next-autotutor-verification-token-0000002"
RETIRED_TOKEN = "retired-autotutor-verification-token-0003"
COMMIT = "7" * 40
CONFIG = "v1.49.7-scoped-verification-identity"

os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "identity.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_ENVIRONMENT"] = "production"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
os.environ["EDU_AGENT_AUTH_DB_AUTHORITY"] = "true"
os.environ["JWT_SECRET"] = "autotutor-verification-jwt-secret-for-smoke"
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = COMMIT
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION"] = CONFIG
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT"] = "v1.49.7-test-salt"
os.environ["EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE"] = "legacy"
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS"] = "0"
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED"] = "true"
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED"] = "true"
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH"] = "false"
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_MACHINE_REQUIRED"] = "true"
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_SHA256"] = hashlib.sha256(CURRENT_TOKEN.encode()).hexdigest()
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_KEY_ID"] = "current-202609"
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_NEXT_TOKEN_SHA256"] = hashlib.sha256(NEXT_TOKEN.encode()).hexdigest()
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_NEXT_TOKEN_KEY_ID"] = "next-202610"
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_BOOTSTRAP_SHA256"] = "b" * 64

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from agent_runtime.autotutor_canary_verification import build_autotutor_canary_verification  # noqa: E402
from security.accounts import create_account  # noqa: E402
from security.auth import create_token  # noqa: E402
from security.autotutor_verification_auth import AutoTutorVerificationIdentitySettings  # noqa: E402


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    settings = AutoTutorVerificationIdentitySettings.from_env()
    assert settings.valid and settings.rotation_state == "dual"
    assert settings.match_token(CURRENT_TOKEN) == "current-202609"
    assert settings.match_token(NEXT_TOKEN) == "next-202610"
    assert settings.match_token(RETIRED_TOKEN) is None
    assert settings.match_token("too-short") is None
    safe = str(settings.safe_summary())
    for forbidden in (CURRENT_TOKEN, NEXT_TOKEN, settings.current_sha256, settings.next_sha256):
        assert forbidden not in safe

    malformed = AutoTutorVerificationIdentitySettings.from_env({
        "EDU_AGENT_AUTOTUTOR_VERIFICATION_MACHINE_REQUIRED": "true",
        "EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_SHA256": "not-a-digest",
        "EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_KEY_ID": "bad key id",
    })
    assert not malformed.valid and malformed.rotation_state == "invalid" and malformed.errors

    create_account("admin-v1497", "admin-v1497", "password", "admin", traffic_cohort="operator")
    create_account("teacher-v1497", "teacher-v1497", "password", "teacher")
    admin_jwt = create_token("admin-v1497", "admin")
    teacher_jwt = create_token("teacher-v1497", "teacher")
    verification = {
        "schema_version": 1,
        "phase": "ready_for_manual_one_percent",
        "status": "READY",
        "decision": "GO",
        "blockers": [],
    }
    snapshot = {
        "schema_version": 1,
        "snapshot_sha256": "sha256:snapshot",
        "snapshot": {"snapshot_kind": "canary"},
    }
    evidence = {
        "agent_type": "auto_tutor",
        "runtime_mode": "active_canary",
        "deployed_commit": COMMIT,
        "config_version": CONFIG,
        "environment": "production",
        "schema_version": 3,
        "decision": "CANDIDATE_GO",
        "evidence_stage": "candidate",
        "evidence_sha256": "sha256:evidence",
    }

    with TestClient(app) as client, \
         patch("agent_runtime.autotutor_canary_verification.build_autotutor_canary_verification", return_value=verification), \
         patch("agent_runtime.autotutor_canary_verification.build_autotutor_canary_snapshot", return_value=snapshot), \
         patch("agent_runtime.evidence_store.load_release_evidence", return_value=None), \
         patch("agent_runtime.evidence_store.save_release_evidence", return_value=evidence):
        for token in (CURRENT_TOKEN, NEXT_TOKEN, admin_jwt):
            response = client.get(
                "/api/admin/agent-runtime/autotutor-canary/verification",
                headers=_bearer(token),
                params={"expected_commit": COMMIT, "expected_config_version": CONFIG},
            )
            assert response.status_code == 200, response.text

        snapshot_response = client.post(
            "/api/admin/agent-runtime/autotutor-canary/snapshots",
            headers=_bearer(CURRENT_TOKEN),
            json={
                "expected_commit": COMMIT,
                "expected_config_version": CONFIG,
                "window_start": "2026-09-02T00:00:00+00:00",
                "window_end": "2026-09-02T01:00:00+00:00",
            },
        )
        assert snapshot_response.status_code == 200, snapshot_response.text
        evidence_get = client.get(
            "/api/admin/agent-runtime/autotutor-canary/evidence",
            headers=_bearer(CURRENT_TOKEN),
        )
        assert evidence_get.status_code == 200, evidence_get.text
        evidence_post = client.post(
            "/api/admin/agent-runtime/autotutor-canary/evidence",
            headers=_bearer(CURRENT_TOKEN),
            json={"evidence": evidence},
        )
        assert evidence_post.status_code == 200, evidence_post.text

        unrelated = client.get(
            "/api/admin/agent-runtime/readiness",
            headers=_bearer(CURRENT_TOKEN),
        )
        assert unrelated.status_code == 401, unrelated.text
        retired = client.get(
            "/api/admin/agent-runtime/autotutor-canary/verification",
            headers=_bearer(RETIRED_TOKEN),
        )
        assert retired.status_code == 401, retired.text
        teacher = client.get(
            "/api/admin/agent-runtime/autotutor-canary/verification",
            headers=_bearer(teacher_jwt),
        )
        assert teacher.status_code == 403, teacher.text

    aggregate = {
        "status": "NOT_READY", "decision": "NO_GO", "blockers": ["insufficient_graph_samples"],
        "assigned_control_count": 100, "assigned_graph_count": 0,
        "selected_graph_count": 0, "committed_graph_count": 0,
    }
    common_patches = (
        patch("agent_runtime.autotutor_canary_verification.runtime_schema_readiness", return_value={"schema_ready": True, "alembic_version": "016"}),
        patch("agent_runtime.autotutor_canary_verification.trusted_rollout_cohort_status", return_value={"ready": True, "verified_actor_count": 1}),
        patch("agent_runtime.autotutor_canary_verification.observation_write_health", return_value={"status": "ok", "ok": True, "failure_count": 0}),
        patch("agent_runtime.autotutor_canary_verification.aggregate_autotutor_transition_canary", return_value=aggregate),
        patch("agent_runtime.autotutor_canary_verification.load_release_evidence", return_value=None),
        patch("agent_runtime.autotutor_canary_verification._admission", return_value={"status": "denied", "reason_codes": []}),
    )
    for active_patch in common_patches:
        active_patch.start()
    try:
        ready = build_autotutor_canary_verification(expected_commit=COMMIT, expected_config_version=CONFIG)
        assert ready["production_verification_ready"] is True, ready
        assert ready["verification_identity"]["rotation_state"] == "dual"
        assert ready["operations"]["environment_bootstrap"] == "attested"
        missing_bootstrap_env = dict(os.environ)
        missing_bootstrap_env.pop("EDU_AGENT_AUTOTUTOR_VERIFICATION_BOOTSTRAP_SHA256", None)
        with patch.dict(os.environ, missing_bootstrap_env, clear=True):
            blocked = build_autotutor_canary_verification(expected_commit=COMMIT, expected_config_version=CONFIG)
        assert "verification_bootstrap_not_attested" in blocked["blockers"], blocked
        assert blocked["production_verification_ready"] is False
    finally:
        for active_patch in reversed(common_patches):
            active_patch.stop()

    print("autotutor_scoped_verification_identity_smoke=PASS")


if __name__ == "__main__":
    main()
