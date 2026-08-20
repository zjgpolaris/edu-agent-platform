from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from uuid import uuid4

from agent_runtime.models import ActorRole, AgentContext, DataScope, DurabilityMode

_TRUE_VALUES = {"1", "true", "yes", "on"}
_AGENT_BPS_ENV = {
    "learning_assistant": "EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS",
    "auto_tutor": "EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS",
    "history_character": "EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS",
    "essay_grader": "EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS",
    "debate": "EDU_AGENT_RUNTIME_V2_DEBATE_BPS",
}


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _bps(name: str, default: int = 0) -> int:
    try:
        return max(0, min(int(os.getenv(name, str(default))), 10_000))
    except (TypeError, ValueError):
        return default


def stable_rollout_bucket(agent_type: str, subject: str) -> int:
    digest = hashlib.sha256(f"runtime-v2:{agent_type}:{subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


@dataclass(frozen=True, slots=True)
class RuntimeV2Settings:
    enabled: bool
    shadow_mode: bool
    global_bps: int
    config_version: str
    kill_switch: bool
    persist_events: bool
    artifact_enabled: bool
    checkpoint_enabled: bool
    resumable_enabled: bool
    dynamic_replan_enabled: bool
    read_fanout_enabled: bool

    @classmethod
    def from_env(cls) -> "RuntimeV2Settings":
        return cls(
            enabled=_enabled("EDU_AGENT_RUNTIME_V2_ENABLED"),
            shadow_mode=_enabled("EDU_AGENT_RUNTIME_V2_SHADOW_MODE", True),
            global_bps=_bps("EDU_AGENT_RUNTIME_V2_PERCENT_BPS"),
            config_version=os.getenv("EDU_AGENT_RUNTIME_V2_CONFIG_VERSION", "v1.33-control")[:120],
            kill_switch=_enabled("EDU_AGENT_RUNTIME_V2_KILL_SWITCH"),
            persist_events=_enabled("EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS", True),
            artifact_enabled=_enabled("EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"),
            checkpoint_enabled=_enabled("EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED"),
            resumable_enabled=_enabled("EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED"),
            dynamic_replan_enabled=_enabled("EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED"),
            read_fanout_enabled=_enabled("EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED"),
        )

    def rollout_decision(self, agent_type: str, subject: str) -> tuple[bool, int]:
        bucket = stable_rollout_bucket(agent_type, subject)
        if self.kill_switch or not self.enabled or not self.persist_events:
            return False, bucket
        agent_bps = _bps(_AGENT_BPS_ENV[agent_type], self.global_bps) if agent_type in _AGENT_BPS_ENV else self.global_bps
        return bucket < min(agent_bps, self.global_bps), bucket

    @property
    def resumable_ready(self) -> bool:
        return self.artifact_enabled and self.checkpoint_enabled and self.resumable_enabled

    @property
    def observable_ready(self) -> bool:
        return self.persist_events and self.artifact_enabled


def create_agent_context(
    *,
    agent_type: str,
    actor_id: str | None,
    actor_role: ActorRole,
    student_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    durability_mode: DurabilityMode,
    source_feature: str | None = None,
    source_session_id: str | None = None,
    data_scope: DataScope = "runtime",
    settings: RuntimeV2Settings | None = None,
) -> AgentContext:
    settings = settings or RuntimeV2Settings.from_env()
    subject = actor_id or student_id or session_id or uuid4().hex
    _, bucket = settings.rollout_decision(agent_type, subject)
    if durability_mode == "resumable" and not settings.resumable_ready:
        raise RuntimeError("resumable runtime requires artifact, checkpoint and resumable readiness")
    return AgentContext(
        run_id=f"run_{uuid4().hex}",
        agent_type=agent_type,
        actor_id=actor_id,
        actor_role=actor_role,
        student_id=student_id,
        session_id=session_id,
        source_feature=source_feature,
        source_session_id=source_session_id,
        trace_id=trace_id or f"trace_{uuid4().hex}",
        data_scope=data_scope,
        durability_mode=durability_mode,
        config_version=settings.config_version,
        rollout_bucket=bucket,
    )
