#!/usr/bin/env python3
"""Generate bounded, attributable AutoTutor release-verification traffic."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
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
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.autotutor_verification_window import control_window_start

UrlOpen = Callable[..., Any]
PHASES = {"control", "canary", "rollback"}
MINIMUM_LATENCY_SAFETY_SAMPLES = 20
FORBIDDEN_RECEIPT_KEYS = {
    "actor_id", "student_id", "username", "password", "token", "secret", "salt",
    "session_id", "answer", "question", "attestation", "authorization",
}


def stable_executor_bucket(subject: str, *, salt: str) -> int:
    digest = hashlib.sha256(f"autotutor-executor:{salt}:{subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


def _issue_traffic_token(
    *, actor_id: str, verification_run_id: str, phase: str,
    deployed_commit: str, config_version: str, secret: str,
) -> str:
    now = int(time.time())
    payload = {
        "v": 1, "actor_id": actor_id, "verification_run_id": verification_run_id,
        "phase": phase, "deployed_commit": deployed_commit, "config_version": config_version,
        "iat": now, "exp": now + 300, "nonce": uuid4().hex,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return "atv1_" + base64.urlsafe_b64encode(raw + signature).decode("ascii").rstrip("=")


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Accept": "application/json", "User-Agent": "edu-agent-autotutor-traffic/1.0"}
    request_headers.update(headers or {})
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(result, dict):
        raise ValueError("verification_response_invalid")
    return result


def _credentials(raw: str) -> list[dict[str, str]]:
    if not raw:
        raise ValueError("verification_credentials_missing")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("verification_credentials_invalid") from exc
    if isinstance(payload, dict):
        payload = payload.get("accounts")
    if not isinstance(payload, list) or not payload:
        raise ValueError("verification_credentials_invalid")
    result: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("verification_credentials_invalid")
        account = {key: str(item.get(key) or "").strip() for key in ("actor_id", "username", "password")}
        if not all(account.values()):
            raise ValueError("verification_credentials_invalid")
        result.append(account)
    return result


class PreflightUnavailable(RuntimeError):
    def __init__(self, diagnostics: dict[str, Any]):
        super().__init__("verification_preflight_unavailable")
        self.diagnostics = diagnostics


def _request_preflight(url: str, *, headers: dict[str, str], deadline: float,
                       urlopen: UrlOpen, sleep: Callable[[float], None],
                       monotonic: Callable[[], float]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retry only this read-only request, with bounded attempts and safe diagnostics."""
    started = monotonic()
    deadline = min(deadline, started + 180)
    attempts = 0
    reason = "deadline_exceeded"
    while attempts < 6 and monotonic() < deadline:
        attempts += 1
        retryable = True
        try:
            payload = _request_json(url, headers=headers, timeout=min(30, deadline - monotonic()),
                                    urlopen=urlopen)
            diagnostics = {"stage": "preflight", "attempts": attempts,
                           "elapsed_ms": round((monotonic() - started) * 1000), "status": "ready"}
            print(json.dumps(diagnostics, sort_keys=True), file=sys.stderr, flush=True)
            return payload, diagnostics
        except urllib.error.HTTPError as exc:
            reason = f"http_{exc.code}"
            retryable = exc.code in {502, 503, 504}
            exc.close()
        except (TimeoutError, urllib.error.URLError, OSError):
            reason = "transport_timeout_or_unavailable"
        except ValueError:
            reason = "invalid_json_response"
            retryable = False
        diagnostics = {"stage": "preflight", "attempts": attempts, "reason": reason,
                       "elapsed_ms": round((monotonic() - started) * 1000), "status": "unavailable"}
        print(json.dumps(diagnostics, sort_keys=True), file=sys.stderr, flush=True)
        remaining = deadline - monotonic()
        if not retryable or attempts >= 6 or remaining <= 0:
            break
        sleep(min(5 * 2 ** (attempts - 1), 30, remaining))
    raise PreflightUnavailable({"stage": "preflight", "attempts": attempts, "reason": reason,
                                "elapsed_ms": round((monotonic() - started) * 1000), "status": "unavailable"})


def _preflight_fact(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fact = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    return dict(fact.get("deployment") or {}), dict(fact.get("configuration") or {})


def _validate_preflight(
    payload: dict[str, Any], *, expected_commit: str, expected_config_version: str, phase: str
) -> dict[str, Any]:
    deployment, configuration = _preflight_fact(payload)
    if deployment.get("environment") != "production":
        raise ValueError("environment_not_production")
    if deployment.get("deployed_commit") != expected_commit:
        raise ValueError("deployed_commit_mismatch")
    if configuration.get("config_version") != expected_config_version:
        raise ValueError("config_version_mismatch")
    mode = configuration.get("mode")
    active_bps = int(configuration.get("active_bps") or 0)
    if phase == "canary" and not (mode == "active_canary" and 1 <= active_bps <= 100):
        raise ValueError("verification_phase_config_mismatch")
    if phase in {"control", "rollback"} and not (mode == "legacy" and active_bps == 0):
        raise ValueError("verification_phase_config_mismatch")
    if configuration.get("kill_switch") is True:
        raise ValueError("kill_switch_enabled")
    return configuration


def _assert_operational_safety(payload: dict[str, Any]) -> None:
    fact = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    aggregate = fact.get("aggregate") or {}
    blockers = set(str(item) for item in aggregate.get("blockers") or [])
    stop_blockers = {
        "unauthorized_graph_traffic", "duplicate_effects_detected",
        "duplicate_transition_observations_detected", "observation_write_failure",
    }
    # Comparator, fallback-rate and active-latency checks have no denominator
    # before the first Graph observation. The aggregate intentionally reports
    # them as not ready, but treating that state as a traffic safety stop would
    # make both the initial Legacy baseline and the first Canary sample
    # impossible to collect. Correctness and fallback invariants become hard
    # stops with the first Graph sample; latency uses the p95 sample floor below.
    assigned_graph_count = int(aggregate.get("assigned_graph_count") or 0)
    if assigned_graph_count > 0:
        stop_blockers.update({
            "comparator_not_exact", "fallback_rate_above_one_percent",
        })
    # A p95 estimate needs at least 20 observations to contain one tail
    # sample. Keep collecting below that floor while every correctness and
    # fallback safety invariant remains enforced; otherwise a single slow
    # transition can permanently prevent the canary from becoming measurable.
    if assigned_graph_count >= MINIMUM_LATENCY_SAFETY_SAMPLES:
        stop_blockers.add("active_latency_regression")
    matched = sorted(blockers & stop_blockers)
    if matched:
        raise RuntimeError(f"verification_safety_stop:{matched[0]}")
    health = fact.get("observation_health") or aggregate.get("observation_write_health") or {}
    if health and health.get("ok") is not True:
        raise RuntimeError("verification_safety_stop:observation_write_unhealthy")


def _select_account(accounts: list[dict[str, str]], *, phase: str, salt: str, active_bps: int) -> dict[str, str]:
    if phase != "canary":
        return accounts[0]
    selected = [item for item in accounts if stable_executor_bucket(item["actor_id"], salt=salt) < active_bps]
    if not selected:
        raise ValueError("verification_graph_subject_unavailable")
    return selected[0]


def _reviewed_answer_texts() -> dict[str, str]:
    path = REPO_ROOT / "knowledge_base" / "history" / "autotutor_content.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for item in payload.get("items") or []:
        for assessment in (item.get("practice_items") or []) + (item.get("exit_ticket_items") or []):
            assessment_id = str(assessment.get("assessment_id") or "")
            options = list(assessment.get("options") or [])
            correct = next((option for option in options if option.get("is_correct")), None)
            if not assessment_id or not isinstance(correct, dict) or not str(correct.get("text") or "").strip():
                continue
            result[assessment_id] = str(correct["text"]).strip()
    return result


def _answer_for_public_question(question: dict[str, Any], reviewed_answers: dict[str, str]) -> str:
    """Resolve the answer from the labels actually exposed by the student API."""
    assessment_id = str(question.get("assessment_id") or "")
    correct_text = reviewed_answers.get(assessment_id)
    if not correct_text:
        raise RuntimeError("verification_assessment_not_in_reviewed_pack")
    normalized_correct = "".join(correct_text.split())
    for raw_option in question.get("options") or []:
        match = re.match(r"^\s*([ABCD])[.．、]\s*(.+?)\s*$", str(raw_option))
        if match and "".join(match.group(2).split()) == normalized_correct:
            return match.group(1)
    raise RuntimeError("verification_public_answer_mapping_unavailable")


def _safe_blocked_reason(state: dict[str, Any]) -> str:
    blocked = state.get("content_blocked") if isinstance(state.get("content_blocked"), dict) else {}
    raw_reason = str(blocked.get("reason") or "unknown")
    feedback = state.get("answer_feedback") if isinstance(state.get("answer_feedback"), dict) else {}
    if raw_reason == "unknown" and feedback.get("is_correct") is True:
        raw_reason = "exit_ticket_unavailable_after_correct_practice"
    elif raw_reason == "unknown" and feedback.get("is_correct") is False:
        raw_reason = "remediation_unavailable_after_wrong_practice"
    return re.sub(r"[^a-z0-9_-]+", "_", raw_reason.lower()).strip("_")[:64] or "unknown"


def _assert_receipt_safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_RECEIPT_KEYS:
                raise ValueError(f"sensitive_receipt_field:{key}")
            _assert_receipt_safe(item)
    elif isinstance(value, list):
        for item in value:
            _assert_receipt_safe(item)


def run_traffic(
    *,
    api_base: str,
    expected_commit: str,
    expected_config_version: str,
    phase: str,
    target_transitions: int,
    maximum_sessions: int,
    timeout_seconds: int,
    control_start: str = "",
    env: dict[str, str] | None = None,
    urlopen: UrlOpen = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    deadline = monotonic() + max(1, timeout_seconds)
    source = dict(os.environ if env is None else env)
    if source.get("AUTOTUTOR_VERIFICATION_ENVIRONMENT") != "production-verification":
        raise ValueError("verification_environment_not_protected")
    parsed = urllib.parse.urlparse(api_base)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("api_base_invalid")
    allowed_hosts = {
        host.strip().lower() for host in source.get("AUTOTUTOR_PRODUCTION_ALLOWED_HOSTS", "").split(",") if host.strip()
    }
    if not allowed_hosts or str(parsed.hostname or "").lower() not in allowed_hosts:
        raise ValueError("api_host_not_allowlisted")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("expected_commit_invalid")
    if phase not in PHASES:
        raise ValueError("verification_phase_invalid")
    machine_token = source.get("AUTOTUTOR_PRODUCTION_API_TOKEN", "")
    bootstrap = source.get("AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256", "")
    salt = source.get("AUTOTUTOR_GRAPH_BUCKET_SALT", "")
    traffic_secret = source.get("AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET", "")
    if not machine_token or not re.fullmatch(r"[0-9a-f]{64}", bootstrap):
        raise ValueError("verification_machine_credential_missing")
    if not salt or len(traffic_secret) < 32:
        raise ValueError("verification_traffic_secret_missing")
    accounts = _credentials(source.get("AUTOTUTOR_VERIFICATION_STUDENT_CREDENTIALS_JSON", ""))
    preflight_params = {
        "expected_commit": expected_commit,
        "expected_config_version": expected_config_version,
    }
    if phase == "canary":
        preflight_params.update({"window_start": control_window_start(control_start),
                                 "window_end": datetime.now(timezone.utc).isoformat()})
    preflight_url = api_base.rstrip("/") + "/api/admin/agent-runtime/autotutor-canary/verification?" + urllib.parse.urlencode(preflight_params)
    preflight, preflight_diagnostics = _request_preflight(preflight_url, headers={
        "Authorization": f"Bearer {machine_token}",
        "X-AutoTutor-Bootstrap-SHA256": bootstrap,
    }, deadline=deadline, urlopen=urlopen, sleep=sleep, monotonic=monotonic)
    configuration = _validate_preflight(
        preflight, expected_commit=expected_commit, expected_config_version=expected_config_version, phase=phase
    )
    _assert_operational_safety(preflight)
    if phase == "canary":
        fact = preflight.get("snapshot", preflight)
        aggregate = fact.get("aggregate") or {}
        if int(aggregate.get("assigned_control_count") or 0) < 100 or (
            aggregate.get("control_latency") or {}
        ).get("p95_ms") is None:
            raise ValueError("verification_control_baseline_insufficient")
    account = _select_account(accounts, phase=phase, salt=salt, active_bps=int(configuration.get("active_bps") or 0))
    login = _request_json(api_base.rstrip("/") + "/api/auth/login", method="POST", payload={
        "username": account["username"], "password": account["password"],
    }, urlopen=urlopen)
    if login.get("role") != "student" or login.get("actor_id") != account["actor_id"] or not login.get("token"):
        raise ValueError("verification_student_identity_mismatch")
    student_token = str(login["token"])
    run_id = "avr_" + uuid4().hex
    reviewed_answers = _reviewed_answer_texts()
    transitions = 0
    sessions = 0
    completed = 0
    failed = 0
    server_errors = 0

    def transition(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal transitions, server_errors
        if monotonic() >= deadline:
            raise TimeoutError("verification_traffic_timeout")
        retry = 0
        while True:
            attestation = _issue_traffic_token(
                actor_id=account["actor_id"], verification_run_id=run_id, phase=phase,
                deployed_commit=expected_commit, config_version=expected_config_version, secret=traffic_secret,
            )
            try:
                result = _request_json(api_base.rstrip("/") + path, method="POST", payload=payload, headers={
                    "Authorization": f"Bearer {student_token}",
                    "X-AutoTutor-Verification-Run": run_id,
                    "X-AutoTutor-Verification-Attestation": attestation,
                }, urlopen=urlopen)
                server_errors = 0
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and retry < 3 and monotonic() < deadline:
                    sleep(float(2 ** retry))
                    retry += 1
                    continue
                if exc.code >= 500:
                    server_errors += 1
                    if server_errors >= 3:
                        raise RuntimeError("consecutive_server_errors") from exc
                    if monotonic() >= deadline:
                        raise TimeoutError("verification_traffic_timeout") from exc
                    sleep(float(2 ** retry))
                    retry += 1
                    # Retry the same payload and idempotency key. A gateway may
                    # time out after the application committed the transition;
                    # starting a new session here would duplicate work.
                    continue
                raise PermissionError("verification_transition_rejected") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                server_errors += 1
                if server_errors >= 3:
                    raise RuntimeError("consecutive_server_errors") from exc
                if monotonic() >= deadline:
                    raise TimeoutError("verification_traffic_timeout") from exc
                sleep(float(2 ** retry))
                retry += 1
                continue
        transitions += 1
        if transitions < target_transitions:
            sleep(1.0)
        return result

    while transitions < target_transitions and sessions < maximum_sessions and monotonic() < deadline:
        sessions += 1
        try:
            state = transition("/api/autotutor/start", {
                "student_id": account["actor_id"],
                "grade": "八年级上册",
                # AutoTutor consumes only the first explicit focus tag. Keep the
                # entity and aspect together so this resolves to the curated
                # history:戊戌变法:cause:v1 objective instead of an unreviewed
                # generic "戊戌变法" objective that is blocked by the content gate.
                "focus_tags": ["戊戌变法失败原因"],
                "focus_reason": "production release verification",
                "idempotency_key": f"{run_id}-start-{sessions}",
            })
            answer_index = 0
            while transitions < target_transitions and state.get("status") == "awaiting_answer" and monotonic() < deadline:
                question = state.get("current_question") or {}
                answer = _answer_for_public_question(question, reviewed_answers)
                # Every third session exercises the reflection path once.
                if sessions % 3 == 0 and answer_index == 0:
                    answer = next((candidate for candidate in ("A", "B", "C", "D") if candidate != answer), "B")
                answer_index += 1
                state = transition("/api/autotutor/answer", {
                    "session_id": state["session_id"],
                    "student_id": account["actor_id"],
                    "answer": answer,
                    "expected_revision": state.get("revision"),
                    "idempotency_key": f"{run_id}-answer-{sessions}-{answer_index}",
                })
            if state.get("status") == "completed":
                completed += 1
            elif state.get("status") == "needs_content":
                safe_reason = _safe_blocked_reason(state)
                raise RuntimeError(f"verification_content_target_unavailable:{safe_reason}")
            if phase == "canary":
                preflight_params["window_end"] = datetime.now(timezone.utc).isoformat()
            safety_url = api_base.rstrip("/") + "/api/admin/agent-runtime/autotutor-canary/verification?" + urllib.parse.urlencode(preflight_params)
            safety = _request_json(safety_url, headers={
                "Authorization": f"Bearer {machine_token}",
                "X-AutoTutor-Bootstrap-SHA256": bootstrap,
            }, urlopen=urlopen)
            _validate_preflight(
                safety, expected_commit=expected_commit, expected_config_version=expected_config_version, phase=phase
            )
            _assert_operational_safety(safety)
        except RuntimeError:
            failed += 1
            # RuntimeError is reserved for safety stops, repeated server
            # failures and unusable verification content. None of these may be
            # swallowed while production traffic continues.
            raise
        except (urllib.error.URLError, TimeoutError, ValueError):
            failed += 1
    receipt = {
        "schema_version": 1,
        "receipt_type": "autotutor_verification_traffic",
        "phase": phase,
        "expected_commit": expected_commit,
        "config_version": expected_config_version,
        "environment": "production",
        "run_fingerprint": "sha256:" + hashlib.sha256(run_id.encode()).hexdigest(),
        "cohort_fingerprint": "sha256:" + hashlib.sha256(
            f"{expected_config_version}\n{salt}\nsha256-mod-10000-v1".encode()
        ).hexdigest(),
        "target_transitions": target_transitions,
        "transitions_sent": transitions,
        "sessions_started": sessions,
        "sessions_completed": completed,
        "sessions_failed": failed,
        "target_reached": transitions >= target_transitions,
        "preflight": preflight_diagnostics,
        "control_window_start": preflight_params.get("window_start"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _assert_receipt_safe(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-config-version", required=True)
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--target-transitions", type=int, default=100)
    parser.add_argument("--maximum-sessions", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=3300)
    parser.add_argument("--control-window-start", default="",
                        help="Canary evidence start, including the same-commit control baseline")
    parser.add_argument("--receipt-output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.target_transitions < 1 or args.maximum_sessions < 1 or args.timeout_seconds < 1:
        parser.error("limits must be positive")
    if args.target_transitions > 1000 or args.maximum_sessions > 100 or args.timeout_seconds > 3600:
        parser.error("limits exceed the production verification safety budget")
    if args.dry_run:
        receipt = {
            "schema_version": 1, "receipt_type": "autotutor_verification_traffic",
            "phase": args.phase, "status": "dry_run", "network_requests": 0,
            "target_transitions": args.target_transitions,
        }
    else:
        try:
            receipt = run_traffic(
                api_base=args.api_base, expected_commit=args.expected_commit,
                expected_config_version=args.expected_config_version, phase=args.phase,
                target_transitions=args.target_transitions, maximum_sessions=args.maximum_sessions,
                timeout_seconds=args.timeout_seconds, control_start=args.control_window_start,
            )
        except PreflightUnavailable as exc:
            receipt = {
                "schema_version": 1, "receipt_type": "autotutor_verification_traffic",
                "phase": args.phase, "status": "failed", "target_reached": False,
                "transitions_sent": 0, "sessions_started": 0,
                "preflight": exc.diagnostics,
            }
    output = Path(args.receipt_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt.get("target_reached", True) else 7


if __name__ == "__main__":
    raise SystemExit(main())
