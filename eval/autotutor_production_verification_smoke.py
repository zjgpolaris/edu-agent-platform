"""AutoTutor production verification is exact, fail-closed and PII-free."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime.autotutor_canary_verification import (  # noqa: E402
    _summarize_content_blocks,
    build_autotutor_canary_snapshot,
    build_autotutor_canary_verification,
    validate_autotutor_canary_snapshot,
)

COMMIT = "c" * 40
CONFIG = "v1.49.5-production-attestation"
NOW = datetime.now(timezone.utc)
START = (NOW - timedelta(hours=1)).isoformat()
END = NOW.isoformat()


def _aggregate(*, control: int = 100, graph: int = 0, status: str = "NOT_READY", blockers: list[str] | None = None) -> dict:
    return {
        "status": status, "decision": "GO" if status == "GO" else "NO_GO", "blockers": blockers or [],
        "slice": {"agent_type": "auto_tutor", "config_version": CONFIG, "deployed_commit": COMMIT,
                  "environment": "production", "data_scope": "runtime", "traffic_cohort": "verified",
                  "since": START, "until": END},
        "assigned_control_count": control, "assigned_graph_count": graph,
        "committed_graph_count": graph,
    }


def _env(mode: str = "legacy", bps: str = "0") -> dict[str, str]:
    return {
        **os.environ,
        "EDU_AGENT_ENVIRONMENT": "production",
        "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": mode,
        "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": bps,
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": CONFIG,
        "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": "secret-test-salt",
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "false",
    }


def _build(aggregate: dict, **kwargs: object) -> dict:
    with patch.dict(os.environ, _env(), clear=True), \
         patch("agent_runtime.autotutor_canary_verification.runtime_schema_readiness", return_value={"schema_ready": True, "alembic_version": "017"}), \
         patch("agent_runtime.autotutor_canary_verification.trusted_rollout_cohort_status", return_value={"ready": True, "verified_actor_count": 2}), \
         patch("agent_runtime.autotutor_canary_verification.observation_write_health", return_value={"status": "ok", "ok": True, "failure_count": 0}), \
         patch("agent_runtime.autotutor_canary_verification.aggregate_autotutor_transition_canary", return_value=aggregate), \
         patch("agent_runtime.autotutor_canary_verification.load_release_evidence", return_value=None), \
         patch("agent_runtime.autotutor_canary_verification._content_block_diagnostics", return_value={"status": "available", "total": 0, "latest_reason": None, "latest_at": None, "by_reason": {}}), \
         patch("agent_runtime.autotutor_canary_verification._admission", return_value={"status": "admitted", "reason_codes": []}):
        return build_autotutor_canary_verification(expected_commit=COMMIT, expected_config_version=CONFIG, **kwargs)


def main() -> None:
    content_diagnostics = _summarize_content_blocks([
        {
            "student_id": "must-not-escape",
            "session_id": "must-not-escape",
            "created_at": "2026-09-03T08:24:00+00:00",
            "metadata": {"traffic_source": "release_verification", "reason": "assessment_not_independent"},
        },
        {
            "created_at": "2026-09-03T08:20:00+00:00",
            "metadata": {"traffic_source": "organic", "reason": "private-organic-reason"},
        },
    ])
    assert content_diagnostics == {
        "status": "available",
        "total": 1,
        "latest_reason": "assessment_not_independent",
        "latest_at": "2026-09-03T08:24:00+00:00",
        "by_reason": {"assessment_not_independent": 1},
    }
    assert "must-not-escape" not in json.dumps(content_diagnostics)

    ready = _build(_aggregate())
    assert ready["phase"] == "ready_for_manual_one_percent" and ready["decision"] == "GO", ready
    encoded = json.dumps(ready)
    assert "secret-test-salt" not in encoded and "bucket_salt" not in encoded
    assert ready["configuration"]["config_fingerprint"].startswith("sha256:")

    collecting = _build(_aggregate(control=100, graph=1, blockers=["insufficient_graph_samples", "transition_kind_coverage_incomplete"]))
    assert collecting["phase"] == "ready_for_manual_one_percent", collecting
    with patch.dict(os.environ, _env("active_canary", "100"), clear=True), \
         patch("agent_runtime.autotutor_canary_verification.runtime_schema_readiness", return_value={"schema_ready": True, "alembic_version": "017"}), \
         patch("agent_runtime.autotutor_canary_verification.trusted_rollout_cohort_status", return_value={"ready": True, "verified_actor_count": 2}), \
         patch("agent_runtime.autotutor_canary_verification.observation_write_health", return_value={"status": "ok", "ok": True}), \
         patch("agent_runtime.autotutor_canary_verification.aggregate_autotutor_transition_canary", return_value=_aggregate(graph=1, blockers=["insufficient_graph_samples", "transition_kind_coverage_incomplete"])), \
         patch("agent_runtime.autotutor_canary_verification.load_release_evidence", return_value=None), \
         patch("agent_runtime.autotutor_canary_verification._content_block_diagnostics", return_value={"status": "available", "total": 0, "latest_reason": None, "latest_at": None, "by_reason": {}}), \
         patch("agent_runtime.autotutor_canary_verification._admission", return_value={"status": "admitted", "reason_codes": []}):
        active = build_autotutor_canary_verification(expected_commit=COMMIT, expected_config_version=CONFIG, minimum_graph=1)
    assert active["progress"]["minimum_graph"] == 100
    assert active["phase"] == "canary_collecting" and active["status"] == "NOT_READY", active

    with patch("agent_runtime.autotutor_canary_verification.build_autotutor_canary_verification", return_value={
        **ready, "generated_at": END, "aggregate": _aggregate(status="GO"),
    }):
        snapshot = build_autotutor_canary_snapshot(window_start=START, window_end=END)
    validate_autotutor_canary_snapshot(snapshot)
    tampered = json.loads(json.dumps(snapshot))
    tampered["snapshot"]["decision"] = "NO_GO"
    try:
        validate_autotutor_canary_snapshot(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered snapshot must be rejected")
    print("autotutor_production_verification_smoke=PASS")


if __name__ == "__main__":
    main()
