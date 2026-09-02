"""An assigned Graph session is permanently downgraded before Provider on revoked admission."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.auto_tutor import (  # noqa: E402
    AutoTutorState,
    _apply_existing_session_canary_admission,
    _restore_state,
)
from agents.autotutor_canary_admission import AutoTutorCanaryAdmissionSnapshot  # noqa: E402
from agents.autotutor_execution import AutoTutorExecutionContext, AutoTutorExecutorSettings  # noqa: E402


def main() -> None:
    state = AutoTutorState(
        session_id="downgrade-smoke",
        trace_id="downgrade-trace",
        student_id="downgrade-student",
        executor_mode="graph_active",
        executor_assigned_mode="graph_active",
        executor_config_version="v1.49.3-canary",
        executor_deployed_commit="e" * 40,
    )
    context = AutoTutorExecutionContext(
        actor_id="downgrade-student", actor_role="student", account_status="active",
        traffic_cohort="verified", data_scope="runtime", rollout_eligible=True,
        eligibility_reason="verified_runtime_actor", environment="production", deployed_commit="e" * 40,
    )
    settings = AutoTutorExecutorSettings.from_env({
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "active_canary",
        "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "100",
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": "v1.49.3-canary",
        "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": "downgrade-smoke",
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
        "EDU_AGENT_ENVIRONMENT": "production",
        "EDU_AGENT_DEPLOYED_COMMIT": "e" * 40,
    })
    denied = AutoTutorCanaryAdmissionSnapshot(
        status="denied", checked_at="2026-09-02T00:00:00+00:00",
        expires_at="2026-09-02T00:00:10+00:00",
        environment="production", deployed_commit="e" * 40,
        config_version="v1.49.3-canary", schema_revision="016",
        observation_health="degraded", active_bps=100,
        reason_codes=("observation_health_degraded",),
    )
    with patch("agents.auto_tutor.evaluate_autotutor_canary_admission", return_value=denied):
        _apply_existing_session_canary_admission(state, context=context, settings=settings)
    assert state.executor_assigned_mode == "graph_active"
    assert state.executor_mode == "legacy"
    assert state.executor_fallback_reason == "admission_revoked:observation_health_degraded"
    restored = _restore_state(state.model_dump(mode="json"))
    assert restored.executor_mode == "legacy" and restored.executor_assigned_mode == "graph_active"
    assert restored.executor_fallback_reason == state.executor_fallback_reason

    # A permanent downgrade never auto-promotes on a later healthy snapshot.
    admitted = replace(denied, status="admitted", observation_health="ok", reason_codes=())
    with patch("agents.auto_tutor.evaluate_autotutor_canary_admission", return_value=admitted):
        _apply_existing_session_canary_admission(restored, context=context, settings=settings)
    assert restored.executor_mode == "legacy"

    # Kill switch bypasses the cached infrastructure snapshot and is immediate.
    killed_state = state.model_copy(update={"executor_mode": "graph_active", "executor_fallback_reason": None})
    killed_settings = replace(settings, kill_switch=True)
    with patch("agents.auto_tutor.evaluate_autotutor_canary_admission") as admission_read:
        _apply_existing_session_canary_admission(killed_state, context=context, settings=killed_settings)
    admission_read.assert_not_called()
    assert killed_state.executor_mode == "legacy"
    assert killed_state.executor_fallback_reason == "kill_switch_enabled"

    commit_drift = state.model_copy(update={
        "executor_mode": "graph_active",
        "executor_deployed_commit": "f" * 40,
        "executor_fallback_reason": None,
    })
    with patch("agents.auto_tutor.evaluate_autotutor_canary_admission", return_value=admitted):
        _apply_existing_session_canary_admission(commit_drift, context=context, settings=settings)
    assert commit_drift.executor_mode == "legacy"
    assert "executor_commit_drift" in commit_drift.executor_admission_reasons
    print("autotutor_existing_session_downgrade_smoke=PASS")


if __name__ == "__main__":
    main()
