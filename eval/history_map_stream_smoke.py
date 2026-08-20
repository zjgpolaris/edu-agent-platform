from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["EDU_AGENT_AUTH_REQUIRED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
import agents.history_map_agent as history_map  # noqa: E402
from api.main import app  # noqa: E402


class UnavailableLlm:
    def stream(self, _messages):
        raise RuntimeError("provider credentials are not configured")
        yield ""  # pragma: no cover - keeps this method a generator

    def invoke(self, _messages):
        raise RuntimeError("provider credentials are not configured")


def main() -> None:
    original_llm = history_map.llm
    original_retrieve = history_map._retrieve_context
    history_map.llm = UnavailableLlm()
    history_map._retrieve_context = lambda _event, _query: []
    try:
        events = list(history_map.stream_map_narrate("battle_changping"))
    finally:
        history_map.llm = original_llm
        history_map._retrieve_context = original_retrieve

    final = next(item["data"] for item in events if item["event"] == "final")
    assert final["response"], final
    assert "长平" in final["response"], final
    assert final["generation_mode"] == "fallback", final
    assert final["degraded"] is True, final
    assert any(item["event"] == "delta" for item in events), events
    assert any(item["event"] == "map_actions" for item in events), events

    original_stream = history_map.stream_map_narrate

    def broken_stream(_event_id: str, _user_query: str = ""):
        raise RuntimeError("unexpected stream failure")

    history_map.stream_map_narrate = broken_stream
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.get("/api/history/geo/narrate?event_id=battle_changping")
    finally:
        history_map.stream_map_narrate = original_stream

    assert response.status_code == 200, response.text
    assert "地图讲解暂不可用" in response.text, response.text
    print("history_map_stream_smoke=PASS")


if __name__ == "__main__":
    main()
