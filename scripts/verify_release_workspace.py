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
        profiles = evidence.get("profiles") if isinstance(evidence.get("profiles"), dict) else {}
        for profile_name in ("real_llm", "production_rag"):
            profile = profiles.get(profile_name)
            if not isinstance(profile, dict) or profile.get("status") != "pass" or profile.get("commit") != head:
                reasons.append(f"{profile_name}_profile_not_passed_for_head")

    payload = {
        "status": "pass" if not reasons else "fail",
        "head": head,
        "config_version": config_version or None,
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
