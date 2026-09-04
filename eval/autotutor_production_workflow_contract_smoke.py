"""The production workflow is manual, immutable, bounded and secret-safe."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = (ROOT / ".github" / "workflows" / "autotutor-production-verification.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source and "schedule:" not in source and "push:" not in source
    assert "permissions:\n  contents: read\n  actions: read" in source
    assert "environment: production-verification" in source and "timeout-minutes: 60" in source
    assert "traffic_timeout_seconds:" in source and "default: '3300'" in source
    assert '--timeout-seconds "$TRAFFIC_TIMEOUT_SECONDS"' in source
    assert "default: v1.49.9-production-canary" in source
    assert "git merge-base --is-ancestor" in source
    assert "--persist-url" in source and "--require-go" in source
    assert "group: autotutor-production-verification" in source and "cancel-in-progress: false" in source
    assert "--stage candidate" in source and "--stage final" in source
    assert "retention-days: 90" in source and "continue-on-error: true" in source
    assert "Verify immutable CI provenance" in source and "ci.yml/runs" in source
    assert "Build blocked CI receipt" in source and "ci_blocked" in source
    assert "if: steps.ci.outputs.verified == 'true'" in source
    assert "--wait-for-deployment" in source and "--deployment-timeout-seconds 300" in source
    assert "--ci-receipt-path" in source and "--output-receipt" in source
    assert "vars.AUTOTUTOR_PRODUCTION_API_BASE" in source
    assert "vars.AUTOTUTOR_PRODUCTION_ALLOWED_HOSTS" in source
    assert "secrets.AUTOTUTOR_PRODUCTION_API_TOKEN" in source
    assert "vars.AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256" in source
    assert "X-AutoTutor-Bootstrap-SHA256" in source
    assert "secrets.AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256" not in source
    assert '"schema_version":2' in source
    assert "secrets.AUTOTUTOR_PRODUCTION_API_BASE" not in source
    assert "autotutor-receipt.json" in source and "GITHUB_STEP_SUMMARY" in source
    assert "Bind produced evidence to workflow receipt" in source and "attach_evidence_to_receipt" in source
    for forbidden in ("deployments: write", "contents: write", "secrets: write"):
        assert forbidden not in source
    assert "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS" not in source
    assert "run_autotutor_canary_verification_traffic.py" in source
    assert "AUTOTUTOR_VERIFICATION_STUDENT_CREDENTIALS_JSON" in source
    assert "AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET" in source
    traffic_step = source.split("- name: Generate controlled AutoTutor traffic", 1)[1].split(
        "- name: Run read-only AutoTutor verification", 1
    )[0]
    assert "id: traffic" in traffic_step and "continue-on-error: true" in traffic_step
    assert "Controlled traffic outcome" in source
    assert "Resolve exact verification window" in source and "id: window" in source
    assert 'echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in traffic_step
    assert 'echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in traffic_step
    assert source.count("${{ steps.window.outputs.start }}") == 3
    assert source.count("${{ steps.window.outputs.end }}") == 3
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "EDU_AGENT_AUTOTUTOR_VERIFICATION_MACHINE_REQUIRED" in render
    assert "EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_SHA256" in render
    assert "EDU_AGENT_AUTOTUTOR_VERIFICATION_BOOTSTRAP_SHA256" in render
    assert "EDU_AGENT_AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET" in render
    assert "EDU_AGENT_AUTOTUTOR_VERIFICATION_STUDENT_IDS" in render
    assert "AUTOTUTOR_PRODUCTION_API_TOKEN" not in render
    print("autotutor_production_workflow_contract_smoke=PASS")


if __name__ == "__main__":
    main()
