#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.evidence_store import save_release_evidence
from agent_runtime.rollout_gate import seal_rollout_evidence
from agent_runtime.rollout_observations import aggregate_control_baseline


def _read_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid eval report: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid eval report object: {path}")
    return payload


def _report_commit(report: dict[str, Any]) -> str:
    return str((report.get("source_revision") or {}).get("commit_sha") or "")


def _report_is_current(report: dict[str, Any], *, deployed_commit: str) -> bool:
    revision = report.get("source_revision") if isinstance(report.get("source_revision"), dict) else {}
    if revision.get("dirty") is not False or str(revision.get("commit_sha") or "") != deployed_commit:
        return False
    try:
        generated = datetime.fromisoformat(str(report.get("generated_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return now - timedelta(days=7) <= generated.astimezone(timezone.utc) <= now + timedelta(minutes=5)


def real_llm_profile(report: dict[str, Any], *, deployed_commit: str) -> dict[str, Any]:
    execution = report.get("llm_execution") if isinstance(report.get("llm_execution"), dict) else {}
    eval_run = report.get("eval_run") if isinstance(report.get("eval_run"), dict) else {}
    commit = _report_commit(report)
    passed = (
        report.get("ok") is True
        and _report_is_current(report, deployed_commit=deployed_commit)
        and eval_run.get("profile") == "real_llm"
        and execution.get("status") == "observed"
        and int(execution.get("run_scoped_calls") or 0) > 0
    )
    return {
        "status": "pass" if passed else "fail",
        "commit": commit or None,
        "eval_run_id": eval_run.get("run_id"),
        "generated_at": report.get("generated_at"),
        "provider": execution.get("provider"),
        "models": sorted((execution.get("models") or {}).keys()),
        "run_scoped_calls": int(execution.get("run_scoped_calls") or 0),
    }


def offline_profile(report: dict[str, Any], *, deployed_commit: str) -> dict[str, Any]:
    eval_run = report.get("eval_run") if isinstance(report.get("eval_run"), dict) else {}
    commit = _report_commit(report)
    passed = (
        report.get("ok") is True
        and _report_is_current(report, deployed_commit=deployed_commit)
        and eval_run.get("profile") == "offline"
        and report.get("evaluation_profile") == "core"
        and not report.get("blocking_skipped_suites")
        and not report.get("not_run_suites")
    )
    return {
        "status": "pass" if passed else "fail",
        "commit": commit or None,
        "eval_run_id": eval_run.get("run_id"),
        "generated_at": report.get("generated_at"),
        "passed_suites": report.get("passed_suites"),
        "total_suites": report.get("total_suites"),
    }


def production_rag_profile(report: dict[str, Any], *, deployed_commit: str) -> dict[str, Any]:
    eval_run = report.get("eval_run") if isinstance(report.get("eval_run"), dict) else {}
    suites = report.get("suites") if isinstance(report.get("suites"), list) else []
    rag_suite = next((suite for suite in suites if isinstance(suite, dict) and suite.get("name") == "production_rag_health_smoke"), None)
    commit = _report_commit(report)
    passed = (
        report.get("ok") is True
        and _report_is_current(report, deployed_commit=deployed_commit)
        and eval_run.get("profile") == "production_canary"
        and isinstance(rag_suite, dict)
        and rag_suite.get("status") == "passed"
    )
    return {
        "status": "pass" if passed else "fail",
        "commit": commit or None,
        "eval_run_id": eval_run.get("run_id"),
        "generated_at": report.get("generated_at"),
        "suite_status": rag_suite.get("status") if isinstance(rag_suite, dict) else "not_run",
    }


def build_evidence(
    *,
    agent_type: str,
    config_version: str,
    runtime_mode: str,
    deployed_commit: str,
    environment: str,
    baseline_config_version: str,
    baseline_commit: str,
    minimum_samples: int,
    offline_report: dict[str, Any],
    real_llm_report: dict[str, Any],
    production_rag_report: dict[str, Any],
) -> dict[str, Any]:
    baseline = aggregate_control_baseline(
        agent_type=agent_type,
        config_version=baseline_config_version,
        deployed_commit=baseline_commit,
        environment=environment,
        minimum_samples=minimum_samples,
    )
    offline = offline_profile(offline_report, deployed_commit=deployed_commit)
    real_llm = real_llm_profile(real_llm_report, deployed_commit=deployed_commit)
    production_rag = production_rag_profile(production_rag_report, deployed_commit=deployed_commit)
    if any(profile["status"] != "pass" for profile in (offline, real_llm, production_rag)):
        raise ValueError("offline, real LLM and production RAG reports must pass for the deployed commit")
    return seal_rollout_evidence({
        "schema_version": 1,
        "agent_type": agent_type,
        "config_version": config_version,
        "runtime_mode": runtime_mode,
        "deployed_commit": deployed_commit,
        "environment": environment,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": {"offline": offline, "real_llm": real_llm, "production_rag": production_rag},
        "control_baseline": baseline,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Build hash-bound Runtime rollout evidence from trusted aggregate inputs.")
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--config-version", required=True)
    parser.add_argument("--runtime-mode", choices=("shadow", "active"), required=True)
    parser.add_argument("--deployed-commit", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--baseline-config-version", required=True)
    parser.add_argument("--baseline-commit", required=True)
    parser.add_argument("--minimum-samples", type=int, default=100)
    parser.add_argument("--offline-report", type=Path, required=True)
    parser.add_argument("--real-llm-report", type=Path, required=True)
    parser.add_argument("--production-rag-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persist", action="store_true", help="Also persist aggregate evidence in the configured database.")
    args = parser.parse_args()
    evidence = build_evidence(
        agent_type=args.agent_type,
        config_version=args.config_version,
        runtime_mode=args.runtime_mode,
        deployed_commit=args.deployed_commit,
        environment=args.environment,
        baseline_config_version=args.baseline_config_version,
        baseline_commit=args.baseline_commit,
        minimum_samples=max(1, args.minimum_samples),
        offline_report=_read_report(args.offline_report),
        real_llm_report=_read_report(args.real_llm_report),
        production_rag_report=_read_report(args.production_rag_report),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.persist:
        save_release_evidence(evidence)
    print(json.dumps({
        "status": "pass",
        "output": str(args.output),
        "persisted": bool(args.persist),
        "evidence_sha256": evidence["evidence_sha256"],
        "baseline_samples": evidence["control_baseline"]["sample_count"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
