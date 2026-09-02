#!/usr/bin/env python3
"""Read-only GitHub Environment bootstrap verification for AutoTutor."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

DEFAULT_ENVIRONMENT = "production-verification"
API_BASE_VARIABLE = "AUTOTUTOR_PRODUCTION_API_BASE"
API_TOKEN_SECRET = "AUTOTUTOR_PRODUCTION_API_TOKEN"


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _seal(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def evaluate_bootstrap(
    *,
    repository: str,
    environment_name: str,
    expected_branch: str,
    environment: dict[str, Any] | None,
    variables: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
    branch_policies: dict[str, Any] | None,
    expected_branch_protected: bool,
) -> dict[str, Any]:
    """Evaluate already-fetched GitHub metadata without secret values or PII."""
    protection_rules = environment.get("protection_rules") or [] if environment else []
    reviewer_count = sum(
        len(rule.get("reviewers") or [])
        for rule in protection_rules
        if rule.get("type") == "required_reviewers"
    )
    deployment_policy = environment.get("deployment_branch_policy") or {} if environment else {}
    custom_names = {
        str(item.get("name") or "")
        for item in ((branch_policies or {}).get("branch_policies") or [])
    }
    protected_allowed = bool(deployment_policy.get("protected_branches") and expected_branch_protected)
    custom_allowed = bool(deployment_policy.get("custom_branch_policies") and expected_branch in custom_names)
    variable_names = {
        str(item.get("name") or "") for item in ((variables or {}).get("variables") or [])
    }
    secret_names = {
        str(item.get("name") or "") for item in ((secrets or {}).get("secrets") or [])
    }
    checks = {
        "environment_exists": environment is not None,
        "required_reviewer_configured": reviewer_count > 0,
        "expected_branch_allowed": protected_allowed or custom_allowed,
        "api_base_variable_configured": API_BASE_VARIABLE in variable_names,
        "api_token_secret_configured": API_TOKEN_SECRET in secret_names,
    }
    blocker_by_check = {
        "environment_exists": "environment_missing",
        "required_reviewer_configured": "required_reviewer_missing",
        "expected_branch_allowed": "expected_branch_policy_missing",
        "api_base_variable_configured": "api_base_variable_missing",
        "api_token_secret_configured": "api_token_secret_missing",
    }
    blockers = [blocker_by_check[name] for name, passed in checks.items() if not passed]
    body = {
        "schema_version": 1,
        "repository": repository,
        "environment": environment_name,
        "expected_branch": expected_branch,
        "decision": "GO" if not blockers else "NO_GO",
        "checks": checks,
        "counts": {
            "required_reviewers": reviewer_count,
            "custom_branch_policies": len(custom_names),
        },
        "blockers": blockers,
    }
    return {**body, "attestation_sha256": _seal(body)}


def verify_attestation(payload: dict[str, Any]) -> bool:
    digest = str(payload.get("attestation_sha256") or "")
    body = {key: value for key, value in payload.items() if key != "attestation_sha256"}
    return len(digest) == 64 and hmac.compare_digest(digest, _seal(body))


def _gh_api(path: str, *, allow_missing: bool = False) -> dict[str, Any] | None:
    result = subprocess.run(
        ["gh", "api", "--method", "GET", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if allow_missing and ("HTTP 404" in result.stderr or "Not Found" in result.stderr):
            return None
        raise RuntimeError(f"gh api failed for {path}: exit {result.returncode}")
    value = json.loads(result.stdout or "{}")
    return value if isinstance(value, dict) else {}


def _repository(value: str | None) -> str:
    repository = (value or os.getenv("GITHUB_REPOSITORY") or "").strip()
    if repository:
        return repository
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("repository is required; pass --repository or authenticate gh in a repository")
    return result.stdout.strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository")
    parser.add_argument("--environment", default=DEFAULT_ENVIRONMENT)
    parser.add_argument("--expected-branch", default="main")
    parser.add_argument("--output")
    parser.add_argument("--require-go", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repository = _repository(args.repository)
    environment_path = f"repos/{repository}/environments/{quote(args.environment, safe='')}"
    environment = _gh_api(environment_path, allow_missing=True)
    if environment is None:
        variables = secrets = branch_policies = None
        branch_protected = False
    else:
        variables = _gh_api(f"{environment_path}/variables")
        secrets = _gh_api(f"{environment_path}/secrets")
        policy = environment.get("deployment_branch_policy") or {}
        branch_policies = (
            _gh_api(f"{environment_path}/deployment-branch-policies")
            if policy.get("custom_branch_policies") else None
        )
        branch_protected = _gh_api(
            f"repos/{repository}/branches/{quote(args.expected_branch, safe='')}/protection",
            allow_missing=True,
        ) is not None
    attestation = evaluate_bootstrap(
        repository=repository,
        environment_name=args.environment,
        expected_branch=args.expected_branch,
        environment=environment,
        variables=variables,
        secrets=secrets,
        branch_policies=branch_policies,
        expected_branch_protected=branch_protected,
    )
    rendered = json.dumps(attestation, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 1 if args.require_go and attestation["decision"] != "GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
