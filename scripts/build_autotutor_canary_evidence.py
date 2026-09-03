#!/usr/bin/env python3
"""Build PII-free, hash-sealed AutoTutor production canary evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.evidence_store import save_release_evidence  # noqa: E402
from agent_runtime.autotutor_canary_verification import validate_autotutor_canary_snapshot  # noqa: E402
from agent_runtime.readiness import runtime_schema_readiness  # noqa: E402
from agent_runtime.rollout_gate import evidence_sha256, seal_rollout_evidence  # noqa: E402
from agent_runtime.rollout_observations import aggregate_autotutor_transition_canary  # noqa: E402


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path.name}")
    return payload


def _snapshot_hash(snapshot: dict) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_traffic_source_distribution(aggregate: dict) -> dict:
    sources = aggregate.get("traffic_sources")
    if not isinstance(sources, dict):
        raise ValueError("production snapshot traffic source distribution is missing")
    for field in ("control", "graph", "committed_graph"):
        try:
            organic = int(sources["organic"][field])
            verification = int(sources["release_verification"][field])
            total = int(sources["total"][field])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("production snapshot traffic source distribution is invalid") from exc
        if min(organic, verification, total) < 0 or organic + verification != total:
            raise ValueError("production snapshot traffic source distribution is invalid")
    return sources


def persist_remote_evidence(
    url: str,
    evidence: dict,
    *,
    token: str,
    bootstrap_sha256: str = "",
) -> dict:
    if not token:
        raise ValueError("API_TOKEN is required to persist evidence remotely")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if bootstrap_sha256:
        if not re.fullmatch(r"[0-9a-f]{64}", bootstrap_sha256):
            raise ValueError("API_BOOTSTRAP_SHA256 is invalid")
        headers["X-AutoTutor-Bootstrap-SHA256"] = bootstrap_sha256
    request = urllib.request.Request(
        url,
        data=json.dumps({"evidence": evidence}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(result, dict) or result.get("evidence_sha256") != evidence.get("evidence_sha256"):
        raise ValueError("remote evidence persistence acknowledgement is invalid")
    return result


def build_autotutor_canary_evidence(
    *,
    deployed_commit: str,
    config_version: str,
    environment: str,
    window_start: str,
    window_end: str,
    minimum_graph_transitions: int = 100,
    drills: dict[str, str] | None = None,
    snapshot_payload: dict | None = None,
    drill_artifact: dict | None = None,
    stage: str = "candidate",
) -> dict:
    if stage != "candidate":
        raise ValueError("Canary evidence builder only creates candidate evidence")
    if environment == "production" and not re.fullmatch(r"[0-9a-f]{40}", deployed_commit):
        raise ValueError("production evidence requires a full deployed commit SHA")
    try:
        start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("evidence window must contain valid ISO-8601 timestamps") from None
    if start >= end:
        raise ValueError("evidence window end must be after its start")
    if environment == "production" and snapshot_payload is None:
        raise ValueError("production candidate evidence requires an exact server snapshot")
    if snapshot_payload is not None:
        validate_autotutor_canary_snapshot(snapshot_payload)
        production_snapshot = dict(snapshot_payload["snapshot"])
        snapshot_slice = production_snapshot.get("slice") or {}
        snapshot_deployment = production_snapshot.get("deployment") or {}
        snapshot_config = production_snapshot.get("configuration") or {}
        if (
            snapshot_deployment.get("deployed_commit") != deployed_commit
            or snapshot_deployment.get("environment") != environment
            or snapshot_config.get("config_version") != config_version
            or snapshot_slice.get("since") != window_start
            or snapshot_slice.get("until") != window_end
        ):
            raise ValueError("production snapshot provenance does not match evidence inputs")
        aggregate = production_snapshot.get("aggregate")
        revision = str((production_snapshot.get("schema") or {}).get("revision") or "")
        schema = {"schema_ready": int(revision or 0) >= 17, "alembic_version": revision}
    else:
        schema = runtime_schema_readiness()
        revision = str(schema.get("alembic_version") or "")
        if not schema.get("schema_ready") or int(revision or 0) < 17:
            raise ValueError("AutoTutor evidence requires runtime schema revision 017")
        aggregate = aggregate_autotutor_transition_canary(
            config_version=config_version,
            deployed_commit=deployed_commit,
            environment=environment,
            since=window_start,
            until=window_end,
            minimum_graph_transitions=minimum_graph_transitions,
        )
        production_snapshot = {
            "schema_version": 1,
            "agent_type": "auto_tutor",
            "slice": aggregate.get("slice"),
            "deployment": {"deployed_commit": deployed_commit, "environment": environment, "schema_revision": revision},
            "configuration": {"config_version": config_version},
            "schema": {"revision": revision},
            "cohort": {"name": "verified"},
            "aggregate": aggregate,
            "status": aggregate.get("status"),
            "decision": aggregate.get("decision"),
            "blockers": aggregate.get("blockers") or [],
        }
    if not isinstance(aggregate, dict):
        raise ValueError("production snapshot aggregate is missing")
    _validate_traffic_source_distribution(aggregate)
    snapshot_config = production_snapshot.get("configuration") or {}
    cohort_fingerprint = str(snapshot_config.get("cohort_fingerprint") or "")
    runtime_state_fingerprint = str(snapshot_config.get("runtime_state_fingerprint") or "")
    if snapshot_payload is not None and (
        not cohort_fingerprint.startswith("sha256:") or not runtime_state_fingerprint.startswith("sha256:")
    ):
        raise ValueError("production snapshot fingerprints are missing")
    drill_results = dict(drills or {
        "restart": "not_run", "writer_failure": "not_run", "kill_switch": "not_run", "rollback": "not_run",
    })
    drill_attestation = None
    if drill_artifact is not None:
        if (
            drill_artifact.get("attestation_type") != "environment_approved_operator"
            or
            drill_artifact.get("deployed_commit") != deployed_commit
            or drill_artifact.get("config_version") != config_version
            or drill_artifact.get("environment") != environment
            or drill_artifact.get("window") != {"start": window_start, "end": window_end}
            or not isinstance(drill_artifact.get("results"), dict)
        ):
            raise ValueError("drill artifact provenance is invalid")
        drill_attestation = dict(drill_artifact)
        drill_results.update(drill_artifact["results"])
    blockers = list(aggregate.get("blockers") or [])
    if any(drill_results.get(name) != "pass" for name in ("restart", "writer_failure", "kill_switch")):
        blockers.append("production_rehearsals_incomplete")
    if aggregate.get("status") == "GO" and not blockers:
        decision = "CANDIDATE_GO"
    elif blockers:
        decision = "NO_GO"
    elif aggregate.get("status") == "NOT_READY":
        decision = "NOT_READY"
    else:
        decision = "NO_GO"
    return seal_rollout_evidence({
        "schema_version": 4,
        "evidence_stage": "candidate",
        "agent_type": "auto_tutor",
        "runtime_mode": "active_canary",
        "deployed_commit": deployed_commit,
        "config_version": config_version,
        "environment": environment,
        "migration_revision": revision,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": window_start, "end": window_end},
        "cohort": "verified",
        "cohort_fingerprint": cohort_fingerprint or None,
        "runtime_state_fingerprint": runtime_state_fingerprint or None,
        "aggregate": aggregate,
        "snapshot_sha256": _snapshot_hash(production_snapshot),
        "production_snapshot": production_snapshot,
        "admission": {
            "schema_ready": bool(schema.get("schema_ready")),
            "schema_revision": revision,
            "observation_health": aggregate.get("observation_write_health"),
        },
        "drills": drill_results,
        "drill_attestation": drill_attestation,
        "drill_attestation_sha256": _snapshot_hash(drill_attestation) if drill_attestation else None,
        "decision": decision,
        "blockers": list(dict.fromkeys(blockers)),
    })


def build_autotutor_final_evidence(*, candidate: dict, rollback_snapshot_payload: dict) -> dict:
    if candidate.get("evidence_sha256") != evidence_sha256(candidate):
        raise ValueError("candidate evidence hash is invalid")
    if (
        int(candidate.get("schema_version") or 0) == 4
        and candidate.get("evidence_stage") == "final"
        and candidate.get("decision") == "GO"
    ):
        return candidate
    if (
        int(candidate.get("schema_version") or 0) != 4
        or candidate.get("evidence_stage") != "candidate"
        or candidate.get("decision") != "CANDIDATE_GO"
    ):
        raise ValueError("final evidence requires candidate GO evidence")
    validate_autotutor_canary_snapshot(rollback_snapshot_payload)
    rollback_snapshot = rollback_snapshot_payload["snapshot"]
    deployment = rollback_snapshot.get("deployment") or {}
    configuration = rollback_snapshot.get("configuration") or {}
    rollback = rollback_snapshot.get("rollback") or {}
    rollback_aggregate = rollback_snapshot.get("aggregate") or {}
    _validate_traffic_source_distribution(rollback_aggregate)
    if (
        rollback_snapshot.get("snapshot_kind") != "rollback"
        or rollback_snapshot.get("phase") != "rollback_ready_for_finalize"
        or rollback_snapshot.get("status") != "READY"
        or rollback_snapshot.get("decision") != "GO"
        or deployment.get("deployed_commit") != candidate.get("deployed_commit")
        or deployment.get("environment") != candidate.get("environment")
        or configuration.get("config_version") != candidate.get("config_version")
        or configuration.get("cohort_fingerprint") != candidate.get("cohort_fingerprint")
        or configuration.get("mode") != "legacy"
        or int(configuration.get("active_bps") or 0) != 0
        or int(rollback.get("assigned_graph_count") or 0) != 0
        or int(rollback.get("selected_graph_count") or 0) != 0
        or int(rollback.get("assigned_control_count") or 0) < int(rollback.get("minimum_control") or 20)
    ):
        raise ValueError("rollback snapshot does not prove a non-vacuous rollback")
    drills = dict(candidate.get("drills") or {})
    drills["rollback"] = "pass"
    return seal_rollout_evidence({
        **{key: value for key, value in candidate.items() if key != "evidence_sha256"},
        "schema_version": 4,
        "evidence_stage": "final",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_evidence_sha256": candidate["evidence_sha256"],
        "rollback_snapshot_sha256": rollback_snapshot_payload["snapshot_sha256"],
        "rollback_snapshot": rollback_snapshot,
        "drills": drills,
        "decision": "GO",
        "blockers": [],
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--config-version", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--minimum-graph-transitions", type=int, default=100)
    parser.add_argument("--restart-rehearsal", choices=("pass", "fail", "not_run"), default="not_run")
    parser.add_argument("--writer-failure-rehearsal", choices=("pass", "fail", "not_run"), default="not_run")
    parser.add_argument("--kill-switch-rehearsal", choices=("pass", "fail", "not_run"), default="not_run")
    parser.add_argument("--rollback-rehearsal", choices=("pass", "fail", "not_run"), default="not_run")
    parser.add_argument("--stage", choices=("candidate", "final"), default="candidate")
    parser.add_argument("--candidate-evidence-path", type=Path)
    parser.add_argument("--rollback-snapshot-path", type=Path)
    parser.add_argument("--snapshot-path", type=Path)
    parser.add_argument("--drill-artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--persist-url")
    parser.add_argument("--require-go", action="store_true")
    args = parser.parse_args()
    if args.stage == "final":
        if not args.candidate_evidence_path or not args.rollback_snapshot_path:
            raise SystemExit("final stage requires --candidate-evidence-path and --rollback-snapshot-path")
        candidate_artifact = _load_json(args.candidate_evidence_path)
        candidate = candidate_artifact.get("payload") if isinstance(candidate_artifact.get("payload"), dict) else candidate_artifact
        evidence = build_autotutor_final_evidence(
            candidate=candidate,
            rollback_snapshot_payload=_load_json(args.rollback_snapshot_path),
        )
    else:
        evidence = build_autotutor_canary_evidence(
            deployed_commit=args.commit,
            config_version=args.config_version,
            environment=args.environment,
            window_start=args.window_start,
            window_end=args.window_end,
            minimum_graph_transitions=max(1, args.minimum_graph_transitions),
            drills={
                "restart": args.restart_rehearsal,
                "writer_failure": args.writer_failure_rehearsal,
                "kill_switch": args.kill_switch_rehearsal,
                "rollback": args.rollback_rehearsal,
            },
            snapshot_payload=_load_json(args.snapshot_path) if args.snapshot_path else None,
            drill_artifact=_load_json(args.drill_artifact) if args.drill_artifact else None,
            stage=args.stage,
        )
    if args.persist:
        save_release_evidence(evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.persist_url:
        persist_remote_evidence(
            args.persist_url,
            evidence,
            token=os.getenv("API_TOKEN", "").strip(),
            bootstrap_sha256=os.getenv("API_BOOTSTRAP_SHA256", "").strip(),
        )
    print(json.dumps({"decision": evidence["decision"], "blockers": evidence["blockers"], "evidence_sha256": evidence["evidence_sha256"]}))
    if args.require_go and evidence.get("decision") not in {"CANDIDATE_GO", "GO"}:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
