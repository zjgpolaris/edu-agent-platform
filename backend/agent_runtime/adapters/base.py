from __future__ import annotations

from typing import AsyncIterator, Protocol

from agent_runtime.models import AgentContext, AgentRunState, ResumeSignal, RuntimeEvent


class RuntimeAdapter(Protocol):
    def stream(self, context: AgentContext, state: AgentRunState) -> AsyncIterator[RuntimeEvent]: ...

    def resume(self, context: AgentContext, state: AgentRunState, signal: ResumeSignal) -> AsyncIterator[RuntimeEvent]: ...

    async def cancel(self, context: AgentContext, state: AgentRunState) -> RuntimeEvent: ...
