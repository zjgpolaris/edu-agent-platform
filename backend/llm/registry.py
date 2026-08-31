"""Single source of truth for EduAgent LLM profiles."""
from __future__ import annotations

import os
from collections.abc import Mapping
from threading import Lock

from .contracts import LLMConfigurationError, LLMProfile
from .capability_manifest import capability_status, optional_capability_enabled
from .managed_model import ManagedChatModel
from .providers import provider_configuration_errors


def _env_text(name: str, default: str) -> str:
    return (os.getenv(name) or "").strip() or default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be a number") from exc


def normalize_provider(value: str | None) -> str:
    provider = (value or "bailian").strip().lower()
    if provider == "dashscope":
        provider = "bailian"
    if provider != "bailian":
        raise LLMConfigurationError(f"unsupported LLM_PROVIDER: {provider}")
    return provider


def build_default_profiles() -> dict[str, LLMProfile]:
    timeout = _env_float("LLM_REQUEST_TIMEOUT_SECONDS", 60.0)
    attempts = _env_int("LLM_MAX_ATTEMPTS", _env_int("LLM_MAX_RETRIES", 2))
    provider = "bailian_openai"
    models = {
        "fast": _env_text("LLM_MODEL_FAST", "qwen3.6-35b-a3b"),
        "quality": _env_text("LLM_MODEL_QUALITY", "qwen3.7-plus"),
        "fallback": _env_text("LLM_MODEL_FALLBACK", "qwen3.7-max-2026-06-08"),
        "reasoning": _env_text("LLM_MODEL_REASONING", "qwen3.7-max-2026-06-08"),
        "multimodal": _env_text("LLM_MODEL_MULTIMODAL", "qwen3.5-omni-flash"),
        "multimodal_quality": _env_text("LLM_MODEL_MULTIMODAL_QUALITY", "qwen3.5-omni-plus"),
    }
    common = {"provider": provider, "timeout_seconds": timeout, "max_attempts": attempts}
    return {
        "fast": LLMProfile(
            name="llm_fast", model=models["fast"], max_tokens=1024,
            fallback_profiles=("fallback",), capabilities=frozenset({"chat", "stream", "json_prompt"}), **common,
        ),
        "quality": LLMProfile(
            name="llm_quality", model=models["quality"], max_tokens=2048,
            fallback_profiles=("fast", "fallback"), capabilities=frozenset({"chat", "stream", "json_prompt"}), **common,
        ),
        "fallback": LLMProfile(
            name="llm_fallback", model=models["fallback"], max_tokens=2048,
            capabilities=frozenset({"chat", "stream", "json_prompt"}), **common,
        ),
        "reasoning": LLMProfile(
            name="llm_reasoning", model=models["reasoning"], max_tokens=2048,
            fallback_profiles=("quality", "fast"), capabilities=frozenset({"chat", "stream", "json_prompt"}), **common,
        ),
        "multimodal": LLMProfile(
            name="llm_multimodal", model=models["multimodal"], max_tokens=4096,
            capabilities=frozenset({"chat", "vision", "json_prompt"}), **common,
        ),
        "multimodal_quality": LLMProfile(
            name="llm_multimodal_quality", model=models["multimodal_quality"], max_tokens=4096,
            capabilities=frozenset({"chat", "vision", "json_prompt"}), **common,
        ),
        "material": LLMProfile(
            name="llm_material", model=models["fast"], max_tokens=4096,
            fallback_profiles=("fallback",), capabilities=frozenset({"chat", "json_prompt"}), **common,
        ),
        "card_pool": LLMProfile(
            name="llm_card_pool", model=models["fast"], max_tokens=3072,
            fallback_profiles=("fallback",), capabilities=frozenset({"chat", "json_prompt"}), **common,
        ),
    }


class LLMRegistry:
    def __init__(self, profiles: Mapping[str, LLMProfile] | None = None, *, client_factory=None) -> None:
        self.provider = normalize_provider(os.getenv("LLM_PROVIDER"))
        self.profiles = dict(profiles or build_default_profiles())
        self._client_factory = client_factory
        self._models: dict[str, ManagedChatModel] = {}
        self._validate_profiles()

    def _validate_profiles(self) -> None:
        for key, profile in self.profiles.items():
            for fallback in profile.fallback_profiles:
                if fallback not in self.profiles:
                    raise LLMConfigurationError(f"LLM profile {key} references unknown fallback {fallback}")

        def visit(key: str, path: tuple[str, ...]) -> None:
            if key in path:
                raise LLMConfigurationError(f"LLM fallback cycle detected: {' -> '.join((*path, key))}")
            for fallback in self.profiles[key].fallback_profiles:
                visit(fallback, (*path, key))

        for key in self.profiles:
            visit(key, ())

    def get_profile(self, name: str) -> LLMProfile:
        try:
            return self.profiles[name]
        except KeyError as exc:
            raise LLMConfigurationError(f"unknown LLM profile: {name}") from exc

    def get_model(self, name: str) -> ManagedChatModel:
        if name not in self._models:
            kwargs = {"client_factory": self._client_factory} if self._client_factory is not None else {}
            kwargs["capability_enabled"] = lambda capability, profile_key=name: optional_capability_enabled(
                self, profile_key, capability
            )
            self._models[name] = ManagedChatModel(self.get_profile(name), self.profiles, **kwargs)
        return self._models[name]

    def capability_status(self) -> dict:
        return capability_status(self)

    def configuration_status(self) -> dict:
        errors = provider_configuration_errors("bailian_openai")
        capabilities = self.capability_status()
        return {
            "ok": not errors,
            "provider": self.provider,
            "transport": "langchain_openai",
            "credentials_configured": not any("API_KEY" in error for error in errors),
            "errors": errors,
            "profiles": {
                key: {
                    "name": profile.name,
                    "model": profile.model,
                    "capabilities": sorted(profile.capabilities),
                    "fallback_profiles": list(profile.fallback_profiles),
                }
                for key, profile in self.profiles.items()
            },
            "capability_manifest": {
                key: capabilities.get(key)
                for key in ("status", "manifest_sha256", "generated_at", "expires_at", "deployment_provenance_match", "reasons")
            },
        }


_default_registry: LLMRegistry | None = None
_registry_lock = Lock()


def get_default_registry() -> LLMRegistry:
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = LLMRegistry()
    return _default_registry
