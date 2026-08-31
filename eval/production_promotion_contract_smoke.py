from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_image_promotion import promotion_errors

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64


def _evidence(environment: str, age_hours: int = 1) -> dict:
    payload = {
        "schema_version": 2,
        "config_version": "v1.45-history-canary",
        "deployed_commit": COMMIT,
        "image_digest": DIGEST,
        "environment": environment,
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat(),
        "profiles": {name: {"status": "pass"} for name in (
            "offline", "real_llm_business_eval", "production_rag", "llm_capabilities"
        )},
    }
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def main() -> None:
    gate = {
        "status": "pass", "terminal_runs": 100, "run_provenance_coverage": 1.0, "observation_write_failures": 0,
        "deployed_commit": COMMIT, "environment": "staging", "config_version": "v1.45-history-canary",
    }
    assert not promotion_errors(_evidence("staging"), gate, commit=COMMIT, digest=DIGEST, environment="staging")
    production_gate = dict(gate, environment="production")
    assert "evidence_observation_window_too_short" in promotion_errors(
        _evidence("production", 1), production_gate, commit=COMMIT, digest=DIGEST, environment="production", minimum_age_hours=48
    )
    assert not promotion_errors(
        _evidence("production", 49), production_gate, commit=COMMIT, digest=DIGEST, environment="production", minimum_age_hours=48
    )
    weak_gate = dict(gate, terminal_runs=99)
    assert "rollout_gate_minimum_100_not_passed" in promotion_errors(
        _evidence("staging"), weak_gate, commit=COMMIT, digest=DIGEST, environment="staging"
    )
    print("production promotion contract smoke passed")


if __name__ == "__main__":
    main()
