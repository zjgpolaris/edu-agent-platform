from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import agents.history_character as character  # noqa: E402
from api.routers.history import _history_session_key  # noqa: E402
from security.auth import Actor  # noqa: E402


class FailingVerifier:
    def invoke(self, _prompt):
        raise RuntimeError("expected verifier outage")


def main() -> None:
    original = character.llm_opus
    character.llm_opus = FailingVerifier()
    state = {
        "character": "测试人物",
        "messages": [{"role": "user", "content": "测试问题"}],
        "retrieved_facts": ["[史料1] 测试史实"],
        "retrieved_sources": [{"citation_label": "[史料1]", "source": "offline", "snippet": "测试史实"}],
        "response_draft": "【回答】测试。[史料1]\n【史料依据】[史料1]\n【学习提示】复习",
        "mode": "factual",
    }
    try:
        result = character.verify_response(state)
    finally:
        character.llm_opus = original
    assert result["verified"] is False, result
    assert result["verification_status"] == "failed"
    assert result["verification_reason"].startswith("verifier_exception")
    assert character.generate_fact_card({**state, **result}) == {}
    assert character._apply_character_memory({**state, **result, "student_id": "student-a"}) is False

    writes: list[str] = []
    original_interaction = character.record_character_interaction
    original_memory = character.update_memory_after_chat
    character.record_character_interaction = lambda student_id, *_args: writes.append(f"interaction:{student_id}")
    character.update_memory_after_chat = lambda student_id, *_args: writes.append(f"memory:{student_id}")
    verified_state = {
        **state,
        "verified": True,
        "student_id": "student-a",
        "memory_updated": False,
    }
    try:
        assert character._apply_character_memory(verified_state) is True
        verified_state["memory_updated"] = True
        assert character._apply_character_memory(verified_state) is True
        assert character._apply_character_memory({**verified_state, "student_id": None, "memory_updated": False}) is False
    finally:
        character.record_character_interaction = original_interaction
        character.update_memory_after_chat = original_memory
    assert writes == ["interaction:student-a", "memory:student-a"]

    original_stream = character.stream_character_response
    executions: list[str] = []

    def fake_stream(graph_state, _retriever):
        executions.append("executed")
        graph_state.update(verified=True, verification_status="verified", fact_card={"key_facts": ["事实"]}, memory_updated=True)
        yield {"event": "final", "data": {"verified": True}}

    character.stream_character_response = fake_stream
    try:
        graph_result = character.build_character_graph(object()).invoke(state)
    finally:
        character.stream_character_response = original_stream
    assert executions == ["executed"]
    assert graph_result["verified"] is True

    teacher = Actor(actor_id="teacher-a", role="teacher")
    assert _history_session_key(teacher, "same-session", "student-a") != _history_session_key(
        teacher, "same-session", "student-b"
    )
    print("history_character_runtime_smoke=PASS")


if __name__ == "__main__":
    main()
