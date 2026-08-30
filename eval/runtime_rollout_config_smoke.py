from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.context import RuntimeV2Settings
from agent_runtime.rollout_config import validate_runtime_rollout_config


COMMIT = "a" * 40
BASELINE_COMMIT = "b" * 40


def _control_env() -> dict[str, str]:
    return {
        "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
        "EDU_AGENT_ENVIRONMENT": "production",
        "EDU_AGENT_RUNTIME_V2_ENABLED": "false",
        "EDU_AGENT_RUNTIME_V2_SHADOW_MODE": "true",
        "EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED": "false",
        "EDU_AGENT_RUNTIME_V2_CONFIG_VERSION": "v1.41-history-control",
        "EDU_AGENT_RUNTIME_V2_PERCENT_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS": "0",
        "EDU_AGENT_RUNTIME_V2_DEBATE_BPS": "0",
    }


def _shadow_env() -> dict[str, str]:
    return {
        **_control_env(),
        "EDU_AGENT_RUNTIME_V2_ENABLED": "true",
        "EDU_AGENT_RUNTIME_V2_CONFIG_VERSION": "v1.42-history-shadow",
        "EDU_AGENT_RUNTIME_V2_PERCENT_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS": "10000",
        "EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS": "true",
        "EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED": "true",
        "EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED": "false",
        "EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED": "false",
        "EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED": "false",
        "EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED": "false",
        "EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_CONFIG_VERSION": "v1.41-history-control",
        "EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_COMMIT": BASELINE_COMMIT,
        "EDU_AGENT_RUNTIME_ROLLOUT_MIN_TERMINAL_RUNS": "100",
    }


def main() -> None:
    control = validate_runtime_rollout_config(phase="control", agent_type="history_character", environ=_control_env())
    assert control.ok, control.as_dict()

    status = {
        "deployment": {"commit": COMMIT},
        "control": {"terminal_samples": 100},
        "safety": {"observation_write_failures": 0},
    }
    shadow_env = _shadow_env()
    shadow = validate_runtime_rollout_config(
        phase="shadow", agent_type="history_character", environ=shadow_env, online_status=status,
    )
    assert shadow.ok, shadow.as_dict()

    unsafe = dict(shadow_env)
    unsafe["EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS"] = "1"
    unsafe["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "false"
    result = validate_runtime_rollout_config(phase="shadow", agent_type="history_character", environ=unsafe, online_status=status)
    assert not result.ok
    assert "shadow_non_target_agent_enabled" in result.errors
    assert "shadow_artifact_persistence_disabled" in result.errors

    insufficient = validate_runtime_rollout_config(
        phase="shadow",
        agent_type="history_character",
        environ=shadow_env,
        online_status={**status, "control": {"terminal_samples": 99}},
    )
    assert "control_samples_insufficient" in insufficient.errors

    active_env = {**shadow_env, "EDU_AGENT_RUNTIME_V2_SHADOW_MODE": "false", "EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED": "false"}
    with patch.dict("os.environ", active_env, clear=True):
        settings = RuntimeV2Settings.from_env()
        active, _ = settings.rollout_decision("history_character", "student-a")
        assert active is False

    print("runtime_rollout_config_smoke=PASS")


if __name__ == "__main__":
    main()
