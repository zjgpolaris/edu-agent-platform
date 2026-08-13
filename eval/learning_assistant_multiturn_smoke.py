"""Smoke: persistent sessions, follow-up context, recovery and owner isolation."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-learning-assistant-multiturn.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from agents import learning_assistant as la
from api.routers.learning import LearningAssistantRequest, learning_assistant_chat
from security.auth import Actor
from services.learning_assistant_session_service import append_message, create_session, get_latest_session, list_messages
from tools.base import ToolResult


def main() -> None:
    student_id = "multiturn-student"
    session = create_session(student_id)
    append_message(session["session_id"], "user", "鸦片战争为什么爆发？")
    append_message(session["session_id"], "assistant", "英国为打开中国市场发动战争。", intent="history_search")
    history = list_messages(session["session_id"])
    assert len(history) == 2
    assert get_latest_session(student_id)["session_id"] == session["session_id"]

    captured: dict = {}
    original_tool = la.run_tool
    original_invoke = la.llm_fast.invoke
    la.run_tool = lambda name, payload, context=None: (captured.update(payload=payload) or ToolResult(
        tool_name=name,
        ok=True,
        data={"sources": [{"topic": "鸦片战争", "snippet": "战后中国社会性质发生变化。"}]},
    ))

    class _Response:
        content = "这里的“它”指鸦片战争；战后中国开始沦为半殖民地半封建社会。"

    la.llm_fast.invoke = lambda messages: _Response()
    try:
        events = list(la.stream_learning_assistant_events({
            "message": "它有什么影响？",
            "student_id": student_id,
            "session_id": session["session_id"],
            "conversation_history": history,
            "actor_role": "student",
        }))
    finally:
        la.run_tool = original_tool
        la.llm_fast.invoke = original_invoke

    intent = next(data for event, data in events if event == "intent")
    final = next(data for event, data in events if event == "final")
    assert intent["intent"] == "history_search", intent
    assert "鸦片战争" in captured["payload"]["query"], captured
    assert "半殖民地" in final["response"], final
    assert final["context_usage"]["history_messages"] == 2

    request = LearningAssistantRequest(session_id=session["session_id"], student_id=None, message="继续解释", stream=False)
    try:
        asyncio.run(learning_assistant_chat(request, Actor(actor_id="other-student", role="student")))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-student session access was not rejected")

    new_session = create_session(student_id)
    assert list_messages(new_session["session_id"]) == []
    print("learning_assistant_multiturn_smoke=PASS")


if __name__ == "__main__":
    main()
