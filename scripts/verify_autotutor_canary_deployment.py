#!/usr/bin/env python3
"""Verify a deployed AutoTutor Canary without mutating production configuration."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

UrlOpen = Callable[..., Any]
PHASES = {"preflight", "control_snapshot", "canary_snapshot", "rollback_verify"}
FORBIDDEN_KEYS = {
    "token", "authorization", "password", "bucket_salt", "email", "student_id", "actor_id", "account_id",
    "session_id", "trace_id", "effect_id", "transition_id", "question", "answer", "raw_prompt", "raw_response", "content",
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


def _warm(api_base: str, *, urlopen: UrlOpen, sleep: Callable[[float], None]) -> bool:
    health_url = api_base.rstrip("/") + "/api/health"
    cold_start = False
    for attempt in range(3):
        try:
            health = _request_json(health_url, token="", timeout=20, urlopen=urlopen)
            if health.get("ok") is True:
                return cold_start
            raise ValueError("health response is not ready")
        except (OSError, TimeoutError, urllib.error.URLError, ValueError):
            cold_start = True
            if attempt == 2:
                raise RuntimeError("deployment_unavailable") from None
            sleep(2**attempt)
    return cold_start


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
    urlopen: UrlOpen = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError("unsupported verification phase")
    cold_start = _warm(api_base, urlopen=urlopen, sleep=sleep)
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
    if phase == "preflight":
        result = _request_json(
            base + "/verification?" + urllib.parse.urlencode(params),
            token=token,
            timeout=30,
            urlopen=urlopen,
        )
    else:
        if not window_start or not window_end:
            raise ValueError("snapshot phases require window_start and window_end")
        result = _request_json(
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
    deployment = result.get("deployment") or (result.get("snapshot") or {}).get("deployment") or {}
    if deployment.get("deployed_commit") != expected_commit:
        raise ValueError("deployed_commit_mismatch")
    configuration = result.get("configuration") or (result.get("snapshot") or {}).get("configuration") or {}
    if configuration.get("config_version") != expected_config_version:
        raise ValueError("config_version_mismatch")
    return {
        "schema_version": 1,
        "phase": phase,
        "cold_start_recovered": cold_start,
        "result": result,
    }


def _exit_code(payload: dict[str, Any]) -> int:
    result = payload.get("result") or {}
    fact = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else result
    status = str((fact or {}).get("status") or "UNKNOWN")
    decision = str((fact or {}).get("decision") or "NO_GO")
    if status in {"READY", "VERIFIED"} and decision == "GO":
        return 0
    if status == "NOT_READY":
        return 2
    if status == "BLOCKED":
        return 3
    return 4


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
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    token = os.getenv("API_TOKEN", "").strip()
    if not token:
        raise SystemExit("API_TOKEN is required")
    try:
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
        )
        code = _exit_code(artifact)
    except ValueError as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": str(exc)}
        code = 5 if str(exc) in {"deployed_commit_mismatch", "config_version_mismatch"} else 4
    except urllib.error.HTTPError as exc:
        artifact = {
            "schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO",
            "error_code": "remote_http_error", "http_status": exc.code,
        }
        code = 5 if exc.code in {401, 403} else 4
    except Exception as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": "network_unavailable", "error_type": exc.__class__.__name__}
        code = 4
    try:
        _assert_pii_free(artifact)
    except ValueError as exc:
        artifact = {"schema_version": 1, "phase": args.phase, "status": "UNKNOWN", "decision": "NO_GO", "error_code": str(exc)}
        code = 5
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_markdown.write_text(_markdown(artifact), encoding="utf-8")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
