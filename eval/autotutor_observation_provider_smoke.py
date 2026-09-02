"""Observation provider captures once and never mutates its caller-owned input."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_execution import (  # noqa: E402
    AutoTutorExecutionContext,
    AutoTutorTransitionOutcome,
    CapturedAutoTutorObservationProvider,
)


def main() -> None:
    calls = 0

    def produce(candidate: dict, command: dict, _context: AutoTutorExecutionContext) -> AutoTutorTransitionOutcome:
        nonlocal calls
        calls += 1
        candidate["revision"] += 1
        return AutoTutorTransitionOutcome(executor_mode="legacy", next_state=candidate, public_result={"answer": command["answer"]})

    before = {"revision": 4, "lesson_plan": [{"status": "active"}]}
    provider = CapturedAutoTutorObservationProvider("lesson_answer", produce)
    bundle = provider.prepare(
        before=before,
        command={"answer": "A"},
        context=AutoTutorExecutionContext(),
    )
    assert calls == 1
    assert before == {"revision": 4, "lesson_plan": [{"status": "active"}]}
    assert bundle.schema_version == "v1.49-observation"
    assert bundle.transition_kind == "lesson_answer"
    assert not any(key in bundle.model_dump() for key in ("legacy_after", "expected_state", "expected_projection"))
    print("autotutor_observation_provider_smoke=PASS")


if __name__ == "__main__":
    main()
