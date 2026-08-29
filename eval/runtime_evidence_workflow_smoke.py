from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "runtime-rollout-evidence.yml"
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
    print("runtime_evidence_workflow_smoke=PASS")


if __name__ == "__main__":
    main()
