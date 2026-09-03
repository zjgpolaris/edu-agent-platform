"""Persisted GO evidence only verifies rollback after runtime returns to BPS zero."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime.autotutor_canary_verification import build_autotutor_canary_verification  # noqa: E402
from agents.autotutor_execution import AutoTutorExecutorSettings  # noqa: E402

COMMIT = "e" * 40
CONFIG = "v1.49.5-production-attestation"


def main() -> None:
    env = {**os.environ, "EDU_AGENT_ENVIRONMENT": "production", "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
           "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "legacy", "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "0",
           "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": CONFIG, "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": "test-salt",
           "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true", "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
           "EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "false"}
    aggregate = {"status": "NOT_READY", "decision": "NO_GO", "blockers": ["insufficient_graph_samples"],
                 "assigned_control_count": 100, "assigned_graph_count": 0, "committed_graph_count": 0}
    evidence = {"schema_version": 4, "evidence_stage": "final", "decision": "GO", "evidence_sha256": "sha256:sealed",
                "cohort_fingerprint": AutoTutorExecutorSettings.from_env(env).cohort_fingerprint,
                "drills": {"restart": "pass", "writer_failure": "pass", "kill_switch": "pass", "rollback": "pass"}}
    with patch.dict(os.environ, env, clear=True), \
         patch("agent_runtime.autotutor_canary_verification.runtime_schema_readiness", return_value={"schema_ready": True, "alembic_version": "017"}), \
         patch("agent_runtime.autotutor_canary_verification.trusted_rollout_cohort_status", return_value={"ready": True, "verified_actor_count": 1}), \
         patch("agent_runtime.autotutor_canary_verification.observation_write_health", return_value={"status": "ok", "ok": True}), \
         patch("agent_runtime.autotutor_canary_verification.aggregate_autotutor_transition_canary", return_value=aggregate), \
         patch("agent_runtime.autotutor_canary_verification.load_release_evidence", return_value=evidence), \
         patch("agent_runtime.autotutor_canary_verification._admission", return_value={"status": "denied", "reason_codes": []}):
        result = build_autotutor_canary_verification(expected_commit=COMMIT, expected_config_version=CONFIG)
    assert result["phase"] == "rollback_verified" and result["status"] == "VERIFIED" and result["decision"] == "GO", result
    print("autotutor_production_rollback_verification_smoke=PASS")


if __name__ == "__main__":
    main()
