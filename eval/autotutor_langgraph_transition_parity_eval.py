"""Run real Legacy transitions with independent Graph Shadow and emit cutover evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TRAJECTORY_PATH = ROOT / "eval" / "auto_tutor_trajectory_eval.py"
REPORT_JSON = ROOT / "eval" / "reports" / "autotutor_shadow_latest.json"
REPORT_MD = ROOT / "eval" / "reports" / "autotutor_shadow_latest.md"

os.environ["EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED"] = "true"
os.environ["EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_TIMEOUT_MS"] = "500"
sys.path.insert(0, str(BACKEND))


def _load_trajectory_module():
    spec = importlib.util.spec_from_file_location("autotutor_shadow_trajectory", TRAJECTORY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("trajectory suite unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_metadata() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip())
        return commit, dirty
    except Exception:
        return "unknown", True


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _dataset_hash() -> str:
    digest = hashlib.sha256()
    for path in (TRAJECTORY_PATH, ROOT / "eval" / "autotutor_langgraph_shadow_parity_smoke.py"):
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def _write_report(report: dict[str, Any]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    lowered = serialized.lower()
    for forbidden in ("authorization", "api_key", "prompt", "session_id", "student_id", "trace_id", "request_id"):
        if forbidden in lowered:
            raise AssertionError(f"sensitive report field detected: {forbidden}")
    REPORT_JSON.write_text(serialized + "\n", encoding="utf-8")
    latency = report["latency_ms"]
    lines = [
        "# AutoTutor LangGraph Shadow Transition Evidence",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Commit: `{report['git_commit']}`{' (dirty)' if report['dirty'] else ''}",
        f"- Graph config: `{report['graph_config_version']}`",
        f"- Transition schema: `{report['transition_schema_version']}`",
        f"- Dataset: `{report['dataset_version']}`",
        f"- Cases: {report['cases_passed']}/{report['cases_total']}",
        f"- Transitions: {report['transitions_matched']}/{report['transitions_total']}",
        f"- Exact parity: {report['exact_parity_rate']:.4f}",
        f"- External calls: {report['external_call_attempts']}",
        f"- Side effects: {report['side_effect_attempts']}",
        f"- Graph latency p50/p95: {latency['p50']:.3f}ms / {latency['p95']:.3f}ms",
        f"- Decision: **{report['decision']}**",
        "",
        "## Transition coverage",
        "",
        "| Kind | Total | Matched |",
        "|---|---:|---:|",
    ]
    for kind, values in sorted(report["transition_coverage"].items()):
        lines.append(f"| {kind} | {values['total']} | {values['matched']} |")
    lines.extend(["", "## Blockers", ""])
    blockers = report["blockers"]
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- None"])
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    trajectory = _load_trajectory_module()
    from agents.autotutor_shadow import shadow_config_version, shadow_metrics_snapshot

    shadow_metrics_snapshot(clear=True)
    case_results: list[dict[str, Any]] = []
    all_metrics: list[dict[str, Any]] = []
    for name, case in trajectory.CASES:
        shadow_metrics_snapshot(clear=True)
        try:
            passed, reason, _detail = case()
        except Exception as exc:  # noqa: BLE001
            passed, reason = False, f"exception:{exc.__class__.__name__}"
        metrics = shadow_metrics_snapshot(clear=True)
        all_metrics.extend(metrics)
        case_results.append({
            "case": name,
            "passed": bool(passed),
            "reason_code": "ok" if passed else str(reason).split(":", 1)[0][:80],
            "transitions": len(metrics),
            "matched": sum(1 for item in metrics if item.get("matched")),
        })

    coverage: dict[str, dict[str, int]] = {}
    reason_counts: dict[str, int] = {}
    for item in all_metrics:
        kind = str(item.get("transition_kind") or "unknown")
        bucket = coverage.setdefault(kind, {"total": 0, "matched": 0})
        bucket["total"] += 1
        bucket["matched"] += int(bool(item.get("matched")))
        for reason in item.get("reason_codes") or []:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1

    transitions_total = len(all_metrics)
    transitions_matched = sum(1 for item in all_metrics if item.get("matched"))
    external_calls = sum(int(item.get("external_call_attempts") or 0) for item in all_metrics)
    side_effects = sum(int(item.get("side_effect_attempts") or 0) for item in all_metrics)
    durations = [float(item.get("duration_ms") or 0.0) for item in all_metrics]
    cases_passed = sum(1 for item in case_results if item["passed"])
    commit, dirty = _git_metadata()
    blockers: list[str] = []
    if cases_passed != len(case_results):
        blockers.append("legacy_transition_cases_failed")
    if not transitions_total or transitions_matched != transitions_total:
        blockers.append("transition_parity_below_100_percent")
    if external_calls:
        blockers.append("shadow_external_calls_detected")
    if side_effects:
        blockers.append("shadow_side_effects_detected")
    if any(reason in {"shadow_execution_failed", "shadow_timeout"} for reason in reason_counts):
        blockers.append("shadow_execution_not_stable")
    if dirty:
        blockers.append("workspace_dirty_commit_evidence_not_sealed")

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "dirty": dirty,
        "graph_config_version": shadow_config_version(),
        "transition_schema_version": "v1.48.1-transition",
        "dataset_version": _dataset_hash(),
        "cases_total": len(case_results),
        "cases_passed": cases_passed,
        "transitions_total": transitions_total,
        "transitions_matched": transitions_matched,
        "exact_parity_rate": round(transitions_matched / transitions_total, 4) if transitions_total else 0.0,
        "transition_coverage": coverage,
        "reason_code_counts": reason_counts,
        "external_call_attempts": external_calls,
        "side_effect_attempts": side_effects,
        "exception_or_timeout_count": sum(reason_counts.get(key, 0) for key in ("shadow_execution_failed", "shadow_timeout")),
        "latency_ms": {
            "mean": round(statistics.fmean(durations), 3) if durations else 0.0,
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
            "active_added_p50": _percentile(durations, 0.50),
            "active_added_p95": _percentile(durations, 0.95),
        },
        "sensitive_field_scan": "passed",
        "case_results": case_results,
        "blockers": blockers,
        "decision": "GO" if not blockers else "NO_GO",
    }
    _write_report(report)
    print(f"autotutor_langgraph_transition_parity={transitions_matched}/{transitions_total}")
    print(f"autotutor_langgraph_transition_cases_passed={cases_passed}")
    print(f"autotutor_langgraph_transition_cases_total={len(case_results)}")
    print(f"autotutor_langgraph_shadow_p95_ms={report['latency_ms']['p95']}")
    print(f"autotutor_langgraph_cutover_decision={report['decision']}")
    hard_blockers = [item for item in blockers if item != "workspace_dirty_commit_evidence_not_sealed"]
    if hard_blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
