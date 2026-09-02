"""AutoTutor canary evidence is exact-slice, immutable, hash-bound and PII-free."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-canary-evidence.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from agent_runtime.evidence_store import load_release_evidence, save_release_evidence  # noqa: E402
from db.engine import engine, get_connection  # noqa: E402
from db.schema import metadata  # noqa: E402
from scripts.build_autotutor_canary_evidence import build_autotutor_canary_evidence  # noqa: E402

COMMIT = "f" * 40
CONFIG = "v1.49.4-evidence-smoke"
START = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
END = datetime.now(timezone.utc).isoformat()


def _aggregate() -> dict:
    return {
        "status": "GO", "decision": "GO", "blockers": [],
        "slice": {
            "agent_type": "auto_tutor", "deployed_commit": COMMIT,
            "config_version": CONFIG, "environment": "production",
            "data_scope": "runtime", "traffic_cohort": "verified",
            "since": START, "until": END,
        },
        "assigned_graph_count": 100, "committed_graph_count": 100,
        "comparator_match_rate": 1.0, "fallback_rate": 0.0,
        "observation_write_health": {"status": "ok", "ok": True, "failure_count": 0},
    }


def main() -> None:
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('016')"))
    schema = {"status": "ready", "schema_ready": True, "alembic_version": "016"}
    with patch("scripts.build_autotutor_canary_evidence.runtime_schema_readiness", return_value=schema), \
         patch("scripts.build_autotutor_canary_evidence.aggregate_autotutor_transition_canary", return_value=_aggregate()):
        evidence = build_autotutor_canary_evidence(
            deployed_commit=COMMIT, config_version=CONFIG, environment="production",
            window_start=START, window_end=END,
            drills={"restart": "pass", "writer_failure": "pass", "kill_switch": "pass", "rollback": "pass"},
        )
    assert evidence["decision"] == "GO" and evidence["evidence_sha256"]
    assert not any(field in json.dumps(evidence) for field in ("student_id", "session_id", "raw_answer", "question_text"))
    saved = save_release_evidence(evidence)
    loaded = load_release_evidence(evidence_sha256=evidence["evidence_sha256"])
    assert loaded == saved == evidence

    not_ready = _aggregate()
    not_ready.update({"status": "NOT_READY", "decision": "NO_GO", "blockers": []})
    with patch("scripts.build_autotutor_canary_evidence.runtime_schema_readiness", return_value=schema), \
         patch("scripts.build_autotutor_canary_evidence.aggregate_autotutor_transition_canary", return_value=not_ready):
        incomplete_drills = build_autotutor_canary_evidence(
            deployed_commit=COMMIT, config_version=CONFIG, environment="production",
            window_start=START, window_end=END,
        )
    assert incomplete_drills["decision"] == "NO_GO"
    assert "production_rehearsals_incomplete" in incomplete_drills["blockers"]

    incomplete = json.loads(json.dumps(evidence))
    incomplete["drills"]["kill_switch"] = "not_run"
    from agent_runtime.rollout_gate import seal_rollout_evidence
    incomplete = seal_rollout_evidence(incomplete)
    try:
        save_release_evidence(incomplete)
    except ValueError:
        pass
    else:
        raise AssertionError("GO evidence must reject incomplete rehearsals")

    with get_connection() as conn:
        conn.execute(text("UPDATE agent_release_evidence SET payload_json='{}' WHERE evidence_sha256=:digest"), {
            "digest": evidence["evidence_sha256"],
        })
    assert load_release_evidence(evidence_sha256=evidence["evidence_sha256"]) is None
    print("autotutor_canary_evidence_smoke=PASS")


if __name__ == "__main__":
    main()
