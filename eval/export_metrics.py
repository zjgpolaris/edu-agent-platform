"""Export AgentOps metrics to stdout / JSON for dashboards and cost analysis."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_ops import build_agent_ops_summary


def export_metrics(limit: int = 200) -> dict:
    summary = build_agent_ops_summary(limit=limit)
    audit = summary.get("audit") or {}
    learning = summary.get("learning") or {}
    tools = summary.get("tools") or {}
    trace = summary.get("trace_correlation") or {}

    metrics = {
        "status": summary.get("status"),
        "audit_total": audit.get("total", 0),
        "audit_failure": audit.get("failure", 0),
        "audit_failure_rate": round(audit.get("failure", 0) / max(audit.get("total", 1), 1), 4),
        "learning_events_total": learning.get("total", 0),
        "tool_call_total": sum((tools.get("by_tool_name") or {}).values()),
        "trace_coverage_rate": trace.get("coverage_rate", 0),
        "top_tools": tools.get("by_tool_name") or {},
        "top_actions": audit.get("by_action") or {},
        "top_features": learning.get("by_feature") or {},
        "failed_eval_cases": _collect_failed_cases(),
    }
    return metrics


def _collect_failed_cases() -> list[dict]:
    """Collect failed cases from the latest eval report for conversion to regression cases."""
    latest = ROOT / "eval" / "reports" / "latest.json"
    if not latest.exists():
        return []
    try:
        report = json.loads(latest.read_text(encoding="utf-8"))
        cases = []
        for suite in report.get("suites") or []:
            for fc in suite.get("failed_cases") or []:
                cases.append({"suite": suite.get("name"), **fc})
        return cases
    except Exception:
        return []


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Export EduAgent AgentOps metrics.")
    parser.add_argument("--limit", type=int, default=200, help="Max events to scan.")
    parser.add_argument("--failed-cases", action="store_true", help="Only print failed eval cases.")
    args = parser.parse_args()

    metrics = export_metrics(limit=args.limit)

    if args.failed_cases:
        cases = metrics["failed_eval_cases"]
        if cases:
            print(json.dumps(cases, ensure_ascii=False, indent=2))
        else:
            print("[]")
        return

    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
