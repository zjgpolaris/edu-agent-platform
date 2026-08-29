from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-agent-ops-smoke.sqlite3")
os.environ["EDU_AGENT_DATA_SCOPE"] = "runtime"
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "agent-ops-smoke-commit"
os.environ["EDU_AGENT_ENVIRONMENT"] = "test"
try:
    Path(os.environ["EDU_AGENT_DB_PATH"]).unlink()
except FileNotFoundError:
    pass

from agent_ops import build_agent_ops_summary
from security.audit_log import record_audit_event
from student_profile import LearningEvent, try_record_learning_event
from trace_store import create_trace_id, emit_trace_event, trace_context
from agent_runtime.event_store import append_run_event, create_run
from agent_runtime.models import AgentContext
from db.engine import get_connection
from sqlalchemy import text


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
            metadata={
                "fallback_used": fallback_used,
                "generation_mode": "fallback" if fallback_used else "llm",
                "total_steps": 3,
                "completed_steps": 2 if fallback_used else 3,
                "completion_status": "partial" if fallback_used else "completed",
                "clarification_resolved": not fallback_used,
            },
        ))
    for routing_mode, task_count in (("semantic", 2), ("rule", 1)):
        assert try_record_learning_event(LearningEvent(
            student_id="agent-ops-student",
            session_id="la_session_1",
            feature="learning_assistant",
            event_type="intent_detected",
            metadata={"routing_mode": routing_mode, "task_count": task_count},
        ))
    assert try_record_learning_event(LearningEvent(
        student_id="agent-ops-student",
        session_id="la_session_1",
        feature="learning_assistant",
        event_type="clarification_requested",
        metadata={"missing_slots": ["lesson_id"]},
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
    assert try_record_learning_event(LearningEvent(
        student_id="agent-ops-student",
        session_id="eval-only",
        feature="learning_assistant",
        event_type="answer_feedback",
        success=False,
        metadata={"feedback": "unresolved", "data_scope": "eval"},
    ))
    assert record_audit_event(
        actor_id="eval-only",
        action="tool.failed",
        resource_type="tool",
        resource_id="eval-only-tool",
        success=False,
        metadata={"data_scope": "eval"},
    )
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
        emit_trace_event(
            agent_name="learning_assistant",
            step_name="route",
            event_type="routing",
            status="success",
            metadata={"routing_mode": "semantic", "task_count": 2},
        )
        emit_trace_event(
            agent_name="learning_assistant",
            step_name="step_1",
            event_type="plan_step",
            status="success",
            metadata={"operation": "search_history_knowledge"},
        )
        emit_trace_event(
            agent_name="learning_assistant",
            step_name="repair_1",
            event_type="repair",
            status="success",
            metadata={"operation": "search_history_knowledge"},
        )

    runtime_context = AgentContext(
        run_id="run-agent-ops-smoke",
        agent_type="learning_assistant",
        actor_id="agent-ops-student",
        actor_role="student",
        student_id="agent-ops-student",
        trace_id=trace_id,
        data_scope="runtime",
        durability_mode="observable",
        config_version="agent-ops-runtime-test",
    )
    create_run(runtime_context, objective="AgentOps Runtime sample")
    append_run_event("run-agent-ops-smoke", expected_revision=0, event_type="route_decided", next_status="routed")

    summary = build_agent_ops_summary(limit=100)
    production = summary.get("production") or {}
    latency = production.get("latency") or {}
    llm = production.get("llm") or {}
    rag = production.get("rag") or {}
    cost = production.get("cost") or {}
    runtime = production.get("runtime") or {}
    assistant_feedback = summary.get("learning_assistant") or {}
    data_scope = summary.get("data_scope") or {}
    runtime_v2 = summary.get("runtime_v2") or {}

    assert latency.get("p95_ms") is not None
    assert latency.get("llm_p95_ms") == 320
    assert llm.get("calls", 0) >= 1
    assert llm.get("fallback_count", 0) >= 1
    assert (llm.get("models") or {}).get("qwen-plus", 0) >= 1
    assert (rag.get("diagnosis") or {}).get("generation_uncited_sources", 0) >= 1
    assert (rag.get("failure_stage") or {}).get("generation", 0) >= 1
    assert cost.get("total_usd_estimated", 0) >= 0.000352
    assert runtime.get("routing_count", 0) >= 1
    assert runtime.get("plan_step_count", 0) >= 1
    assert runtime.get("repair_count", 0) >= 1
    assert runtime.get("repair_success_rate") == 1.0
    assert assistant_feedback.get("feedback_total") == 2
    assert (data_scope.get("learning") or {}).get("eval") == 1
    assert (data_scope.get("audit") or {}).get("eval") == 1
    assert (summary.get("audit") or {}).get("failure") == 0
    assert assistant_feedback.get("resolved") == 1
    assert assistant_feedback.get("unresolved") == 1
    assert assistant_feedback.get("resolution_rate") == 0.5
    assert assistant_feedback.get("followup_rate") == 0.5
    assert assistant_feedback.get("context_resolution_rate") == 1.0
    assert assistant_feedback.get("answer_fallback_rate") == 0.5
    assert assistant_feedback.get("answer_real_llm_rate") == 0.5
    assert assistant_feedback.get("semantic_routing_rate") == 0.5
    assert assistant_feedback.get("clarification_rate") == 0.5
    assert assistant_feedback.get("clarification_resolution_rate") == 1.0
    assert assistant_feedback.get("multi_intent_rate") == 0.5
    assert assistant_feedback.get("plan_completion_rate") == 0.5
    assert assistant_feedback.get("partial_completion_rate") == 0.5
    assert assistant_feedback.get("session_resume_rate") == 0.5
    assert assistant_feedback.get("autotutor_return_rate") == 0.5
    assert runtime_v2.get("status") == "ok"
    assert (runtime_v2.get("by_agent") or {}).get("learning_assistant") == 1
    assert (runtime_v2.get("by_config_version") or {}).get("agent-ops-runtime-test") == 1
    assert (runtime_v2.get("by_revision") or {}).get("1") == 1
    assert (runtime_v2.get("by_runtime_mode") or {}).get("active") == 1
    assert (runtime_v2.get("event_coverage_by_runtime_mode") or {}).get("active") == 1.0
    assert runtime_v2.get("invalid_transition_total") == 0
    assert runtime_v2.get("duplicate_side_effect_prevented_total") == 0
    assert runtime_v2.get("run_provenance_coverage") == 1.0
    assert runtime_v2.get("missing_run_provenance_total") == 0
    assert runtime_v2.get("mismatched_current_provenance_total") == 0
    with get_connection() as conn:
        conn.execute(text("UPDATE agent_runs SET context_refs_json=:refs WHERE run_id=:run_id"), {
            "run_id": runtime_context.run_id,
            "refs": json.dumps({
                "runtime_mode": "active",
                "data_scope": "runtime",
                "deployed_commit": "previous-deployment",
                "environment": "test",
            }),
        })
    mismatched_runtime = (build_agent_ops_summary(limit=100).get("runtime_v2") or {})
    assert mismatched_runtime.get("run_provenance_coverage") == 0.0
    assert mismatched_runtime.get("mismatched_current_provenance_total") == 1
    print("agent_ops_smoke=PASS")


if __name__ == "__main__":
    main()
