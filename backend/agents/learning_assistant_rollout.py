from __future__ import annotations

import hashlib
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from agents.learning_assistant_router import env_enabled


class RolloutDecision(BaseModel):
    schema_version: Literal[1] = 1
    route_mode: Literal["control", "shadow", "semantic_active"]
    planner_mode: Literal["control", "composition_active"]
    bucket: int = Field(ge=0, le=9999)
    semantic_percent_bps: int = Field(ge=0, le=10000)
    planner_percent_bps: int = Field(ge=0, le=10000)
    subject_type: Literal["student", "session", "request"]
    subject_hash: str = Field(min_length=8, max_length=32)
    reason_code: str
    config_version: str


def _percent_bps(name: str, *, enabled: bool) -> int:
    raw = os.getenv(name)
    if raw is None:
        return 10000 if enabled else 0
    try:
        return min(10000, max(0, int(raw)))
    except ValueError:
        return 0


def _subject(req: dict[str, Any]) -> tuple[str, str]:
    student_id = str(req.get("student_id") or "").strip()
    if student_id:
        return "student", student_id
    session_id = str(req.get("session_id") or "").strip()
    if session_id:
        return "session", session_id
    return "request", str(req.get("trace_id") or req.get("request_id") or "anonymous-request")


def _bucket(subject: str) -> tuple[int, str]:
    salt = os.getenv("EDU_AGENT_ASSISTANT_ROLLOUT_SALT", "edu-agent-local-rollout")
    digest = hashlib.sha256(f"{salt}:{subject}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10000, digest[:16]


def build_rollout_decision(
    req: dict[str, Any],
    *,
    high_risk: bool,
    composition_candidate: bool,
) -> RolloutDecision:
    semantic_enabled = env_enabled("EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED")
    planner_enabled = env_enabled("EDU_AGENT_ASSISTANT_PLANNER_ENABLED")
    shadow_enabled = env_enabled("EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE", True)
    kill_switch = env_enabled("EDU_AGENT_ASSISTANT_ROLLOUT_KILL_SWITCH")
    semantic_percent = _percent_bps("EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS", enabled=semantic_enabled)
    planner_percent = _percent_bps("EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS", enabled=planner_enabled)
    subject_type, subject = _subject(req)
    bucket, subject_hash = _bucket(subject)
    config_version = os.getenv("EDU_AGENT_ASSISTANT_ROLLOUT_CONFIG_VERSION", "v1.30-control")[:80]

    route_mode: Literal["control", "shadow", "semantic_active"] = "control"
    planner_mode: Literal["control", "composition_active"] = "control"
    reason_code = "feature_disabled"
    if kill_switch:
        reason_code = "kill_switch"
    elif high_risk:
        reason_code = "high_risk_rule_only"
    elif semantic_enabled and shadow_enabled:
        route_mode = "shadow"
        reason_code = "semantic_shadow"
    elif semantic_enabled and bucket < semantic_percent:
        route_mode = "semantic_active"
        reason_code = "semantic_bucket_active"
    elif semantic_enabled:
        reason_code = "semantic_bucket_control"

    if not kill_switch and not high_risk and planner_enabled and composition_candidate and bucket < planner_percent:
        planner_mode = "composition_active"

    return RolloutDecision(
        route_mode=route_mode,
        planner_mode=planner_mode,
        bucket=bucket,
        semantic_percent_bps=semantic_percent,
        planner_percent_bps=planner_percent,
        subject_type=subject_type,
        subject_hash=subject_hash,
        reason_code=reason_code,
        config_version=config_version,
    )
