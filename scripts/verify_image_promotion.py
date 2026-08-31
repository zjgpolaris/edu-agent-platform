#!/usr/bin/env python3
"""Verify that an immutable image has environment evidence before promotion."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid evidence file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid evidence object: {path}")
    return payload


def promotion_errors(evidence: dict, gate: dict, *, commit: str, digest: str, environment: str, minimum_age_hours: int = 0) -> list[str]:
    errors: list[str] = []
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        errors.append("commit_not_full_sha")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        errors.append("image_digest_invalid")
    if int(evidence.get("schema_version") or 0) != 2:
        errors.append("evidence_schema_v2_required")
    clean_evidence = dict(evidence)
    sealed_digest = str(clean_evidence.pop("evidence_sha256", ""))
    calculated_digest = hashlib.sha256(
        json.dumps(clean_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not sealed_digest or sealed_digest != calculated_digest:
        errors.append("evidence_hash_invalid")
    for field, expected in (("deployed_commit", commit), ("image_digest", digest), ("environment", environment)):
        if evidence.get(field) != expected:
            errors.append(f"evidence_{field}_mismatch")
    profiles = evidence.get("profiles") if isinstance(evidence.get("profiles"), dict) else {}
    for name in ("offline", "real_llm_business_eval", "production_rag", "llm_capabilities"):
        if (profiles.get(name) or {}).get("status") != "pass":
            errors.append(f"evidence_{name}_not_passed")
    if gate.get("status") != "pass" or int(gate.get("terminal_runs") or 0) < 100:
        errors.append("rollout_gate_minimum_100_not_passed")
    for field, expected in (
        ("deployed_commit", commit), ("environment", environment), ("config_version", evidence.get("config_version"))
    ):
        if gate.get(field) != expected:
            errors.append(f"rollout_gate_{field}_mismatch")
    if gate.get("run_provenance_coverage") != 1.0 or int(gate.get("observation_write_failures") or 0) != 0:
        errors.append("rollout_gate_provenance_invalid")
    try:
        generated = datetime.fromisoformat(str(evidence.get("generated_at") or "").replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours < minimum_age_hours:
            errors.append("evidence_observation_window_too_short")
        if age_hours > 168:
            errors.append("evidence_stale")
    except ValueError:
        errors.append("evidence_generated_at_invalid")
    return list(dict.fromkeys(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--rollout-gate", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--minimum-age-hours", type=int, default=0)
    args = parser.parse_args()
    errors = promotion_errors(
        _read(args.evidence), _read(args.rollout_gate), commit=args.commit, digest=args.image_digest,
        environment=args.environment, minimum_age_hours=max(0, args.minimum_age_hours),
    )
    print(json.dumps({"status": "pass" if not errors else "fail", "reasons": errors}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
