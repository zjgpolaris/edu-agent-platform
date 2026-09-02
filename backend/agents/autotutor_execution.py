"""AutoTutor v1.49 executor contracts, trusted sticky routing and rollout config."""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from deployment import deployed_commit, deployment_environment
from services.autotutor_transition_service import LearningEventIntent, WeakpointEvidenceIntent
from student_profile import MemoryEntryUpsert


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
    bucket_salt_configured: bool
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
        config = str(env.get("EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION", "v1.49.7-scoped-verification-identity")).strip()[:120]
        salt_configured = bool(str(env.get("EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT", "")).strip())
        salt = str(env.get("EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT", "v1.49.7")).strip()[:120]
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
            if not salt_configured:
                errors.append("bucket_salt_missing")
            environment = str(env.get("EDU_AGENT_ENVIRONMENT", "") or (deployment_environment() if environ is None else "local"))
            commit = str(env.get("EDU_AGENT_DEPLOYED_COMMIT", "") or env.get("RENDER_GIT_COMMIT", "") or (deployed_commit() if environ is None else ""))
            if environment == "production" and not re.fullmatch(r"[0-9a-f]{40}", commit):
                errors.append("deployed_commit_invalid")
            if environment == "production" and bps > 100:
                errors.append("production_active_bps_exceeds_one_percent")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            active_bps=max(0, min(bps, 1000)),
            config_version=config or "v1.49.7-scoped-verification-identity",
            bucket_salt=salt or "v1.49.7",
            bucket_salt_configured=salt_configured,
            kill_switch=kill_switch,
            comparator_enabled=comparator,
            fallback_enabled=fallback,
            valid=not errors,
            reason_codes=tuple(dict.fromkeys(errors)),
        )

    @property
    def cohort_fingerprint(self) -> str:
        payload = "\n".join((self.config_version, self.bucket_salt, "sha256-mod-10000-v1"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def runtime_state_fingerprint(self) -> str:
        payload = "\n".join((
            self.mode,
            str(self.active_bps),
            self.config_version,
            str(self.kill_switch).lower(),
            str(self.comparator_enabled).lower(),
            str(self.fallback_enabled).lower(),
        ))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def config_fingerprint(self) -> str:
        """Compatibility alias for the mutable runtime-state identity."""
        return self.runtime_state_fingerprint

    def safe_summary(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "active_bps": self.active_bps,
            "config_version": self.config_version,
            "config_fingerprint": self.config_fingerprint,
            "cohort_fingerprint": self.cohort_fingerprint,
            "runtime_state_fingerprint": self.runtime_state_fingerprint,
            "cohort_salt_configured": self.bucket_salt_configured,
            "kill_switch": self.kill_switch,
            "comparator_enabled": self.comparator_enabled,
            "fallback_enabled": self.fallback_enabled,
            "valid": self.valid,
            "reason_codes": list(self.reason_codes),
        }


def stable_executor_bucket(subject: str, *, salt: str) -> int:
    digest = hashlib.sha256(f"autotutor-executor:{salt}:{subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


@dataclass(frozen=True, slots=True)
class AutoTutorExecutorDecision:
    mode: ExecutorMode
    config_version: str | None
    bucket: int | None
    assignment_reason: str


def select_executor(
    *,
    subject: str,
    context: AutoTutorExecutionContext,
    settings: AutoTutorExecutorSettings | None = None,
    admission: Any | None = None,
) -> AutoTutorExecutorDecision:
    settings = settings or AutoTutorExecutorSettings.from_env()
    bucket = stable_executor_bucket(subject, salt=settings.bucket_salt)
    if context.internal_force_graph and context.environment != "production":
        return AutoTutorExecutorDecision("graph_active", settings.config_version, bucket, "development_force_graph")
    if settings.mode != "active_canary":
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, "executor_mode_not_active_canary")
    if not settings.valid:
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, settings.reason_codes[0])
    if settings.kill_switch:
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, "kill_switch_enabled")
    if context.environment == "production" and (admission is None or not admission.admitted):
        reason = (admission.reason_codes[0] if admission and admission.reason_codes else "canary_admission_missing")
        return AutoTutorExecutorDecision("legacy", settings.config_version, bucket, f"admission_denied:{reason}")
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
    return AutoTutorExecutorDecision("graph_active", settings.config_version, bucket, "graph_bucket_selected")


class AutoTutorObservationBundle(BaseModel):
    """Immutable, reusable input captured exactly once for a transition."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal["v1.49.2-observation"] = "v1.49.2-observation"
    transition_id: str
    transition_kind: TransitionKind
    command: dict[str, Any] = Field(default_factory=dict)
    plan: list[dict[str, Any]] = Field(default_factory=list)
    content: dict[str, Any] | None = None
    reflection: dict[str, Any] | None = None
    advance_content: dict[str, Any] | None = None
    exit_ticket: dict[str, Any] | None = None
    clock: dict[str, float] = Field(default_factory=dict)
    identifiers: dict[str, str] = Field(default_factory=dict)
    selection: dict[str, str] = Field(default_factory=dict)
    call_counts: dict[str, int] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def _forbidden_keys(cls) -> set[str]:
        return {
            "materialized", "next_state", "public_result", "expected_state",
            "expected_projection", "effect_intents", "runtime_events",
            "verified_mastery", "derived_status", "legacy_after",
        }

    def assert_no_derived_outcome(self) -> None:
        def visit(value: Any) -> None:
            if isinstance(value, dict):
                forbidden = self._forbidden_keys().intersection(value)
                if forbidden:
                    raise ValueError(f"observation_derived_outcome_forbidden:{sorted(forbidden)[0]}")
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(self.model_dump(mode="python"))


class AutoTutorObservationProvider(Protocol):
    def prepare(
        self,
        *,
        before: Any,
        command: dict[str, Any],
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundle: ...


class AutoTutorTransitionDiagnostics(BaseModel):
    transition_id: str | None = None
    observation_external_calls: int = 0
    provider_latency_ms: float = 0.0
    executor_latency_ms: float = 0.0
    comparator_latency_ms: float = 0.0
    comparator_matched: bool = True
    fallback_reason: str | None = None
    visited_nodes: list[str] = Field(default_factory=list)


class AutoTutorTransitionOutcome(BaseModel):
    """Complete internal outcome; only one instance may cross the commit boundary."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    schema_version: Literal["v1.49.2-outcome"] = "v1.49.2-outcome"
    executor_mode: ExecutorMode
    next_state: object
    learning_events: list[LearningEventIntent] = Field(default_factory=list)
    weakpoint_evidence: list[WeakpointEvidenceIntent] = Field(default_factory=list)
    review_memory: MemoryEntryUpsert | None = None
    runtime_events: list[dict[str, object]] = Field(default_factory=list)
    runtime_finalize: dict[str, object] | None = None
    public_result: dict[str, object] = Field(default_factory=dict)
    diagnostics: AutoTutorTransitionDiagnostics = Field(default_factory=AutoTutorTransitionDiagnostics)


class AutoTutorTransitionExecutor(Protocol):
    mode: ExecutorMode

    def execute(self, *, before: Any, command: dict[str, Any], observations: AutoTutorObservationBundle) -> AutoTutorTransitionOutcome: ...


class LegacyTransitionExecutor:
    mode: ExecutorMode = "legacy"

    def execute(self, *, before: Any, command: dict[str, Any], observations: AutoTutorObservationBundle) -> AutoTutorTransitionOutcome:
        from agents.autotutor_transition_kernel import execute_autotutor_transition

        outcome = execute_autotutor_transition(before=before, command=command, observations=observations)
        outcome.executor_mode = "legacy"
        return outcome


class GraphActiveTransitionExecutor:
    mode: ExecutorMode = "graph_active"

    def execute(self, *, before: Any, command: dict[str, Any], observations: AutoTutorObservationBundle) -> AutoTutorTransitionOutcome:
        from agents.autotutor_graph import execute_autotutor_active

        return execute_autotutor_active(before=before, command=command, observations=observations)


def validate_autotutor_executor_config(environ: Mapping[str, str] | None = None) -> AutoTutorExecutorSettings:
    """Return the fail-closed AutoTutor-specific active-canary validation result."""
    return AutoTutorExecutorSettings.from_env(environ)


def compare_transition_outcomes(
    selected: AutoTutorTransitionOutcome,
    comparator: AutoTutorTransitionOutcome,
) -> tuple[bool, tuple[str, ...]]:
    """Compare complete business semantics while ignoring executor diagnostics."""
    reasons: list[str] = []

    def stable(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if isinstance(value, dict):
            return {
                key: stable(item)
                for key, item in sorted(value.items())
                if key not in {"executor_mode", "executor_fallback_reason", "latency_ms"}
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    if stable(selected.next_state) != stable(comparator.next_state):
        reasons.append("state_mismatch")
    if stable(selected.public_result) != stable(comparator.public_result):
        reasons.append("public_result_mismatch")
    if stable(selected.runtime_events) != stable(comparator.runtime_events):
        reasons.append("runtime_event_mismatch")
    if stable(selected.learning_events) != stable(comparator.learning_events):
        reasons.append("learning_effect_mismatch")
    if stable(selected.weakpoint_evidence) != stable(comparator.weakpoint_evidence):
        reasons.append("weakpoint_effect_mismatch")
    if stable(selected.review_memory) != stable(comparator.review_memory):
        reasons.append("review_effect_mismatch")
    if stable(selected.runtime_finalize) != stable(comparator.runtime_finalize):
        reasons.append("runtime_finalize_mismatch")
    return not reasons, tuple(reasons)
