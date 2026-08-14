from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

db_path = Path(tempfile.gettempdir()) / "edu-agent-agent-ops-scope-smoke.sqlite3"
db_path.unlink(missing_ok=True)
os.environ["EDU_AGENT_DB_PATH"] = str(db_path)
os.environ["EDU_AGENT_DATA_SCOPE"] = "runtime"

from agent_ops import build_agent_ops_summary
from security.audit_log import record_audit_event
from student_profile import LearningEvent, try_record_learning_event


def main() -> None:
    for index in range(150):
        assert record_audit_event(
            actor_id="runtime-actor",
            action="runtime.completed",
            resource_type="request",
            resource_id=str(index),
            data_scope="runtime",
        )
    assert record_audit_event(
        actor_id="runtime-actor",
        action="tool.confirmation_required",
        resource_type="tool",
        resource_id="delete_memory",
        success=False,
        data_scope="runtime",
    )
    assert record_audit_event(
        actor_id="runtime-actor",
        action="tool.denied",
        resource_type="tool",
        resource_id="delete_memory",
        success=False,
        metadata={"user_denied": True},
        data_scope="runtime",
    )
    for index in range(1000):
        assert record_audit_event(
            actor_id="eval-actor",
            action="eval.completed",
            resource_type="suite",
            resource_id=str(index),
            data_scope="eval",
        )

    assert try_record_learning_event(LearningEvent(
        student_id="scope-student",
        feature="learning_assistant",
        event_type="runtime_answer",
        success=True,
        data_scope="runtime",
    ))
    assert try_record_learning_event(LearningEvent(
        student_id="scope-student",
        feature="learning_assistant",
        event_type="eval_answer",
        success=False,
        data_scope="eval",
    ))

    runtime = build_agent_ops_summary(limit=100, scope="runtime", minimum_runtime_events=10)
    evaluation = build_agent_ops_summary(limit=100, scope="eval", minimum_runtime_events=10)

    assert runtime["window"]["scope"] == "runtime"
    assert runtime["audit"]["total"] == 100
    assert "eval.completed" not in runtime["audit"]["by_action"]
    assert runtime["audit"]["unexpected_failure"] == 0
    assert runtime["audit"]["expected_control"] == 1
    assert runtime["audit"]["user_denied"] == 1
    assert runtime["audit"]["success_rate"] == 1.0
    assert runtime["readiness"]["sample_sufficient"] is True
    assert runtime["data_scope"]["audit"]["runtime"] == 152
    assert runtime["data_scope"]["audit"]["eval"] == 1000

    assert evaluation["window"]["scope"] == "eval"
    assert evaluation["audit"]["total"] == 100
    assert "runtime.completed" not in evaluation["audit"]["by_action"]
    assert evaluation["learning"]["unexpected_failure"] == 1
    assert evaluation["readiness"]["status"] == "not_applicable"

    print("agent_ops_scope_smoke=PASS")
    print("scope_isolation_rate=1.0")
    print("expected_control_classification_rate=1.0")


if __name__ == "__main__":
    main()
