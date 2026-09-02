"""Deterministic GitHub Environment bootstrap attestation fixtures."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_autotutor_verification_environment import (  # noqa: E402
    evaluate_bootstrap,
    verify_attestation,
)


def _evaluate(**overrides: object) -> dict:
    values = {
        "repository": "example/edu-agent-platform",
        "environment_name": "production-verification",
        "expected_branch": "main",
        "environment": {
            "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}]}],
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
        },
        "variables": {"variables": [{"name": "AUTOTUTOR_PRODUCTION_API_BASE", "value": "must-not-leak"}]},
        "secrets": {"secrets": [{"name": "AUTOTUTOR_PRODUCTION_API_TOKEN"}]},
        "branch_policies": {"branch_policies": [{"name": "main"}]},
        "expected_branch_protected": False,
    }
    values.update(overrides)
    return evaluate_bootstrap(**values)  # type: ignore[arg-type]


def main() -> None:
    ready = _evaluate()
    assert ready["decision"] == "GO" and ready["blockers"] == [] and verify_attestation(ready)
    assert "must-not-leak" not in str(ready)

    cases = {
        "environment_missing": {"environment": None},
        "required_reviewer_missing": {
            "environment": {
                "protection_rules": [],
                "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
            },
        },
        "expected_branch_policy_missing": {"branch_policies": {"branch_policies": [{"name": "release"}]}},
        "api_base_variable_missing": {"variables": {"variables": []}},
        "api_token_secret_missing": {"secrets": {"secrets": []}},
    }
    for blocker, override in cases.items():
        result = _evaluate(**override)
        assert result["decision"] == "NO_GO" and blocker in result["blockers"], result
        assert verify_attestation(result)

    protected = _evaluate(
        environment={
            "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "Team"}]}],
            "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
        },
        branch_policies=None,
        expected_branch_protected=True,
    )
    assert protected["decision"] == "GO", protected
    tampered = copy.deepcopy(ready)
    tampered["decision"] = "NO_GO"
    assert not verify_attestation(tampered)
    assert _evaluate()["attestation_sha256"] == ready["attestation_sha256"]
    print("autotutor_verification_environment_bootstrap_smoke=PASS")


if __name__ == "__main__":
    main()
