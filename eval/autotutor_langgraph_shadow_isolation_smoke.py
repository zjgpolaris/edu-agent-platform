"""Integration tripwires for AutoTutor Shadow external calls and writes."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-shadow-isolation.sqlite3"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
os.environ["EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_TIMEOUT_MS"] = "500"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from agents import auto_tutor as at  # noqa: E402
from agents.autotutor_shadow import (  # noqa: E402
    DenyShadowPorts,
    build_transition_envelope,
    capture_transition_observations,
    run_autotutor_shadow_transition,
)
from db.engine import get_connection  # noqa: E402


def _all_table_counts() -> dict[str, int]:
    with get_connection() as conn:
        names = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).scalars().all()
        return {
            name: int(conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one())
            for name in names
            if not name.startswith("sqlite_")
        }


def _correct_answer(session_id: str) -> str:
    state = at._store.get(session_id)
    assert state is not None
    if state.phase == "exit_ticket" and state.exit_ticket:
        return str(state.exit_ticket.question.get("answer") or "A")
    return str((state.lesson_plan[state.current_step_index].question or {}).get("answer") or "A")


def main() -> None:
    captured: dict = {}

    def capture(kind: str, **kwargs):
        captured.update({"kind": kind, **kwargs})

    with patch.object(at, "_maybe_run_langgraph_shadow_transition", side_effect=capture):
        started = at.start_session("shadow-isolation", actor_role="student")
    assert captured["kind"] == "start"
    observations = capture_transition_observations("start", captured["before"], captured["after"])
    envelope = build_transition_envelope(
        transition_kind="start",
        before=captured["before"],
        observations=observations,
    )
    counts_before = _all_table_counts()
    result = run_autotutor_shadow_transition(envelope, captured["after"])
    counts_after = _all_table_counts()
    assert result.matched, result
    assert result.external_call_attempts == 0, result
    assert result.side_effect_attempts == 0, result
    assert counts_after == counts_before, "direct Shadow changed database rows"

    attempted = DenyShadowPorts()
    attempted.attempts["model"] = 1
    denied = run_autotutor_shadow_transition(envelope, captured["after"], ports=attempted)
    assert "shadow_external_call_attempted" in denied.reason_codes, denied

    # Graph failure occurs only after the active start commit and cannot remove it.
    os.environ["EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED"] = "true"
    with patch("agents.autotutor_graph.AUTOTUTOR_SHADOW_GRAPH.invoke", side_effect=RuntimeError("graph down")):
        failure_safe = at.start_session("shadow-failure-safe", actor_role="student")
    persisted = at._load_persisted_session(failure_safe["session_id"])
    assert persisted is not None, "active start was not committed before Shadow failure"
    assert persisted.revision == failure_safe["revision"]

    # A committed answer invokes Shadow once; idempotent replay and stale revision do not.
    sid = started["session_id"]
    state = at._load_persisted_session(sid)
    assert state is not None
    answer = _correct_answer(sid)
    with patch.object(at, "_maybe_run_langgraph_shadow_transition") as shadow_spy:
        first = at.submit_answer(
            sid,
            answer,
            actor_role="student",
            expected_revision=state.revision,
            idempotency_key="shadow-isolation-answer",
        )
        assert shadow_spy.call_count == 1, "committed transition did not invoke Shadow"
        replay = at.submit_answer(
            sid,
            answer,
            actor_role="student",
            expected_revision=state.revision,
            idempotency_key="shadow-isolation-answer",
        )
        assert replay.get("idempotent_replay") is True
        assert shadow_spy.call_count == 1, "idempotent replay invoked Shadow"
        try:
            at.submit_answer(
                sid,
                "D" if answer != "D" else "C",
                actor_role="student",
                expected_revision=state.revision,
                idempotency_key="shadow-isolation-answer",
            )
        except at.AutoTutorIdempotencyConflict:
            pass
        else:
            raise AssertionError("idempotency conflict was not rejected")
        assert shadow_spy.call_count == 1, "conflict transition invoked Shadow"
        stale = at.submit_answer(
            sid,
            answer,
            actor_role="student",
            expected_revision=state.revision,
            idempotency_key="shadow-isolation-stale",
        )
        assert stale.get("stale_answer_ignored") is True
        assert shadow_spy.call_count == 1, "stale transition invoked Shadow"
        with patch.object(at, "_claim_answer_transition", return_value=("busy", None)):
            busy = at.submit_answer(
                sid,
                answer,
                actor_role="student",
                expected_revision=first["revision"],
                idempotency_key="shadow-isolation-busy",
            )
        assert busy.get("transition_in_progress") is True
        assert shadow_spy.call_count == 1, "busy transition invoked Shadow"
    assert first.get("revision") == state.revision + 1
    print("autotutor_langgraph_shadow_isolation_smoke=PASS")


if __name__ == "__main__":
    main()
