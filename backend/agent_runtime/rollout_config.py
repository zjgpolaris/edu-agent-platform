from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from deployment import deployed_commit, deployment_environment


TRUE_VALUES = {"1", "true", "yes", "on"}
AGENT_BPS_ENV = {
    "history_character": "EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS",
    "learning_assistant": "EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS",
    "auto_tutor": "EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS",
    "essay_grader": "EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS",
    "debate": "EDU_AGENT_RUNTIME_V2_DEBATE_BPS",
}


def _enabled(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in TRUE_VALUES


def _bps(env: Mapping[str, str], name: str) -> int:
    try:
        return int(str(env.get(name, "0")).strip())
    except ValueError:
        return -1


@dataclass(frozen=True, slots=True)
class RolloutConfigValidation:
    phase: str
    agent_type: str
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    config_version: str
    environment: str
    deployed_commit: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "phase": self.phase,
            "agent_type": self.agent_type,
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "config_version": self.config_version or None,
            "environment": self.environment or None,
            "deployed_commit": self.deployed_commit or None,
        }


def validate_runtime_rollout_config(
    *,
    phase: str,
    agent_type: str,
    environ: Mapping[str, str] | None = None,
    online_status: Mapping[str, object] | None = None,
) -> RolloutConfigValidation:
    if phase not in {"control", "shadow"}:
        raise ValueError("phase must be control or shadow")
    if agent_type not in AGENT_BPS_ENV:
        raise ValueError("unsupported rollout agent type")
    env = environ or os.environ
    errors: list[str] = []
    warnings: list[str] = []
    config = str(env.get("EDU_AGENT_RUNTIME_V2_CONFIG_VERSION", "")).strip()[:120]
    environment = str(env.get("EDU_AGENT_ENVIRONMENT", "") or (deployment_environment() if environ is None else "local")).strip()[:80]
    commit = str(env.get("EDU_AGENT_DEPLOYED_COMMIT", "") or env.get("RENDER_GIT_COMMIT", "") or (deployed_commit() if environ is None else "")).strip()[:120]
    enabled = _enabled(env, "EDU_AGENT_RUNTIME_V2_ENABLED")
    shadow_mode = _enabled(env, "EDU_AGENT_RUNTIME_V2_SHADOW_MODE", True)
    kill_switch = _enabled(env, "EDU_AGENT_RUNTIME_V2_KILL_SWITCH")

    if not config:
        errors.append("runtime_config_version_missing")
    elif config == "v1.33-control":
        errors.append("runtime_config_version_legacy_default")
    if environment == "production" and not re.fullmatch(r"[0-9a-f]{40}", commit):
        errors.append("deployed_commit_invalid")

    if phase == "control":
        if enabled:
            errors.append("control_runtime_must_be_disabled")
        if any(_bps(env, name) > 0 for name in AGENT_BPS_ENV.values()):
            errors.append("control_agent_bps_must_be_zero")
        if "control" not in config:
            warnings.append("control_config_version_name_unexpected")
    else:
        if not enabled:
            errors.append("shadow_runtime_disabled")
        if not shadow_mode:
            errors.append("shadow_mode_disabled")
        if kill_switch:
            errors.append("kill_switch_enabled")
        if _bps(env, "EDU_AGENT_RUNTIME_V2_PERCENT_BPS") != 10_000:
            errors.append("shadow_global_bps_not_10000")
        if _bps(env, AGENT_BPS_ENV[agent_type]) != 10_000:
            errors.append("shadow_target_agent_bps_not_10000")
        if any(_bps(env, name) > 0 for key, name in AGENT_BPS_ENV.items() if key != agent_type):
            errors.append("shadow_non_target_agent_enabled")
        if not _enabled(env, "EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS", True):
            errors.append("shadow_event_persistence_disabled")
        if not _enabled(env, "EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"):
            errors.append("shadow_artifact_persistence_disabled")
        if "shadow" not in config:
            errors.append("shadow_config_version_name_invalid")
        baseline_config = str(env.get("EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_CONFIG_VERSION", "")).strip()
        baseline_commit = str(env.get("EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_COMMIT", "")).strip()
        if not baseline_config:
            errors.append("baseline_config_version_missing")
        if not re.fullmatch(r"[0-9a-f]{40}", baseline_commit):
            errors.append("baseline_commit_invalid")
        for name, code in (
            ("EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED", "shadow_checkpoint_must_be_disabled"),
            ("EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED", "shadow_resumable_must_be_disabled"),
            ("EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED", "shadow_dynamic_replan_must_be_disabled"),
            ("EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED", "shadow_read_fanout_must_be_disabled"),
        ):
            if _enabled(env, name):
                errors.append(code)
        try:
            minimum = int(str(env.get("EDU_AGENT_RUNTIME_ROLLOUT_MIN_TERMINAL_RUNS", "100")))
        except ValueError:
            minimum = 0
        if environment == "production" and minimum < 100:
            errors.append("production_minimum_samples_below_100")
        if online_status is not None:
            auth = online_status.get("auth_configuration") if isinstance(online_status.get("auth_configuration"), Mapping) else {}
            if environment == "production" and not bool(auth.get("ok")):
                errors.append("production_auth_configuration_invalid")
            cohort = online_status.get("trusted_cohort") if isinstance(online_status.get("trusted_cohort"), Mapping) else {}
            if environment == "production" and not bool(cohort.get("ready")):
                errors.append("trusted_cohort_missing")
            deployment = online_status.get("deployment") if isinstance(online_status.get("deployment"), Mapping) else {}
            online_commit = str(deployment.get("commit") or "")
            if online_commit and commit and online_commit != commit:
                errors.append("deployed_commit_mismatch")
            control = online_status.get("control") if isinstance(online_status.get("control"), Mapping) else {}
            if int(control.get("terminal_samples") or 0) < max(100, minimum):
                errors.append("control_samples_insufficient")
            observation = online_status.get("safety") if isinstance(online_status.get("safety"), Mapping) else {}
            if int(observation.get("observation_write_failures") or 0) > 0:
                errors.append("rollout_observation_write_failures_detected")

    if not shadow_mode and not _enabled(env, "EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED"):
        errors.append("runtime_active_not_approved")
    return RolloutConfigValidation(
        phase=phase,
        agent_type=agent_type,
        ok=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        config_version=config,
        environment=environment,
        deployed_commit=commit,
    )
