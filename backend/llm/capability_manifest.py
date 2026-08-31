"""Hash-bound LLM capability evidence and fail-closed optional capability gates."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from deployment import deployed_commit, deployment_environment, deployment_image_digest, runtime_config_version

from .providers import bailian_base_url


SCHEMA_VERSION = 1
OPTIONAL_CAPABILITIES = frozenset({"tool_calling", "native_structured_output"})
_TRUE_VALUES = {"1", "true", "yes", "on"}
_MANIFEST_CACHE: dict[tuple[str, ...], tuple[float, dict[str, Any] | None, str]] = {}


def _canonical(payload: dict[str, Any], *, digest_field: str = "manifest_sha256") -> bytes:
    clean = {key: value for key, value in payload.items() if key != digest_field}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def capability_manifest_sha256(payload: dict[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(_canonical(payload)).hexdigest()}"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def endpoint_fingerprint() -> str:
    parsed = urlparse(bailian_base_url())
    host = (parsed.hostname or "").lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    normalized = f"{parsed.scheme.lower()}://{host}{parsed.path.rstrip('/')}"
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def current_provenance() -> dict[str, str]:
    provider = (os.getenv("LLM_PROVIDER") or "bailian").strip().lower()
    return {
        "provider": "bailian" if provider == "dashscope" else provider,
        "deployed_commit": deployed_commit(),
        "image_digest": deployment_image_digest(),
        "runtime_config_version": runtime_config_version(),
        "environment": deployment_environment(),
        "endpoint_fingerprint": endpoint_fingerprint(),
    }


def build_capability_manifest(
    probe_report: dict[str, Any],
    registry: Any,
    *,
    expires_hours: int = 168,
    provenance: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a content-minimized manifest from a live probe report."""
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_profiles = {
        str(item.get("profile")): item
        for item in (probe_report.get("profiles") or [])
        if isinstance(item, dict) and item.get("profile")
    }
    profiles: dict[str, Any] = {}
    for key, configured in registry.profiles.items():
        item = source_profiles.get(key, {})
        checks = item.get("checks") if isinstance(item.get("checks"), dict) else {}
        required_names = list(item.get("required_checks") or [])
        required_checks = {
            name: _safe_check(checks.get(name))
            for name in required_names
        }
        optional_checks = {
            name: _safe_check(checks.get(name))
            for name in sorted(OPTIONAL_CAPABILITIES)
            if name in checks
        }
        validated = set(configured.capabilities if item.get("result") == "pass" else ())
        validated.update(name for name, result in optional_checks.items() if result.get("status") == "pass")
        profiles[key] = {
            "profile_name": configured.name,
            "model": configured.model,
            "max_tokens": configured.max_tokens,
            "fallback_profiles": list(configured.fallback_profiles),
            "required_checks": required_checks,
            "optional_checks": optional_checks,
            "required_status": "pass" if item.get("result") == "pass" and required_names else "fail",
            "validated_capabilities": sorted(validated),
            "trace_ids": [str(item["trace_id"])[:200]] if item.get("trace_id") else [],
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "provider": str(probe_report.get("provider") or registry.provider),
        "transport": str(probe_report.get("transport") or "langchain_openai"),
        **(provenance or current_provenance()),
        "dependencies": {
            "langchain_core": _package_version("langchain-core"),
            "langchain_openai": _package_version("langchain-openai"),
            "langgraph": _package_version("langgraph"),
            "openai": _package_version("openai"),
        },
        "profiles": profiles,
        "generated_at": timestamp.isoformat(),
        "expires_at": (timestamp + timedelta(hours=max(1, min(int(expires_hours), 24 * 31)))).isoformat(),
    }
    manifest["manifest_sha256"] = capability_manifest_sha256(manifest)
    return manifest


def _safe_check(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "not_run"}
    result: dict[str, Any] = {"status": "pass" if value.get("ok") is True else "fail"}
    if isinstance(value.get("latency_ms"), (int, float)):
        result["latency_ms"] = max(0, int(value["latency_ms"]))
    if value.get("error_type"):
        result["error_type"] = str(value["error_type"])[:120]
    for name in ("provider_request_id", "input_tokens", "output_tokens", "total_tokens"):
        if value.get(name) is not None:
            result[name] = value[name]
    return result


def validate_capability_manifest(
    payload: dict[str, Any],
    registry: Any | None = None,
    *,
    expected_provenance: dict[str, str] | None = None,
    require_expected_provenance: bool = False,
    now: datetime | None = None,
) -> list[str]:
    reasons: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        reasons.append("manifest_schema_unsupported")
    if payload.get("manifest_sha256") != capability_manifest_sha256(payload):
        reasons.append("manifest_hash_mismatch")
    current = expected_provenance if expected_provenance is not None else current_provenance()
    for field in ("provider", "deployed_commit", "image_digest", "runtime_config_version", "environment", "endpoint_fingerprint"):
        expected = str(current.get(field) or "")
        actual = str(payload.get(field) or "")
        if require_expected_provenance and not expected:
            reasons.append(f"current_{field}_missing")
        if not actual:
            reasons.append(f"manifest_{field}_missing")
        elif expected and actual != expected:
            reasons.append(f"manifest_{field}_mismatch")
    generated = _parse_time(payload.get("generated_at"))
    expires = _parse_time(payload.get("expires_at"))
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if generated is None:
        reasons.append("manifest_generated_at_invalid")
    elif generated > timestamp + timedelta(minutes=5):
        reasons.append("manifest_generated_in_future")
    if expires is None:
        reasons.append("manifest_expires_at_invalid")
    elif expires <= timestamp:
        reasons.append("manifest_stale")
    elif generated is not None and expires - generated > timedelta(days=31):
        reasons.append("manifest_expiry_too_long")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict):
        reasons.append("manifest_profiles_invalid")
        raw_profiles = {}
    if registry is not None:
        for key, profile in registry.profiles.items():
            item = raw_profiles.get(key)
            if not isinstance(item, dict):
                reasons.append(f"manifest_profile_{key}_missing")
                continue
            if item.get("profile_name") != profile.name:
                reasons.append(f"manifest_profile_{key}_name_mismatch")
            if item.get("model") != profile.model:
                reasons.append(f"manifest_profile_{key}_model_mismatch")
            if item.get("max_tokens") != profile.max_tokens:
                reasons.append(f"manifest_profile_{key}_max_tokens_mismatch")
            if item.get("fallback_profiles") != list(profile.fallback_profiles):
                reasons.append(f"manifest_profile_{key}_fallback_mismatch")
            if item.get("required_status") != "pass":
                reasons.append(f"manifest_profile_{key}_required_not_passed")
    expected_digest = os.getenv("EDU_AGENT_LLM_CAPABILITY_MANIFEST_SHA256", "").strip()
    if expected_digest and payload.get("manifest_sha256") != expected_digest:
        reasons.append("manifest_expected_hash_mismatch")
    return list(dict.fromkeys(reasons))


def _load_capability_manifest_file(path: str | Path) -> dict[str, Any] | None:
    configured = str(path).strip()
    if not configured:
        return None
    try:
        payload = json.loads(Path(configured).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_capability_manifest_cache() -> None:
    _MANIFEST_CACHE.clear()


def resolve_capability_manifest(path: str | Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve file override first, otherwise query the exact DB provenance."""
    configured = str(path or os.getenv("EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH", "")).strip()
    provenance = current_provenance()
    if configured:
        payload = _load_capability_manifest_file(configured)
        return payload, {
            "source": "file_override",
            "store_status": "bypassed",
            "queried_provenance": provenance,
            "warnings": ["manifest_file_override_in_production"] if deployment_environment() == "production" else [],
        }
    key = tuple(provenance.get(field, "") for field in (
        "provider", "environment", "deployed_commit", "image_digest", "runtime_config_version", "endpoint_fingerprint"
    ))
    ttl = max(0, min(int(os.getenv("EDU_AGENT_LLM_MANIFEST_CACHE_TTL_SECONDS", "60")), 3600))
    cached = _MANIFEST_CACHE.get(key)
    if cached and time.monotonic() - cached[0] <= ttl:
        return cached[1], {
            "source": "database", "store_status": cached[2], "queried_provenance": provenance,
            "cache_status": "hit", "warnings": [],
        }
    try:
        from .capability_store import load_capability_manifest_exact
        payload = load_capability_manifest_exact(provenance)
        store_status = "pass" if payload is not None else "missing"
    except Exception as exc:
        from .capability_store import CapabilityManifestStoreUnavailable
        if not isinstance(exc, CapabilityManifestStoreUnavailable):
            raise
        payload, store_status = None, "unavailable"
    _MANIFEST_CACHE[key] = (time.monotonic(), payload, store_status)
    return payload, {
        "source": "database", "store_status": store_status, "queried_provenance": provenance,
        "cache_status": "miss", "warnings": [],
    }


def load_capability_manifest(path: str | Path | None = None) -> dict[str, Any] | None:
    return resolve_capability_manifest(path)[0]


def requested_optional_capabilities() -> dict[str, set[str]]:
    """Parse `profile:capability` entries; invalid/unknown entries enable nothing."""
    result: dict[str, set[str]] = {}
    for entry in os.getenv("EDU_AGENT_LLM_ENABLED_CAPABILITIES", "").split(","):
        profile, separator, capability = entry.strip().partition(":")
        if separator and profile and capability in OPTIONAL_CAPABILITIES:
            result.setdefault(profile, set()).add(capability)
    return result


def capability_status(registry: Any, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    if manifest is not None:
        payload = manifest
        resolution = {
            "source": "argument", "store_status": "not_queried", "queried_provenance": current_provenance(),
            "warnings": [],
        }
    else:
        payload, resolution = resolve_capability_manifest()
    reasons = ["manifest_missing"] if payload is None else validate_capability_manifest(
        payload, registry, require_expected_provenance=True
    )
    valid = payload is not None and not reasons
    requested = requested_optional_capabilities()
    raw_profiles = payload.get("profiles", {}) if isinstance(payload, dict) else {}
    profiles: dict[str, Any] = {}
    for key, configured in registry.profiles.items():
        evidence = raw_profiles.get(key, {}) if isinstance(raw_profiles, dict) else {}
        validated = set(evidence.get("validated_capabilities") or []) if valid and isinstance(evidence, dict) else set()
        enabled_optional = requested.get(key, set()).intersection(validated)
        profiles[key] = {
            "profile_name": configured.name,
            "model": configured.model,
            "configured_capabilities": sorted(configured.capabilities),
            "validated_capabilities": sorted(validated),
            "enabled_capabilities": sorted(set(configured.capabilities).union(enabled_optional)),
            "requested_optional_capabilities": sorted(requested.get(key, set())),
            "required_status": evidence.get("required_status", "unknown") if isinstance(evidence, dict) else "unknown",
            "required_checks": evidence.get("required_checks", {}) if valid and isinstance(evidence, dict) else {},
            "optional_checks": evidence.get("optional_checks", {}) if valid and isinstance(evidence, dict) else {},
        }
    return {
        "status": "pass" if valid else "missing" if payload is None else "invalid",
        "manifest_sha256": payload.get("manifest_sha256") if isinstance(payload, dict) else None,
        "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
        "expires_at": payload.get("expires_at") if isinstance(payload, dict) else None,
        "deployment_provenance_match": valid,
        "manifest_source": resolution["source"],
        "manifest_store_status": resolution["store_status"],
        "queried_provenance": resolution["queried_provenance"],
        "cache_status": resolution.get("cache_status", "not_applicable"),
        "warnings": resolution.get("warnings", []),
        "required_profile_count": len(registry.profiles),
        "passed_profile_count": sum(1 for item in profiles.values() if item["required_status"] == "pass") if valid else 0,
        "reasons": reasons,
        "profiles": profiles,
    }


def optional_capability_enabled(registry: Any, profile_key: str, capability: str) -> bool:
    if capability not in OPTIONAL_CAPABILITIES:
        return capability in registry.get_profile(profile_key).capabilities
    status = capability_status(registry)
    return capability in set((status.get("profiles", {}).get(profile_key, {}) or {}).get("enabled_capabilities") or [])
