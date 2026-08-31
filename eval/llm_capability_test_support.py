from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TEST_COMMIT = "capability-contract-commit"
TEST_IMAGE = "sha256:" + "a" * 64
TEST_CONFIG = "v1.45-capability-contract"
TEST_ENVIRONMENT = "staging"


def configure_provenance() -> None:
    os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = TEST_COMMIT
    os.environ["EDU_AGENT_IMAGE_DIGEST"] = TEST_IMAGE
    os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = TEST_CONFIG
    os.environ["EDU_AGENT_ENVIRONMENT"] = TEST_ENVIRONMENT


def passing_probe_report(registry, *, optional_profile: str = "quality") -> dict:
    profiles = []
    for key, profile in registry.profiles.items():
        required = ["invoke", "json_prompt"]
        if "stream" in profile.capabilities:
            required.append("stream")
        if "vision" in profile.capabilities:
            required.append("vision_base64")
        if key in {"material", "card_pool"}:
            required.append("configured_max_tokens")
        checks = {name: {"ok": True, "latency_ms": 3} for name in required}
        checks.update({
            "tool_calling": {"ok": key == optional_profile, "latency_ms": 4},
            "native_structured_output": {"ok": False, "latency_ms": 4, "error_type": "Unsupported"},
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
    return {
        "provider": "bailian",
        "transport": "langchain_openai",
        "profiles": profiles,
        "result": "pass",
    }


def valid_manifest(registry, *, now: datetime | None = None) -> dict:
    from llm.capability_manifest import build_capability_manifest, current_provenance

    return build_capability_manifest(
        passing_probe_report(registry),
        registry,
        provenance=current_provenance(),
        now=now or datetime.now(timezone.utc),
    )
