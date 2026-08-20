from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-contract-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from agent_runtime.capability_registry import build_default_registry  # noqa: E402
from agent_runtime.completion import CompletionEvaluator  # noqa: E402
from agent_runtime.context import RuntimeV2Settings  # noqa: E402
from agent_runtime.event_store import StaleRevisionError, append_run_event, create_run, get_run, list_run_events  # noqa: E402
from agent_runtime.models import (  # noqa: E402
    AgentBudget,
    AgentContext,
    AgentPlan,
    AgentRunState,
    AgentStep,
    EvidenceClaim,
    StepResult,
)
from agent_runtime.transitions import InvalidTransitionError, transition_state  # noqa: E402
from security.audit_log import list_audit_events  # noqa: E402
from tools.base import ToolExecutionContext  # noqa: E402
from tools.registry import run_tool  # noqa: E402


def main() -> None:
    rollout_env = {
        "EDU_AGENT_RUNTIME_V2_ENABLED": "true",
        "EDU_AGENT_RUNTIME_V2_PERCENT_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS": "true",
        "EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED": "true",
        "EDU_AGENT_RUNTIME_V2_KILL_SWITCH": "false",
    }
    with patch.dict(os.environ, rollout_env, clear=False):
        settings = RuntimeV2Settings.from_env()
        assert settings.rollout_decision("learning_assistant", "student-a")[0] is True
        assert settings.observable_ready is True
    with patch.dict(os.environ, {**rollout_env, "EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS": "false"}, clear=False):
        assert RuntimeV2Settings.from_env().rollout_decision("learning_assistant", "student-a")[0] is False
    with patch.dict(os.environ, {**rollout_env, "EDU_AGENT_RUNTIME_V2_KILL_SWITCH": "true"}, clear=False):
        assert RuntimeV2Settings.from_env().rollout_decision("learning_assistant", "student-a")[0] is False

    try:
        AgentStep(
            step_id="write",
            kind="tool",
            operation="write.operation",
            side_effect="write",
            risk_level="medium",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("write step accepted without idempotency key")

    try:
        AgentPlan(
            plan_id="plan_bad",
            objective="bad dependency",
            strategy="sequential",
            generated_by="deterministic",
            planner_version="test",
            steps=[
                AgentStep(step_id="two", kind="control", operation="noop", depends_on=["one"]),
                AgentStep(step_id="one", kind="control", operation="noop"),
            ],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("forward dependency was accepted")

    state = AgentRunState(run_id="run_contract_state", durability_mode="observable", objective="contract", budget=AgentBudget())
    routed = transition_state(state, "routed")
    assert routed.revision == 1
    try:
        transition_state(routed, "completed")
    except InvalidTransitionError:
        pass
    else:
        raise AssertionError("invalid routed -> completed transition was accepted")

    registry = build_default_registry()
    history = registry.resolve("history.search", "learning_assistant")
    assert history.tool_name == "search_history_knowledge"
    assert history.requires_evidence is True
    try:
        registry.resolve("essay.grade", "learning_assistant")
    except PermissionError:
        pass
    else:
        raise AssertionError("capability caller allowlist was bypassed")

    context = AgentContext(
        run_id="run_contract_store",
        agent_type="learning_assistant",
        actor_id="student-a",
        actor_role="student",
        student_id="student-a",
        session_id="session-a",
        trace_id="trace-contract",
        data_scope="eval",
        durability_mode="observable",
        config_version="contract-test",
    )
    created = create_run(context, objective="contract smoke", idempotency_key="contract-idempotency")
    duplicate = create_run(context, objective="ignored", idempotency_key="contract-idempotency")
    assert duplicate["run_id"] == created["run_id"]
    event = append_run_event(
        context.run_id,
        expected_revision=0,
        event_type="route_decided",
        public_payload={"prompt": "must not persist", "mode": "rule"},
        next_status="routed",
    )
    assert event.sequence == 2
    assert event.data["prompt"] == "[REDACTED]"
    try:
        append_run_event(context.run_id, expected_revision=0, event_type="route_decided", next_status="routed")
    except StaleRevisionError:
        pass
    else:
        raise AssertionError("stale CAS event append succeeded")
    events = list_run_events(context.run_id)
    assert [item.sequence for item in events] == [1, 2]
    assert get_run(context.run_id)["revision"] == 1

    invalid_context = context.model_copy(update={"run_id": "run_invalid_transition", "trace_id": "trace-invalid-transition"})
    create_run(invalid_context, objective="invalid transition audit")
    try:
        append_run_event(
            invalid_context.run_id,
            expected_revision=0,
            event_type="run_completed",
            next_status="completed",
        )
    except InvalidTransitionError:
        pass
    else:
        raise AssertionError("event store accepted invalid received -> completed transition")
    invalid_audits = list_audit_events(action="agent_runtime.invalid_transition", limit=10)
    assert any(item.get("resource_id") == invalid_context.run_id for item in invalid_audits)

    evidence_state = AgentRunState(
        run_id="run_evidence",
        durability_mode="observable",
        objective="evidence",
        budget=AgentBudget(),
        step_results={
            "answer": StepResult(
                step_id="answer",
                operation="history.answer",
                status="completed",
                evidence_claims=[EvidenceClaim(
                    claim_id="claim-1",
                    text="critical fact",
                    critical=True,
                    source_ids=["unknown-source"],
                    producer_step_id="answer",
                )],
            )
        },
    )
    decision = CompletionEvaluator().evaluate(evidence_state, evidence_required=True, known_source_ids={"known-source"})
    assert decision.completion_allowed is False
    assert "unknown_source_id" in decision.reason_codes

    high_risk_payload = {"student_id": "student-a", "memory_id": "demo_wrong_memory_001", "reason": "runtime contract"}
    confirmation = run_tool(
        "delete_demo_memory",
        high_risk_payload,
        context=ToolExecutionContext(
            actor_id="student-a",
            role="student",
            student_id="student-a",
            run_id="run-contract-confirm",
            step_id="step-confirm",
            run_revision=3,
            request_source="runtime_contract",
        ),
    )
    assert confirmation.error and confirmation.error.code == "confirmation_required"
    replayed_on_other_revision = run_tool(
        "delete_demo_memory",
        high_risk_payload,
        context=ToolExecutionContext(
            actor_id="student-a",
            role="student",
            student_id="student-a",
            run_id="run-contract-confirm",
            step_id="step-confirm",
            run_revision=4,
            confirmed=True,
            confirmation_token=confirmation.metadata.get("confirmation_token"),
            request_source="runtime_contract",
        ),
    )
    assert replayed_on_other_revision.error and replayed_on_other_revision.error.code == "invalid_confirmation"

    print("agent_runtime_contract_smoke=PASS")


if __name__ == "__main__":
    main()
