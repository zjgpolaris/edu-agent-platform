from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from llm_capability_test_support import configure_provenance, passing_probe_report, valid_manifest

configure_provenance()

from llm.capability_manifest import (  # noqa: E402
    build_capability_manifest,
    capability_manifest_sha256,
    capability_status,
    current_provenance,
)
from llm.registry import LLMRegistry  # noqa: E402


def main() -> None:
    registry = LLMRegistry()
    os.environ["EDU_AGENT_LLM_ENABLED_CAPABILITIES"] = "quality:tool_calling"
    os.environ.pop("EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH", None)
    assert capability_status(registry)["status"] == "missing"
    assert "tool_calling" not in capability_status(registry)["profiles"]["quality"]["enabled_capabilities"]

    report = passing_probe_report(registry)
    report["profiles"][0]["result"] = "fail"
    required_failure = build_capability_manifest(report, registry, provenance=current_provenance())
    assert required_failure["profiles"]["fast"]["required_status"] == "fail"

    manifest = valid_manifest(registry)
    assert manifest["profiles"]["quality"]["optional_checks"]["tool_calling"]["status"] == "pass"
    assert manifest["profiles"]["quality"]["optional_checks"]["native_structured_output"]["status"] == "fail"
    path = Path(tempfile.gettempdir()) / "edu-agent-llm-capability-gate.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH"] = str(path)
    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_SHA256"] = manifest["manifest_sha256"]
    status = capability_status(registry)
    assert status["status"] == "pass", status
    assert "tool_calling" in status["profiles"]["quality"]["enabled_capabilities"]
    assert "native_structured_output" not in status["profiles"]["quality"]["enabled_capabilities"]

    tampered = deepcopy(manifest)
    tampered["profiles"]["quality"]["model"] = "tampered"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    invalid = capability_status(registry)
    assert invalid["status"] == "invalid"
    assert "manifest_hash_mismatch" in invalid["reasons"]
    assert "tool_calling" not in invalid["profiles"]["quality"]["enabled_capabilities"]

    tampered["manifest_sha256"] = capability_manifest_sha256(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_SHA256"] = tampered["manifest_sha256"]
    assert "manifest_profile_quality_model_mismatch" in capability_status(registry)["reasons"]
    print("llm_capability_gate_smoke=PASS")


if __name__ == "__main__":
    main()
