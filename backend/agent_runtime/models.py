from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ActorRole = Literal["anonymous", "student", "teacher", "admin"]
DataScope = Literal["runtime", "eval", "demo"]
DurabilityMode = Literal["trace_only", "observable", "resumable", "queued"]
PersistedDurabilityMode = Literal["observable", "resumable", "queued"]
RunStatus = Literal[
    "received",
    "routed",
    "planned",
    "running",
    "verifying",
    "waiting_input",
    "waiting_confirmation",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
TerminalStatus = Literal["completed", "partial", "failed", "cancelled"]
StepStatus = Literal[
    "completed",
    "partial",
    "waiting_input",
    "waiting_confirmation",
    "failed",
    "cancelled",
    "degraded",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_data_scope() -> DataScope:
    value = os.getenv("EDU_AGENT_DATA_SCOPE", "runtime")
    return value if value in {"runtime", "eval", "demo"} else "runtime"


class AgentContext(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=5, max_length=96)
    agent_type: str = Field(min_length=1, max_length=80)
    actor_id: str | None = Field(default=None, max_length=128)
    actor_role: ActorRole = "anonymous"
    student_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    source_feature: str | None = Field(default=None, max_length=80)
    source_session_id: str | None = Field(default=None, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    data_scope: DataScope = Field(default_factory=default_data_scope)
    durability_mode: DurabilityMode
    config_version: str = Field(min_length=1, max_length=120)
    rollout_bucket: int | None = Field(default=None, ge=0, le=9999)
    locale: str = Field(default="zh-CN", max_length=24)

    @model_validator(mode="after")
    def validate_trusted_identity(self) -> "AgentContext":
        if self.actor_role == "student" and self.actor_id and self.student_id and self.actor_id != self.student_id:
            raise ValueError("student actor cannot target another student")
        return self


class AgentBudget(BaseModel):
    max_steps: int = Field(default=3, ge=1, le=12)
    max_tool_calls: int = Field(default=3, ge=0, le=12)
    max_llm_calls: int = Field(default=3, ge=0, le=12)
    max_replans: int = Field(default=0, ge=0, le=1)
    max_wall_time_ms: int = Field(default=15_000, ge=1000, le=300_000)
    max_parallel_reads: int = Field(default=1, ge=1, le=3)
    estimated_cost_limit_usd: float | None = Field(default=None, ge=0)


class AgentStep(BaseModel):
    step_id: str = Field(min_length=1, max_length=96)
    kind: Literal["tool", "generation", "subgraph", "verification", "control"]
    operation: str = Field(min_length=1, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    success_criteria: list[str] = Field(default_factory=list, max_length=24)
    side_effect: Literal["none", "read", "write", "session_create", "external_call"] = "none"
    risk_level: Literal["low", "medium", "high"] = "low"
    idempotency_key: str | None = Field(default=None, max_length=200)
    timeout_seconds: int = Field(default=15, ge=1, le=300)

    @model_validator(mode="after")
    def validate_side_effect_contract(self) -> "AgentStep":
        if self.side_effect in {"write", "session_create"} and not self.idempotency_key:
            raise ValueError("write and session_create steps require idempotency_key")
        if self.step_id in self.depends_on:
            raise ValueError("step cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("step dependencies must be unique")
        return self


class AgentPlan(BaseModel):
    schema_version: Literal[1] = 1
    plan_id: str = Field(min_length=1, max_length=96)
    revision: int = Field(default=0, ge=0)
    objective: str = Field(min_length=1, max_length=500)
    strategy: Literal["direct", "sequential", "subgraph"]
    steps: list[AgentStep] = Field(min_length=1, max_length=12)
    required_output: dict[str, Any] = Field(default_factory=dict)
    generated_by: Literal["deterministic", "template", "llm_proposal"]
    planner_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_dependency_dag(self) -> "AgentPlan":
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique within a plan")
        seen: set[str] = set()
        for step in self.steps:
            unknown_or_forward = [dependency for dependency in step.depends_on if dependency not in seen]
            if unknown_or_forward:
                raise ValueError(f"dependencies must reference prior steps: {unknown_or_forward}")
            seen.add(step.step_id)
        return self


class EvidenceClaim(BaseModel):
    claim_id: str = Field(min_length=1, max_length=96)
    text: str = Field(min_length=1, max_length=1200)
    critical: bool = False
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    citations: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    producer_step_id: str = Field(min_length=1, max_length=96)


class StepResult(BaseModel):
    step_id: str
    operation: str
    status: StepStatus
    output: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    evidence_claims: list[EvidenceClaim] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    retryable: bool = False
    side_effect_committed: bool = False
    attempt: int = Field(default=1, ge=1)
    latency_ms: float | None = Field(default=None, ge=0)


class CompletionDecision(BaseModel):
    status: Literal["completed", "partial", "waiting_input", "waiting_confirmation", "failed", "cancelled"]
    completion_allowed: bool
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    verification_status: Literal["verified", "partial", "failed", "not_required"]
    reason_codes: list[str] = Field(default_factory=list)
    deliverable_refs: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def completed_requires_permission(self) -> "CompletionDecision":
        if self.status == "completed" and not self.completion_allowed:
            raise ValueError("completed decision requires completion_allowed")
        if self.completion_allowed and self.status != "completed":
            raise ValueError("completion_allowed is only valid for completed status")
        return self


class AgentRunState(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    revision: int = Field(default=0, ge=0)
    durability_mode: PersistedDurabilityMode
    status: RunStatus = "received"
    objective: str = Field(min_length=1, max_length=500)
    current_step_id: str | None = None
    plan: AgentPlan | None = None
    step_results: dict[str, StepResult] = Field(default_factory=dict)
    completion: CompletionDecision | None = None
    budget: AgentBudget = Field(default_factory=AgentBudget)
    used_budget: dict[str, int | float] = Field(default_factory=dict)
    context_refs: dict[str, Any] = Field(default_factory=dict)
    input_artifact_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def validate_terminal_completion(self) -> "AgentRunState":
        if self.status in {"completed", "partial", "failed", "cancelled"} and self.completion is None:
            raise ValueError("terminal run state requires a completion decision")
        if self.plan and len(self.plan.steps) > self.budget.max_steps:
            raise ValueError("plan exceeds max_steps budget")
        return self


class ResumeSignal(BaseModel):
    expected_revision: int = Field(ge=0)
    kind: Literal["input", "confirmation", "retry"]
    correlation_key: str = Field(min_length=1, max_length=200)
    input_patch: dict[str, Any] = Field(default_factory=dict)
    confirmation_token: str | None = Field(default=None, max_length=4096)


class RuntimeEvent(BaseModel):
    schema_version: Literal[2] = 2
    run_id: str
    trace_id: str
    sequence: int = Field(ge=0)
    event: str = Field(min_length=1, max_length=80)
    timestamp: str = Field(default_factory=utc_now_iso)
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def persistable(self) -> bool:
        return self.event not in {"generation_delta", "product_event", "heartbeat"}


class ResolvedContext(BaseModel):
    conversation_message_ids: list[str] = Field(default_factory=list)
    trusted_topic: str | None = None
    textbook_ref: dict[str, str] | None = None
    weakpoint_refs: list[str] = Field(default_factory=list)
    preference_refs: list[str] = Field(default_factory=list)
    unresolved_goal: dict[str, Any] | None = None
    token_budget: int = Field(default=2000, ge=0, le=50_000)
