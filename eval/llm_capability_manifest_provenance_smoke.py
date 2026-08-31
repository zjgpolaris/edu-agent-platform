from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from llm_capability_test_support import configure_provenance, valid_manifest

configure_provenance()

from llm.capability_manifest import capability_manifest_sha256, validate_capability_manifest  # noqa: E402
from llm.registry import LLMRegistry  # noqa: E402


def _reseal(payload: dict) -> dict:
    payload["manifest_sha256"] = capability_manifest_sha256(payload)
    return payload


def main() -> None:
    registry = LLMRegistry()
    now = datetime.now(timezone.utc)
    manifest = valid_manifest(registry, now=now)
    assert validate_capability_manifest(manifest, registry, now=now) == []

    for field in (
        "deployed_commit",
        "image_digest",
        "runtime_config_version",
        "environment",
        "endpoint_fingerprint",
    ):
        changed = _reseal({**manifest, field: f"wrong-{field}"})
        assert f"manifest_{field}_mismatch" in validate_capability_manifest(changed, registry, now=now)

    for field, wrong, reason in (
        ("model", "wrong-model", "manifest_profile_quality_model_mismatch"),
        ("max_tokens", 1, "manifest_profile_quality_max_tokens_mismatch"),
        ("fallback_profiles", [], "manifest_profile_quality_fallback_mismatch"),
    ):
        changed = deepcopy(manifest)
        changed["profiles"]["quality"][field] = wrong
        _reseal(changed)
        assert reason in validate_capability_manifest(changed, registry, now=now)

    future = deepcopy(manifest)
    future["generated_at"] = (now + timedelta(minutes=6)).isoformat()
    _reseal(future)
    assert "manifest_generated_in_future" in validate_capability_manifest(future, registry, now=now)

    stale = deepcopy(manifest)
    stale["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    _reseal(stale)
    assert "manifest_stale" in validate_capability_manifest(stale, registry, now=now)
    print("llm_capability_manifest_provenance_smoke=PASS")


if __name__ == "__main__":
    main()
