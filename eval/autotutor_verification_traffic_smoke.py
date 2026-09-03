"""The traffic runner is bounded, signed and emits a PII-free receipt."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_execution import stable_executor_bucket  # noqa: E402
from scripts.run_autotutor_canary_verification_traffic import (  # noqa: E402
    _assert_operational_safety,
    run_traffic,
)

COMMIT = "b" * 40
CONFIG = "v1.49.9-production-canary"
SALT = "runner-smoke-salt"


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

    actor = next(
        f"verification-{index}" for index in range(10_000)
        if stable_executor_bucket(f"verification-{index}", salt=SALT) < 100
    )
    requests = []
    states = iter([
        {"session_id": "private-session", "status": "awaiting_answer", "revision": 1,
         "current_question": {"assessment_id": "wuxu-cause-practice-1"}},
        {"session_id": "private-session", "status": "completed", "revision": 2},
    ])

    def urlopen(request, timeout=30):
        requests.append(request)
        url = request.full_url
        if "/verification?" in url:
            return Response({
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
    attestations = [request.headers.get("X-autotutor-verification-attestation") for request in transition_requests]
    assert all(attestations) and len(set(attestations)) == 2
    assert all(request.headers.get("X-autotutor-verification-run") for request in transition_requests)

    blocked_states = iter([
        {"session_id": "blocked-session", "status": "needs_content", "revision": 1},
    ])

    def blocked_urlopen(request, timeout=30):
        url = request.full_url
        if "/verification?" in url:
            return Response({
                "deployment": {"environment": "production", "deployed_commit": COMMIT},
                "configuration": {"mode": "active_canary", "active_bps": 100,
                                  "config_version": CONFIG, "kill_switch": False},
            })
        if url.endswith("/api/auth/login"):
            return Response({"role": "student", "actor_id": actor, "token": "student-jwt"})
        return Response(next(blocked_states))

    try:
        run_traffic(
            api_base="https://edu.example", expected_commit=COMMIT,
            expected_config_version=CONFIG, phase="canary", target_transitions=2,
            maximum_sessions=2, timeout_seconds=30, env=env,
            urlopen=blocked_urlopen, sleep=lambda _: None,
        )
        raise AssertionError("unusable verification content did not stop traffic")
    except RuntimeError as exc:
        assert str(exc) == "verification_content_target_unavailable"
    print("autotutor_verification_traffic_smoke=PASS")


if __name__ == "__main__":
    main()
