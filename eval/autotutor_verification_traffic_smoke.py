"""The traffic runner is bounded, signed and emits a PII-free receipt."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_execution import stable_executor_bucket  # noqa: E402
from scripts.run_autotutor_canary_verification_traffic import run_traffic  # noqa: E402

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
    attestations = [request.headers.get("X-autotutor-verification-attestation") for request in transition_requests]
    assert all(attestations) and len(set(attestations)) == 2
    assert all(request.headers.get("X-autotutor-verification-run") for request in transition_requests)
    print("autotutor_verification_traffic_smoke=PASS")


if __name__ == "__main__":
    main()
