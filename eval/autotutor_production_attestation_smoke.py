"""v1.49.5 separates fingerprints and requires non-vacuous rollback traffic."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime.autotutor_canary_verification import build_autotutor_canary_verification  # noqa: E402
from agents.autotutor_execution import AutoTutorExecutorSettings  # noqa: E402
from scripts.verify_autotutor_canary_deployment import _assert_pii_free  # noqa: E402

COMMIT = "9" * 40
CONFIG = "v1.49.5-production-attestation"
END = datetime.now(timezone.utc)
START = END - timedelta(minutes=30)


def _env(*, mode: str = "legacy", bps: str = "0", salt: str = "stable-secret") -> dict[str, str]:
    return {
        **os.environ, "EDU_AGENT_ENVIRONMENT": "production", "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": mode, "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": bps,
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": CONFIG, "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": salt,
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true", "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "false",
    }


def _aggregate(*, control: int, assigned_graph: int = 0, selected_graph: int = 0) -> dict:
    return {
        "status": "NOT_READY", "decision": "NO_GO", "blockers": ["insufficient_graph_samples"],
        "assigned_control_count": control, "assigned_graph_count": assigned_graph,
        "selected_graph_count": selected_graph, "committed_graph_count": 0,
    }


def _verify(aggregate: dict, *, exact: bool, evidence: dict | None = None) -> dict:
    candidate = evidence or {"schema_version": 4, "evidence_stage": "candidate", "decision": "CANDIDATE_GO",
                             "evidence_sha256": "candidate", "drills": {"restart": "pass"},
                             "cohort_fingerprint": AutoTutorExecutorSettings.from_env(_env()).cohort_fingerprint}
    kwargs = {"window_start": START.isoformat(), "window_end": END.isoformat()} if exact else {}
    with patch.dict(os.environ, _env(), clear=True), \
         patch("agent_runtime.autotutor_canary_verification.runtime_schema_readiness", return_value={"schema_ready": True, "alembic_version": "016"}), \
         patch("agent_runtime.autotutor_canary_verification.trusted_rollout_cohort_status", return_value={"ready": True, "verified_actor_count": 1}), \
         patch("agent_runtime.autotutor_canary_verification.observation_write_health", return_value={"status": "ok", "ok": True, "failure_count": 0}), \
         patch("agent_runtime.autotutor_canary_verification.aggregate_autotutor_transition_canary", return_value=aggregate), \
         patch("agent_runtime.autotutor_canary_verification.load_release_evidence", return_value=candidate), \
         patch("agent_runtime.autotutor_canary_verification._admission", return_value={"status": "denied", "reason_codes": []}):
        return build_autotutor_canary_verification(
            expected_commit=COMMIT, expected_config_version=CONFIG, minimum_rollback_control=1, **kwargs,
        )


def main() -> None:
    active = AutoTutorExecutorSettings.from_env(_env(mode="active_canary", bps="100"))
    rollback = AutoTutorExecutorSettings.from_env(_env())
    changed_salt = AutoTutorExecutorSettings.from_env(_env(salt="different-secret"))
    assert active.cohort_fingerprint == rollback.cohort_fingerprint
    assert active.runtime_state_fingerprint != rollback.runtime_state_fingerprint
    assert changed_salt.cohort_fingerprint != rollback.cohort_fingerprint
    assert "stable-secret" not in str(rollback.safe_summary())

    pending = _verify(_aggregate(control=100), exact=False)
    assert pending["phase"] == "rollback_pending" and pending["status"] == "NOT_READY", pending
    empty = _verify(_aggregate(control=0), exact=True)
    assert empty["phase"] == "rollback_collecting" and empty["progress"]["minimum_rollback_control"] == 20, empty
    leaked = _verify(_aggregate(control=20, assigned_graph=1, selected_graph=1), exact=True)
    assert leaked["phase"] == "rollback_blocked" and "rollback_graph_traffic_detected" in leaked["blockers"], leaked
    ready = _verify(_aggregate(control=20), exact=True)
    assert ready["phase"] == "rollback_ready_for_finalize" and ready["decision"] == "GO", ready
    legacy = _verify(_aggregate(control=20), exact=True, evidence={"schema_version": 3, "decision": "GO"})
    assert legacy["phase"] == "legacy_evidence_requires_upgrade" and legacy["decision"] == "NO_GO", legacy
    final = _verify(_aggregate(control=20), exact=True, evidence={
        "schema_version": 4, "evidence_stage": "final", "decision": "GO",
        "evidence_sha256": "sha256:final", "candidate_evidence_sha256": "sha256:candidate",
        "cohort_fingerprint": rollback.cohort_fingerprint, "drills": {"rollback": "pass"},
    })
    assert final["phase"] == "rollback_verified" and final["v150_entry_ready"] is True, final
    assert final["v150_entry_decision"] == "GO" and final["v150_entry_blockers"] == [], final
    assert final["evidence"]["candidate_sha256"] == "sha256:candidate"
    assert final["evidence"]["final_sha256"] == "sha256:final"

    for field in ("session_id", "trace_id", "effect_id", "transition_id", "raw_response", "content"):
        try:
            _assert_pii_free({field: "forbidden"})
        except ValueError:
            pass
        else:
            raise AssertionError(f"privacy scan must reject {field}")
    print("autotutor_production_attestation_smoke=PASS")


if __name__ == "__main__":
    main()
