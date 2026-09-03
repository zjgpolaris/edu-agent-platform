"""Canary aggregation discloses organic and release-verification samples separately."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-canary-source-aggregation.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime.rollout_observations import aggregate_autotutor_transition_canary, record_rollout_observation  # noqa: E402
from db.engine import engine  # noqa: E402
from db.schema import metadata  # noqa: E402
from services.weekly_summary_service import _collect_metrics  # noqa: E402
from student_profile import LearningEvent, record_learning_event  # noqa: E402

COMMIT = "d" * 40
CONFIG = "v1.49.9-production-canary"


def _record(index: int, source: str, *, graph: bool = True) -> None:
    executor = "graph_active" if graph else "legacy"
    record_rollout_observation(
        agent_type="auto_tutor", runtime_mode="active", status="committed", latency_ms=10,
        trace_id=f"trace-{index}", data_scope="runtime", config_version=CONFIG,
        deployed_commit=COMMIT, environment="staging", traffic_cohort="verified",
        rollout_eligible=True, eligibility_reason="verified_runtime_actor",
        assigned_executor=executor, selected_executor=executor,
        transition_kind=("start", "lesson_answer", "exit_ticket_answer")[index % 3],
        transition_id=f"transition-{index}", observation_schema_version="v1.49.2-observation",
        outcome_schema_version="v1.49.2-outcome", commit_status="committed",
        assignment_reason="graph_bucket_selected" if graph else "bucket_not_selected", admission_status="admitted",
        admission_checked_at=datetime.now(timezone.utc).isoformat(), comparator_matched=True if graph else None,
        observation_external_calls=1, effect_intent_count=1, traffic_source=source,
        verification_run_id=f"avr_source_{index:04d}" if source == "release_verification" else None,
    )


def main() -> None:
    metadata.create_all(engine)
    for index in range(100):
        _record(index, "organic" if index < 40 else "release_verification")
    for index in range(100, 110):
        _record(index, "organic", graph=False)
    result = aggregate_autotutor_transition_canary(
        config_version=CONFIG, deployed_commit=COMMIT, environment="staging",
        since=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        minimum_graph_transitions=100,
    )
    assert result["decision"] == "GO", result
    assert result["traffic_sources"]["organic"]["graph"] == 40
    assert result["traffic_sources"]["release_verification"]["committed_graph"] == 60
    assert result["traffic_sources"]["total"]["graph"] == 100
    record_learning_event(LearningEvent(
        student_id="verification-report-student", feature="auto_tutor",
        event_type="session_complete", metadata={"traffic_source": "release_verification"},
    ))
    metrics = _collect_metrics("verification-report-student", date.today())
    assert metrics["active_days"] == 0 and metrics["autotutor_sessions"] == 0
    print("autotutor_canary_source_aggregation_smoke=PASS")


if __name__ == "__main__":
    main()
