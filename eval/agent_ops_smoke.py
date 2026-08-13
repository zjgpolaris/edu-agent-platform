from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-agent-ops-smoke.sqlite3")
try:
    Path(os.environ["EDU_AGENT_DB_PATH"]).unlink()
except FileNotFoundError:
    pass

from agent_ops import build_agent_ops_summary
from student_profile import LearningEvent, try_record_learning_event
from trace_store import create_trace_id, emit_trace_event, trace_context


def main() -> None:
    for feedback, history_messages in (("resolved", 2), ("unresolved", 0)):
        assert try_record_learning_event(LearningEvent(
            student_id="agent-ops-student",
            session_id="la_agent_ops",
            feature="learning_assistant",
            event_type="answer_feedback",
            metadata={"feedback": feedback, "history_messages": history_messages},
        ))
    for session_id in ("la_session_1", "la_session_2"):
        assert try_record_learning_event(LearningEvent(student_id="agent-ops-student", session_id=session_id, feature="learning_assistant", event_type="session_created"))
    assert try_record_learning_event(LearningEvent(student_id="agent-ops-student", session_id="la_session_1", feature="learning_assistant", event_type="session_resumed"))
    assert try_record_learning_event(LearningEvent(student_id="agent-ops-student", session_id="la_session_1", feature="learning_assistant", event_type="question_asked"))
    assert try_record_learning_event(LearningEvent(student_id="agent-ops-student", session_id="la_session_1", feature="learning_assistant", event_type="followup_asked"))
    for fallback_used in (True, False):
        assert try_record_learning_event(LearningEvent(
            student_id="agent-ops-student",
            session_id="la_session_1",
            feature="learning_assistant",
            event_type="answer_completed",
            metadata={"fallback_used": fallback_used},
        ))
    for assistant_session_id in ("la_handoff_1", "la_handoff_2"):
        assert try_record_learning_event(LearningEvent(
            student_id="agent-ops-student",
            session_id=f"at_{assistant_session_id}",
            feature="auto_tutor",
            event_type="autotutor_question_asked",
            metadata={"assistant_session_id": assistant_session_id},
        ))
    assert try_record_learning_event(LearningEvent(
        student_id="agent-ops-student",
        session_id="at_la_handoff_1",
        feature="auto_tutor",
        event_type="autotutor_question_returned",
        metadata={"assistant_session_id": "la_handoff_1"},
    ))
    trace_id = create_trace_id()
    with trace_context(trace_id):
        emit_trace_event(
            agent_name="agent_ops_smoke",
            step_name="rag_retrieval",
            event_type="retrieval",
            status="success",
            latency_ms=88,
            metadata={
                "rag_inspector": {
                    "retrieval_strategy": "textbook_hybrid",
                    "diagnosis_code": "generation_uncited_sources",
                    "failure_stage": "generation",
                },
            },
        )
        emit_trace_event(
            agent_name="agent_ops_smoke",
            step_name="response_generation",
            event_type="llm",
            status="success",
            latency_ms=320,
            metadata={
                "configured_model": "qwen-plus",
                "response_chars": 120,
                "input_tokens_estimated": 80,
                "output_tokens_estimated": 90,
                "cost_usd_estimated": 0.000352,
                "fallback_used": True,
            },
        )
        emit_trace_event(
            agent_name="agent_ops_smoke",
            step_name="tool_result",
            event_type="tool_result",
            status="success",
            latency_ms=42,
            metadata={"tool_name": "search_history_knowledge"},
        )

    summary = build_agent_ops_summary(limit=100)
    production = summary.get("production") or {}
    latency = production.get("latency") or {}
    llm = production.get("llm") or {}
    rag = production.get("rag") or {}
    cost = production.get("cost") or {}
    assistant_feedback = summary.get("learning_assistant") or {}

    assert latency.get("p95_ms") is not None
    assert latency.get("llm_p95_ms") == 320
    assert llm.get("calls", 0) >= 1
    assert llm.get("fallback_count", 0) >= 1
    assert (llm.get("models") or {}).get("qwen-plus", 0) >= 1
    assert (rag.get("diagnosis") or {}).get("generation_uncited_sources", 0) >= 1
    assert (rag.get("failure_stage") or {}).get("generation", 0) >= 1
    assert cost.get("total_usd_estimated", 0) >= 0.000352
    assert assistant_feedback.get("feedback_total") == 2
    assert assistant_feedback.get("resolved") == 1
    assert assistant_feedback.get("unresolved") == 1
    assert assistant_feedback.get("resolution_rate") == 0.5
    assert assistant_feedback.get("followup_rate") == 0.5
    assert assistant_feedback.get("context_resolution_rate") == 1.0
    assert assistant_feedback.get("answer_fallback_rate") == 0.5
    assert assistant_feedback.get("session_resume_rate") == 0.5
    assert assistant_feedback.get("autotutor_return_rate") == 0.5
    print("agent_ops_smoke=PASS")


if __name__ == "__main__":
    main()
