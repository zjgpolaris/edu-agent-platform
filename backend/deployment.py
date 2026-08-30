from __future__ import annotations

import os
import re


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def deployed_commit() -> str:
    for name in ("EDU_AGENT_DEPLOYED_COMMIT", "RENDER_GIT_COMMIT", "GITHUB_SHA"):
        value = os.getenv(name, "").strip()
        if value:
            return value[:120]
    return ""


def runtime_config_version() -> str:
    return os.getenv("EDU_AGENT_RUNTIME_V2_CONFIG_VERSION", "").strip()[:120]


def runtime_configuration_errors(*, enabled: bool | None = None, config_version: str | None = None) -> list[str]:
    if enabled is None:
        enabled = _enabled("EDU_AGENT_RUNTIME_V2_ENABLED")
    if not enabled:
        return []
    errors: list[str] = []
    config_version = runtime_config_version() if config_version is None else config_version.strip()[:120]
    if not config_version:
        errors.append("runtime_config_version_missing")
    elif config_version == "v1.33-control":
        errors.append("runtime_config_version_legacy_default")
    if not _enabled("EDU_AGENT_RUNTIME_V2_SHADOW_MODE", True) and not _enabled("EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED"):
        errors.append("runtime_active_not_approved")
    return errors


def auth_configuration_status() -> dict[str, object]:
    """Return a secret-free authentication deployment contract."""
    production = deployment_environment() == "production"
    auth_enabled = _enabled("EDU_AGENT_AUTH_REQUIRED")
    secret = os.getenv("JWT_SECRET", "")
    insecure_default = secret in {"change-me-in-production", "runtime-security-smoke-secret", "secret", "test-secret"}
    low_entropy_placeholder = bool(secret) and (
        len(set(secret)) < 6 or bool(re.fullmatch(r"(?i)(change|replace|example|password|secret|test)[-_a-z0-9]*", secret))
    )
    secret_strong = len(secret.encode("utf-8")) >= 32 and not insecure_default and not low_entropy_placeholder
    errors: list[str] = []
    if production and not auth_enabled:
        errors.append("production_auth_not_enabled")
    if production and not secret:
        errors.append("jwt_secret_missing")
    elif production and len(secret.encode("utf-8")) < 32:
        errors.append("jwt_secret_too_short")
    elif production and (insecure_default or low_entropy_placeholder):
        errors.append("jwt_secret_insecure_default")
    return {
        "ok": not errors,
        "required": production,
        "auth_required": auth_enabled or production,
        "jwt_secret_configured": bool(secret),
        "jwt_secret_strong": secret_strong,
        "errors": errors,
    }


def auth_configuration_errors() -> list[str]:
    return list(auth_configuration_status()["errors"])


def deployment_environment() -> str:
    value = os.getenv("EDU_AGENT_ENVIRONMENT", "").strip()
    if not value and os.getenv("RENDER_SERVICE_NAME"):
        value = "production"
    if not value:
        value = os.getenv("LANGFUSE_ENVIRONMENT", "local").strip() or "local"
    return value[:80]
