"""The traffic runner is bounded, signed and emits a PII-free receipt."""
from __future__ import annotations

import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_execution import stable_executor_bucket  # noqa: E402
from agents.autotutor_content import _resolve_content_path  # noqa: E402
from scripts.run_autotutor_canary_verification_traffic import (  # noqa: E402
    _answer_for_public_question,
    _assert_operational_safety,
    _reviewed_answer_texts,
    _safe_blocked_reason,
    _request_preflight,
    PreflightUnavailable,
    main as traffic_main,
    run_traffic,
)

COMMIT = "b" * 40
CONFIG = "v1.49.9-production-canary"
SALT = "runner-smoke-salt"
CONTROL_START = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


class Response:
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def main() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "!knowledge_base/history/**" in dockerignore
    assert "test -f /app/knowledge_base/history/autotutor_content.json" in dockerfile

    reviewed_answers = _reviewed_answer_texts()
    public_question = {
        "assessment_id": "wuxu-cause-practice-3",
        "options": [
            "A. 干扰项一",
            "B. 干扰项二",
            f"C. {reviewed_answers['wuxu-cause-practice-3']}",
            "D. 干扰项三",
        ],
    }
    assert _answer_for_public_question(public_question, reviewed_answers) == "C"
    assert _safe_blocked_reason({
        "content_blocked": {"message": "redacted"},
        "answer_feedback": {"is_correct": True},
    }) == "exit_ticket_unavailable_after_correct_practice"
    assert _safe_blocked_reason({
        "content_blocked": {"message": "redacted"},
        "answer_feedback": {"is_correct": False},
    }) == "remediation_unavailable_after_wrong_practice"

    with TemporaryDirectory() as directory:
        app_root = Path(directory) / "app"
        flattened_content = app_root / "knowledge_base/history/autotutor_content.json"
        flattened_content.parent.mkdir(parents=True)
        flattened_content.write_text("{}", encoding="utf-8")
        module_path = app_root / "agents/autotutor_content.py"
        assert _resolve_content_path(module_path) == flattened_content.resolve()

    _assert_operational_safety({
        "aggregate": {
            "assigned_graph_count": 0,
            "blockers": ["comparator_not_exact", "fallback_rate_above_one_percent"],
        },
        "observation_health": {"ok": True},
    })
    try:
        _assert_operational_safety({
            "aggregate": {
                "assigned_graph_count": 1,
                "blockers": ["fallback_rate_above_one_percent"],
            },
            "observation_health": {"ok": True},
        })
        raise AssertionError("observed Graph fallback rate did not stop traffic")
    except RuntimeError as exc:
        assert str(exc) == "verification_safety_stop:fallback_rate_above_one_percent"

    _assert_operational_safety({
        "aggregate": {
            "assigned_graph_count": 19,
            "blockers": ["active_latency_regression"],
        },
        "observation_health": {"ok": True},
    })
    try:
        _assert_operational_safety({
            "aggregate": {
                "assigned_graph_count": 20,
                "blockers": ["active_latency_regression"],
            },
            "observation_health": {"ok": True},
        })
        raise AssertionError("mature Graph latency regression did not stop traffic")
    except RuntimeError as exc:
        assert str(exc) == "verification_safety_stop:active_latency_regression"

    actor = next(
        f"verification-{index}" for index in range(10_000)
        if stable_executor_bucket(f"verification-{index}", salt=SALT) < 100
    )
    requests = []
    states = iter([
        {"session_id": "private-session", "status": "awaiting_answer", "revision": 1,
         "current_question": public_question},
        {"session_id": "private-session", "status": "completed", "revision": 2},
    ])

    def urlopen(request, timeout=30):
        requests.append(request)
        url = request.full_url
        if "/verification?" in url:
            return Response({
                "aggregate": {"assigned_control_count": 100, "control_latency": {"p95_ms": 100}},
                "deployment": {"environment": "production", "deployed_commit": COMMIT},
                "configuration": {"mode": "active_canary", "active_bps": 100,
                                  "config_version": CONFIG, "kill_switch": False},
            })
        if url.endswith("/api/auth/login"):
            return Response({"role": "student", "actor_id": actor, "token": "student-jwt"})
        return Response(next(states))

    env = {
        "AUTOTUTOR_VERIFICATION_ENVIRONMENT": "production-verification",
        "AUTOTUTOR_PRODUCTION_API_TOKEN": "m" * 40,
        "AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256": "c" * 64,
        "AUTOTUTOR_PRODUCTION_ALLOWED_HOSTS": "edu.example",
        "AUTOTUTOR_GRAPH_BUCKET_SALT": SALT,
        "AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET": "t" * 48,
        "AUTOTUTOR_VERIFICATION_STUDENT_CREDENTIALS_JSON": json.dumps([
            {"actor_id": actor, "username": "private-user", "password": "private-password"}
        ]),
    }
    receipt = run_traffic(
        control_start=CONTROL_START,
        api_base="https://edu.example", expected_commit=COMMIT,
        expected_config_version=CONFIG, phase="canary", target_transitions=2,
        maximum_sessions=2, timeout_seconds=30, env=env, urlopen=urlopen, sleep=lambda _: None,
    )
    assert receipt["target_reached"] is True and receipt["transitions_sent"] == 2
    serialized = json.dumps(receipt)
    for secret in (actor, "private-user", "private-password", "student-jwt", SALT, "t" * 48):
        assert secret not in serialized
    transition_requests = [request for request in requests if "/api/autotutor/" in request.full_url]
    assert len(transition_requests) == 2
    start_payload = json.loads(transition_requests[0].data.decode("utf-8"))
    assert start_payload["focus_tags"] == ["戊戌变法失败原因"]
    answer_payload = json.loads(transition_requests[1].data.decode("utf-8"))
    assert answer_payload["answer"] == "C"
    attestations = [request.headers.get("X-autotutor-verification-attestation") for request in transition_requests]
    assert all(attestations) and len(set(attestations)) == 2
    assert all(request.headers.get("X-autotutor-verification-run") for request in transition_requests)
    checks = [urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
              for request in requests if "/verification?" in request.full_url]
    assert all(check["window_start"] == [CONTROL_START] for check in checks)
    assert checks[-1]["window_end"][0] > checks[0]["window_end"][0]

    flaky_requests = []
    flaky_states = iter([
        {"session_id": "retry-session", "status": "awaiting_answer", "revision": 1,
         "current_question": public_question},
        {"session_id": "retry-session", "status": "completed", "revision": 2},
    ])
    transient_failures = 0

    def flaky_urlopen(request, timeout=30):
        nonlocal transient_failures
        url = request.full_url
        if "/verification?" in url:
            return Response({
                "aggregate": {"assigned_control_count": 100, "control_latency": {"p95_ms": 100}},
                "deployment": {"environment": "production", "deployed_commit": COMMIT},
                "configuration": {"mode": "active_canary", "active_bps": 100,
                                  "config_version": CONFIG, "kill_switch": False},
            })
        if url.endswith("/api/auth/login"):
            return Response({"role": "student", "actor_id": actor, "token": "student-jwt"})
        flaky_requests.append(request)
        if transient_failures < 2:
            transient_failures += 1
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", None, None)
        return Response(next(flaky_states))

    retry_receipt = run_traffic(
        control_start=CONTROL_START,
        api_base="https://edu.example", expected_commit=COMMIT,
        expected_config_version=CONFIG, phase="canary", target_transitions=2,
        maximum_sessions=2, timeout_seconds=30, env=env, urlopen=flaky_urlopen, sleep=lambda _: None,
    )
    assert retry_receipt["target_reached"] is True and retry_receipt["transitions_sent"] == 2
    assert len(flaky_requests) == 4
    retried_start_payloads = [request.data for request in flaky_requests[:3]]
    assert len(set(retried_start_payloads)) == 1

    failed_requests = []

    def unavailable_urlopen(request, timeout=30):
        url = request.full_url
        if "/verification?" in url:
            return Response({
                "aggregate": {"assigned_control_count": 100, "control_latency": {"p95_ms": 100}},
                "deployment": {"environment": "production", "deployed_commit": COMMIT},
                "configuration": {"mode": "active_canary", "active_bps": 100,
                                  "config_version": CONFIG, "kill_switch": False},
            })
        if url.endswith("/api/auth/login"):
            return Response({"role": "student", "actor_id": actor, "token": "student-jwt"})
        failed_requests.append(request)
        raise urllib.error.HTTPError(url, 502, "Bad Gateway", None, None)

    try:
        run_traffic(
            control_start=CONTROL_START,
            api_base="https://edu.example", expected_commit=COMMIT,
            expected_config_version=CONFIG, phase="canary", target_transitions=2,
            maximum_sessions=2, timeout_seconds=30, env=env,
            urlopen=unavailable_urlopen, sleep=lambda _: None,
        )
        raise AssertionError("three consecutive server errors did not stop traffic")
    except RuntimeError as exc:
        assert str(exc) == "consecutive_server_errors"
    assert len(failed_requests) == 3
    assert len(set(request.data for request in failed_requests)) == 1

    blocked_states = iter([
        {
            "session_id": "blocked-session", "status": "needs_content", "revision": 1,
            "content_blocked": {"reason": "missing_reviewed_content"},
        },
    ])

    def blocked_urlopen(request, timeout=30):
        url = request.full_url
        if "/verification?" in url:
            return Response({
                "aggregate": {"assigned_control_count": 100, "control_latency": {"p95_ms": 100}},
                "deployment": {"environment": "production", "deployed_commit": COMMIT},
                "configuration": {"mode": "active_canary", "active_bps": 100,
                                  "config_version": CONFIG, "kill_switch": False},
            })
        if url.endswith("/api/auth/login"):
            return Response({"role": "student", "actor_id": actor, "token": "student-jwt"})
        return Response(next(blocked_states))

    try:
        run_traffic(
            control_start=CONTROL_START,
            api_base="https://edu.example", expected_commit=COMMIT,
            expected_config_version=CONFIG, phase="canary", target_transitions=2,
            maximum_sessions=2, timeout_seconds=30, env=env,
            urlopen=blocked_urlopen, sleep=lambda _: None,
        )
        raise AssertionError("unusable verification content did not stop traffic")
    except RuntimeError as exc:
        assert str(exc) == "verification_content_target_unavailable:missing_reviewed_content"
    # No login or transition is allowed when the selected exact window has no baseline.
    def no_baseline(request, timeout=30):
        assert "/verification?" in request.full_url
        return Response({
            "deployment": {"environment": "production", "deployed_commit": COMMIT},
            "configuration": {"mode": "active_canary", "active_bps": 100, "config_version": CONFIG},
            "aggregate": {"assigned_control_count": 99, "control_latency": {"p95_ms": 100}},
        })
    try:
        run_traffic(api_base="https://edu.example", expected_commit=COMMIT,
                    expected_config_version=CONFIG, phase="canary", target_transitions=2,
                    maximum_sessions=2, timeout_seconds=30, env=env,
                    control_start=CONTROL_START, urlopen=no_baseline)
        raise AssertionError("missing baseline allowed traffic")
    except ValueError as exc:
        assert str(exc) == "verification_control_baseline_insufficient"

    # Deterministic clock: retry transient reads, bound total time and never retry auth errors.
    for failures, expected_attempts, succeeds in [
        ([TimeoutError("private-host"), 503], 3, True),
        ([401], 1, False), ([403], 1, False), ([400], 1, False),
        ([TimeoutError("private-host")] * 10, 6, False),
    ]:
        ticks = [0.0]
        calls = []
        pending = list(failures)
        def fake_read(request, timeout=30):
            calls.append(timeout)
            if pending:
                item = pending.pop(0)
                if isinstance(item, int):
                    raise urllib.error.HTTPError(request.full_url, item, "private body", None, None)
                raise item
            return Response({"ok": True})
        def advance(seconds):
            ticks[0] += seconds
        try:
            value, diagnostic = _request_preflight("https://edu.example/preflight", headers={},
                deadline=180, urlopen=fake_read, sleep=advance, monotonic=lambda: ticks[0])
            assert succeeds and value == {"ok": True}
        except PreflightUnavailable as exc:
            assert not succeeds
            diagnostic = exc.diagnostics
        assert len(calls) == expected_attempts
        assert "private" not in json.dumps(diagnostic)
        assert ticks[0] <= 180

    ticks = [0.0]
    def slow_read(request, timeout=30):
        ticks[0] += timeout
        raise TimeoutError()
    try:
        _request_preflight("https://edu.example/preflight", headers={}, deadline=12,
            urlopen=slow_read, sleep=lambda seconds: None, monotonic=lambda: ticks[0])
        raise AssertionError("exhausted deadline accepted")
    except PreflightUnavailable as exc:
        assert ticks[0] == 12 and exc.diagnostics["attempts"] == 1
    with TemporaryDirectory() as directory:
        output = Path(directory) / "failed-receipt.json"
        argv = ["traffic", "--api-base", "https://edu.example", "--expected-commit", COMMIT,
                "--expected-config-version", CONFIG, "--phase", "canary",
                "--control-window-start", CONTROL_START, "--receipt-output", str(output)]
        with patch.object(sys, "argv", argv), patch(
            "scripts.run_autotutor_canary_verification_traffic.run_traffic",
            side_effect=PreflightUnavailable({"stage": "preflight", "attempts": 6, "reason": "http_503"}),
        ):
            assert traffic_main() == 7
        failed_receipt = json.loads(output.read_text())
        assert failed_receipt["target_reached"] is False and failed_receipt["transitions_sent"] == 0
        assert failed_receipt["preflight"]["reason"] == "http_503"
    print("autotutor_verification_traffic_smoke=PASS")


if __name__ == "__main__":
    main()
