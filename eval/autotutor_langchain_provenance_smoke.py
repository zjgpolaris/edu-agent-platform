"""Structured invocation provenance must distinguish real and deterministic paths."""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from langchain_core.messages import AIMessage  # noqa: E402
from llm.contracts import LLMProfile  # noqa: E402
from llm.managed_model import ManagedChatModel  # noqa: E402
from structured_output import invoke_structured, invoke_structured_with_provenance  # noqa: E402


class Decision(BaseModel):
    action: str


class FakeClient:
    def __init__(self, responses: list[object]):
        self.responses = list(responses)

    def invoke(self, _messages, **_kwargs):
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def profile(name: str, model: str, *, fallbacks: tuple[str, ...] = ()) -> LLMProfile:
    return LLMProfile(
        name=name,
        provider="bailian_openai",
        model=model,
        max_tokens=128,
        max_attempts=1,
        fallback_profiles=fallbacks,
    )


def managed(primary_responses: list[object], fallback_responses: list[object] | None = None) -> ManagedChatModel:
    profiles = {
        "quality": profile("quality", "model-quality", fallbacks=("fallback",)),
        "fallback": profile("fallback", "model-fallback"),
    }
    clients = {
        "quality": FakeClient(primary_responses),
        "fallback": FakeClient(fallback_responses or []),
    }
    return ManagedChatModel(
        profiles["quality"],
        profiles,
        client_factory=lambda item: clients[item.name],
        sleep=lambda _delay: None,
    )


class ConcurrentLLM:
    name = "quality"
    model = "configured-model"

    def invoke(self, messages):
        request_id = str(messages[0]["content"])
        return AIMessage(
            content='{"action":"ok"}',
            response_metadata={
                "edu_agent_provenance": {
                    "provider": "bailian",
                    "transport": "bailian_openai",
                    "configured_profile": "quality",
                    "executed_profile": f"profile-{request_id}",
                    "configured_model": "configured-model",
                    "executed_model": f"model-{request_id}",
                    "model_attempt": 2,
                }
            },
        )


def main() -> None:
    original_disabled = os.environ.pop("EDU_AGENT_LLM_DISABLED", None)
    try:
        primary = invoke_structured_with_provenance(
            managed([AIMessage(content='{"action":"reteach"}')]),
            [{"role": "user", "content": "reflect"}],
            model=Decision,
            fallback=Decision(action="fallback"),
        )
        assert primary.value.action == "reteach", primary
        assert primary.provenance.decision_source == "langchain_primary", primary.provenance
        assert primary.provenance.executed_profile == "quality", primary.provenance
        assert primary.provenance.fallback_used is False, primary.provenance

        model_fallback = invoke_structured_with_provenance(
            managed([TimeoutError("private upstream body")], [AIMessage(content='{"action":"lower_difficulty"}')]),
            [{"role": "user", "content": "reflect"}],
            model=Decision,
            fallback=Decision(action="fallback"),
        )
        assert model_fallback.value.action == "lower_difficulty", model_fallback
        assert model_fallback.provenance.decision_source == "langchain_fallback_profile", model_fallback.provenance
        assert model_fallback.provenance.executed_profile == "fallback", model_fallback.provenance
        assert model_fallback.provenance.executed_model == "model-fallback", model_fallback.provenance

        repaired = invoke_structured_with_provenance(
            managed([
                AIMessage(content='{"action":"reteach",}'),
                AIMessage(content='{"action":"reteach"}'),
            ]),
            [{"role": "user", "content": "reflect"}],
            model=Decision,
            fallback=Decision(action="fallback"),
        )
        assert repaired.value.action == "reteach", repaired
        assert repaired.provenance.structured_repair_used is True, repaired.provenance
        assert repaired.provenance.decision_source == "langchain_primary", repaired.provenance

        deterministic = invoke_structured_with_provenance(
            managed([TimeoutError("private primary")], [TimeoutError("private fallback")]),
            [{"role": "user", "content": "reflect"}],
            model=Decision,
            fallback=Decision(action="fallback"),
        )
        assert deterministic.value.action == "fallback", deterministic
        assert deterministic.provenance.decision_source == "deterministic_fallback", deterministic.provenance
        assert deterministic.provenance.provider is None and deterministic.provenance.executed_model is None
        assert deterministic.provenance.fallback_used is True

        legacy_value = invoke_structured(
            managed([AIMessage(content='{"action":"legacy-compatible"}')]),
            [{"role": "user", "content": "reflect"}],
            model=Decision,
            fallback=Decision(action="fallback"),
        )
        assert isinstance(legacy_value, Decision) and legacy_value.action == "legacy-compatible"

        llm = ConcurrentLLM()

        def invoke_one(index: int) -> tuple[str | None, str | None]:
            result = invoke_structured_with_provenance(
                llm,
                [{"role": "user", "content": str(index)}],
                model=Decision,
            )
            return result.provenance.executed_profile, result.provenance.executed_model

        with ThreadPoolExecutor(max_workers=8) as pool:
            concurrent = list(pool.map(invoke_one, range(24)))
        assert concurrent == [(f"profile-{index}", f"model-{index}") for index in range(24)], concurrent
    finally:
        if original_disabled is not None:
            os.environ["EDU_AGENT_LLM_DISABLED"] = original_disabled

    print("autotutor_langchain_provenance_smoke=PASS")


if __name__ == "__main__":
    main()
