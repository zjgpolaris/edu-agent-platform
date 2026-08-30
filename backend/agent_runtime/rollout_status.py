from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from agent_runtime.context import RuntimeV2Settings
from agent_runtime.evidence_store import load_release_evidence
from agent_runtime.readiness import runtime_schema_readiness
from agent_runtime.rollout_config import validate_runtime_rollout_config
from agent_runtime.rollout_gate import build_rollout_readiness
from agent_runtime.rollout_observations import control_observation_progress, observation_write_health
from deployment import deployed_commit, deployment_environment, runtime_configuration_errors, runtime_config_version


SUPPORTED_ROLLOUT_AGENTS = {"history_character"}
HARD_GATE_REASONS = {
    "duplicate_side_effects_detected",
    "invalid_transitions_detected",
    "high_risk_without_confirmation_detected",
    "terminal_consistency_below_100pct",
    "unexpected_failure_rate_above_2pct",
    "event_coverage_below_80pct",
    "p95_regression_above_10pct",
}


def _minimum_samples(value: int | None) -> int:
    if value is None:
        try:
            value = int(os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_MIN_TERMINAL_RUNS", "100"))
        except ValueError:
            value = 100
    minimum = max(1, min(int(value), 100_000))
    return max(100, minimum) if deployment_environment() == "production" else minimum


def _evidence_age_hours(evidence: dict[str, Any] | None) -> float | None:
    if not evidence:
        return None
    try:
        generated = datetime.fromisoformat(str(evidence.get("generated_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 3600, 2)


def build_rollout_status(
    *,
    agent_type: str,
    window_hours: int = 168,
    minimum_samples: int | None = None,
) -> dict[str, Any]:
    """Build a phase-aware, PII-free operator view for one rollout slice."""
    if agent_type not in SUPPORTED_ROLLOUT_AGENTS:
        raise ValueError("unsupported rollout agent type")
    minimum = _minimum_samples(minimum_samples)
    window_hours = max(1, min(int(window_hours), 24 * 31))
    settings = RuntimeV2Settings.from_env()
    commit = deployed_commit()
    environment = deployment_environment()
    config = runtime_config_version()
    runtime_mode = "shadow" if settings.shadow_mode else "active"
    schema = runtime_schema_readiness()
    observation_health = observation_write_health(window_minutes=15)
    deployment_errors = runtime_configuration_errors(enabled=settings.enabled, config_version=config)

    baseline_config = os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_CONFIG_VERSION", "").strip()
    baseline_commit = os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_COMMIT", "").strip()
    if not settings.enabled:
        baseline_config = baseline_config or config
        baseline_commit = baseline_commit or commit
    try:
        control = control_observation_progress(
            agent_type=agent_type,
            config_version=baseline_config,
            deployed_commit=baseline_commit,
            environment=environment,
            minimum_samples=minimum,
        )
    except Exception as exc:
        control = {
            "commit": baseline_commit or None,
            "config_version": baseline_config or None,
            "environment": environment or None,
            "terminal_samples": 0,
            "minimum_samples": minimum,
            "sample_sufficient": False,
            "baseline_ready": False,
            "p50_ms": None,
            "p95_ms": None,
            "error_type": exc.__class__.__name__,
        }

    config_phase = "shadow" if settings.enabled else "control"
    config_validation = validate_runtime_rollout_config(phase=config_phase, agent_type=agent_type)
    if settings.enabled:
        gate = build_rollout_readiness(
            agent_type=agent_type,
            window_hours=window_hours,
            minimum_terminal_runs=minimum,
            config_version=config,
            runtime_mode=runtime_mode,
            deployed_commit=commit,
            environment=environment,
        )
    else:
        gate = {
            "status": "unknown",
            "agent_type": agent_type,
            "config_version": config or None,
            "runtime_mode": "control",
            "deployed_commit": commit or None,
            "environment": environment or None,
            "terminal_runs": 0,
            "minimum_terminal_runs": minimum,
            "reasons": ["runtime_disabled_control_collection"],
            "profiles": {"offline": "unknown", "real_llm": "unknown", "production_rag": "unknown"},
        }

    evidence = load_release_evidence(
        agent_type=agent_type,
        config_version=config,
        runtime_mode=runtime_mode,
        deployed_commit=commit,
        environment=environment,
    ) if settings.enabled else None
    evidence_age = _evidence_age_hours(evidence)
    evidence_fresh = evidence_age is not None and 0 <= evidence_age <= 168
    gate_reasons = [str(item) for item in gate.get("reasons") or []]
    hard_gate_reasons = [reason for reason in gate_reasons if reason in HARD_GATE_REASONS]

    blockers: list[str] = []
    if not schema.get("schema_ready"):
        blockers.append("runtime_schema_not_ready")
    blockers.extend(deployment_errors)
    if observation_health.get("status") == "unavailable":
        blockers.append("rollout_observation_health_unavailable")
    elif int(observation_health.get("failure_count") or 0) > 0:
        blockers.append("rollout_observation_write_failures_detected")
    blockers.extend(config_validation.errors)

    terminal_runs = int(gate.get("terminal_runs") or 0)
    if hard_gate_reasons:
        phase = "stopped"
        status = "blocked"
        blockers.extend(hard_gate_reasons)
        next_action = "stop_rollout"
    elif blockers:
        phase = "deployment_blocked"
        status = "blocked"
        next_action = "fix_deployment_contract"
    elif not bool(control.get("sample_sufficient")):
        phase = "collecting_control"
        status = "blocked"
        blockers.append("control_samples_insufficient")
        next_action = "continue_collecting_control"
    elif not settings.enabled:
        phase = "control_ready"
        status = "pass"
        next_action = "run_shadow_preflight"
    elif terminal_runs < minimum:
        phase = "collecting_shadow"
        status = "unknown"
        blockers.append("terminal_samples_insufficient")
        next_action = "continue_collecting_shadow"
    elif gate.get("status") in {"unknown", "fail"} or not evidence_fresh:
        phase = "evidence_pending"
        status = "blocked" if gate.get("status") == "fail" else "unknown"
        blockers.extend(gate_reasons)
        next_action = "investigate_gate_failure" if gate.get("status") == "fail" else "run_rollout_evidence"
    elif evidence_age is not None and evidence_age < 48:
        phase = "shadow_observing"
        status = "warn" if gate.get("status") == "warn" else "pass"
        next_action = "continue_48h_observation"
    else:
        phase = "shadow_complete"
        status = "pass" if gate.get("status") == "pass" else "warn"
        next_action = "shadow_operational_complete"

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "phase": phase,
        "status": status,
        "agent_type": agent_type,
        "deployment": {
            "commit": commit or None,
            "environment": environment or None,
            "config_version": config or None,
            "runtime_enabled": settings.enabled,
            "runtime_mode": runtime_mode,
            "kill_switch": settings.kill_switch,
        },
        "control": control,
        "shadow": {
            "terminal_runs": terminal_runs,
            "minimum_terminal_runs": minimum,
            "run_provenance_coverage": gate.get("run_provenance_coverage"),
            "event_coverage": gate.get("event_coverage"),
            "terminal_consistency": gate.get("terminal_consistency"),
            "unexpected_failure_rate": gate.get("unexpected_failure_rate"),
            "p95_regression": gate.get("p95_regression"),
            "run_latency": gate.get("run_latency") or {},
        },
        "safety": {
            "duplicate_side_effects": int(gate.get("duplicate_side_effects") or 0),
            "duplicate_attempts_prevented": int(gate.get("duplicate_attempts_prevented") or 0),
            "invalid_transitions": int(gate.get("invalid_transitions") or 0),
            "high_risk_without_confirmation": int(gate.get("high_risk_without_confirmation") or 0),
            "observation_write_failures": observation_health.get("failure_count"),
        },
        "evidence": {
            "present": evidence is not None,
            "fresh": evidence_fresh,
            "age_hours": evidence_age,
            "sha256": evidence.get("evidence_sha256") if evidence else None,
            "profiles": gate.get("profiles") or {"offline": "unknown", "real_llm": "unknown", "production_rag": "unknown"},
        },
        "gate": {"status": gate.get("status", "unknown"), "reasons": gate_reasons},
        "config_validation": config_validation.as_dict(),
        "blockers": blockers,
        "next_action": next_action,
    }
