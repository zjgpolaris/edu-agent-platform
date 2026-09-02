"""v1.49 trusted sticky executor routing and fail-closed configuration."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_execution import (  # noqa: E402
    AutoTutorExecutionContext,
    AutoTutorExecutorSettings,
    select_executor,
    stable_executor_bucket,
)


def _context(**updates: object) -> AutoTutorExecutionContext:
    values = {
        "actor_id": "verified-student",
        "actor_role": "student",
        "account_status": "active",
        "traffic_cohort": "verified",
        "data_scope": "runtime",
        "rollout_eligible": True,
        "eligibility_reason": "verified_runtime_actor",
        "environment": "local",
    }
    values.update(updates)
    return AutoTutorExecutionContext(**values)  # type: ignore[arg-type]


def main() -> None:
    active_env = {
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "active_canary",
        "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "1000",
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": "v1.49-test",
        "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": "routing-test",
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
    }
    settings = AutoTutorExecutorSettings.from_env(active_env)
    assert settings.valid and settings.active_bps == 1000
    subject = next(
        f"verified-{index}"
        for index in range(1000)
        if stable_executor_bucket(f"verified-{index}", salt=settings.bucket_salt) < settings.active_bps
    )
    first = select_executor(subject=subject, context=_context(), settings=settings)
    second = select_executor(subject=subject, context=_context(), settings=settings)
    assert first == second and first.mode == "graph_active"
    for cohort, scope, role in (
        ("demo", "runtime", "student"),
        ("unverified", "runtime", "student"),
        ("operator", "runtime", "admin"),
        ("verified", "eval", "student"),
        ("anonymous", "runtime", "anonymous"),
    ):
        decision = select_executor(
            subject=subject,
            context=_context(
                traffic_cohort=cohort,
                data_scope=scope,
                actor_role=role,
                rollout_eligible=False,
                eligibility_reason=f"{cohort}_excluded",
            ),
            settings=settings,
        )
        assert decision.mode == "legacy"
    unsafe = AutoTutorExecutorSettings.from_env({**active_env, "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "1001"})
    assert not unsafe.valid
    assert select_executor(subject=subject, context=_context(), settings=unsafe).mode == "legacy"
    killed = AutoTutorExecutorSettings.from_env({**active_env, "EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "true"})
    assert select_executor(subject=subject, context=_context(), settings=killed).mode == "legacy"
    legacy = AutoTutorExecutorSettings.from_env({})
    assert legacy.mode == "legacy" and legacy.active_bps == 0
    production_unsafe = AutoTutorExecutorSettings.from_env({
        **active_env,
        "EDU_AGENT_ENVIRONMENT": "production",
        "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "101",
    })
    assert not production_unsafe.valid
    assert "production_active_bps_exceeds_one_percent" in production_unsafe.reason_codes
    print("autotutor_langgraph_active_routing_smoke=PASS")


if __name__ == "__main__":
    main()
