from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from tools.base import ToolResult
from tools.registry import TOOLS


class GenericCapabilityInput(BaseModel):
    payload: dict = Field(default_factory=dict)


class GenericCapabilityOutput(BaseModel):
    result: dict = Field(default_factory=dict)


class CapabilityBinding(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=40)
    kind: Literal["tool", "function", "subgraph", "generation"]
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    executor: str = Field(min_length=1, max_length=240)
    allowed_callers: list[str] = Field(min_length=1)
    tool_name: str | None = None
    durability_mode: Literal["trace_only", "observable", "resumable", "queued"]
    requires_evidence: bool = False
    default_timeout_seconds: int = Field(default=15, ge=1, le=300)

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_tool_reference(self) -> "CapabilityBinding":
        if self.kind == "tool" and not self.tool_name:
            raise ValueError("tool capability must reference ToolSpec.name")
        if self.kind != "tool" and self.tool_name:
            raise ValueError("only tool capabilities may reference ToolSpec.name")
        self.input_model.model_json_schema()
        self.output_model.model_json_schema()
        return self


class CapabilityRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, CapabilityBinding] = {}

    def register(self, binding: CapabilityBinding) -> None:
        if binding.name in self._bindings:
            raise ValueError(f"duplicate capability operation: {binding.name}")
        if binding.kind == "tool":
            spec = TOOLS.get(str(binding.tool_name))
            if spec is None:
                raise ValueError(f"capability references unknown tool: {binding.tool_name}")
            if binding.input_model is not spec.input_model:
                raise ValueError("tool capability input_model must come from ToolSpec")
            if binding.default_timeout_seconds != spec.timeout_seconds:
                raise ValueError("tool capability timeout must come from ToolSpec")
        self._bindings[binding.name] = binding

    def resolve(self, operation: str, caller: str) -> CapabilityBinding:
        binding = self._bindings.get(operation)
        if binding is None:
            raise LookupError(f"unknown capability operation: {operation}")
        if caller not in binding.allowed_callers:
            raise PermissionError(f"caller {caller} is not allowed to use {operation}")
        return binding

    def list_for(self, caller: str) -> list[CapabilityBinding]:
        return [binding for binding in self._bindings.values() if caller in binding.allowed_callers]

    def clear(self) -> None:
        self._bindings.clear()


def build_default_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    definitions = [
        ("history.search", "search_history_knowledge", ["learning_assistant", "auto_tutor", "history_character", "debate"], True),
        ("textbook.lesson", "get_textbook_lesson", ["learning_assistant", "quiz"], True),
        ("quiz.generate", "generate_quiz", ["learning_assistant", "auto_tutor"], True),
        ("profile.review_plan", "suggest_review_plan", ["learning_assistant"], False),
        ("character.recommend", "recommend_character", ["learning_assistant", "history_ui"], False),
        ("timeline.start", "start_timeline_game", ["learning_assistant"], False),
        ("memory.delete_demo", "delete_demo_memory", ["learning_assistant"], False),
    ]
    for name, tool_name, callers, evidence in definitions:
        spec = TOOLS[tool_name]
        registry.register(
            CapabilityBinding(
                name=name,
                version="1",
                kind="tool",
                input_model=spec.input_model,
                output_model=spec.output_model or ToolResult,
                executor=f"tools.registry:{tool_name}",
                allowed_callers=callers,
                tool_name=tool_name,
                durability_mode="observable",
                requires_evidence=evidence,
                default_timeout_seconds=spec.timeout_seconds,
            )
        )
    for name, kind, callers, evidence, durability in [
        ("history_character.answer", "subgraph", ["history_ui"], True, "observable"),
        ("essay.grade", "subgraph", ["chinese_api"], False, "resumable"),
        ("debate.run", "subgraph", ["debate_api"], True, "observable"),
        ("timeline.generate", "function", ["game_tool"], True, "trace_only"),
        ("card.generate", "function", ["game_tool"], True, "trace_only"),
        ("answer_from_sources", "generation", ["learning_assistant"], True, "observable"),
        ("answer_from_lesson", "generation", ["learning_assistant"], True, "observable"),
        ("quiz_from_sources", "generation", ["learning_assistant"], True, "observable"),
        ("quiz_from_lesson", "generation", ["learning_assistant"], True, "observable"),
        ("chat_answer", "generation", ["learning_assistant"], False, "observable"),
    ]:
        registry.register(CapabilityBinding(
            name=name,
            version="1",
            kind=kind,
            input_model=GenericCapabilityInput,
            output_model=GenericCapabilityOutput,
            executor=f"agent_runtime:{name}",
            allowed_callers=callers,
            durability_mode=durability,
            requires_evidence=evidence,
        ))
    return registry
