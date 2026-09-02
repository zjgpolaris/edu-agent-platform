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
from agents.autotutor_graph import execute_autotutor_active  # noqa: E402
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
    os.environ["EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE"] = "shadow"

    def capture(observation):
        captured["observation"] = observation
        return execute_autotutor_active(observation)

    with patch("agents.autotutor_graph.execute_autotutor_active", side_effect=capture) as graph_spy:
        started = at.start_session("shadow-isolation", actor_role="student")
    assert graph_spy.call_count == 1
    observation = captured["observation"]
    assert observation.transition_kind == "start"
    assert not any(key in observation.model_dump() for key in ("legacy_after", "expected_state", "expected_projection"))

    # Shadow failure is diagnostic and cannot remove the active Legacy start.
    with patch("agents.autotutor_graph.execute_autotutor_active", side_effect=RuntimeError("graph down")):
        failure_safe = at.start_session("shadow-failure-safe", actor_role="student")
    persisted = at._load_persisted_session(failure_safe["session_id"])
    assert persisted is not None, "active start was not committed before Shadow failure"
    assert persisted.revision == failure_safe["revision"]

    # A candidate answer invokes pre-commit Shadow once; replay/stale/busy do not.
    sid = started["session_id"]
    state = at._load_persisted_session(sid)
    assert state is not None
    answer = _correct_answer(sid)
    with patch("agents.autotutor_graph.execute_autotutor_active", wraps=execute_autotutor_active) as shadow_spy:
        first = at.submit_answer(
            sid,
            answer,
            actor_role="student",
            expected_revision=state.revision,
            idempotency_key="shadow-isolation-answer",
        )
        assert shadow_spy.call_count == 1, "candidate transition did not invoke Shadow"
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
