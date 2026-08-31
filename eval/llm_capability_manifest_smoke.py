from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "capability-smoke-commit"
os.environ["EDU_AGENT_IMAGE_DIGEST"] = "sha256:" + "a" * 64
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "v1.45-capability-smoke"
os.environ["EDU_AGENT_ENVIRONMENT"] = "staging"

from llm.capability_manifest import (  # noqa: E402
    build_capability_manifest,
    capability_manifest_sha256,
    capability_status,
    current_provenance,
    validate_capability_manifest,
)
from llm.registry import LLMRegistry  # noqa: E402
from llm.contracts import LLMCapabilityError  # noqa: E402


class _Native:
    def bind_tools(self, tools, **kwargs):
        return ("bound-tools", tools, kwargs)

    def with_structured_output(self, schema, **kwargs):
        return ("bound-structured", schema, kwargs)


def _report(registry: LLMRegistry) -> dict:
    profiles = []
    for key, profile in registry.profiles.items():
        required = ["invoke", "json_prompt"]
        if "stream" in profile.capabilities:
            required.append("stream")
        if "vision" in profile.capabilities:
            required.append("vision_base64")
        if key in {"material", "card_pool"}:
            required.append("configured_max_tokens")
        checks = {name: {"ok": True, "latency_ms": 5} for name in required}
        checks.update({
            "tool_calling": {"ok": key == "quality", "latency_ms": 8, "error_type": None if key == "quality" else "Unsupported"},
            "native_structured_output": {"ok": False, "latency_ms": 8, "error_type": "Unsupported"},
        })
        profiles.append({
            "profile": key,
            "name": profile.name,
            "model": profile.model,
            "max_tokens": profile.max_tokens,
            "fallback_profiles": list(profile.fallback_profiles),
            "required_checks": required,
            "checks": checks,
            "result": "pass",
            "trace_id": f"trace-{key}",
        })
    return {"provider": "bailian", "transport": "langchain_openai", "profiles": profiles, "result": "pass"}


def main() -> None:
    registry = LLMRegistry(client_factory=lambda _profile: _Native())
    now = datetime.now(timezone.utc)
    manifest = build_capability_manifest(
        _report(registry), registry, provenance=current_provenance(), now=now
    )
    assert validate_capability_manifest(manifest, registry, now=now) == []
    assert set(manifest["profiles"]) == set(registry.profiles)
    assert manifest["profiles"]["quality"]["optional_checks"]["tool_calling"]["status"] == "pass"
    assert manifest["profiles"]["fast"]["optional_checks"]["tool_calling"]["status"] == "fail"
    assert "error_type" in manifest["profiles"]["fast"]["optional_checks"]["tool_calling"]
    encoded = json.dumps(manifest).lower()
    for forbidden in ("authorization", "api_key", "base64,", "student_content"):
        assert forbidden not in encoded

    tampered = deepcopy(manifest)
    tampered["profiles"]["quality"]["model"] = "tampered"
    assert "manifest_hash_mismatch" in validate_capability_manifest(tampered, registry, now=now)

    stale = deepcopy(manifest)
    stale["generated_at"] = (now - timedelta(days=9)).isoformat()
    stale["expires_at"] = (now - timedelta(days=2)).isoformat()
    stale["manifest_sha256"] = capability_manifest_sha256(stale)
    assert "manifest_stale" in validate_capability_manifest(stale, registry, now=now)

    mismatch = deepcopy(manifest)
    mismatch["image_digest"] = "sha256:" + "b" * 64
    mismatch["manifest_sha256"] = capability_manifest_sha256(mismatch)
    assert "manifest_image_digest_mismatch" in validate_capability_manifest(mismatch, registry, now=now)

    manifest_path = Path(tempfile.gettempdir()) / "edu-agent-llm-capability-smoke.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH"] = str(manifest_path)
    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_SHA256"] = manifest["manifest_sha256"]
    os.environ["EDU_AGENT_LLM_ENABLED_CAPABILITIES"] = (
        "quality:tool_calling,fast:tool_calling,quality:native_structured_output,invalid-entry"
    )
    status = capability_status(registry)
    assert status["status"] == "pass", status
    assert "tool_calling" in status["profiles"]["quality"]["enabled_capabilities"]
    assert "tool_calling" not in status["profiles"]["fast"]["enabled_capabilities"]
    assert "native_structured_output" not in status["profiles"]["quality"]["enabled_capabilities"]
    assert registry.get_model("quality").bind_tools([{"name": "safe"}])[0] == "bound-tools"
    for model, action in (
        (registry.get_model("fast"), lambda item: item.bind_tools([{"name": "safe"}])),
        (registry.get_model("quality"), lambda item: item.with_structured_output(dict)),
    ):
        try:
            action(model)
            raise AssertionError("unvalidated optional capability must fail closed")
        except LLMCapabilityError:
            pass

    image_digest = os.environ.pop("EDU_AGENT_IMAGE_DIGEST")
    missing_provenance = capability_status(registry)
    assert "current_image_digest_missing" in missing_provenance["reasons"]
    os.environ["EDU_AGENT_IMAGE_DIGEST"] = image_digest

    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_SHA256"] = "sha256:wrong"
    invalid = capability_status(registry)
    assert invalid["status"] == "invalid"
    assert "manifest_expected_hash_mismatch" in invalid["reasons"]
    assert "tool_calling" not in invalid["profiles"]["quality"]["enabled_capabilities"]

    print("llm_capability_manifest_smoke=PASS")


if __name__ == "__main__":
    main()
