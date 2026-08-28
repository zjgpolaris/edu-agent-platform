from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

db_path = Path(tempfile.gettempdir()) / "edu-agent-runtime-rollout-gate-smoke.sqlite3"
db_path.unlink(missing_ok=True)
os.environ["EDU_AGENT_DB_PATH"] = str(db_path)
os.environ["EDU_AGENT_DATA_SCOPE"] = "runtime"

from agent_runtime.event_store import ensure_runtime_tables
from agent_runtime.rollout_gate import build_rollout_readiness, seal_rollout_evidence
from db.engine import get_connection
from security.audit_log import record_audit_event

SCHEMA_READY = {"status": "ready", "schema_ready": True, "alembic_version": "011"}
DEPLOYED_COMMIT = "rollout-smoke-commit"


def _evidence(config_version: str, *, runtime_mode: str = "active", baseline_p95_ms: float = 1000) -> dict:
    return seal_rollout_evidence({
        "schema_version": 1,
        "agent_type": "history_character",
        "config_version": config_version,
        "runtime_mode": runtime_mode,
        "deployed_commit": DEPLOYED_COMMIT,
        "environment": "staging",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": {
            "offline": {"status": "pass", "commit": DEPLOYED_COMMIT},
            "real_llm": {"status": "pass", "commit": DEPLOYED_COMMIT},
            "production_rag": {"status": "pass", "commit": DEPLOYED_COMMIT},
        },
        "control_baseline": {
            "agent_type": "history_character",
            "commit": "control-commit",
            "config_version": "legacy-control",
            "environment": "staging",
            "sample_count": 150,
            "p50_ms": baseline_p95_ms * 0.7,
            "p95_ms": baseline_p95_ms,
            "source": "server_trace_aggregate",
        },
    })


def _insert_slice(
    config_version: str,
    *,
    terminal_count: int,
    pending_count: int = 0,
    duration_ms: int = 1000,
    terminal_events: bool = True,
    data_scope: str = "runtime",
) -> list[str]:
    now = datetime.now(timezone.utc)
    run_ids: list[str] = []
    with get_connection() as conn:
        for index in range(terminal_count + pending_count):
            run_id = f"run_{config_version}_{index}"
            run_ids.append(run_id)
            terminal = index < terminal_count
            created = now - timedelta(minutes=5, milliseconds=index)
            finished = created + timedelta(milliseconds=duration_ms) if terminal else None
            status = "completed" if terminal else "received"
            completion = {"status": "completed", "reason_codes": ["completion_criteria_satisfied"]} if terminal else None
            refs = {"runtime_mode": "active", "data_scope": data_scope, "rollout_bucket": index}
            conn.execute(text("""INSERT INTO agent_runs (
                run_id, agent_type, actor_id, student_id, session_id, parent_run_id,
                durability_mode, status, revision, current_step_id, objective,
                context_refs_json, input_artifact_refs_json, plan_json, state_json,
                completion_json, budget_json, used_budget_json, config_version,
                trace_id, idempotency_scope, idempotency_key, last_event_sequence,
                expires_at, created_at, updated_at, finished_at
            ) VALUES (
                :run_id, 'history_character', 'smoke-admin', NULL, NULL, NULL,
                'observable', :status, :revision, NULL, 'rollout smoke',
                :refs, '[]', NULL, '{}', :completion, '{}', '{}', :config_version,
                :trace_id, :scope, NULL, :last_sequence,
                NULL, :created_at, :updated_at, :finished_at
            )"""), {
                "run_id": run_id,
                "status": status,
                "revision": 1 if terminal else 0,
                "refs": json.dumps(refs),
                "completion": json.dumps(completion) if completion else None,
                "config_version": config_version,
                "trace_id": f"trace_{config_version}_{index}",
                "scope": f"actor:smoke-admin:{config_version}:{index}",
                "last_sequence": 2 if terminal and terminal_events else 1,
                "created_at": created.isoformat(),
                "updated_at": (finished or created).isoformat(),
                "finished_at": finished.isoformat() if finished else None,
            })
            conn.execute(text("""INSERT INTO agent_run_events (
                event_id, run_id, sequence, event_type, step_id, operation, status,
                public_payload_json, internal_metadata_json, data_scope, created_at
            ) VALUES (:event_id, :run_id, 1, 'run_started', NULL, NULL, 'received', '{}', '{}', :data_scope, :created_at)"""), {
                "event_id": f"evt_{config_version}_{index}_start",
                "run_id": run_id,
                "data_scope": data_scope,
                "created_at": created.isoformat(),
            })
            if terminal and terminal_events:
                conn.execute(text("""INSERT INTO agent_run_events (
                    event_id, run_id, sequence, event_type, step_id, operation, status,
                    public_payload_json, internal_metadata_json, data_scope, created_at
                ) VALUES (:event_id, :run_id, 2, 'run_completed', NULL, NULL, 'completed', '{}', '{}', :data_scope, :created_at)"""), {
                    "event_id": f"evt_{config_version}_{index}_terminal",
                    "run_id": run_id,
                    "data_scope": data_scope,
                    "created_at": finished.isoformat(),
                })
    return run_ids


def _gate(config_version: str, **kwargs) -> dict:
    return build_rollout_readiness(
        agent_type="history_character",
        config_version=config_version,
        runtime_mode="active",
        deployed_commit=DEPLOYED_COMMIT,
        environment="staging",
        evidence=kwargs.pop("evidence", _evidence(config_version)),
        schema_readiness=SCHEMA_READY,
        minimum_terminal_runs=100,
        **kwargs,
    )


def main() -> None:
    ensure_runtime_tables()
    # Ensure the audit table exists without adding a safety signal.
    assert record_audit_event(actor_id="smoke", action="rollout.smoke", data_scope="runtime")

    no_samples = _gate("no-samples")
    assert no_samples["status"] == "unknown"
    assert "terminal_samples_insufficient" in no_samples["reasons"]

    _insert_slice("insufficient", terminal_count=99)
    insufficient = _gate("insufficient")
    assert insufficient["status"] == "unknown"

    _insert_slice("coverage-warn", terminal_count=100, pending_count=7)
    coverage_warn = _gate("coverage-warn")
    assert coverage_warn["status"] == "warn", coverage_warn
    assert 0.93 < coverage_warn["event_coverage"] < 0.95

    _insert_slice("inconsistent", terminal_count=100, terminal_events=False)
    inconsistent = _gate("inconsistent")
    assert inconsistent["status"] == "fail"
    assert "terminal_consistency_below_100pct" in inconsistent["reasons"]

    safety_run_ids = _insert_slice("safety", terminal_count=100)
    for action in (
        "agent_runtime.duplicate_side_effect_prevented",
        "tool.idempotent_replay",
    ):
        assert record_audit_event(
            actor_id="smoke",
            action=action,
            resource_type="agent_run",
            resource_id=safety_run_ids[0],
            success=False,
            data_scope="runtime",
        )
    prevention = _gate("safety")
    assert prevention["status"] == "pass", prevention
    assert prevention["duplicate_side_effects"] == 0
    assert prevention["duplicate_attempts_prevented"] == 1
    assert prevention["idempotent_replays"] == 1

    for action in (
        "agent_runtime.duplicate_side_effect_executed",
        "agent_runtime.invalid_transition",
        "agent_runtime.high_risk_without_confirmation",
    ):
        assert record_audit_event(
            actor_id="smoke",
            action=action,
            resource_type="agent_run",
            resource_id=safety_run_ids[0],
            success=False,
            data_scope="runtime",
        )
    safety = _gate("safety")
    assert safety["status"] == "fail"
    assert safety["duplicate_side_effects"] == 1
    assert safety["invalid_transitions"] == 1
    assert safety["high_risk_without_confirmation"] == 1

    _insert_slice("pass", terminal_count=100)
    passed = _gate("pass")
    assert passed["status"] == "pass", passed
    assert passed["event_coverage"] == 1.0
    assert passed["terminal_consistency"] == 1.0
    assert passed["p95_regression"] == 0.0

    _insert_slice("eval-only", terminal_count=100, data_scope="eval")
    isolated = _gate("eval-only")
    assert isolated["run_count"] == 0
    assert isolated["status"] == "unknown"

    mismatched = _evidence("commit-mismatch")
    mismatched["deployed_commit"] = "different-commit"
    mismatched = seal_rollout_evidence(mismatched)
    commit_mismatch = _gate("commit-mismatch", evidence=mismatched)
    assert commit_mismatch["status"] == "unknown"
    assert "evidence_deployed_commit_mismatch" in commit_mismatch["reasons"]

    evidence_path = Path(tempfile.gettempdir()) / "edu-agent-rollout-smoke-evidence.json"
    evidence_path.write_text(json.dumps(_evidence("pass")), encoding="utf-8")
    os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "pass"
    os.environ["EDU_AGENT_RUNTIME_V2_SHADOW_MODE"] = "false"
    os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = DEPLOYED_COMMIT
    os.environ["EDU_AGENT_RUNTIME_ROLLOUT_EVIDENCE_PATH"] = str(evidence_path)
    from fastapi.testclient import TestClient
    from api.main import app

    response = TestClient(app).get(
        "/api/admin/agent-runtime/rollout-readiness",
        params={"agent_type": "history_character", "minimum_terminal_runs": 100},
    )
    assert response.status_code == 200, response.text
    api_payload = response.json()
    assert api_payload["agent_type"] == "history_character"
    assert api_payload["config_version"] == "pass"
    assert "objective" not in api_payload
    assert "completion_json" not in api_payload
    evidence_path.unlink(missing_ok=True)

    print("agent_runtime_rollout_gate_smoke=PASS")


if __name__ == "__main__":
    main()
