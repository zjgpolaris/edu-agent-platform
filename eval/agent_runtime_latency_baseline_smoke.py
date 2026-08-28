from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

db_path = Path(tempfile.gettempdir()) / "edu-agent-runtime-latency-baseline-smoke.sqlite3"
db_path.unlink(missing_ok=True)
os.environ["EDU_AGENT_DB_PATH"] = str(db_path)

from sqlalchemy import text

from agent_runtime.event_store import ensure_runtime_tables
from agent_runtime.rollout_gate import build_rollout_readiness, seal_rollout_evidence
from db.engine import get_connection
from security.audit_log import record_audit_event

COMMIT = "latency-smoke-commit"
SCHEMA_READY = {"schema_ready": True}


def _evidence(config: str, baseline_p95: float) -> dict:
    return seal_rollout_evidence({
        "schema_version": 1,
        "agent_type": "history_character",
        "config_version": config,
        "runtime_mode": "active",
        "deployed_commit": COMMIT,
        "profiles": {
            "real_llm": {"status": "pass", "commit": COMMIT},
            "production_rag": {"status": "pass", "commit": COMMIT},
        },
        "control_baseline": {
            "agent_type": "history_character",
            "commit": "control",
            "config_version": "legacy-control",
            "environment": "staging",
            "sample_count": 100,
            "p50_ms": baseline_p95,
            "p95_ms": baseline_p95,
            "source": "server_trace_aggregate",
        },
    })


def _insert(config: str, durations: list[int], *, invalid_timestamp: bool = False) -> None:
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    with get_connection() as conn:
        for index, duration in enumerate(durations):
            run_id = f"run_{config}_{index}"
            created = now + timedelta(milliseconds=index)
            finished = created + timedelta(milliseconds=duration)
            finished_value = "not-a-timestamp" if invalid_timestamp and index == len(durations) - 1 else finished.isoformat()
            conn.execute(text("""INSERT INTO agent_runs (
                run_id, agent_type, actor_id, student_id, session_id, parent_run_id,
                durability_mode, status, revision, current_step_id, objective,
                context_refs_json, input_artifact_refs_json, plan_json, state_json,
                completion_json, budget_json, used_budget_json, config_version,
                trace_id, idempotency_scope, idempotency_key, last_event_sequence,
                expires_at, created_at, updated_at, finished_at
            ) VALUES (
                :run_id, 'history_character', 'smoke', NULL, NULL, NULL,
                'observable', 'completed', 1, NULL, 'latency smoke',
                :refs, '[]', NULL, '{}', :completion, '{}', '{}', :config,
                :trace_id, :scope, NULL, 2, NULL, :created_at, :finished_at, :finished_at
            )"""), {
                "run_id": run_id,
                "refs": json.dumps({"runtime_mode": "active", "data_scope": "runtime"}),
                "completion": json.dumps({"status": "completed", "reason_codes": ["completion_criteria_satisfied"]}),
                "config": config,
                "trace_id": f"trace_{config}_{index}",
                "scope": f"actor:smoke:{config}:{index}",
                "created_at": created.isoformat(),
                "finished_at": finished_value,
            })
            for sequence, event_type, event_time in ((1, "run_started", created), (2, "run_completed", finished)):
                conn.execute(text("""INSERT INTO agent_run_events (
                    event_id, run_id, sequence, event_type, step_id, operation, status,
                    public_payload_json, internal_metadata_json, data_scope, created_at
                ) VALUES (:event_id, :run_id, :sequence, :event_type, NULL, NULL, 'completed', '{}', '{}', 'runtime', :created_at)"""), {
                    "event_id": f"evt_{config}_{index}_{sequence}",
                    "run_id": run_id,
                    "sequence": sequence,
                    "event_type": event_type,
                    "created_at": event_time.isoformat(),
                })


def _gate(config: str, baseline_p95: float, evidence: dict | None = None) -> dict:
    return build_rollout_readiness(
        agent_type="history_character",
        config_version=config,
        runtime_mode="active",
        deployed_commit=COMMIT,
        minimum_terminal_runs=100,
        evidence=evidence or _evidence(config, baseline_p95),
        schema_readiness=SCHEMA_READY,
    )


def main() -> None:
    ensure_runtime_tables()
    assert record_audit_event(actor_id="smoke", action="latency.smoke", data_scope="runtime")

    _insert("latency-pass", list(range(901, 1001)) + [1000], invalid_timestamp=True)
    passed = _gate("latency-pass", 1000)
    assert passed["status"] == "pass", passed
    assert passed["run_latency"]["sample_count"] == 100
    assert passed["run_latency"]["invalid_timestamp_count"] == 1
    assert passed["run_latency"]["p50_ms"] == 950
    assert passed["run_latency"]["p95_ms"] == 995
    assert passed["p95_regression"] == -0.005

    _insert("latency-warn", [1060] * 100)
    warned = _gate("latency-warn", 1000)
    assert warned["status"] == "warn"
    assert warned["p95_regression"] == 0.06

    _insert("latency-fail", [1101] * 100)
    failed = _gate("latency-fail", 1000)
    assert failed["status"] == "fail"
    assert "p95_regression_above_10pct" in failed["reasons"]

    bad_hash = _evidence("bad-hash", 1000)
    bad_hash["control_baseline"]["p95_ms"] = 999
    hash_result = _gate("bad-hash", 1000, evidence=bad_hash)
    assert hash_result["status"] == "unknown"
    assert "rollout_evidence_hash_mismatch" in hash_result["reasons"]
    assert "control_baseline_hash_mismatch" in hash_result["reasons"]

    print("agent_runtime_latency_baseline_smoke=PASS")


if __name__ == "__main__":
    main()
