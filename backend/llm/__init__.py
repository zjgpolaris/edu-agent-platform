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
from .capability_manifest import capability_status, load_capability_manifest
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
    "capability_status",
    "get_default_registry",
    "load_capability_manifest",
]
