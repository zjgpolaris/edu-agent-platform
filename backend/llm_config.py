"""Compatibility facade for the unified LangChain-backed LLM registry."""
from __future__ import annotations

import logging
import os

from llm import ManagedChatModel, get_default_registry
from llm.providers import bailian_base_url_host


logger = logging.getLogger(__name__)


def _mask_secret(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 10:
        return f"set(len={len(value)})"
    return f"{value[:6]}...{value[-4:]}(len={len(value)})"


_registry = get_default_registry()
LLM_PROVIDER = _registry.provider

MODEL_FAST = _registry.get_profile("fast").model
MODEL_QUALITY = _registry.get_profile("quality").model
MODEL_FALLBACK = _registry.get_profile("fallback").model
MODEL_REASONING = _registry.get_profile("reasoning").model
MODEL_MULTIMODAL = _registry.get_profile("multimodal").model
MODEL_MULTIMODAL_QUALITY = _registry.get_profile("multimodal_quality").model

llm_fast = _registry.get_model("fast")
llm_quality = _registry.get_model("quality")
llm_reasoning = _registry.get_model("reasoning")
llm_multimodal = _registry.get_model("multimodal")
llm_multimodal_quality = _registry.get_model("multimodal_quality")
llm_material = _registry.get_model("material")
llm_card_pool = _registry.get_model("card_pool")


def get_llm(name: str) -> ManagedChatModel:
    """Return a managed model by profile key."""
    return _registry.get_model(name)


def llm_configuration_status() -> dict:
    return _registry.configuration_status()


logger.info(
    "llm_config_loaded provider=%s transport=langchain_openai fast=%s quality=%s fallback=%s reasoning=%s multimodal=%s multimodal_quality=%s bailian_base_url=%s bailian_key=%s",
    LLM_PROVIDER,
    MODEL_FAST,
    MODEL_QUALITY,
    MODEL_FALLBACK,
    MODEL_REASONING,
    MODEL_MULTIMODAL,
    MODEL_MULTIMODAL_QUALITY,
    bailian_base_url_host(),
    _mask_secret(os.getenv("BAILIAN_API_KEY")),
)


__all__ = [
    "LLM_PROVIDER",
    "MODEL_FAST",
    "MODEL_QUALITY",
    "MODEL_FALLBACK",
    "MODEL_REASONING",
    "MODEL_MULTIMODAL",
    "MODEL_MULTIMODAL_QUALITY",
    "ManagedChatModel",
    "get_llm",
    "llm_card_pool",
    "llm_configuration_status",
    "llm_fast",
    "llm_material",
    "llm_multimodal",
    "llm_multimodal_quality",
    "llm_quality",
    "llm_reasoning",
]
