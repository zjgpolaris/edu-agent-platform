"""Real Graph + real local DB + ASGI API, without external model/network."""
from pathlib import Path
import os
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from scripts.dev_autotutor_graph_demo import prepare_directory, demo_environment, deny_external_network, NETWORK_COUNTS
directory = prepare_directory()
env = demo_environment(directory, {})
os.environ.clear()
os.environ.update(env)
deny_external_network()

from db.engine import engine, get_connection
from db.schema import metadata
from sqlalchemy import text
from scripts.seed_pilot_demo import seed
from fastapi.testclient import TestClient
from api.main import app
from agents import auto_tutor as at


def main():
    metadata.create_all(engine)
    seed(verbose=False)
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "pilot-student", "password": "pilot123"})
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    payload = {"student_id": "pilot-student", "focus_tags": ["洋务运动目的"], "idempotency_key": "demo-flow-start-150"}
    with patch.object(at.DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER, "prepare", wraps=at.DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER.prepare) as provider:
        response = client.post("/api/autotutor/start", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["execution"]["selected_executor"] == "graph_active", state.get("execution")
        assert state["execution"]["visited_nodes"], state
        replay = client.post("/api/autotutor/start", headers=headers, json=payload).json()
        assert replay["session_id"] == state["session_id"] and replay["idempotent_replay"]
        assert provider.call_count == 1
    assert client.post("/api/autotutor/start", headers=headers, json={**payload, "focus_tags": ["戊戌变法失败原因"]}).status_code == 409
    # A new interpreter reads the durable summary with the same isolated DB.
    code = """
import sys
from scripts.dev_autotutor_graph_demo import deny_external_network
deny_external_network()
from agents import auto_tutor as at
state = at._load_persisted_session(sys.argv[1])
assert state.execution_profile == 'local_demo_graph'
assert state.execution_summary['selected_executor'] == 'graph_active'
assert state.execution_summary['revision'] == state.revision
"""
    subprocess.run([sys.executable, "-c", code, state["session_id"]], cwd=ROOT,
                   env={**env, "PYTHONPATH": str(ROOT) + os.pathsep + str(ROOT / "backend")}, check=True, timeout=30)
    internal = at._load_persisted_session(state["session_id"])
    from agents.autotutor_execution import AutoTutorExecutionContext
    from agents.autotutor_demo_policy import isolated_context
    recovered = at._execute_selected_transition(before=internal, transition_kind="recovery_resume", command={},
        context=isolated_context(AutoTutorExecutionContext(actor_id="pilot-student", actor_role="student")), started_at=perf_counter())
    assert recovered.public_result["execution"]["visited_nodes"] == ["load_context", "recovery_resume", "validate_state", "route_current_phase", "build_outcome"]
    assert recovered.next_state.revision == internal.revision
    for index in range(8):
        internal = at._load_persisted_session(state["session_id"])
        correct = internal.exit_ticket.question["answer"] if internal.phase == "exit_ticket" else internal.lesson_plan[internal.current_step_index].question["answer"]
        answer = ("B" if correct != "B" else "A") if index == 0 else correct
        body = {"session_id": state["session_id"], "answer": answer, "expected_revision": state["revision"], "idempotency_key": f"demo-answer-150-{index}"}
        response = client.post("/api/autotutor/answer", headers=headers, json=body)
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["execution"]["selected_executor"] == "graph_active", state["execution"]
        assert state["execution"]["revision"] == state["revision"]
        if index == 0:
            assert state.get("reflection"), "demo projection dropped transition reflection"
        replay = client.post("/api/autotutor/answer", headers=headers, json=body).json()
        assert replay["revision"] == state["revision"]
        if state["status"] == "completed":
            break
    assert state["status"] == "completed" and state["mastery"]["status"] == "verified"
    at._store._sessions.clear()
    loaded = client.get(f'/api/autotutor/session/{state["session_id"]}', headers=headers).json()
    assert loaded["execution"] == state["execution"]
    trace = client.get(f'/api/autotutor/session/{state["session_id"]}/demo-trace', headers=headers).json()
    assert trace["execution"] == state["execution"]
    teacher = client.post("/api/auth/login", json={"username": "pilot-teacher", "password": "pilot123"}).json()
    evidence = client.get(f'/api/autotutor/session/{state["session_id"]}/evidence', headers={"Authorization": "Bearer " + teacher["token"]})
    assert evidence.status_code == 200 and evidence.json()["execution"] == state["execution"]
    with get_connection() as conn:
        rows = conn.execute(text("SELECT environment,data_scope,traffic_cohort,rollout_eligible,traffic_source FROM agent_rollout_observations WHERE config_version='v1.50-local-graph-demo'")).mappings().all()
        assert rows and all(r["data_scope"] == "demo" and r["environment"] == "local" and not r["rollout_eligible"] and r["traffic_cohort"] == "demo" and r["traffic_source"] == "organic" for r in rows)
    from agent_runtime.rollout_observations import aggregate_autotutor_transition_canary
    aggregate = aggregate_autotutor_transition_canary(config_version="v1.50-local-graph-demo", deployed_commit=env["EDU_AGENT_DEPLOYED_COMMIT"], environment="production", since="2000-01-01T00:00:00+00:00")
    assert aggregate["selected_graph_count"] == 0, aggregate
    from scripts.build_autotutor_canary_evidence import _load_json
    try:
        _load_json(directory / "demo.json")
    except ValueError as exc:
        assert str(exc) == "demo_artifact_is_not_production_evidence"
    else:
        raise AssertionError("demo manifest accepted")
    other = client.post("/api/autotutor/start", headers=headers, json={**payload, "idempotency_key": "demo-flow-kill-150"}).json()
    with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "true"}):
        result = client.post("/api/autotutor/answer", headers=headers, json={"session_id": other["session_id"], "answer": "A", "expected_revision": other["revision"]}).json()
        assert result["execution"]["selected_executor"] == "legacy", result
        assert result["execution"]["fallback_reason"] == "kill_switch_enabled"
    assert NETWORK_COUNTS["external_attempts"] == 0, NETWORK_COUNTS
    # Same-key concurrent starts acquire observations once, not twice.
    actor = dict(actor_id="pilot-student", actor_role="student", traffic_cohort="demo")
    with patch.object(at.DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER, "prepare", wraps=at.DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER.prepare) as provider:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(at.start_session, "pilot-student", focus_tags=["洋务运动目的"], idempotency_key="demo-parallel", **actor) for _ in range(2)]
            results = [f.result() for f in futures]
        assert results[0]["session_id"] == results[1]["session_id"] and provider.call_count == 1
    sys.path.insert(0, str(ROOT / "eval"))
    from autotutor_atomic_observation_checks import reject_observation_insert
    from agent_runtime.rollout_observations import RolloutObservationWriteError
    with reject_observation_insert():
        try:
            at.start_session("pilot-student", focus_tags=["洋务运动目的"], idempotency_key="demo-atomic-fail", **actor)
        except RolloutObservationWriteError:
            pass
        else:
            raise AssertionError("demo committed without observation")
    assert at._load_start_idempotent_session("pilot-student", "demo-atomic-fail") is None
    for mode in ("exception", "mismatch", "disabled", "revoked"):
        item = at.start_session("pilot-student", focus_tags=["洋务运动目的"], idempotency_key="demo-fallback-" + mode, **actor)
        injection = {
            "exception": patch.object(at.GraphActiveTransitionExecutor, "execute", side_effect=RuntimeError("private payload")),
            "mismatch": patch.object(at, "compare_transition_outcomes", return_value=(False, ("private mismatch",))),
            "disabled": patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_DEMO_GRAPH_ENABLED": "false"}),
            "revoked": patch("security.accounts.get_account", return_value={"role": "student", "account_status": "active", "traffic_cohort": "verified"}),
        }[mode]
        with injection:
            result = at.submit_answer(item["session_id"], "A", expected_revision=item["revision"], idempotency_key="demo-fallback-answer", **actor)
        execution = result["execution"]
        assert execution["assigned_executor"] == "graph_active" and execution["selected_executor"] == "legacy", execution
        assert execution["fallback_reason"] == {"exception": "graph_execution_failed", "mismatch": "comparator_mismatch", "disabled": "demo_graph_disabled", "revoked": "demo_actor_ineligible"}[mode], execution
        assert "private" not in str(execution)
        assert at._load_persisted_session(item["session_id"]).executor_mode == "legacy"
    assert NETWORK_COUNTS["external_attempts"] == 0, NETWORK_COUNTS
    print("autotutor_demo_graph_flow_smoke=PASS external_network_calls=0 production_evidence=false")


if __name__ == "__main__":
    main()
