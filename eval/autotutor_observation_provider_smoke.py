"""Observation provider captures source inputs once and preserves caller state."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents import auto_tutor as at  # noqa: E402
from agents.autotutor_execution import AutoTutorExecutionContext  # noqa: E402
from agents.autotutor_observations import DefaultAutoTutorObservationProvider  # noqa: E402


def main() -> None:
    before = at.AutoTutorState(
        session_id="provider-smoke",
        trace_id="trace-provider-smoke",
        student_id="provider-smoke-student",
        created_at=1.0,
        updated_at=1.0,
    )
    original = before.model_dump(mode="json")
    plan = [at.LessonStep(knowledge_point="洋务运动目的", difficulty="medium")]

    with (
        patch.object(at, "get_student_profile", return_value=type("Profile", (), {"grade": "八年级", "weak_topics": [], "recent_topics": []})()),
        patch.object(at, "get_weakpoints", return_value=[]),
        patch.object(at, "_generate_plan", return_value=plan),
        patch.object(at, "_KERNEL_ACT", return_value=None) as act,
    ):
        bundle = DefaultAutoTutorObservationProvider().prepare(
            before=before,
            command={"transition_kind": "start", "focus_tags": ["洋务运动目的"]},
            context=AutoTutorExecutionContext(),
        )

    assert act.call_count == 1
    assert before.model_dump(mode="json") == original
    assert bundle.schema_version == "v1.49.1-observation"
    assert bundle.transition_kind == "start"
    bundle.assert_no_derived_outcome()
    payload = bundle.model_dump(mode="json")
    assert not any(key in payload for key in ("materialized", "legacy_after", "expected_state", "expected_projection"))
    print("autotutor_observation_provider_smoke=PASS")


if __name__ == "__main__":
    main()
