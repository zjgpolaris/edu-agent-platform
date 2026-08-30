"""Provider-neutral LLM access for EduAgent."""

from .contracts import (
    LLMAuthenticationError,
    LLMCapabilityError,
    LLMConfigurationError,
    LLMEmptyResponseError,
    LLMError,
    LLMProfile,
    LLMProviderError,
    LLMRateLimitError,
    LLMStreamInterruptedError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from .managed_model import ManagedChatModel
from .registry import LLMRegistry, get_default_registry

__all__ = [
    "LLMAuthenticationError",
    "LLMCapabilityError",
    "LLMConfigurationError",
    "LLMEmptyResponseError",
    "LLMError",
    "LLMProfile",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMRegistry",
    "LLMStreamInterruptedError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "ManagedChatModel",
    "get_default_registry",
]
