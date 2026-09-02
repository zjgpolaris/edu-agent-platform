"""AutoTutor v1.49 executor contracts, trusted sticky routing and rollout config."""
from __future__ import annotations

import copy
import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from deployment import deployed_commit, deployment_environment


ExecutorMode = Literal["legacy", "graph_active"]
ConfiguredExecutorMode = Literal["legacy", "shadow", "active_canary"]
TransitionKind = Literal["start", "lesson_answer", "exit_ticket_answer", "recovery_resume"]
_TRUE = {"1", "true", "yes", "on"}


def _enabled(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    return default if raw is None else str(raw).strip().lower() in _TRUE


def _integer(env: Mapping[str, str], name: str, default: int = 0) -> int:
    try:
        return int(str(env.get(name, default)).strip())
    except (TypeError, ValueError):
        return -1


@dataclass(frozen=True, slots=True)
class AutoTutorExecutionContext:
    actor_id: str | None = None
    actor_role: str | None = None
    account_status: str = "anonymous"
    traffic_cohort: str = "anonymous"
    data_scope: str = "runtime"
    rollout_eligible: bool = False
    eligibility_reason: str = "anonymous_actor"
    environment: str = "local"
    deployed_commit: str = ""
    internal_force_graph: bool = False


@dataclass(frozen=True, slots=True)
class AutoTutorExecutorSettings:
    mode: ConfiguredExecutorMode
    active_bps: int
    config_version: str
    bucket_salt: str
    kill_switch: bool
    comparator_enabled: bool
    fallback_enabled: bool
    valid: bool
    reason_codes: tuple[str, ...]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AutoTutorExecutorSettings":
        env = environ or os.environ
        explicit = str(env.get("EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE", "")).strip().lower()
        if explicit:
            mode = explicit
        elif _enabled(env, "EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED"):
            mode = "shadow"
        else:
            mode = "legacy"
        errors: list[str] = []
        if mode not in {"legacy", "shadow", "active_canary"}:
            errors.append("executor_mode_invalid")
            mode = "legacy"
        bps = _integer(env, "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS")
        config = str(env.get("EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION", "v1.49-active")).strip()[:120]
        salt = str(env.get("EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT", "v1.49")).strip()[:120]
        kill_switch = _enabled(env, "EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH")
        comparator = _enabled(env, "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED", True)
        fallback = _enabled(env, "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED", True)
        if bps < 0 or bps > 1000:
            errors.append("active_bps_out_of_range")
        if mode == "active_canary":
            if bps < 1:
                errors.append("active_bps_must_be_positive")
            if kill_switch:
                errors.append("kill_switch_enabled")
            if not comparator:
                errors.append("comparator_disabled")
            if not fallback:
                errors.append("fallback_disabled")
            if not config:
                errors.append("config_version_missing")
            if not salt:
                errors.append("bucket_salt_missing")
            environment = str(env.get("EDU_AGENT_ENVIRONMENT", "") or (deployment_environment() if environ is None else "local"))
            commit = str(env.get("EDU_AGENT_DEPLOYED_COMMIT", "") or env.get("RENDER_GIT_COMMIT", "") or (deployed_commit() if environ is None else ""))
            if environment == "production" and not re.fullmatch(r"[0-9a-f]{40}", commit):
                errors.append("deployed_commit_invalid")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            active_bps=max(0, min(bps, 1000)),
            config_version=config or "v1.49-active",
            bucket_salt=salt or "v1.49",
            kill_switch=kill_switch,
            comparator_enabled=comparator,
            fallback_enabled=fallback,
            valid=not errors,
            reason_codes=tuple(dict.fromkeys(errors)),
        )


def stable_executor_bucket(subject: str, *, salt: str) -> int:
    digest = hashlib.sha256(f"autotutor-executor:{salt}:{subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


@dataclass(frozen=True, slots=True)
class AutoTutorExecutorDecision:
    mode: ExecutorMode
    config_version: str | None
    bucket: int | None
    fallback_reason: str | None


def select_executor(
    *,
    subject: str,
    context: AutoTutorExecutionContext,
    settings: AutoTutorExecutorSettings | None = None,
) -> AutoTutorExecutorDecision:
    settings = settings or AutoTutorExecutorSettings.from_env()
    bucket = stable_executor_bucket(subject, salt=settings.bucket_salt)
    if context.internal_force_graph and context.environment != "production":
        return AutoTutorExecutorDecision("graph_active", settings.config_version, bucket, None)
    if settings.mode != "active_canary":
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, None)
    if not settings.valid:
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, settings.reason_codes[0])
    if settings.kill_switch:
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, "kill_switch_enabled")
    trusted = (
        context.account_status == "active"
        and context.traffic_cohort == "verified"
        and context.data_scope == "runtime"
        and context.rollout_eligible
    )
    if not trusted:
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, context.eligibility_reason or "rollout_ineligible")
    if bucket >= settings.active_bps:
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, "bucket_not_selected")
    return AutoTutorExecutorDecision("graph_active", settings.config_version, bucket, None)


class AutoTutorObservationBundle(BaseModel):
    """Immutable, reusable input captured exactly once for a transition."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal["v1.49-observation"] = "v1.49-observation"
    transition_kind: TransitionKind
    command: dict[str, Any] = Field(default_factory=dict)
    clock: dict[str, float] = Field(default_factory=dict)
    identifiers: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    materialized: dict[str, Any] = Field(default_factory=dict, exclude=True)


class AutoTutorObservationProvider(Protocol):
    def prepare(
        self,
        *,
        before: Any,
        command: dict[str, Any],
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundle: ...


class AutoTutorTransitionDiagnostics(BaseModel):
    observation_external_calls: int = 0
    executor_latency_ms: float = 0.0
    comparator_latency_ms: float = 0.0
    comparator_matched: bool = True
    fallback_reason: str | None = None
    visited_nodes: list[str] = Field(default_factory=list)


class AutoTutorTransitionOutcome(BaseModel):
    """Complete internal outcome; only one instance may cross the commit boundary."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    schema_version: Literal["v1.49-outcome"] = "v1.49-outcome"
    executor_mode: ExecutorMode
    next_state: Any
    learning_events: list[Any] = Field(default_factory=list)
    weakpoint_evidence: list[Any] = Field(default_factory=list)
    review_memory: Any | None = None
    runtime_events: list[dict[str, Any]] = Field(default_factory=list)
    runtime_finalize: dict[str, Any] | None = None
    public_result: dict[str, Any] = Field(default_factory=dict)
    diagnostics: AutoTutorTransitionDiagnostics = Field(default_factory=AutoTutorTransitionDiagnostics)


class AutoTutorTransitionExecutor(Protocol):
    mode: ExecutorMode

    def execute(self, *, before: Any, command: dict[str, Any], observations: AutoTutorObservationBundle) -> AutoTutorTransitionOutcome: ...


class LegacyTransitionExecutor:
    mode: ExecutorMode = "legacy"

    def execute(self, *, before: Any, command: dict[str, Any], observations: AutoTutorObservationBundle) -> AutoTutorTransitionOutcome:
        del before, command
        outcome = AutoTutorTransitionOutcome.model_validate(copy.deepcopy(observations.materialized))
        outcome.executor_mode = "legacy"
        return outcome


class GraphActiveTransitionExecutor:
    mode: ExecutorMode = "graph_active"

    def execute(self, *, before: Any, command: dict[str, Any], observations: AutoTutorObservationBundle) -> AutoTutorTransitionOutcome:
        del before, command
        from agents.autotutor_graph import execute_autotutor_active

        return execute_autotutor_active(observations)


def validate_autotutor_executor_config(environ: Mapping[str, str] | None = None) -> AutoTutorExecutorSettings:
    """Return the fail-closed AutoTutor-specific active-canary validation result."""
    return AutoTutorExecutorSettings.from_env(environ)


class CapturedAutoTutorObservationProvider:
    """Capture one producer result while preserving the caller-owned before state."""

    def __init__(
        self,
        transition_kind: TransitionKind,
        producer: Callable[[Any, dict[str, Any], AutoTutorExecutionContext], AutoTutorTransitionOutcome],
    ):
        self._transition_kind = transition_kind
        self._producer = producer

    def prepare(
        self,
        *,
        before: Any,
        command: dict[str, Any],
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundle:
        candidate_before = copy.deepcopy(before)
        outcome = self._producer(candidate_before, copy.deepcopy(command), context)
        return AutoTutorObservationBundle(
            transition_kind=self._transition_kind,
            command=copy.deepcopy(command),
            provenance={"external_call_set": "single_active_transition"},
            materialized=outcome.model_dump(round_trip=True),
        )


def clone_observation(bundle: AutoTutorObservationBundle) -> AutoTutorObservationBundle:
    return bundle.model_copy(update={"materialized": copy.deepcopy(bundle.materialized)})
