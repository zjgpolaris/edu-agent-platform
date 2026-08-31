#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LATEST_REPORT = ROOT / "eval" / "reports" / "latest.json"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=30).strip()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def main() -> None:
    reasons: list[str] = []
    head = _git("rev-parse", "HEAD")
    dirty_lines = [line for line in _git("status", "--porcelain=v1", "--untracked-files=all").splitlines() if line]
    if dirty_lines:
        reasons.append("working_tree_not_clean")
    root_lock = ROOT / "package-lock.json"
    tracked = set(_git("ls-files").splitlines())
    if root_lock.exists() and "package-lock.json" not in tracked:
        reasons.append("unexpected_root_package_lock")

    config_version = os.getenv("EDU_AGENT_RUNTIME_V2_CONFIG_VERSION", "").strip()
    deployed_commit = os.getenv("EDU_AGENT_DEPLOYED_COMMIT", "").strip()
    image_digest = os.getenv("EDU_AGENT_IMAGE_DIGEST", "").strip()
    require_evidence_v2 = os.getenv("EDU_AGENT_REQUIRE_LLM_EVIDENCE_V2", "").strip().lower() in {"1", "true", "yes", "on"}
    if not config_version:
        reasons.append("runtime_config_version_missing")
    if deployed_commit != head:
        reasons.append("deployed_commit_does_not_match_head")

    report = _read_json(LATEST_REPORT)
    report_revision = ((report or {}).get("source_revision") or {}).get("commit_sha")
    if report_revision != head:
        reasons.append("eval_report_revision_does_not_match_head")
    if ((report or {}).get("source_revision") or {}).get("dirty") is not False:
        reasons.append("eval_report_revision_not_clean")

    evidence_path_raw = os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_EVIDENCE_PATH", "").strip()
    evidence_path = Path(evidence_path_raw) if evidence_path_raw else None
    evidence = _read_json(evidence_path) if evidence_path else None
    if evidence is None:
        reasons.append("rollout_evidence_missing_or_invalid")
    else:
        from agent_runtime.rollout_gate import evidence_sha256

        if evidence.get("evidence_sha256") != evidence_sha256(evidence):
            reasons.append("rollout_evidence_hash_mismatch")
        if evidence.get("deployed_commit") != head:
            reasons.append("rollout_evidence_revision_does_not_match_head")
        if evidence.get("config_version") != config_version:
            reasons.append("rollout_evidence_config_does_not_match_instance")
        schema_version = int(evidence.get("schema_version") or 1)
        if require_evidence_v2 and schema_version != 2:
            reasons.append("rollout_evidence_schema_v2_required")
        if schema_version == 2:
            if not image_digest:
                reasons.append("image_digest_missing")
            elif evidence.get("image_digest") != image_digest:
                reasons.append("rollout_evidence_image_does_not_match_instance")
        profiles = evidence.get("profiles") if isinstance(evidence.get("profiles"), dict) else {}
        profile_names = (
            ("real_llm", "production_rag")
            if schema_version == 1
            else ("real_llm_business_eval", "production_rag", "llm_capabilities")
        )
        for profile_name in profile_names:
            profile = profiles.get(profile_name)
            if not isinstance(profile, dict) or profile.get("status") != "pass" or profile.get("commit") != head:
                reasons.append(f"{profile_name}_profile_not_passed_for_head")
        if schema_version == 2:
            from llm.capability_manifest import resolve_capability_manifest
            manifest, manifest_resolution = resolve_capability_manifest()
            if manifest is None:
                reasons.append("llm_capability_manifest_missing_or_invalid")
            else:
                from llm.capability_manifest import validate_capability_manifest
                from llm.registry import get_default_registry

                manifest_reasons = validate_capability_manifest(
                    manifest, get_default_registry(), require_expected_provenance=True
                )
                reasons.extend(manifest_reasons)
                capability = profiles.get("llm_capabilities") or {}
                if capability.get("manifest_sha256") != manifest.get("manifest_sha256"):
                    reasons.append("llm_capability_manifest_evidence_mismatch")

    payload = {
        "status": "pass" if not reasons else "fail",
        "head": head,
        "config_version": config_version or None,
        "image_digest": image_digest or None,
        "required_evidence_schema": 2 if require_evidence_v2 else 1,
        "dirty_entry_count": len(dirty_lines),
        "eval_report_revision": report_revision,
        "evidence_path": str(evidence_path) if evidence_path else None,
        "reasons": list(dict.fromkeys(reasons)),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if reasons:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
