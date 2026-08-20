from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_runtime.models import AgentRunState, CompletionDecision, RunStatus, utc_now_iso


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "received": {"routed", "failed", "cancelled"},
    "routed": {"planned", "waiting_input", "failed", "cancelled"},
    "planned": {"running", "waiting_confirmation", "failed", "cancelled"},
    "running": {"running", "verifying", "waiting_input", "waiting_confirmation", "partial", "failed", "cancelled"},
    "waiting_input": {"running", "cancelled", "failed"},
    "waiting_confirmation": {"running", "cancelled", "failed"},
    "verifying": {"completed", "partial", "failed"},
    "completed": set(),
    "partial": set(),
    "failed": set(),
    "cancelled": set(),
}


@dataclass(slots=True)
class InvalidTransitionError(ValueError):
    current_status: str
    next_status: str

    def __str__(self) -> str:
        return f"invalid agent run transition: {self.current_status} -> {self.next_status}"


def validate_transition(current_status: str, next_status: str) -> None:
    if next_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise InvalidTransitionError(current_status, next_status)


def transition_state(
    state: AgentRunState,
    next_status: RunStatus,
    *,
    current_step_id: str | None = None,
    completion: CompletionDecision | None = None,
    context_patch: dict[str, Any] | None = None,
) -> AgentRunState:
    validate_transition(state.status, next_status)
    payload = state.model_dump()
    payload.update(
        status=next_status,
        revision=state.revision + 1,
        current_step_id=current_step_id,
        updated_at=utc_now_iso(),
    )
    if completion is not None:
        payload["completion"] = completion.model_dump()
    if context_patch:
        payload["context_refs"] = {**state.context_refs, **context_patch}
    return AgentRunState.model_validate(payload)
