"""A Graph-only defect must be detected before one Legacy outcome is committed."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-comparator-sensitivity.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
os.environ["EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE"] = "legacy"
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "b" * 40
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "v1.49.2-sensitivity"
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from agents import autotutor_graph as graph  # noqa: E402
from agents.auto_tutor import _load_persisted_session, start_session  # noqa: E402
from db.engine import engine, get_connection  # noqa: E402
from db.schema import metadata  # noqa: E402


def main() -> None:
    metadata.create_all(engine)
    original = graph._active_apply_start

    def corrupt_start(state):
        result = original(state)
        result["draft"].replans += 1
        return result

    with patch.object(graph, "_active_apply_start", corrupt_start):
        corrupt_graph = graph.build_autotutor_active_graph()
    with patch.object(graph, "AUTOTUTOR_ACTIVE_GRAPH", corrupt_graph):
        result = start_session(
            "comparator-sensitivity-student",
            grade="八年级上册",
            focus_tags=["洋务运动目的"],
            actor_id="comparator-sensitivity-student",
            actor_role="student",
            account_status="active",
            traffic_cohort="verified",
            rollout_eligible=True,
            eligibility_reason="verified_runtime_actor",
            internal_force_graph=True,
            idempotency_key="comparator-sensitivity-start",
        )

    state = _load_persisted_session(result["session_id"])
    assert state is not None
    assert state.executor_assigned_mode == "graph_active"
    assert state.executor_mode == "legacy"
    assert str(state.executor_fallback_reason).startswith("active_comparator_mismatch")
    assert state.replans == 0
    with get_connection() as conn:
        duplicates = int(conn.execute(text("""SELECT COUNT(*) FROM (
            SELECT effect_key FROM learning_events WHERE session_id=:session_id
            AND effect_key IS NOT NULL GROUP BY effect_key HAVING COUNT(*) > 1
        ) duplicate_effects"""), {"session_id": state.session_id}).scalar() or 0)
        observation = conn.execute(text("""SELECT assigned_executor, selected_executor,
            comparator_matched, fallback_reason, commit_status, transition_id
            FROM agent_rollout_observations WHERE trace_id=:trace_id"""), {
            "trace_id": state.trace_id,
        }).mappings().one()
    assert duplicates == 0
    assert observation["assigned_executor"] == "graph_active"
    assert observation["selected_executor"] == "legacy"
    assert observation["comparator_matched"] == 0
    assert str(observation["fallback_reason"]).startswith("active_comparator_mismatch")
    assert observation["commit_status"] == "fallback"
    assert observation["transition_id"]
    print("autotutor_comparator_sensitivity_smoke=PASS")


if __name__ == "__main__":
    main()
