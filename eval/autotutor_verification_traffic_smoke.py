"""The traffic runner is bounded, signed and emits a PII-free receipt."""
from __future__ import annotations

import json
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

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
    answer_payload = json.loads(transition_requests[1].data.decode("utf-8"))
    assert answer_payload["answer"] == "C"
    attestations = [request.headers.get("X-autotutor-verification-attestation") for request in transition_requests]
    assert all(attestations) and len(set(attestations)) == 2
    assert all(request.headers.get("X-autotutor-verification-run") for request in transition_requests)

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
        assert str(exc) == "verification_content_target_unavailable:missing_reviewed_content"
    print("autotutor_verification_traffic_smoke=PASS")


if __name__ == "__main__":
    main()
