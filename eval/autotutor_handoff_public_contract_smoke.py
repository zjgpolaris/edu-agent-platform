"""AutoTutor handoff remains allowlisted on create, read and legacy resume."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-public-handoff.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents.auto_tutor import get_learning_assistant_context, start_session  # noqa: E402
from api.routers.learning import LearningAssistantSessionCreateRequest, learning_assistant_create_session  # noqa: E402
from db.engine import get_connection  # noqa: E402
from security.auth import Actor  # noqa: E402
from services.learning_assistant_session_service import get_session  # noqa: E402
from sqlalchemy import text  # noqa: E402


FORBIDDEN = {
    "student_id", "strategy", "rationale", "reason", "reason_codes", "claims",
    "source_id", "source_ids", "sources", "answer", "correct", "correct_answer",
    "is_correct", "options", "feedback", "misconception_code", "trace", "trace_id",
    "runtime", "run_id", "steps", "prompt", "tool_result", "side_effect_ledger",
}


def _assert_safe(value, path: str = "context") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in FORBIDDEN, f"forbidden {path}.{key}"
            _assert_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_safe(item, f"{path}[{index}]")


def main() -> None:
    student_id = "public-handoff-student"
    started = start_session(student_id, grade="八年级上册", focus_tags=["洋务运动目的"])
    public = get_learning_assistant_context(started["session_id"])
    _assert_safe(public)
    assert set(public) == {
        "schema_version", "autotutor_session_id", "phase", "knowledge_point",
        "difficulty", "teaching", "question", "return_path",
    }
    req = LearningAssistantSessionCreateRequest(
        student_id=student_id,
        source_feature="auto_tutor",
        source_session_id=started["session_id"],
    )
    created = asyncio.run(learning_assistant_create_session(req, Actor(actor_id=student_id, role="student")))
    _assert_safe(created["context"])

    legacy_context = {
        **created["context"],
        "strategy": "internal plan",
        "student_id": student_id,
        "teaching": {
            **(created["context"].get("teaching") or {}),
            "claims": [{"source_ids": ["secret-source"], "answer": "A"}],
        },
        "runtime": {"trace_id": "secret-trace"},
    }
    with get_connection() as conn:
        conn.execute(
            text("UPDATE assistant_sessions SET context_json=:context WHERE session_id=:session_id"),
            {"context": json.dumps(legacy_context, ensure_ascii=False), "session_id": created["session_id"]},
        )
    restored = get_session(created["session_id"])
    _assert_safe(restored["context"])
    assert restored["context"]["knowledge_point"] == public["knowledge_point"]
    print("autotutor_handoff_public_contract_smoke=PASS")


if __name__ == "__main__":
    main()
