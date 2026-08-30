"""Stable contracts for provider-neutral LLM profiles and failures."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ProviderName = Literal["bailian_openai"]


@dataclass(frozen=True)
class LLMProfile:
    name: str
    provider: ProviderName
    model: str
    max_tokens: int
    timeout_seconds: float = 60.0
    max_attempts: int = 2
    fallback_profiles: tuple[str, ...] = ()
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"chat"}))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("LLM profile name must not be empty")
        if not self.model.strip():
            raise ValueError(f"LLM profile {self.name} model must not be empty")
        if self.max_tokens <= 0:
            raise ValueError(f"LLM profile {self.name} max_tokens must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError(f"LLM profile {self.name} timeout_seconds must be positive")
        if self.max_attempts <= 0:
            raise ValueError(f"LLM profile {self.name} max_attempts must be positive")


class LLMError(RuntimeError):
    """Base error exposed by the managed model boundary."""


class LLMConfigurationError(LLMError):
    pass


class LLMAuthenticationError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMEmptyResponseError(LLMError):
    pass


class LLMCapabilityError(LLMError):
    pass


class LLMStreamInterruptedError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    pass
