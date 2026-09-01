"""Deterministic contract for the student-safe AutoTutor demo journey."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_demo_trace import project_demo_trace  # noqa: E402


def main() -> None:
    state = {
        "session_id": "at_demo",
        "status": "awaiting_answer",
        "runtime_steps": [
            {
                "sequence": 1,
                "event_type": "plan",
                "status": "success",
                "latency_ms": 12.4,
                "metadata": {
                    "targeted_points": ["洋务运动目的"],
                    "prompt": "secret prompt",
                    "authorization": "Bearer secret",
                },
            },
            {
                "sequence": 2,
                "event_type": "reflect",
                "status": "success",
                "metadata": {
                    "diagnosis": "raw model diagnosis",
                    "password": "secret",
                    "chain_of_thought": "hidden",
                    "decision_provenance": {
                        "decision_source": "deterministic_fallback",
                        "provider": None,
                        "request_id": "secret-request",
                    },
                },
            },
            {
                "sequence": 3,
                "event_type": "re_plan",
                "status": "success",
                "metadata": {"adjustment": "reteach", "database_url": "postgres://secret"},
            },
            {"sequence": 4, "event_type": "unknown_internal_event", "status": "success", "metadata": {"token": "secret"}},
        ],
    }
    payload = project_demo_trace(state)
    assert [event["phase"] for event in payload["events"]] == ["plan", "reflect", "re_plan"], payload
    assert payload["events"][0]["duration_ms"] == 12.4, payload
    assert "补讲核心概念" in payload["events"][2]["summary"], payload
    assert payload["events"][0]["decision_source"] == "policy", payload
    assert payload["events"][1]["decision_source"] == "deterministic_fallback", payload
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for secret in ("secret", "authorization", "password", "database_url", "chain_of_thought", "raw model diagnosis", "request_id"):
        assert secret not in serialized, serialized
    print("demo_trace_projection_smoke=PASS")


if __name__ == "__main__":
    main()
