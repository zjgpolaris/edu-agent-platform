from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402

from llm.contracts import (  # noqa: E402
    LLMCapabilityError,
    LLMConfigurationError,
    LLMProfile,
    LLMStreamInterruptedError,
)
from llm.managed_model import ManagedChatModel  # noqa: E402
from llm.registry import LLMRegistry  # noqa: E402


class FakeClient:
    def __init__(self, *, invokes=None, streams=None):
        self.invokes = list(invokes or [])
        self.streams = list(streams or [])
        self.invoke_calls = 0
        self.stream_calls = 0

    def invoke(self, _messages, **_kwargs):
        self.invoke_calls += 1
        result = self.invokes.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def stream(self, _messages, **_kwargs):
        self.stream_calls += 1
        result = self.streams.pop(0)
        for item in result:
            if isinstance(item, BaseException):
                raise item
            yield item


def profile(name: str, model: str, *, fallbacks=(), attempts=1, capabilities=None) -> LLMProfile:
    return LLMProfile(
        name=name,
        provider="bailian_openai",
        model=model,
        max_tokens=128,
        max_attempts=attempts,
        fallback_profiles=tuple(fallbacks),
        capabilities=frozenset(capabilities or {"chat", "stream"}),
    )


def main() -> None:
    original_disabled = os.environ.pop("EDU_AGENT_LLM_DISABLED", None)
    try:
        profiles = {
            "primary": profile("primary", "model-a", fallbacks=("fallback",), attempts=2),
            "fallback": profile("fallback", "model-b"),
        }
        primary = FakeClient(invokes=[TimeoutError("secret provider body"), AIMessage(content="  ok  ")])
        fallback = FakeClient(invokes=[AIMessage(content="fallback")])
        clients = {"primary": primary, "fallback": fallback}
        model = ManagedChatModel(
            profiles["primary"], profiles, client_factory=lambda item: clients[item.name], sleep=lambda _delay: None
        )
        response = model.invoke([{"role": "user", "content": "hello"}])
        assert isinstance(response, AIMessage)
        assert response.content == "ok"
        assert primary.invoke_calls == 2 and fallback.invoke_calls == 0
        assert model.name == "primary"
        assert model.model == "model-a"
        assert model.fallback_models == ["model-b"]

        empty_primary = FakeClient(invokes=[AIMessage(content="")])
        good_fallback = FakeClient(invokes=[AIMessage(content=[{"type": "text", "text": "block-ok"}])])
        model = ManagedChatModel(
            profiles["primary"],
            profiles,
            client_factory=lambda item: empty_primary if item.name == "primary" else good_fallback,
            sleep=lambda _delay: None,
        )
        assert model.invoke("hello").content == "block-ok"
        assert empty_primary.invoke_calls == 1 and good_fallback.invoke_calls == 1

        before_emit_primary = FakeClient(streams=[[TimeoutError("timeout")]])
        before_emit_fallback = FakeClient(streams=[[AIMessageChunk(content="fallback-stream")]])
        model = ManagedChatModel(
            profiles["primary"],
            profiles,
            client_factory=lambda item: before_emit_primary if item.name == "primary" else before_emit_fallback,
            sleep=lambda _delay: None,
        )
        assert "".join(model.stream_text("hello")) == "fallback-stream"

        after_emit_primary = FakeClient(
            streams=[[AIMessageChunk(content="partial"), TimeoutError("timeout after output")]]
        )
        unused_fallback = FakeClient(streams=[[AIMessageChunk(content="must-not-appear")]])
        model = ManagedChatModel(
            profiles["primary"],
            profiles,
            client_factory=lambda item: after_emit_primary if item.name == "primary" else unused_fallback,
            sleep=lambda _delay: None,
        )
        iterator = model.stream_text("hello")
        assert next(iterator) == "partial"
        try:
            next(iterator)
            raise AssertionError("stream interruption must fail")
        except LLMStreamInterruptedError:
            pass
        assert unused_fallback.stream_calls == 0

        try:
            model.bind_tools([])
            raise AssertionError("unverified tool capability must be blocked")
        except LLMCapabilityError:
            pass

        image_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                ],
            }
        ]
        image_client = FakeClient(invokes=[AIMessage(content="vision-ok")])
        vision_profile = profile("vision", "vision-model", capabilities={"chat", "vision"})
        vision_model = ManagedChatModel(
            vision_profile,
            {"vision": vision_profile},
            client_factory=lambda _item: image_client,
            sleep=lambda _delay: None,
        )
        assert vision_model.invoke(image_messages).content == "vision-ok"
        text_only = profile("text", "text-model")
        text_model = ManagedChatModel(
            text_only,
            {"text": text_only},
            client_factory=lambda _item: image_client,
            sleep=lambda _delay: None,
        )
        try:
            text_model.invoke(image_messages)
            raise AssertionError("text profile must reject image input")
        except LLMCapabilityError:
            pass

        registry = LLMRegistry(
            profiles={
                "primary": profile("primary", "model-a", fallbacks=("fallback",)),
                "fallback": profile("fallback", "model-b"),
            },
            client_factory=lambda item: clients[item.name],
        )
        assert registry.get_model("primary") is registry.get_model("primary")
        assert registry.configuration_status()["transport"] == "langchain_openai"

        original_provider = os.environ.get("LLM_PROVIDER")
        os.environ["LLM_PROVIDER"] = "unknown-provider"
        try:
            try:
                LLMRegistry(profiles=profiles, client_factory=lambda item: clients[item.name])
                raise AssertionError("unknown provider must fail fast")
            except LLMConfigurationError:
                pass
        finally:
            if original_provider is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = original_provider
    finally:
        if original_disabled is not None:
            os.environ["EDU_AGENT_LLM_DISABLED"] = original_disabled

    print("llm_provider_contract_smoke=PASS")


if __name__ == "__main__":
    main()
