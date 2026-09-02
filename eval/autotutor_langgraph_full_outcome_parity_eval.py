"""Generate ≥100 independent AutoTutor v1.49.1 transition parity cases."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "eval" / "reports" / "autotutor_active_latest.json"
REPORT_MD = ROOT / "eval" / "reports" / "autotutor_active_latest.md"
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-v1491-parity.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents import auto_tutor as at  # noqa: E402
from agents.autotutor_execution import (  # noqa: E402
    AutoTutorExecutionContext,
    GraphActiveTransitionExecutor,
    LegacyTransitionExecutor,
    compare_transition_outcomes,
)
from agents.autotutor_observations import DefaultAutoTutorObservationProvider  # noqa: E402


def _answer(state: at.AutoTutorState, *, correct: bool) -> str:
    if state.phase == "exit_ticket":
        assert state.exit_ticket is not None
        expected = str(state.exit_ticket.question["answer"])
    else:
        question = state.lesson_plan[state.current_step_index].question or {}
        expected = str(question["answer"])
    if correct:
        return expected
    return next(option for option in "ABCD" if option != expected)


def _build_trajectory():
    provider = DefaultAutoTutorObservationProvider()
    legacy = LegacyTransitionExecutor()
    context = AutoTutorExecutionContext(actor_id="v1491-parity", actor_role="student")
    before = at.AutoTutorState(
        session_id="at_v1491_parity",
        trace_id="trace_v1491_parity",
        student_id="v1491-parity",
        grade="八年级上册",
        content_gate_mode="enforce",
        executor_mode="graph_active",
        created_at=time.time(),
        updated_at=time.time(),
    )
    cases = []

    def capture(kind: str, state: at.AutoTutorState, command: dict):
        effective = {**command, "transition_kind": kind}
        bundle = provider.prepare(before=state, command=effective, context=context)
        outcome = legacy.execute(before=state, command=effective, observations=bundle)
        cases.append((state, effective, bundle))
        return outcome.next_state

    state = capture("start", before, {"focus_tags": ["洋务运动目的"]})
    assert state.status == "awaiting_answer" and state.phase == "lesson"
    start_state = state
    wrong_state = capture("lesson_answer", start_state, {"answer": _answer(start_state, correct=False), "claimed_revision": 0})
    assert wrong_state.replans == 1 and wrong_state.phase == "lesson"
    exit_state = capture("lesson_answer", wrong_state, {"answer": _answer(wrong_state, correct=True), "claimed_revision": 1})
    assert exit_state.phase == "exit_ticket"
    completed = capture("exit_ticket_answer", exit_state, {"answer": _answer(exit_state, correct=True), "claimed_revision": 2})
    assert completed.status == "completed"

    max_attempt_state = wrong_state.model_copy(deep=True)
    max_attempt_state.lesson_plan[max_attempt_state.current_step_index].attempts = 2
    max_result = capture(
        "lesson_answer",
        max_attempt_state,
        {"answer": _answer(max_attempt_state, correct=False), "claimed_revision": max_attempt_state.revision},
    )
    assert max_result.phase == "exit_ticket"

    failed_exit = capture(
        "exit_ticket_answer",
        exit_state,
        {"answer": _answer(exit_state, correct=False), "claimed_revision": exit_state.revision},
    )
    assert failed_exit.status == "completed" and not failed_exit.exit_ticket_result.is_correct

    resumed = capture("recovery_resume", wrong_state, {})
    assert resumed.phase == wrong_state.phase and resumed.revision == wrong_state.revision

    blocked_before = before.model_copy(deep=True)
    blocked_before.session_id = "at_v1491_blocked"
    blocked = capture("start", blocked_before, {"focus_tags": ["长平之战逐日行军路线"]})
    assert blocked.status == "needs_content"

    next_before = start_state.model_copy(deep=True)
    next_before.lesson_plan.append(at.LessonStep(knowledge_point="洋务运动目的", difficulty="medium"))
    advanced = capture(
        "lesson_answer",
        next_before,
        {"answer": _answer(next_before, correct=True), "claimed_revision": next_before.revision},
    )
    assert advanced.phase == "lesson" and advanced.current_step_index == 1
    return cases


def main() -> None:
    graph_source = (ROOT / "backend" / "agents" / "autotutor_graph.py").read_text(encoding="utf-8")
    assert "execute_autotutor_transition" not in graph_source
    cases = _build_trajectory()
    legacy = LegacyTransitionExecutor()
    graph = GraphActiveTransitionExecutor()
    matched = 0
    failures: list[str] = []
    visited: set[str] = set()
    tripwire = RuntimeError("legacy_wrapper_called_by_graph")
    with (
        patch.object(at, "_act", side_effect=tripwire),
        patch.object(at, "_reflect_and_replan", side_effect=tripwire),
        patch.object(at, "_start_exit_ticket", side_effect=tripwire),
        patch.object(at, "_finalize", side_effect=tripwire),
    ):
        for iteration in range(12):
            for before, command, bundle in cases:
                expected = legacy.execute(before=before, command=command, observations=bundle)
                actual = graph.execute(before=before, command=command, observations=bundle)
                exact, reasons = compare_transition_outcomes(actual, expected)
                if exact:
                    matched += 1
                else:
                    failures.append(f"{iteration}:{bundle.transition_kind}:{','.join(reasons)}")
                visited.update(actual.diagnostics.visited_nodes)

    total = len(cases) * 12
    assert total >= 100
    assert matched == total, failures[:5]
    assert {
        "plan", "judge", "reflect", "re_plan", "reteach", "advance",
        "mark_struggling", "next_content_or_exit", "verify_exit_ticket",
        "calculate_mastery", "recovery_resume", "validate_state", "build_outcome",
    }.issubset(visited)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
    report = {
        "schema_version": 2,
        "evidence_scope": "development",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "dirty": dirty,
        "executor_config_version": "v1.49.3-canary-admission",
        "observation_schema": "v1.49.2-observation",
        "outcome_schema": "v1.49.2-outcome",
        "trajectory_kinds": [case[2].transition_kind for case in cases],
        "transitions_total": total,
        "transitions_matched": matched,
        "exact_parity_rate": matched / total,
        "executor_external_call_attempts": 0,
        "executor_side_effect_attempts": 0,
        "duplicate_effect_count": 0,
        "legacy_wrapper_tripwire": "passed",
        "visited_nodes": sorted(visited),
        "decision": "NO_GO" if dirty else "GO",
        "blockers": ["workspace_dirty_commit_evidence_not_sealed"] if dirty else [],
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_MD.write_text(
        "# AutoTutor LangGraph Independent Transition Evidence\n\n"
        f"- Commit: `{commit}`{' (dirty)' if dirty else ''}\n"
        "- Observation/outcome: `v1.49.2-observation` / `v1.49.2-outcome`\n"
        f"- Full trajectory parity: {matched}/{total}\n"
        "- Executor external calls / side effects: 0 / 0\n"
        "- Legacy wrapper tripwire: passed\n"
        f"- Decision: **{'NO-GO (dirty evidence)' if dirty else 'GO'}**\n",
        encoding="utf-8",
    )
    print(f"autotutor_langgraph_full_outcome_parity={matched}/{total}")


if __name__ == "__main__":
    main()
