from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

db_path = Path(tempfile.gettempdir()) / "edu-agent-runtime-rollout-status-smoke.sqlite3"
db_path.unlink(missing_ok=True)
os.environ["EDU_AGENT_DB_PATH"] = str(db_path)
os.environ["EDU_AGENT_DATA_SCOPE"] = "runtime"
COMMIT = "c" * 40
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = COMMIT
os.environ["EDU_AGENT_ENVIRONMENT"] = "staging"
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "v1.41-history-control"
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "false"
os.environ["EDU_AGENT_RUNTIME_V2_SHADOW_MODE"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "0"
os.environ["EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS"] = "0"

from agent_runtime.event_store import ensure_runtime_tables
from agent_runtime.rollout_observations import control_observation_progress, record_rollout_observation
from agent_runtime.rollout_status import build_rollout_status
from security.accounts import create_account
from security.auth import create_token


def _shadow_env() -> dict[str, str]:
    return {
        "EDU_AGENT_DB_PATH": str(db_path),
        "EDU_AGENT_DATA_SCOPE": "runtime",
        "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
        "EDU_AGENT_ENVIRONMENT": "staging",
        "EDU_AGENT_RUNTIME_V2_CONFIG_VERSION": "v1.42-history-shadow",
        "EDU_AGENT_RUNTIME_V2_ENABLED": "true",
        "EDU_AGENT_RUNTIME_V2_SHADOW_MODE": "true",
        "EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED": "false",
        "EDU_AGENT_RUNTIME_V2_PERCENT_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_DEBATE_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS": "true",
        "EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED": "true",
        "EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_CONFIG_VERSION": "v1.41-history-control",
        "EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_COMMIT": COMMIT,
        "EDU_AGENT_RUNTIME_ROLLOUT_MIN_TERMINAL_RUNS": "3",
    }


def _gate(*, terminal_runs: int, status: str = "unknown", reasons: list[str] | None = None) -> dict:
    return {
        "status": status,
        "terminal_runs": terminal_runs,
        "run_provenance_coverage": 1.0 if terminal_runs else None,
        "event_coverage": 1.0 if terminal_runs else None,
        "terminal_consistency": 1.0 if terminal_runs else None,
        "unexpected_failure_rate": 0.0 if terminal_runs else None,
        "duplicate_side_effects": 0,
        "duplicate_attempts_prevented": 0,
        "invalid_transitions": 0,
        "high_risk_without_confirmation": 0,
        "p95_regression": 0.0 if terminal_runs else None,
        "run_latency": {"p95_ms": 1000 if terminal_runs else None},
        "profiles": {"offline": "unknown", "real_llm": "unknown", "production_rag": "unknown"},
        "reasons": reasons or [],
    }


def main() -> None:
    ensure_runtime_tables()
    create_account("rollout-admin", "rollout-admin", "rollout-admin-password", "admin", traffic_cohort="operator")
    for index, scope in enumerate(("runtime", "runtime", "runtime", "eval")):
        record_rollout_observation(
            agent_type="history_character",
            runtime_mode="control",
            status="completed",
            latency_ms=100 + index,
            trace_id=f"trace-{index}",
            data_scope=scope,
            config_version="v1.41-history-control",
            deployed_commit=COMMIT,
            environment="staging",
        )
    progress = control_observation_progress(
        agent_type="history_character",
        config_version="v1.41-history-control",
        deployed_commit=COMMIT,
        environment="staging",
        minimum_samples=3,
    )
    assert progress["terminal_samples"] == 3
    assert progress["baseline_ready"] is True

    with patch("agent_runtime.rollout_status.runtime_schema_readiness", return_value={"status": "ready", "schema_ready": True, "alembic_version": "012"}), \
         patch("agent_runtime.rollout_status.observation_write_health", return_value={"status": "ok", "ok": True, "failure_count": 0, "by_reason": {}}):
        control_status = build_rollout_status(agent_type="history_character", minimum_samples=3)
    assert control_status["phase"] == "control_ready", control_status
    assert control_status["next_action"] == "run_shadow_preflight"
    assert "student_id" not in str(control_status)

    control_ready = dict(progress)
    health = {"status": "ok", "ok": True, "failure_count": 0, "by_reason": {}}
    schema = {"status": "ready", "schema_ready": True, "alembic_version": "012"}
    with patch.dict(os.environ, _shadow_env(), clear=True), \
         patch("agent_runtime.rollout_status.control_observation_progress", return_value=control_ready), \
         patch("agent_runtime.rollout_status.observation_write_health", return_value=health), \
         patch("agent_runtime.rollout_status.runtime_schema_readiness", return_value=schema), \
         patch("agent_runtime.rollout_status.load_release_evidence", return_value=None), \
         patch("agent_runtime.rollout_status.build_rollout_readiness", return_value=_gate(terminal_runs=2)):
        collecting = build_rollout_status(agent_type="history_character", minimum_samples=3)
        assert collecting["phase"] == "collecting_shadow", collecting

    with patch.dict(os.environ, _shadow_env(), clear=True), \
         patch("agent_runtime.rollout_status.control_observation_progress", return_value=control_ready), \
         patch("agent_runtime.rollout_status.observation_write_health", return_value=health), \
         patch("agent_runtime.rollout_status.runtime_schema_readiness", return_value=schema), \
         patch("agent_runtime.rollout_status.load_release_evidence", return_value=None), \
         patch("agent_runtime.rollout_status.build_rollout_readiness", return_value=_gate(terminal_runs=3, reasons=["rollout_evidence_missing"])):
        pending = build_rollout_status(agent_type="history_character", minimum_samples=3)
        assert pending["phase"] == "evidence_pending", pending
        assert pending["next_action"] == "run_rollout_evidence"

    with patch.dict(os.environ, _shadow_env(), clear=True), \
         patch("agent_runtime.rollout_status.control_observation_progress", return_value=control_ready), \
         patch("agent_runtime.rollout_status.observation_write_health", return_value=health), \
         patch("agent_runtime.rollout_status.runtime_schema_readiness", return_value=schema), \
         patch("agent_runtime.rollout_status.load_release_evidence", return_value=None), \
         patch("agent_runtime.rollout_status.build_rollout_readiness", return_value=_gate(terminal_runs=3, status="fail", reasons=["invalid_transitions_detected"])):
        stopped = build_rollout_status(agent_type="history_character", minimum_samples=3)
        assert stopped["phase"] == "stopped", stopped
        assert stopped["next_action"] == "stop_rollout"

    from fastapi.testclient import TestClient
    from api.main import app

    with patch("agent_runtime.rollout_status.runtime_schema_readiness", return_value={"status": "ready", "schema_ready": True, "alembic_version": "012"}), \
         patch("agent_runtime.rollout_status.observation_write_health", return_value={"status": "ok", "ok": True, "failure_count": 0, "by_reason": {}}):
        response = TestClient(app).get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character", "minimum_samples": 3},
        )
        assert response.status_code == 200, response.text
        assert response.json()["phase"] == "control_ready"
    production_env = {
        **os.environ,
        "EDU_AGENT_ENVIRONMENT": "production",
        "EDU_AGENT_AUTH_REQUIRED": "true",
        "EDU_AGENT_AUTH_DB_AUTHORITY": "true",
        "JWT_SECRET": "rollout-status-production-secret-3d1a5a8c",
    }
    with patch.dict(os.environ, production_env, clear=True):
        admin_headers = {"Authorization": f"Bearer {create_token('rollout-admin', 'admin')}"}
        response = TestClient(app).get(
            "/api/admin/agent-runtime/rollout-status",
            params={"agent_type": "history_character", "minimum_samples": 99},
            headers=admin_headers,
        )
        assert response.status_code == 400, response.text

    print("agent_runtime_rollout_status_smoke=PASS")


if __name__ == "__main__":
    main()
