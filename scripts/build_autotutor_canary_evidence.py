#!/usr/bin/env python3
"""Build PII-free, hash-sealed AutoTutor production canary evidence."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.evidence_store import save_release_evidence  # noqa: E402
from agent_runtime.readiness import runtime_schema_readiness  # noqa: E402
from agent_runtime.rollout_gate import seal_rollout_evidence  # noqa: E402
from agent_runtime.rollout_observations import aggregate_autotutor_transition_canary  # noqa: E402


def build_autotutor_canary_evidence(
    *,
    deployed_commit: str,
    config_version: str,
    environment: str,
    window_start: str,
    window_end: str,
    minimum_graph_transitions: int = 100,
    drills: dict[str, str] | None = None,
) -> dict:
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
    schema = runtime_schema_readiness()
    revision = str(schema.get("alembic_version") or "")
    if not schema.get("schema_ready") or int(revision or 0) < 16:
        raise ValueError("AutoTutor evidence requires runtime schema revision 016")
    aggregate = aggregate_autotutor_transition_canary(
        config_version=config_version,
        deployed_commit=deployed_commit,
        environment=environment,
        since=window_start,
        until=window_end,
        minimum_graph_transitions=minimum_graph_transitions,
    )
    drill_results = drills or {"restart": "not_run", "writer_failure": "not_run", "kill_switch": "not_run"}
    blockers = list(aggregate.get("blockers") or [])
    if any(drill_results.get(name) != "pass" for name in ("restart", "writer_failure", "kill_switch")):
        blockers.append("production_rehearsals_incomplete")
    if aggregate.get("status") == "GO" and not blockers:
        decision = "GO"
    elif blockers:
        decision = "NO_GO"
    elif aggregate.get("status") == "NOT_READY":
        decision = "NOT_READY"
    else:
        decision = "NO_GO"
    return seal_rollout_evidence({
        "schema_version": 3,
        "agent_type": "auto_tutor",
        "runtime_mode": "active_canary",
        "deployed_commit": deployed_commit,
        "config_version": config_version,
        "environment": environment,
        "migration_revision": revision,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": window_start, "end": window_end},
        "cohort": "verified",
        "aggregate": aggregate,
        "admission": {
            "schema_ready": bool(schema.get("schema_ready")),
            "schema_revision": revision,
            "observation_health": aggregate.get("observation_write_health"),
        },
        "drills": drill_results,
        "decision": decision,
        "blockers": list(dict.fromkeys(blockers)),
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
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
        },
    )
    if args.persist:
        save_release_evidence(evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": evidence["decision"], "blockers": evidence["blockers"], "evidence_sha256": evidence["evidence_sha256"]}))


if __name__ == "__main__":
    main()
