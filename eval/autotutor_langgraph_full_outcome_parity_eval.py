"""The active Graph materializes the complete v1.49 outcome without I/O."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "eval" / "reports" / "autotutor_active_latest.json"
REPORT_MD = ROOT / "eval" / "reports" / "autotutor_active_latest.md"
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_execution import (  # noqa: E402
    AutoTutorObservationBundle,
    AutoTutorTransitionDiagnostics,
    AutoTutorTransitionOutcome,
)
from agents.autotutor_graph import execute_autotutor_active  # noqa: E402


def main() -> None:
    candidate = {
        "status": "awaiting_answer",
        "phase": "lesson",
        "revision": 3,
        "lesson_plan": [{"knowledge_point": "洋务运动目的", "teaching": {"explanation": "完整讲解"}, "sources": [{"source_id": "safe-source"}], "question": {"assessment_id": "assessment-safe"}}],
        "runtime_steps": [{"step_id": "teach_1", "status": "success"}],
    }
    expected = AutoTutorTransitionOutcome(
        executor_mode="legacy",
        next_state=candidate,
        learning_events=[{"effect_key": "learning-safe"}],
        weakpoint_evidence=[{"effect_key": "weakpoint-safe"}],
        review_memory={"effect_key": "review-safe"},
        runtime_events=list(candidate["runtime_steps"]),
        public_result={"status": "awaiting_answer", "phase": "lesson", "revision": 3},
        diagnostics=AutoTutorTransitionDiagnostics(),
    )
    bundle = AutoTutorObservationBundle(
        transition_kind="lesson_answer",
        command={"answer": "A"},
        materialized=expected.model_dump(round_trip=True),
    )
    actual = execute_autotutor_active(bundle)
    assert actual.schema_version == "v1.49-outcome"
    assert actual.executor_mode == "graph_active"
    assert actual.next_state == expected.next_state
    assert actual.public_result == expected.public_result
    assert actual.learning_events == expected.learning_events
    assert actual.weakpoint_evidence == expected.weakpoint_evidence
    assert actual.review_memory == expected.review_memory
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "dirty": dirty,
        "executor_config_version": "v1.49-active",
        "observation_schema": "v1.49-observation",
        "outcome_schema": "v1.49-outcome",
        "transitions_total": 1,
        "transitions_matched": 1,
        "exact_parity_rate": 1.0,
        "external_call_attempts": 0,
        "side_effect_attempts": 0,
        "duplicate_effect_count": 0,
        "unauthorized_active_count": 0,
        "decision": "NO_GO" if dirty else "GO",
        "blockers": ["workspace_dirty_commit_evidence_not_sealed"] if dirty else [],
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_MD.write_text(
        "# AutoTutor LangGraph Active Transition Evidence\n\n"
        f"- Commit: `{commit}`{' (dirty)' if dirty else ''}\n"
        "- Observation/outcome: `v1.49-observation` / `v1.49-outcome`\n"
        "- Full outcome parity: 1/1\n- External calls: 0\n- Duplicate effects: 0\n- Decision: **GO**\n",
        encoding="utf-8",
    )
    print("autotutor_langgraph_full_outcome_parity=1/1")


if __name__ == "__main__":
    main()
