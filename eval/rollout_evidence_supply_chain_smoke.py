from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-rollout-evidence-supply-chain.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.evidence_store import load_release_evidence, save_release_evidence
from agent_runtime.rollout_observations import (
    aggregate_control_baseline,
    observation_write_health,
    record_rollout_observation,
    try_record_rollout_observation,
)
from db.engine import engine
from db.schema import metadata
from scripts.build_rollout_evidence import build_evidence, offline_profile, production_rag_profile, real_llm_profile

DEPLOYED_COMMIT = "v140-deployed-commit"
BASELINE_COMMIT = "v140-control-commit"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _real_llm_report() -> dict:
    return {
        "ok": True,
        "generated_at": _now(),
        "source_revision": {"commit_sha": DEPLOYED_COMMIT, "dirty": False},
        "eval_run": {"run_id": "eval_real_v140", "profile": "real_llm"},
        "llm_execution": {
            "status": "observed",
            "run_scoped_calls": 12,
            "provider": "bailian",
            "models": {"quality-model": 12},
        },
    }


def _offline_report() -> dict:
    return {
        "ok": True,
        "generated_at": _now(),
        "evaluation_profile": "core",
        "source_revision": {"commit_sha": DEPLOYED_COMMIT, "dirty": False},
        "eval_run": {"run_id": "eval_offline_v140", "profile": "offline"},
        "blocking_skipped_suites": [],
        "not_run_suites": [],
        "passed_suites": 85,
        "total_suites": 85,
    }


def _production_rag_report() -> dict:
    return {
        "ok": True,
        "generated_at": _now(),
        "source_revision": {"commit_sha": DEPLOYED_COMMIT, "dirty": False},
        "eval_run": {"run_id": "eval_rag_v140", "profile": "production_canary"},
        "suites": [{"name": "production_rag_health_smoke", "status": "passed"}],
    }


def main() -> None:
    metadata.create_all(engine)
    for index in range(100):
        record_rollout_observation(
            agent_type="history_character",
            config_version="v1.40-history-control",
            runtime_mode="control",
            deployed_commit=BASELINE_COMMIT,
            environment="staging",
            status="completed",
            latency_ms=900 + index,
            trace_id=f"trace_{index}",
            data_scope="runtime",
        )
    record_rollout_observation(
        agent_type="history_character",
        config_version="v1.40-history-control",
        runtime_mode="control",
        deployed_commit=BASELINE_COMMIT,
        environment="staging",
        status="idempotent_replay",
        latency_ms=1,
        trace_id="trace_replay",
        data_scope="runtime",
    )
    baseline = aggregate_control_baseline(
        agent_type="history_character",
        config_version="v1.40-history-control",
        deployed_commit=BASELINE_COMMIT,
        environment="staging",
        minimum_samples=100,
    )
    assert baseline["sample_count"] == 100
    assert baseline["p50_ms"] == 949.0
    assert baseline["p95_ms"] == 994.0

    assert offline_profile(_offline_report(), deployed_commit=DEPLOYED_COMMIT)["status"] == "pass"
    real_profile = real_llm_profile(_real_llm_report(), deployed_commit=DEPLOYED_COMMIT)
    rag_profile = production_rag_profile(_production_rag_report(), deployed_commit=DEPLOYED_COMMIT)
    assert real_profile["status"] == "pass"
    assert rag_profile["status"] == "pass"
    stale = _real_llm_report()
    stale["source_revision"]["commit_sha"] = "stale"
    assert real_llm_profile(stale, deployed_commit=DEPLOYED_COMMIT)["status"] == "fail"
    dirty = _real_llm_report()
    dirty["source_revision"]["dirty"] = True
    assert real_llm_profile(dirty, deployed_commit=DEPLOYED_COMMIT)["status"] == "fail"

    evidence = build_evidence(
        agent_type="history_character",
        config_version="v1.40-history-shadow",
        runtime_mode="shadow",
        deployed_commit=DEPLOYED_COMMIT,
        environment="staging",
        baseline_config_version="v1.40-history-control",
        baseline_commit=BASELINE_COMMIT,
        minimum_samples=100,
        offline_report=_offline_report(),
        real_llm_report=_real_llm_report(),
        production_rag_report=_production_rag_report(),
    )
    save_release_evidence(evidence)
    loaded = load_release_evidence(
        agent_type="history_character",
        config_version="v1.40-history-shadow",
        runtime_mode="shadow",
        deployed_commit=DEPLOYED_COMMIT,
        environment="staging",
    )
    assert loaded == evidence
    assert save_release_evidence(evidence) == evidence
    assert observation_write_health()["status"] == "ok"
    assert try_record_rollout_observation(
        agent_type="history_character",
        runtime_mode="invalid",
        status="failed",
        latency_ms=1,
        trace_id="trace_invalid",
        data_scope="runtime",
    ) is None
    degraded = observation_write_health()
    assert degraded["status"] == "degraded", degraded
    assert degraded["by_reason"]["provenance_invalid"] == 1
    print("rollout_evidence_supply_chain_smoke=PASS")


if __name__ == "__main__":
    main()
