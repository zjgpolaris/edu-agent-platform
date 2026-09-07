"""Timing isolation, missing-field semantics and real transition instrumentation."""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from agents import autotutor_timing as timing


def main():
    barrier = threading.Barrier(2)
    @timing.transition_timing
    def transition(mode):
        timing.dimension("selected_executor", mode)
        timing.dimension("verification_run_id", "private-run")
        timing.dimension("student_id", "private-student")
        timing.timed_call("session_read", barrier.wait, 2)
        if mode == "legacy":
            raise ValueError("private-exception")
        return {"private": "private-result"}
    with patch.object(timing._logger, "info") as log, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(transition, mode) for mode in ("legacy", "graph_active")]
        try:
            futures[0].result(3)
            raise AssertionError("exception swallowed")
        except ValueError:
            pass
        assert futures[1].result(3) == {"private": "private-result"}
    records = [json.loads(call.args[0]) for call in log.call_args_list]
    assert len(records) == 2 and "private" not in json.dumps(records)
    assert {r["selected_executor"]: r["status"] for r in records} == {"legacy": "failed", "graph_active": "returned"}
    assert all("session_read" in r["phases_ms"] and "admission" not in r["phases_ms"] for r in records)
    assert timing._current.get() is None
    @timing.transition_timing
    def replay():
        return {"idempotent_replay": True}
    with patch.object(timing._logger, "info", side_effect=RuntimeError("log failed")):
        assert replay()["idempotent_replay"]

    # Exercise actual start/answer/exit/fallback/replay calls on an isolated DB.
    from autotutor_langgraph_active_transaction_smoke import main as transactions
    with patch.object(timing._logger, "info") as log:
        transactions()
    records = [json.loads(call.args[0]) for call in log.call_args_list]
    committed = [r for r in records if "observation_write" in r["phases_ms"]]
    assert {r["transition_kind"] for r in committed} >= {"start", "lesson_answer", "exit_ticket_answer"}
    assert {r["selected_executor"] for r in committed} == {"legacy", "graph_active"}
    assert all("business_commit" in r["phases_ms"] and "execution_components_ms" in r for r in committed)
    assert all("business_schema" in r["phases_ms"] for r in committed)
    assert any("session_claim" in r["phases_ms"] for r in committed)
    assert "active-transition-student" not in json.dumps(records)
    print("autotutor_transition_timing_smoke=PASS")


if __name__ == "__main__":
    main()
