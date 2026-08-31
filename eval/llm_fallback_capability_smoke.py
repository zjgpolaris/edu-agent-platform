from __future__ import annotations

from langchain_core.messages import AIMessage

from llm_capability_test_support import configure_provenance

configure_provenance()

from llm.contracts import LLMProfile, LLMUnavailableError  # noqa: E402
from llm.managed_model import ManagedChatModel  # noqa: E402


class _Client:
    def __init__(self, *, succeeds: bool) -> None:
        self.succeeds = succeeds
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if not self.succeeds:
            raise TimeoutError("primary unavailable")
        return AIMessage(content="fallback-ok")


def main() -> None:
    primary = LLMProfile(
        name="primary",
        provider="bailian_openai",
        model="primary-model",
        max_tokens=100,
        max_attempts=1,
        fallback_profiles=("fallback",),
        capabilities=frozenset({"chat"}),
    )
    fallback = LLMProfile(
        name="fallback",
        provider="bailian_openai",
        model="fallback-model",
        max_tokens=100,
        max_attempts=1,
        capabilities=frozenset({"chat"}),
    )
    clients = {"primary": _Client(succeeds=False), "fallback": _Client(succeeds=True)}
    model = ManagedChatModel(
        primary,
        {"primary": primary, "fallback": fallback},
        client_factory=lambda profile: clients[profile.name],
        sleep=lambda _seconds: None,
    )
    assert model.invoke("hello").content == "fallback-ok"
    assert clients["fallback"].calls == 1

    clients["primary"].calls = clients["fallback"].calls = 0
    try:
        model.invoke("hello", allow_fallback=False)
        raise AssertionError("direct profile probe must not accept fallback-only success")
    except LLMUnavailableError:
        pass
    assert clients["primary"].calls == 1
    assert clients["fallback"].calls == 0
    print("llm_fallback_capability_smoke=PASS")


if __name__ == "__main__":
    main()
