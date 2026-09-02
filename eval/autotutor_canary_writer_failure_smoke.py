"""Observation writer failure is non-fatal and blocks the exact production slice."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-writer-failure.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, str(ROOT / "backend"))

from agent_runtime import rollout_observations  # noqa: E402
from db.engine import engine  # noqa: E402
from db.schema import metadata  # noqa: E402

COMMIT = "a" * 40
CONFIG = "v1.49.3-writer-failure-smoke"


def main() -> None:
    metadata.create_all(engine)
    rollout_observations._last_failure_audit.clear()
    committed_student_response = {"status": "committed", "next_action": "continue"}
    with patch.object(
        rollout_observations,
        "record_rollout_observation",
        side_effect=RuntimeError("forced writer failure"),
    ):
        result = rollout_observations.try_record_rollout_observation(
            agent_type="auto_tutor",
            runtime_mode="active_canary",
            status="completed",
            latency_ms=10,
            trace_id="writer-failure-trace",
            data_scope="runtime",
            config_version=CONFIG,
            deployed_commit=COMMIT,
            environment="production",
        )
    assert result is None
    assert committed_student_response == {"status": "committed", "next_action": "continue"}
    health = rollout_observations.observation_write_health(
        config_version=CONFIG,
        deployed_commit=COMMIT,
        environment="production",
    )
    assert health["status"] == "degraded", health
    assert health["ok"] is False
    assert health["by_reason"] == {"database_error": 1}
    print("autotutor_canary_writer_failure_smoke=PASS")


if __name__ == "__main__":
    main()
