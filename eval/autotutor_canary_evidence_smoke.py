"""AutoTutor canary evidence is exact-slice, immutable, hash-bound and PII-free."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from scripts.build_autotutor_canary_evidence import (  # noqa: E402
    _snapshot_hash,
    build_autotutor_canary_evidence,
    build_autotutor_final_evidence,
)

COMMIT = "f" * 40
CONFIG = "v1.49.5-evidence-smoke"
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
        "traffic_sources": {
            "organic": {"control": 0, "graph": 40, "committed_graph": 40},
            "release_verification": {"control": 0, "graph": 60, "committed_graph": 60},
            "total": {"control": 0, "graph": 100, "committed_graph": 100},
        },
        "comparator_match_rate": 1.0, "fallback_rate": 0.0,
        "observation_write_health": {"status": "ok", "ok": True, "failure_count": 0},
    }


def main() -> None:
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('017')"))
    configuration = {
        "config_version": CONFIG, "mode": "active_canary", "active_bps": 100,
        "cohort_fingerprint": "sha256:" + "1" * 64,
        "runtime_state_fingerprint": "sha256:" + "2" * 64,
    }
    canary_snapshot = {
        "schema_version": 1, "agent_type": "auto_tutor", "snapshot_kind": "canary",
        "slice": _aggregate()["slice"],
        "deployment": {"deployed_commit": COMMIT, "environment": "production", "schema_revision": "017"},
        "configuration": configuration, "schema": {"revision": "017"},
        "aggregate": _aggregate(), "status": "READY", "decision": "GO", "blockers": [],
    }
    canary_payload = {"snapshot": canary_snapshot, "snapshot_sha256": _snapshot_hash(canary_snapshot)}
    evidence = build_autotutor_canary_evidence(
        deployed_commit=COMMIT, config_version=CONFIG, environment="production",
        window_start=START, window_end=END,
        drills={"restart": "pass", "writer_failure": "pass", "kill_switch": "pass"},
        snapshot_payload=canary_payload,
        drill_artifact={
            "attestation_type": "environment_approved_operator", "deployed_commit": COMMIT,
            "config_version": CONFIG, "environment": "production", "window": {"start": START, "end": END},
            "results": {"restart": "pass", "writer_failure": "pass", "kill_switch": "pass"},
        },
    )
    assert evidence["decision"] == "CANDIDATE_GO" and evidence["evidence_stage"] == "candidate"
    assert not any(field in json.dumps(evidence) for field in ("student_id", "session_id", "raw_answer", "question_text"))
    saved_candidate = save_release_evidence(evidence)
    assert load_release_evidence(evidence_sha256=evidence["evidence_sha256"]) == saved_candidate

    rollback_snapshot = {
        "schema_version": 1, "agent_type": "auto_tutor", "snapshot_kind": "rollback",
        "deployment": {"deployed_commit": COMMIT, "environment": "production", "schema_revision": "017"},
        "configuration": {**configuration, "mode": "legacy", "active_bps": 0,
                          "runtime_state_fingerprint": "sha256:" + "3" * 64},
        "rollback": {"assigned_control_count": 20, "assigned_graph_count": 0,
                     "selected_graph_count": 0, "minimum_control": 20},
        "aggregate": {"traffic_sources": {
            "organic": {"control": 5, "graph": 0, "committed_graph": 0},
            "release_verification": {"control": 15, "graph": 0, "committed_graph": 0},
            "total": {"control": 20, "graph": 0, "committed_graph": 0},
        }},
        "phase": "rollback_ready_for_finalize", "status": "READY", "decision": "GO", "blockers": [],
    }
    rollback_payload = {"snapshot": rollback_snapshot, "snapshot_sha256": _snapshot_hash(rollback_snapshot)}
    final = build_autotutor_final_evidence(candidate=evidence, rollback_snapshot_payload=rollback_payload)
    assert final["decision"] == "GO" and final["evidence_stage"] == "final"
    assert final["aggregate"]["traffic_sources"]["release_verification"]["committed_graph"] == 60
    assert final["rollback_snapshot"]["aggregate"]["traffic_sources"]["release_verification"]["control"] == 15
    saved = save_release_evidence(final)
    loaded = load_release_evidence(evidence_sha256=final["evidence_sha256"])
    assert loaded == saved == final
    assert build_autotutor_final_evidence(candidate=final, rollback_snapshot_payload=rollback_payload) == final

    empty_rollback = json.loads(json.dumps(rollback_snapshot))
    empty_rollback["rollback"]["assigned_control_count"] = 0
    empty_payload = {"snapshot": empty_rollback, "snapshot_sha256": _snapshot_hash(empty_rollback)}
    try:
        build_autotutor_final_evidence(candidate=evidence, rollback_snapshot_payload=empty_payload)
    except ValueError:
        pass
    else:
        raise AssertionError("zero-traffic rollback must not finalize evidence")

    not_ready = _aggregate()
    not_ready.update({"status": "NOT_READY", "decision": "NO_GO", "blockers": []})
    incomplete_snapshot = dict(canary_snapshot)
    incomplete_snapshot["aggregate"] = not_ready
    incomplete_payload = {"snapshot": incomplete_snapshot, "snapshot_sha256": _snapshot_hash(incomplete_snapshot)}
    incomplete_drills = build_autotutor_canary_evidence(
        deployed_commit=COMMIT, config_version=CONFIG, environment="production",
        window_start=START, window_end=END, snapshot_payload=incomplete_payload,
    )
    assert incomplete_drills["decision"] == "NO_GO"
    assert "production_rehearsals_incomplete" in incomplete_drills["blockers"]

    incomplete = json.loads(json.dumps(final))
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
            "digest": final["evidence_sha256"],
        })
    assert load_release_evidence(evidence_sha256=final["evidence_sha256"]) is None
    print("autotutor_canary_evidence_smoke=PASS")


if __name__ == "__main__":
    main()
