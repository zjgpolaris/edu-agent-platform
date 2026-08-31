from __future__ import annotations

from llm_capability_test_support import configure_provenance, passing_probe_report

configure_provenance()

from llm.capability_manifest import build_capability_manifest, current_provenance, validate_capability_manifest  # noqa: E402
from llm.registry import LLMRegistry  # noqa: E402


def main() -> None:
    registry = LLMRegistry()
    expected = set(registry.profiles)
    assert expected == {
        "fast", "quality", "fallback", "reasoning", "multimodal",
        "multimodal_quality", "material", "card_pool",
    }
    report = passing_probe_report(registry)
    assert {item["profile"] for item in report["profiles"]} == expected
    manifest = build_capability_manifest(report, registry, provenance=current_provenance())
    assert validate_capability_manifest(manifest, registry) == []

    report["profiles"] = [item for item in report["profiles"] if item["profile"] != "card_pool"]
    incomplete = build_capability_manifest(report, registry, provenance=current_provenance())
    reasons = validate_capability_manifest(incomplete, registry)
    assert "manifest_profile_card_pool_required_not_passed" in reasons
    assert incomplete["profiles"]["card_pool"]["required_status"] == "fail"
    print("llm_profile_coverage_smoke=PASS")


if __name__ == "__main__":
    main()
