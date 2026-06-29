from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolResult(BaseModel):
    tool_name: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


ToolRiskLevel = Literal["low", "medium", "high"]
ToolSideEffect = Literal["none", "read", "write", "session_create", "external_call"]
ToolRole = Literal["anonymous", "student", "teacher", "admin"]


class ToolExecutionContext(BaseModel):
    actor_id: str | None = None
    role: ToolRole = "anonymous"
    student_id: str | None = None
    confirmed: bool = False
    confirmation_token: str | None = None
    request_source: str = "unknown"


class ToolSpec(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel], ToolResult]
    output_model: type[BaseModel] | None = None
    risk_level: ToolRiskLevel = "low"
    side_effect: ToolSideEffect = "none"
    required_role: ToolRole = "anonymous"
    requires_confirmation: bool = False
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    audit_enabled: bool = True

    model_config = {"arbitrary_types_allowed": True}
