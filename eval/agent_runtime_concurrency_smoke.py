from __future__ import annotations

import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-concurrency-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from agent_runtime.event_store import StaleRevisionError, append_run_event, create_run, list_run_events  # noqa: E402
from agent_runtime.models import AgentContext  # noqa: E402
import agents.auto_tutor as auto_tutor  # noqa: E402
from services.learning_assistant_session_service import append_idempotent_user_message, create_session, list_messages  # noqa: E402


def main() -> None:
    context = AgentContext(
        run_id="run_cas",
        agent_type="learning_assistant",
        actor_id="student-cas",
        actor_role="student",
        student_id="student-cas",
        trace_id="trace-cas",
        durability_mode="observable",
        config_version="cas-test",
    )
    create_run(context, objective="CAS")
    barrier = threading.Barrier(2)

    def append_once(index: int) -> str:
        barrier.wait()
        try:
            append_run_event("run_cas", expected_revision=0, event_type="route_decided", public_payload={"worker": index}, next_status="routed")
            return "ok"
        except StaleRevisionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append_once, (1, 2)))
    assert sorted(outcomes) == ["ok", "stale"], outcomes
    sequences = [event.sequence for event in list_run_events("run_cas")]
    assert sequences == [1, 2], sequences

    started = auto_tutor.start_session("student-cas", grade="八年级上册", idempotency_key="start-cas-0001")
    session_id = started["session_id"]
    internal = auto_tutor._load_persisted_session(session_id)
    assert internal is not None
    answer = str((internal.lesson_plan[internal.current_step_index].question or {}).get("answer") or "A")
    answer_barrier = threading.Barrier(2)

    def submit_once(index: int) -> dict:
        answer_barrier.wait()
        return auto_tutor.submit_answer(
            session_id,
            answer,
            expected_revision=started["revision"],
            idempotency_key=f"same-answer-transition-{index}" if False else "same-answer-transition-0001",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(submit_once, (1, 2)))
    final = auto_tutor.get_session(session_id)
    final_internal = auto_tutor._load_persisted_session(session_id)
    assert final_internal is not None
    assert final["revision"] == started["revision"] + 1, final
    assert len(final_internal.step_history) == 1
    assert sum(bool(item.get("idempotent_replay")) or bool(item.get("stale_answer_ignored")) for item in answers) >= 1

    assistant_session = create_session("student-cas", source_feature="standalone")
    message_barrier = threading.Barrier(2)

    def persist_user_once(_: int) -> str:
        message_barrier.wait()
        return append_idempotent_user_message(
            assistant_session["session_id"],
            "并发重试只保留一条用户消息",
            idempotency_key="learning-message-cas-0001",
            source_feature="standalone",
        )["message_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        message_ids = list(pool.map(persist_user_once, (1, 2)))
    assert len(set(message_ids)) == 1, message_ids
    persisted_messages = list_messages(assistant_session["session_id"], limit=100)
    assert len(persisted_messages) == 1, persisted_messages

    print("agent_runtime_concurrency_smoke=PASS")


if __name__ == "__main__":
    main()
