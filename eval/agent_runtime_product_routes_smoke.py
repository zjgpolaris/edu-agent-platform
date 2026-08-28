from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-product-routes-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_DEBATE_BPS"] = "10000"

from fastapi.testclient import TestClient  # noqa: E402
import agents.debate_supervisor as debate  # noqa: E402
import agents.history_character as character  # noqa: E402
import rag.knowledge_base as knowledge_base  # noqa: E402
from agent_runtime.event_store import get_run, list_run_events  # noqa: E402
from api.main import app  # noqa: E402
from api.routers.history import _debate_runtime_outcome  # noqa: E402


character_executions: list[str] = []


def fake_character_stream(state, _retriever):
    character_executions.append(str(state.get("session_id") or "unknown"))
    state["memory_updated"] = True
    state["verified"] = True
    state["verification_status"] = "verified"
    yield {"event": "sources", "data": {"sources": [{"source_id": "history:test"}]}}
    yield {"event": "final", "data": {
        "response": "【回答】有据回答\n【史料依据】[history:test]\n【学习提示】继续核验",
        "sources": [{"source_id": "history:test"}],
        "verified": True,
        "verification_status": "verified",
        "verification_reason": None,
        "completion_status": "completed",
    }}
    yield {"event": "fact_card", "data": {"card": {"key_facts": ["有据事实"]}}}


async def fake_debate_run(topic: str, *, trace_id: str | None = None):
    claim_source = "S2" if topic == "未知来源辩题" else "S1"
    return {
        "topic": topic,
        "trace_id": trace_id,
        "rounds": [{"side": "pro", "argument": "[S1]", "round": 1}],
        "sources": [{"citation_label": "S1"}],
        "fact_check": {"claims": [{"claim_id": "fact_1", "supported": True, "source_ids": [claim_source]}]},
        "verdict": "有据裁判",
        "coach_summary": "核验来源",
        "completion_status": "completed",
    }


def main() -> None:
    assert _debate_runtime_outcome({
        "sources": [{"citation_label": "S1"}],
        "fact_check": {"claims": [{"supported": True, "source_ids": ["S1"]}]},
        "completion_status": "completed",
        "generation_mode": "fallback",
        "fallback_roles": ["pro_debater"],
    }) == ("partial", "verified", ["debate_generation_degraded"])

    original_character = character.stream_character_response
    original_retriever = knowledge_base.get_retriever
    original_debate = debate.run_debate
    character.stream_character_response = fake_character_stream
    knowledge_base.get_retriever = lambda _name: object()
    debate.run_debate = fake_debate_run
    try:
        with TestClient(app) as client:
            character_payload = {
                "character": "测试人物",
                "message": "请给出有据回答",
                "student_id": "student-route",
                "session_id": "character-route",
                "stream": False,
                "idempotency_key": "character-route-0001",
            }
            first = client.post("/api/history/character/chat", json=character_payload)
            assert first.status_code == 200, first.text
            first_data = first.json()
            run = get_run(first_data["run_id"])
            assert run["status"] == "completed"
            assert character_executions == ["character-route"], character_executions
            first_events = list_run_events(run["run_id"])
            assert all(event.event != "product_event" for event in first_events), first_events
            first_event_count = len(first_events)
            replay = client.post("/api/history/character/chat", json=character_payload)
            assert replay.status_code == 200, replay.text
            assert replay.json()["run_id"] == run["run_id"]
            assert replay.json()["idempotent_replay"] is True
            assert len(list_run_events(run["run_id"])) == first_event_count
            streamed_replay = client.post(
                "/api/history/character/chat",
                json={**character_payload, "stream": True},
            )
            assert streamed_replay.status_code == 200
            assert run["run_id"] in streamed_replay.text
            assert "idempotent_replay" in streamed_replay.text
            assert len(list_run_events(run["run_id"])) == first_event_count
            assert character_executions == ["character-route"], character_executions

            fresh_stream = client.post(
                "/api/history/character/chat",
                json={
                    **character_payload,
                    "session_id": "character-route-stream",
                    "idempotency_key": "character-route-stream-0001",
                    "stream": True,
                },
            )
            assert fresh_stream.status_code == 200, fresh_stream.text
            assert "event: sources" in fresh_stream.text
            assert "event: final" in fresh_stream.text
            assert "event: runtime_terminal" in fresh_stream.text
            assert character_executions == ["character-route", "character-route-stream"], character_executions

            debate_payload = {"topic": "测试辩题", "idempotency_key": "debate-route-0001"}
            debate_response = client.post("/api/history/debate/start", json=debate_payload)
            assert debate_response.status_code == 200, debate_response.text
            debate_data = debate_response.json()
            assert debate_data["completion_status"] == "completed"
            assert get_run(debate_data["run_id"])["status"] == "completed"
            debate_stream_replay = client.post("/api/history/debate/stream", json=debate_payload)
            assert debate_stream_replay.status_code == 200
            assert debate_data["run_id"] in debate_stream_replay.text
            unknown_source = client.post(
                "/api/history/debate/start",
                json={"topic": "未知来源辩题", "idempotency_key": "debate-route-unknown-0001"},
            )
            assert unknown_source.status_code == 200, unknown_source.text
            unknown_data = unknown_source.json()
            assert unknown_data["completion_status"] == "partial"
            assert get_run(unknown_data["run_id"])["status"] == "partial"
    finally:
        character.stream_character_response = original_character
        knowledge_base.get_retriever = original_retriever
        debate.run_debate = original_debate

    print("agent_runtime_product_routes_smoke=PASS")


if __name__ == "__main__":
    main()
