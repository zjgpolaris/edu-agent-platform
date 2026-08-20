from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from agent_runtime.models import AgentBudget


BudgetKind = Literal["steps", "tool_calls", "llm_calls", "replans"]


@dataclass(slots=True)
class BudgetExceededError(RuntimeError):
    kind: str
    limit: int | float

    def __str__(self) -> str:
        return f"agent budget exceeded: {self.kind} > {self.limit}"


@dataclass
class BudgetTracker:
    budget: AgentBudget
    started_at: float = field(default_factory=perf_counter)
    steps: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    replans: int = 0
    estimated_cost_usd: float = 0.0

    def consume(self, kind: BudgetKind, amount: int = 1) -> None:
        current = int(getattr(self, kind)) + amount
        limit = int(getattr(self.budget, f"max_{kind}"))
        if current > limit:
            raise BudgetExceededError(kind, limit)
        setattr(self, kind, current)
        self.check_wall_time()

    def add_cost(self, amount_usd: float) -> None:
        self.estimated_cost_usd += max(float(amount_usd), 0.0)
        limit = self.budget.estimated_cost_limit_usd
        if limit is not None and self.estimated_cost_usd > limit:
            raise BudgetExceededError("estimated_cost_usd", limit)

    def check_wall_time(self) -> None:
        elapsed_ms = (perf_counter() - self.started_at) * 1000
        if elapsed_ms > self.budget.max_wall_time_ms:
            raise BudgetExceededError("wall_time_ms", self.budget.max_wall_time_ms)

    def snapshot(self) -> dict[str, int | float]:
        return {
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "llm_calls": self.llm_calls,
            "replans": self.replans,
            "wall_time_ms": round((perf_counter() - self.started_at) * 1000, 2),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }
