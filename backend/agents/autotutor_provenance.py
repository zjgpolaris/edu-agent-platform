"""Safe AutoTutor decision provenance projections."""
from __future__ import annotations

from typing import Any


_SOURCES = {
    "policy",
    "tool",
    "langchain_primary",
    "langchain_fallback_profile",
    "deterministic_fallback",
    "evidence_store",
}


def _text(value: Any, *, limit: int = 120) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def public_decision_provenance(value: Any) -> dict[str, Any] | None:
    """Allowlist provenance without prompts, usage, request IDs or endpoints."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        return None
    source = _text(value.get("decision_source"), limit=60)
    if source not in _SOURCES:
        return None
    payload: dict[str, Any] = {
        "decision_source": source,
        "fallback_used": bool(value.get("fallback_used")),
        "structured_repair_used": bool(value.get("structured_repair_used")),
        "model": None,
    }
    if source in {"langchain_primary", "langchain_fallback_profile"}:
        nested_model = value.get("model") if isinstance(value.get("model"), dict) else {}
        payload["model"] = {
            "provider": _text(value.get("provider") or nested_model.get("provider"), limit=60),
            "profile": _text(value.get("executed_profile") or value.get("profile") or nested_model.get("profile"), limit=80),
            "name": _text(value.get("executed_model") or nested_model.get("name"), limit=120),
            "fallback_used": source == "langchain_fallback_profile",
        }
    return payload


def public_session_decision_summary(state: dict[str, Any]) -> dict[str, Any]:
    reflections = state.get("reflect_log") if isinstance(state.get("reflect_log"), list) else []
    projected = [
        item
        for reflection in reflections
        if isinstance(reflection, dict)
        for item in [public_decision_provenance(reflection.get("decision_provenance"))]
        if item is not None
    ]
    succeeded = [item for item in projected if item["decision_source"] in {"langchain_primary", "langchain_fallback_profile"}]
    deterministic = [item for item in projected if item["decision_source"] == "deterministic_fallback"]
    latest_model = next((item.get("model") for item in reversed(succeeded) if item.get("model")), None)
    return {
        "llm_decision_attempted": bool(projected),
        "llm_decision_succeeded": bool(succeeded),
        "deterministic_fallback_used": bool(deterministic),
        "provider": (latest_model or {}).get("provider"),
        "profile": (latest_model or {}).get("profile"),
        "model": (latest_model or {}).get("name"),
    }
