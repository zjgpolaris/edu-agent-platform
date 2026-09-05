"""AutoTutor canary aggregation is exact-slice, assignment-aware and fail-closed."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-canary-aggregation.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "a" * 40
os.environ["EDU_AGENT_ENVIRONMENT"] = "staging"
os.environ["EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION"] = "v1.49.3-smoke"
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime.rollout_observations import (  # noqa: E402
    aggregate_autotutor_transition_canary,
    record_rollout_observation,
)
from db.schema import metadata  # noqa: E402
from db.engine import engine  # noqa: E402
from agent_runtime.rollout_status import build_rollout_status  # noqa: E402
from sqlalchemy import text  # noqa: E402

CONFIG = "v1.49.3-smoke"
COMMIT = "a" * 40
ENVIRONMENT = "staging"


def _record(index: int, *, matched: bool | None = True, assigned: str = "graph_active", selected: str = "graph_active", cohort: str = "verified") -> None:
    kind = ("start", "lesson_answer", "exit_ticket_answer")[index % 3]
    record_rollout_observation(
        agent_type="auto_tutor", runtime_mode="active" if assigned == "graph_active" else "control", status=f"committed:{kind}",
        latency_ms=20 + (index % 10), trace_id=f"trace-{assigned}-{index}", data_scope="runtime",
        config_version=CONFIG, deployed_commit=COMMIT, environment=ENVIRONMENT,
        traffic_cohort=cohort, rollout_eligible=cohort == "verified",
        eligibility_reason="verified_runtime_actor" if cohort == "verified" else "unverified_actor",
        assigned_executor=assigned, selected_executor=selected, transition_kind=kind,
        transition_id=f"transition-{assigned}-{index}", observation_schema_version="v1.49.2-observation",
        outcome_schema_version="v1.49.2-outcome", commit_status="committed",
        assignment_reason="graph_bucket_selected" if assigned == "graph_active" else "bucket_not_selected",
        admission_status="admitted", admission_reason=None, admission_checked_at=datetime.now(timezone.utc).isoformat(),
        comparator_matched=matched, fallback_reason=None if selected == "graph_active" else "active_comparator_mismatch",
        provider_latency_ms=2, executor_latency_ms=8, comparator_latency_ms=7,
        observation_external_calls=1, effect_intent_count=1,
    )


def _aggregate() -> dict:
    return aggregate_autotutor_transition_canary(
        config_version=CONFIG, deployed_commit=COMMIT, environment=ENVIRONMENT,
        since=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        minimum_graph_transitions=100,
    )


def main() -> None:
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('017')"))
    for index in range(100):
        _record(index)
        _record(index, matched=None, assigned="legacy", selected="legacy")
    passing = _aggregate()
    assert passing["decision"] == "GO", passing
    assert passing["assigned_graph_count"] == 100
    assert passing["committed_graph_count"] == 100
    assert passing["assigned_control_count"] == 100
    assert passing["transition_kind_coverage"] == ["exit_ticket_answer", "lesson_answer", "start"]
    assert passing["comparator_match_rate"] == 1.0
    assert passing["fallback_rate"] == 0.0
    # Production collects control first and Graph later. A Graph-only window
    # loses the baseline; the combined exact window must retain both phases.
    now = datetime.now(timezone.utc)
    control_at = (now - timedelta(hours=1)).isoformat()
    with engine.begin() as conn:
        conn.execute(text("UPDATE agent_rollout_observations SET created_at=:created_at WHERE assigned_executor='legacy'"),
                     {"created_at": control_at})
    assert "control_baseline_missing" in _aggregate()["blockers"]
    combined = aggregate_autotutor_transition_canary(
        config_version=CONFIG, deployed_commit=COMMIT, environment=ENVIRONMENT,
        since=(now - timedelta(hours=2)).isoformat(), until=(now + timedelta(seconds=1)).isoformat(),
    )
    assert combined["decision"] == "GO" and combined["assigned_control_count"] == 100, combined
    wrong_commit = aggregate_autotutor_transition_canary(
        config_version=CONFIG, deployed_commit="b" * 40, environment=ENVIRONMENT,
        since=(now - timedelta(hours=2)).isoformat(), until=(now + timedelta(seconds=1)).isoformat(),
    )
    assert wrong_commit["assigned_control_count"] == 0 and wrong_commit["committed_graph_count"] == 0
    with engine.begin() as conn:
        conn.execute(text("UPDATE agent_rollout_observations SET created_at=:created_at WHERE assigned_executor='legacy'"),
                     {"created_at": now.isoformat()})
    readiness = build_rollout_status(agent_type="auto_tutor", minimum_samples=100)
    assert readiness["status"] == "GO", readiness
    assert readiness["autotutor_transition_canary"]["assigned_graph_count"] == 100
    from fastapi.testclient import TestClient
    from api.main import app

    response = TestClient(app).get(
        "/api/admin/agent-runtime/rollout-status",
        params={"agent_type": "auto_tutor", "minimum_samples": 100},
    )
    assert response.status_code == 200, response.text
    assert response.json()["autotutor_transition_canary"]["committed_graph_count"] == 100
    from agent_ops import build_agent_ops_summary

    agent_ops = build_agent_ops_summary(scope="runtime", window_hours=1, minimum_runtime_events=1)
    assert agent_ops["runtime_v2"]["autotutor_transition_canary"]["committed_graph_count"] == 100

    _record(100, matched=None)
    unknown = _aggregate()
    assert unknown["comparator_unknown_count"] == 1
    assert unknown["comparator_match_rate"] == round(100 / 101, 6)
    assert "comparator_not_exact" in unknown["blockers"]

    _record(101, matched=False, selected="legacy")
    failing = _aggregate()
    assert failing["decision"] == "NO_GO"
    assert "comparator_not_exact" in failing["blockers"]
    assert failing["assigned_graph_count"] == 102

    _record(102, cohort="unverified")
    unauthorized = _aggregate()
    assert "unauthorized_graph_traffic" in unauthorized["blockers"]
    assert unauthorized["unauthorized_graph_count"] == 1
    print("autotutor_canary_aggregation_smoke=PASS")


if __name__ == "__main__":
    main()
