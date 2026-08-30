from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "runtime-rollout-evidence.yml"
PREFLIGHT_WORKFLOW = ROOT / ".github" / "workflows" / "runtime-rollout-preflight.yml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_rollout_gate import validation_errors


def main() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    required_inputs = {
        "deployed_commit", "agent_type", "target_config_version", "runtime_mode",
        "baseline_config_version", "baseline_commit", "target_environment",
        "minimum_samples", "ready_url",
    }
    assert all(f"      {name}:" in raw for name in required_inputs)
    assert "  workflow_dispatch:" in raw
    assert "    environment: production" in raw
    assert "  cancel-in-progress: false" in raw
    assert 'test "$MINIMUM_SAMPLES" -ge 100' in raw
    assert 'test "$TARGET_ENVIRONMENT" = "production"' in raw
    assert "--require-clean-revision" in raw
    assert "--require-real-llm" in raw
    assert "production_rag_health_smoke" in raw
    assert "build_rollout_evidence.py" in raw and "--persist" in raw
    assert "--ready-require-runtime" in raw
    assert "validate_rollout_gate.py" in raw
    assert "include-output" not in raw
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in raw
    assert '--agent-type "${{ inputs.agent_type }}"' not in raw
    assert '--config-version "${{ inputs.target_config_version }}"' not in raw
    assert validation_errors({
        "status": "pass",
        "run_provenance_coverage": 1.0,
        "observation_write_failures": 0,
    }) == []
    assert validation_errors({"status": "pass"}) == [
        "rollout gate provenance coverage is not 100%",
        "rollout observation writes are unhealthy",
    ]
    preflight = PREFLIGHT_WORKFLOW.read_text(encoding="utf-8")
    for name in (
        "deployed_commit", "agent_type", "target_config_version", "baseline_config_version",
        "baseline_commit", "minimum_samples", "ready_url",
    ):
        assert f"      {name}:" in preflight
    assert "  workflow_dispatch:" in preflight
    assert "    environment: production" in preflight
    assert "permissions:\n  contents: read" in preflight
    assert 'test "$MINIMUM_SAMPLES" -ge 100' in preflight
    assert "validate_runtime_rollout_config.py" in preflight
    assert "agent-runtime/rollout-status" in preflight
    assert "EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED: 'false'" in preflight
    assert "EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS: '0'" in preflight
    assert "DATABASE_URL" not in preflight
    assert "DIRECT_URL" not in preflight
    assert "JWT_SECRET" not in preflight
    assert "secrets.API_TOKEN" not in preflight
    assert "RUNTIME_ADMIN_USERNAME: ${{ secrets.RUNTIME_ADMIN_USERNAME }}" in preflight
    assert "RUNTIME_ADMIN_PASSWORD: ${{ secrets.RUNTIME_ADMIN_PASSWORD }}" in preflight
    assert "/api/auth/login" in preflight
    assert 'p.get("role")=="admin"' in preflight
    assert "::add-mask::$API_TOKEN" in preflight
    print("runtime_evidence_workflow_smoke=PASS")


if __name__ == "__main__":
    main()
