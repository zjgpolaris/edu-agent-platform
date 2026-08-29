from __future__ import annotations

import os


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
        enabled = os.getenv("EDU_AGENT_RUNTIME_V2_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return []
    errors: list[str] = []
    config_version = runtime_config_version() if config_version is None else config_version.strip()[:120]
    if not config_version:
        errors.append("runtime_config_version_missing")
    elif config_version == "v1.33-control":
        errors.append("runtime_config_version_legacy_default")
    return errors


def deployment_environment() -> str:
    value = os.getenv("EDU_AGENT_ENVIRONMENT", "").strip()
    if not value and os.getenv("RENDER_SERVICE_NAME"):
        value = "production"
    if not value:
        value = os.getenv("LANGFUSE_ENVIRONMENT", "local").strip() or "local"
    return value[:80]
