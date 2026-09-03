"""Fail-closed production admission for the AutoTutor Graph canary."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

REQUIRED_SCHEMA_REVISION = 17
_CACHE_TTL_SECONDS = 10.0
_cache_lock = threading.Lock()
_cache: dict[tuple[str, str, str], tuple[float, "AutoTutorCanaryAdmissionSnapshot"]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=_CACHE_TTL_SECONDS)).isoformat()


@dataclass(frozen=True, slots=True)
class AutoTutorCanaryAdmissionSnapshot:
    status: Literal["admitted", "denied", "unknown"]
    checked_at: str
    expires_at: str
    environment: str
    deployed_commit: str
    config_version: str
    schema_revision: str | None
    observation_health: Literal["ok", "degraded", "unavailable"]
    active_bps: int
    reason_codes: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return self.status == "admitted" and not self.reason_codes


def clear_autotutor_canary_admission_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _infrastructure_snapshot(*, settings: Any, context: Any) -> AutoTutorCanaryAdmissionSnapshot:
    checked_at = _now_iso()
    reasons: list[str] = []
    schema_revision: str | None = None
    health_status: Literal["ok", "degraded", "unavailable"] = "unavailable"
    try:
        from agent_runtime.readiness import runtime_schema_readiness

        schema = runtime_schema_readiness()
        schema_revision = str(schema.get("alembic_version") or "") or None
        try:
            revision_number = int(schema_revision or "0")
        except ValueError:
            revision_number = 0
        if not schema.get("schema_ready") or revision_number < REQUIRED_SCHEMA_REVISION:
            reasons.append("runtime_schema_not_ready")
    except Exception:
        reasons.append("runtime_schema_query_failed")

    try:
        from agent_runtime.rollout_observations import observation_write_health

        health = observation_write_health(
            window_minutes=15,
            config_version=settings.config_version,
            deployed_commit=context.deployed_commit,
            environment=context.environment,
        )
        raw_health = str(health.get("status") or "unavailable")
        health_status = raw_health if raw_health in {"ok", "degraded", "unavailable"} else "unavailable"  # type: ignore[assignment]
        if not health.get("ok"):
            reasons.append("observation_health_" + health_status)
    except Exception:
        reasons.append("observation_health_query_failed")

    status: Literal["admitted", "denied", "unknown"]
    if any(reason.endswith("query_failed") for reason in reasons):
        status = "unknown"
    else:
        status = "denied" if reasons else "admitted"
    return AutoTutorCanaryAdmissionSnapshot(
        status=status,
        checked_at=checked_at,
        expires_at=_expires_iso(),
        environment=context.environment,
        deployed_commit=context.deployed_commit,
        config_version=settings.config_version,
        schema_revision=schema_revision,
        observation_health=health_status,
        active_bps=settings.active_bps,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def evaluate_autotutor_canary_admission(*, settings: Any, context: Any) -> AutoTutorCanaryAdmissionSnapshot:
    """Return one PII-free snapshot. Production failures always deny Graph."""
    checked_at = _now_iso()
    base_reasons: list[str] = []
    if settings.mode != "active_canary":
        base_reasons.append("executor_mode_not_active_canary")
    if not settings.valid:
        base_reasons.extend(settings.reason_codes or ("executor_config_invalid",))
    if settings.kill_switch:
        base_reasons.append("kill_switch_enabled")
    if context.environment == "production" and not (1 <= settings.active_bps <= 100):
        base_reasons.append("production_active_bps_invalid")
    trusted = (
        context.account_status == "active"
        and context.traffic_cohort == "verified"
        and context.data_scope == "runtime"
        and context.rollout_eligible
        and context.actor_role == "student"
    )
    if not trusted:
        base_reasons.append(context.eligibility_reason or "rollout_ineligible")
    if context.internal_force_graph and context.environment == "production":
        base_reasons.append("production_internal_force_forbidden")

    if context.environment != "production":
        return AutoTutorCanaryAdmissionSnapshot(
            status="denied" if base_reasons else "admitted",
            checked_at=checked_at,
            expires_at=_expires_iso(),
            environment=context.environment,
            deployed_commit=context.deployed_commit,
            config_version=settings.config_version,
            schema_revision=None,
            observation_health="ok",
            active_bps=settings.active_bps,
            reason_codes=tuple(dict.fromkeys(base_reasons)),
        )
    if base_reasons:
        return AutoTutorCanaryAdmissionSnapshot(
            status="denied",
            checked_at=checked_at,
            expires_at=_expires_iso(),
            environment=context.environment,
            deployed_commit=context.deployed_commit,
            config_version=settings.config_version,
            schema_revision=None,
            observation_health="unavailable",
            active_bps=settings.active_bps,
            reason_codes=tuple(dict.fromkeys(base_reasons)),
        )

    key = (context.environment, context.deployed_commit, settings.runtime_state_fingerprint)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now < cached[0]:
            return cached[1]
    snapshot = _infrastructure_snapshot(settings=settings, context=context)
    with _cache_lock:
        _cache[key] = (now + _CACHE_TTL_SECONDS, snapshot)
    return snapshot
