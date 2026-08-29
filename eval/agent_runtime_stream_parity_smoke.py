from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-parity-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "stream-parity-test"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS"] = "10000"

import agents.learning_assistant as assistant  # noqa: E402
from agent_runtime.event_store import list_run_events  # noqa: E402


class Response:
    content = "这是同一执行源产生的确定性回答。"


class FakeModel:
    model = "fake-runtime-parity"

    def invoke(self, _messages):
        return Response()


def main() -> None:
    original = assistant.llm_fast
    assistant.llm_fast = FakeModel()
    request = {
        "message": "你好，请简单介绍你能做什么",
        "student_id": "student-parity",
        "session_id": "session-parity",
        "actor_id": "student-parity",
        "actor_role": "student",
        "trace_id": "trace-parity",
        "idempotency_key": "learning-parity-0001",
    }
    try:
        first = list(assistant.stream_learning_assistant_events(dict(request)))
        second = list(assistant.stream_learning_assistant_events(dict(request)))
    finally:
        assistant.llm_fast = original
    first_final = next(data for event, data in first if event == "final")
    second_final = next(data for event, data in second if event == "final")
    assert first_final["run_id"] == second_final["run_id"]
    assert first_final["completion_status"] == second_final["completion_status"]
    assert first_final["response"] == second_final["response"]
    assert second_final["idempotent_replay"] is True
    persisted_events = list_run_events(first_final["run_id"])
    assert all(event.event not in {"generation_delta", "heartbeat"} for event in persisted_events)
    sequences = [event.sequence for event in persisted_events]
    assert sequences == sorted(set(sequences))
    print("agent_runtime_stream_parity_smoke=PASS")


if __name__ == "__main__":
    main()
