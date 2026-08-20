from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-checkpoint-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from agent_runtime.artifact_store import create_artifact, get_artifact, list_run_artifacts, purge_expired_artifacts  # noqa: E402
from agent_runtime.checkpoint_store import latest_checkpoint, prune_terminal_checkpoints, save_checkpoint  # noqa: E402
from agent_runtime.completion import CompletionEvaluator  # noqa: E402
from agent_runtime.event_store import append_run_event, create_run, get_run, list_run_events  # noqa: E402
from agent_runtime.models import AgentContext  # noqa: E402


def context(run_id: str, mode: str) -> AgentContext:
    return AgentContext(
        run_id=run_id,
        agent_type="essay_grader",
        actor_id="student-a",
        actor_role="student",
        student_id="student-a",
        session_id=run_id,
        trace_id=f"trace-{run_id}",
        data_scope="eval",
        durability_mode=mode,
        config_version="checkpoint-test",
    )


def main() -> None:
    run_id = "run_checkpoint"
    created = create_run(context(run_id, "resumable"), objective="safe essay review")
    assert created["expires_at"] is not None
    artifact = create_artifact(
        run_id,
        owner_actor_id="student-a",
        student_id="student-a",
        artifact_type="input",
        sensitivity="student_content",
        content={"essay": "private essay body"},
    )
    assert artifact["expires_at"] is not None
    try:
        get_artifact(artifact["artifact_id"], actor_id="student-b", actor_role="student")
    except PermissionError:
        pass
    else:
        raise AssertionError("non-owner artifact read succeeded")
    owned = get_artifact(artifact["artifact_id"], actor_id="student-a", actor_role="student")
    assert owned["content"]["essay"] == "private essay body"

    append_run_event(run_id, expected_revision=created["revision"], event_type="route_decided", next_status="routed")
    routed = get_run(run_id)
    checkpoint = save_checkpoint(
        run_id,
        revision=routed["revision"],
        node_name="artifact_saved",
        state={"artifact_id": artifact["artifact_id"]},
        side_effect_ledger=[],
    )
    assert latest_checkpoint(run_id)["checkpoint_id"] == checkpoint["checkpoint_id"]
    for index in range(6):
        save_checkpoint(
            run_id,
            revision=routed["revision"],
            node_name=f"artifact_saved_{index}",
            state={"artifact_id": artifact["artifact_id"], "index": index},
        )
    assert prune_terminal_checkpoints(run_id, keep=2) == 0
    persisted = " ".join(str(event.data) for event in list_run_events(run_id))
    assert "private essay body" not in persisted

    append_run_event(run_id, expected_revision=routed["revision"], event_type="plan_created", next_status="planned")
    planned = get_run(run_id)
    append_run_event(run_id, expected_revision=planned["revision"], event_type="step_started", next_status="running")
    running = get_run(run_id)
    append_run_event(run_id, expected_revision=running["revision"], event_type="verification_result", next_status="verifying")
    verifying = get_run(run_id)
    decision = CompletionEvaluator().from_outcome(
        status="partial",
        completed_steps=0,
        total_steps=1,
        verification_status="partial",
        reason_codes=["checkpoint_retention_test"],
        deliverable_refs=[artifact["artifact_id"]],
        unresolved_items=["review"],
    )
    append_run_event(
        run_id,
        expected_revision=verifying["revision"],
        event_type="run_completed",
        next_status="partial",
        completion=decision,
    )
    assert prune_terminal_checkpoints(run_id, keep=2) == 5

    visible_before_expired = len(list_run_artifacts(run_id, actor_id="student-a", actor_role="student"))
    create_artifact(
        run_id,
        owner_actor_id="student-a",
        student_id="student-a",
        artifact_type="review_payload",
        sensitivity="student_content",
        content={"expired": True},
        expires_at="2000-01-01T00:00:00+00:00",
    )
    assert len(list_run_artifacts(run_id, actor_id="student-a", actor_role="student")) == visible_before_expired
    assert purge_expired_artifacts() == 1

    observable_id = "run_observable_no_checkpoint"
    create_run(context(observable_id, "observable"), objective="short request")
    try:
        save_checkpoint(observable_id, revision=0, node_name="bad", state={})
    except ValueError:
        pass
    else:
        raise AssertionError("observable run accepted checkpoint")

    print("agent_runtime_checkpoint_smoke=PASS")


if __name__ == "__main__":
    main()
