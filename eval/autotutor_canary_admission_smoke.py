"""Production AutoTutor Graph admission is cached, PII-free and fail-closed."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_canary_admission import (  # noqa: E402
    clear_autotutor_canary_admission_cache,
    evaluate_autotutor_canary_admission,
)
from agents.autotutor_execution import (  # noqa: E402
    AutoTutorExecutionContext,
    AutoTutorExecutorSettings,
    select_executor,
    stable_executor_bucket,
)

COMMIT = "d" * 40


def _settings(**updates: str) -> AutoTutorExecutorSettings:
    env = {
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "active_canary",
        "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "100",
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": "v1.49.3-admission-smoke",
        "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": "v1.49.3-admission-smoke",
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "false",
        "EDU_AGENT_ENVIRONMENT": "production",
        "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
    }
    env.update(updates)
    return AutoTutorExecutorSettings.from_env(env)


def _context(**updates: object) -> AutoTutorExecutionContext:
    values = {
        "actor_id": "verified-admission-student",
        "actor_role": "student",
        "account_status": "active",
        "traffic_cohort": "verified",
        "data_scope": "runtime",
        "rollout_eligible": True,
        "eligibility_reason": "verified_runtime_actor",
        "environment": "production",
        "deployed_commit": COMMIT,
    }
    values.update(updates)
    return AutoTutorExecutionContext(**values)  # type: ignore[arg-type]


def main() -> None:
    source = (ROOT / "backend" / "agents" / "auto_tutor.py").read_text(encoding="utf-8")
    start_source = source[source.index("def start_session("):source.index("def submit_answer(")]
    answer_source = source[source.index("def _submit_answer_locked("):source.index("def _advance(")]
    assert start_source.index("evaluate_autotutor_canary_admission(") < start_source.index("_execute_selected_transition(")
    assert answer_source.index("_apply_existing_session_canary_admission(") < answer_source.index("_execute_selected_transition(")

    schema = {"status": "ready", "schema_ready": True, "alembic_version": "017"}
    health = {"status": "ok", "ok": True, "failure_count": 0}
    clear_autotutor_canary_admission_cache()
    with patch("agent_runtime.readiness.runtime_schema_readiness", return_value=schema) as schema_read, \
         patch("agent_runtime.rollout_observations.observation_write_health", return_value=health) as health_read:
        admitted = evaluate_autotutor_canary_admission(settings=_settings(), context=_context())
        cached = evaluate_autotutor_canary_admission(settings=_settings(), context=_context())
    assert admitted.admitted and cached.admitted
    assert schema_read.call_count == 1 and health_read.call_count == 1
    assert "student" not in str(admitted).lower()

    subject = next(
        f"verified-{index}"
        for index in range(100_000)
        if stable_executor_bucket(f"verified-{index}", salt=_settings().bucket_salt) < 100
    )
    decision = select_executor(subject=subject, context=_context(), settings=_settings(), admission=admitted)
    assert decision.mode == "graph_active" and decision.assignment_reason == "graph_bucket_selected"

    clear_autotutor_canary_admission_cache()
    with patch("agent_runtime.readiness.runtime_schema_readiness", return_value={"schema_ready": False, "alembic_version": "015"}), \
         patch("agent_runtime.rollout_observations.observation_write_health", return_value=health):
        denied = evaluate_autotutor_canary_admission(settings=_settings(), context=_context())
    assert not denied.admitted and "runtime_schema_not_ready" in denied.reason_codes
    assert select_executor(subject=subject, context=_context(), settings=_settings(), admission=denied).mode == "legacy"

    clear_autotutor_canary_admission_cache()
    with patch("agent_runtime.readiness.runtime_schema_readiness", return_value=schema), \
         patch("agent_runtime.rollout_observations.observation_write_health", return_value={"status": "degraded", "ok": False}):
        unhealthy = evaluate_autotutor_canary_admission(settings=_settings(), context=_context())
    assert not unhealthy.admitted and "observation_health_degraded" in unhealthy.reason_codes

    clear_autotutor_canary_admission_cache()
    with patch("agent_runtime.readiness.runtime_schema_readiness", side_effect=RuntimeError("forced")):
        unknown = evaluate_autotutor_canary_admission(settings=_settings(), context=_context())
    assert unknown.status == "unknown" and not unknown.admitted

    killed = evaluate_autotutor_canary_admission(
        settings=_settings(EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH="true"),
        context=_context(),
    )
    assert not killed.admitted and "kill_switch_enabled" in killed.reason_codes
    untrusted = evaluate_autotutor_canary_admission(settings=_settings(), context=_context(traffic_cohort="unverified", rollout_eligible=False))
    assert not untrusted.admitted
    unsafe_bps = _settings(EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS="101")
    assert not unsafe_bps.valid
    print("autotutor_canary_admission_smoke=PASS")


if __name__ == "__main__":
    main()
