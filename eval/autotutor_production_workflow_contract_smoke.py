"""The production workflow is manual, immutable, bounded and secret-safe."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = (ROOT / ".github" / "workflows" / "autotutor-production-verification.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source and "schedule:" not in source and "push:" not in source
    assert "permissions:\n  contents: read" in source
    assert "environment: production-verification" in source and "timeout-minutes: 10" in source
    assert "git merge-base --is-ancestor" in source
    assert "--persist-url" in source and "--require-go" in source
    assert "retention-days: 30" in source and "continue-on-error: true" in source
    assert "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS" not in source
    print("autotutor_production_workflow_contract_smoke=PASS")


if __name__ == "__main__":
    main()
