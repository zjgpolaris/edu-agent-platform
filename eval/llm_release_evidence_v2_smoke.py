from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timezone

from llm_capability_test_support import TEST_COMMIT, TEST_CONFIG, TEST_ENVIRONMENT, TEST_IMAGE, configure_provenance

configure_provenance()
os.environ["EDU_AGENT_REQUIRE_LLM_EVIDENCE_V2"] = "true"

from agent_runtime.rollout_gate import _evidence_reasons, seal_rollout_evidence  # noqa: E402


def _baseline() -> dict:
    return {
        "agent_type": "history_character",
        "config_version": "v1.44-control",
        "commit": "control-commit",
        "environment": TEST_ENVIRONMENT,
        "source": "server_trace_aggregate",
        "trust_contract": "verified-cohort-v1",
        "sample_count": 100,
        "p95_ms": 900.0,
    }


def _profiles() -> dict:
    common = {"status": "pass", "commit": TEST_COMMIT}
    return {
        "offline": dict(common),
        "real_llm_business_eval": dict(common),
        "production_rag": dict(common),
        "llm_capabilities": {
            **common,
            "image_digest": TEST_IMAGE,
            "runtime_config_version": TEST_CONFIG,
            "environment": TEST_ENVIRONMENT,
            "manifest_sha256": "sha256:" + "b" * 64,
        },
    }


def _reasons(evidence: dict) -> list[str]:
    reasons, _baseline_result, _profiles_result = _evidence_reasons(
        evidence,
        agent_type="history_character",
        config_version=TEST_CONFIG,
        runtime_mode="shadow",
        deployed_commit=TEST_COMMIT,
        environment=TEST_ENVIRONMENT,
        minimum_terminal_runs=100,
    )
    return reasons


def main() -> None:
    evidence = seal_rollout_evidence({
        "schema_version": 2,
        "agent_type": "history_character",
        "config_version": TEST_CONFIG,
        "runtime_mode": "shadow",
        "deployed_commit": TEST_COMMIT,
        "image_digest": TEST_IMAGE,
        "environment": TEST_ENVIRONMENT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": _profiles(),
        "control_baseline": _baseline(),
    })
    assert _reasons(evidence) == []

    tampered = deepcopy(evidence)
    tampered["image_digest"] = "sha256:" + "c" * 64
    assert "rollout_evidence_hash_mismatch" in _reasons(tampered)
    assert "evidence_image_digest_mismatch" in _reasons(tampered)

    legacy = deepcopy(evidence)
    legacy["schema_version"] = 1
    legacy["profiles"] = {
        "offline": {"status": "pass", "commit": TEST_COMMIT},
        "real_llm": {"status": "pass", "commit": TEST_COMMIT},
        "production_rag": {"status": "pass", "commit": TEST_COMMIT},
    }
    legacy = seal_rollout_evidence(legacy)
    assert "rollout_evidence_schema_v2_required" in _reasons(legacy)
    print("llm_release_evidence_v2_smoke=PASS")


if __name__ == "__main__":
    main()
