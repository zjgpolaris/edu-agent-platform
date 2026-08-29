from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.release_gate import _ready_summary, _with_query
from eval.run_core_evals import DEDICATED_INTEGRATION_SUITES, SMOKE_SUITES, SUITE_FILES


def main() -> None:
    for suite in DEDICATED_INTEGRATION_SUITES:
        assert suite in SUITE_FILES, f"dedicated suite must remain directly runnable: {suite}"
        assert suite not in SMOKE_SUITES, f"dedicated suite leaked into generic smoke: {suite}"

    url = _with_query("https://example.com/api/ready?foo=1", {"require_rag": "true", "require_external": "true", "require_runtime": "true"})
    assert "require_rag=true" in url
    assert "require_external=true" in url
    assert "foo=1" in url
    assert "require_runtime=true" in url

    summary = _ready_summary(
        {
            "status": "degraded",
            "mode": "readiness-shallow",
            "required_checks": ["database", "llm_config", "rag", "external_dependencies"],
            "failed_required_checks": [],
            "warning_checks": ["latest_eval"],
        }
    )
    assert "status=degraded" in summary
    assert "required=database,llm_config,rag,external_dependencies" in summary
    assert "warnings=latest_eval" in summary
    print("release_gate_smoke=PASS")


if __name__ == "__main__":
    main()
