#!/usr/bin/env python3
"""Verify a deployed AutoTutor Canary without mutating production configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

UrlOpen = Callable[..., Any]
PHASES = {"preflight", "control_snapshot", "canary_snapshot", "rollback_verify"}
CONFIG_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
FORBIDDEN_KEYS = {
    "token", "authorization", "password", "secret", "bucket_salt", "cookie", "email", "student_id", "actor_id", "account_id",
    "session_id", "trace_id", "effect_id", "transition_id", "question", "answer", "prompt", "response", "raw_prompt",
    "raw_response", "content",
}


def _assert_pii_free(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"sensitive_field_present:{key}")
            _assert_pii_free(item)
    elif isinstance(value, list):
        for item in value:
            _assert_pii_free(item)


def _request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": "edu-agent-autotutor-verifier/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "")
        if "json" not in content_type.lower():
            raise ValueError("remote response is not JSON")
        result = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(result, dict):
        raise ValueError("remote response must be an object")
    return result


def _warm(
    api_base: str,
    *,
    urlopen: UrlOpen,
    sleep: Callable[[float], None],
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    health_url = api_base.rstrip("/") + "/api/health"
    cold_start = False
    attempt = 0
    while True:
        attempt += 1
        try:
            health = _request_json(health_url, token="", timeout=20, urlopen=urlopen)
            if health.get("ok") is True:
                return cold_start
            raise ValueError("health response is not ready")
        except (OSError, TimeoutError, urllib.error.URLError, ValueError):
            cold_start = True
            if (deadline is None and attempt >= 3) or (deadline is not None and monotonic() >= deadline):
                raise ValueError("production_api_unavailable") from None
            sleep(min(30, 5 * (2 ** min(attempt - 1, 3))) if deadline is not None else 2 ** (attempt - 1))


def validate_ci_provenance(payload: dict[str, Any] | None, *, expected_commit: str) -> dict[str, Any]:
    """Validate a PII-free GitHub Actions receipt produced by the workflow."""
    if not isinstance(payload, dict):
        raise ValueError("ci_run_missing")
    status = str(payload.get("status") or "unknown")
    conclusion = str(payload.get("conclusion") or "")
    event = str(payload.get("event") or "")
    head_sha = str(payload.get("head_sha") or "")
    workflow = str(payload.get("workflow") or "")
    if status in {"queued", "in_progress", "pending"}:
        raise ValueError("ci_run_not_complete")
    if status != "verified" or conclusion != "success":
        raise ValueError(str(payload.get("error_code") or "ci_run_not_successful"))
    if workflow != "EduAgent CI" or event != "push" or head_sha != expected_commit:
        raise ValueError("ci_provenance_mismatch")
    result = {
        "workflow": workflow,
        "status": "verified",
        "conclusion": conclusion,
        "event": event,
        "head_sha": head_sha,
        "run_id": str(payload.get("run_id") or "") or None,
    }
    _assert_pii_free(result)
    return result


def _fact(result: dict[str, Any]) -> dict[str, Any]:
    snapshot = result.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else result


def verify_remote(
    *,
    api_base: str,
    token: str,
    expected_commit: str,
    expected_config_version: str,
    phase: str,
    window_start: str | None = None,
    window_end: str | None = None,
    minimum_control: int = 100,
    minimum_graph: int = 100,
    minimum_rollback_control: int = 20,
    wait_for_deployment: bool = False,
    deployment_timeout_seconds: int = 300,
    require_ci_provenance: bool = False,
    ci_provenance: dict[str, Any] | None = None,
    urlopen: UrlOpen = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError("unsupported verification phase")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("expected_commit_invalid")
    if not CONFIG_VERSION_PATTERN.fullmatch(expected_config_version):
        raise ValueError("expected_config_version_invalid")
    parsed_api_base = urllib.parse.urlparse(api_base)
    if parsed_api_base.scheme != "https" or not parsed_api_base.netloc:
        raise ValueError("api_base_invalid")
    verified_ci = validate_ci_provenance(ci_provenance, expected_commit=expected_commit) if require_ci_provenance else None
    deadline = monotonic() + max(0, int(deployment_timeout_seconds))
    cold_start = _warm(
        api_base,
        urlopen=urlopen,
        sleep=sleep,
        deadline=deadline if wait_for_deployment else None,
        monotonic=monotonic,
    )
    params = {
        "expected_commit": expected_commit,
        "expected_config_version": expected_config_version,
        "minimum_control": str(minimum_control),
        "minimum_graph": str(minimum_graph),
        "minimum_rollback_control": str(minimum_rollback_control),
    }
    if window_start:
        params["window_start"] = window_start
    if window_end:
        params["window_end"] = window_end
    base = api_base.rstrip("/") + "/api/admin/agent-runtime/autotutor-canary"

    def fetch() -> dict[str, Any]:
        if phase == "preflight":
            return _request_json(
                base + "/verification?" + urllib.parse.urlencode(params),
                token=token,
                timeout=30,
                urlopen=urlopen,
            )
        if not window_start or not window_end:
            raise ValueError("snapshot phases require window_start and window_end")
        return _request_json(
            base + "/snapshots",
            token=token,
            method="POST",
            payload={
                "expected_commit": expected_commit,
                "expected_config_version": expected_config_version,
                "window_start": window_start,
                "window_end": window_end,
                "minimum_control": minimum_control,
                "minimum_graph": minimum_graph,
                "minimum_rollback_control": minimum_rollback_control,
            },
            timeout=30,
            urlopen=urlopen,
        )

    attempts = 0
    stable_count = 0
    stable_signature: tuple[str, str, str] | None = None
    last_error = "deployment_not_converged"
    result: dict[str, Any] = {}
    while True:
        attempts += 1
        try:
            result = fetch()
            fact = _fact(result)
            deployment = fact.get("deployment") or {}
            configuration = fact.get("configuration") or {}
            signature = (
                str(deployment.get("deployed_commit") or ""),
                str(configuration.get("config_version") or ""),
                str(deployment.get("environment") or ""),
            )
            if signature[0] != expected_commit:
                last_error = "deployment_not_converged" if wait_for_deployment else "deployed_commit_mismatch"
                stable_count = 0
            elif signature[1] != expected_config_version:
                last_error = "config_version_mismatch"
                stable_count = 0
            elif signature[2] != "production":
                last_error = "environment_not_production"
                stable_count = 0
            else:
                stable_count = stable_count + 1 if signature == stable_signature else 1
                stable_signature = signature
                if not wait_for_deployment or stable_count >= 2:
                    break
        except urllib.error.HTTPError:
            raise
        except ValueError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            last_error = "production_api_unavailable"
            stable_count = 0
        if not wait_for_deployment or monotonic() >= deadline:
            raise ValueError(last_error)
        sleep(min(30, 5 * (2 ** min(attempts - 1, 3))))
    return {
        "schema_version": 1,
        "phase": phase,
        "cold_start_recovered": cold_start,
        "deployment_converged": True,
        "deployment_attempts": attempts,
        "ci": verified_ci or {"status": "not_required"},
        "result": result,
    }


def _exit_code(payload: dict[str, Any]) -> int:
    result = payload.get("result") or {}
    fact = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else result
    status = str((fact or {}).get("status") or "UNKNOWN")
    decision = str((fact or {}).get("decision") or "NO_GO")
    if status in {"READY", "VERIFIED"} and decision == "GO":
        return 0
    return 6


def build_workflow_receipt(
    artifact: dict[str, Any],
    *,
    expected_commit: str,
    expected_config_version: str,
    phase: str,
    ci_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fact = _fact(artifact.get("result") or {})
    deployment = fact.get("deployment") or {}
    evidence = fact.get("evidence") or {}
    raw_ci = ci_provenance or artifact.get("ci") or {}
    safe_ci = {
        key: raw_ci.get(key)
        for key in ("workflow", "status", "conclusion", "event", "head_sha", "run_id", "error_code")
        if raw_ci.get(key) is not None
    }
    safe_expected_commit = expected_commit if re.fullmatch(r"[0-9a-f]{40}", expected_commit) else None
    safe_config_version = expected_config_version if CONFIG_VERSION_PATTERN.fullmatch(expected_config_version) else None
    receipt = {
        "schema_version": 1,
        "receipt_type": "autotutor_production_verification",
        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "unknown"),
        "workflow_run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1") or "1"),
        "workflow_actor": os.getenv("GITHUB_ACTOR", "unknown"),
        "action": phase,
        "expected_commit": safe_expected_commit,
        "deployed_commit": deployment.get("deployed_commit"),
        "config_version": safe_config_version,
        "environment": deployment.get("environment") or "production",
        "ci": safe_ci or {"status": "unknown"},
        "window": fact.get("window") or {"start": None, "end": None},
        "result": {
            "status": fact.get("status") or artifact.get("status") or "UNKNOWN",
            "decision": fact.get("decision") or artifact.get("decision") or "NO_GO",
            "phase": fact.get("phase") or phase,
            "blockers": fact.get("blockers") or ([artifact["error_code"]] if artifact.get("error_code") else []),
        },
        "snapshot_sha256": (artifact.get("result") or {}).get("snapshot_sha256"),
        "evidence_stage": evidence.get("stage"),
        "evidence_sha256": evidence.get("sha256"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return seal_workflow_receipt(receipt)


def seal_workflow_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical hash seal; replacing a prior seal is idempotent."""
    receipt = dict(receipt)
    receipt.pop("receipt_sha256", None)
    _assert_pii_free(receipt)
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return receipt


def attach_evidence_to_receipt(receipt: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Bind the evidence produced after the remote verification step."""
    updated = dict(receipt)
    updated["evidence_stage"] = evidence.get("evidence_stage")
    updated["evidence_sha256"] = evidence.get("evidence_sha256")
    return seal_workflow_receipt(updated)


def _markdown(payload: dict[str, Any]) -> str:
    result = payload.get("result") or {}
    fact = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else result
    deployment = fact.get("deployment") or {}
    return "\n".join((
        "# AutoTutor Production Verification",
        "",
        f"- Action: `{payload.get('phase')}`",
        f"- Status: `{fact.get('status', 'UNKNOWN')}`",
        f"- Decision: `{fact.get('decision', 'NO_GO')}`",
        f"- Commit: `{deployment.get('deployed_commit') or 'missing'}`",
        f"- Cold start recovered: `{str(bool(payload.get('cold_start_recovered'))).lower()}`",
        f"- Blockers: `{', '.join(fact.get('blockers') or []) or 'none'}`",
        "",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-config-version", required=True)
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    parser.add_argument("--minimum-control", type=int, default=100)
    parser.add_argument("--minimum-graph", type=int, default=100)
    parser.add_argument("--minimum-rollback-control", type=int, default=20)
    parser.add_argument("--wait-for-deployment", action="store_true")
    parser.add_argument("--deployment-timeout-seconds", type=int, default=300)
    parser.add_argument("--require-ci-provenance", action="store_true")
    parser.add_argument("--ci-receipt-path", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path)
    args = parser.parse_args()
    token = os.getenv("API_TOKEN", "").strip()
    ci_provenance = None
    try:
        if args.require_ci_provenance and not args.ci_receipt_path:
            raise ValueError("ci_run_missing")
        if args.ci_receipt_path:
            try:
                ci_provenance = json.loads(args.ci_receipt_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise ValueError("ci_run_missing") from None
        if not token:
            raise PermissionError("production_api_token_missing")
        if not args.api_base.strip():
            raise PermissionError("production_api_base_missing")
        artifact = verify_remote(
            api_base=args.api_base,
            token=token,
            expected_commit=args.expected_commit,
            expected_config_version=args.expected_config_version,
            phase=args.phase,
            window_start=args.window_start,
            window_end=args.window_end,
            minimum_control=max(1, args.minimum_control),
            minimum_graph=max(1, args.minimum_graph),
            minimum_rollback_control=max(1, args.minimum_rollback_control),
            wait_for_deployment=args.wait_for_deployment,
            deployment_timeout_seconds=max(0, args.deployment_timeout_seconds),
            require_ci_provenance=args.require_ci_provenance,
            ci_provenance=ci_provenance,
        )
        code = _exit_code(artifact)
    except PermissionError as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": str(exc)}
        code = 3
    except ValueError as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": str(exc)}
        error = str(exc)
        if error in {"unsupported verification phase", "expected_commit_invalid", "expected_config_version_invalid", "api_base_invalid", "snapshot phases require window_start and window_end"}:
            code = 2
        elif error.startswith("ci_"):
            code = 4
        elif error in {"deployed_commit_mismatch", "deployment_not_converged", "config_version_mismatch", "environment_not_production", "production_api_unavailable"}:
            code = 5
        else:
            code = 7
    except urllib.error.HTTPError as exc:
        artifact = {
            "schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO",
            "error_code": "remote_http_error", "http_status": exc.code,
        }
        artifact["error_code"] = "production_api_auth_failed" if exc.code in {401, 403} else "production_api_http_error"
        code = 3 if exc.code in {401, 403} else 5
    except Exception as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": "network_unavailable", "error_type": exc.__class__.__name__}
        code = 5
    try:
        _assert_pii_free(artifact)
    except ValueError as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": str(exc)}
        code = 8
    receipt = build_workflow_receipt(
        artifact,
        expected_commit=args.expected_commit,
        expected_config_version=args.expected_config_version,
        phase=args.phase,
        ci_provenance=ci_provenance,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_markdown.write_text(_markdown(artifact), encoding="utf-8")
    if args.output_receipt:
        args.output_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.output_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
