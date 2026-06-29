"""Eval report generator for agent evaluation dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


def generate_report(results: list[dict[str, Any]], suite_name: str) -> dict[str, Any]:
    """Generate evaluation report from test results."""
    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    failed = total - passed

    suites: dict[str, dict[str, Any]] = {}
    for result in results:
        suite = result.get("suite", "unknown")
        if suite not in suites:
            suites[suite] = {"total": 0, "passed": 0, "failed": 0, "metrics": {}}
        suites[suite]["total"] += 1
        if result.get("success"):
            suites[suite]["passed"] += 1
        else:
            suites[suite]["failed"] += 1
        # Add metrics
        if "metrics" in result:
            for key, value in result["metrics"].items():
                if key not in suites[suite]["metrics"]:
                    suites[suite]["metrics"][key] = []
                suites[suite]["metrics"][key].append(value)

    # Calculate average metrics
    for suite in suites.values():
        suite["pass_rate"] = suite["passed"] / suite["total"] if suite["total"] > 0 else 0
        for key, values in suite["metrics"].items():
            suite["metrics"][key] = sum(values) / len(values) if values else 0

    failed_cases = [
        {"suite": r.get("suite"), "case": r.get("case"), "reason": r.get("error")}
        for r in results if not r.get("success")
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": suite_name,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": 0,
            "pass_rate": passed / total if total > 0 else 0,
        },
        "suites": [
            {
                "name": name,
                **data,
            }
            for name, data in suites.items()
        ],
        "failed_cases": failed_cases,
    }
    return report


def save_report(report: dict[str, Any], output_dir: str = "eval/reports") -> None:
    """Save evaluation report to JSON and Markdown."""
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "latest.json"), "w") as f:
        json.dump(report, f, indent=2)
    with open(os.path.join(output_dir, "latest.md"), "w") as f:
        f.write(generate_markdown_report(report))


def generate_markdown_report(report: dict[str, Any]) -> str:
    """Generate Markdown format evaluation report."""
    lines = [
        "# Eval Report",
        f"**Generated at:** {report['generated_at']}",
        f"**Suite:** {report['suite']}",
        "",
        "## Summary",
        f"- Total: {report['summary']['total']}",
        f"- Passed: {report['summary']['passed']}",
        f"- Failed: {report['summary']['failed']}",
        f"- Pass Rate: {report['summary']['pass_rate']:.2%}",
        "",
        "## Suites",
    ]
    for suite in report["suites"]:
        lines.append(f"### {suite['name']}")
        lines.append(f"- Pass Rate: {suite['pass_rate']:.2%}")
        for key, value in suite.get("metrics", {}).items():
            lines.append(f"- {key}: {value:.2%}")
        lines.append("")
    if report["failed_cases"]:
        lines.append("## Failed Cases")
        for case in report["failed_cases"]:
            lines.append(f"- **{case['suite']}/{case['case']}**: {case['reason']}")
    return "\n".join(lines)


def load_latest_report(output_dir: str = "eval/reports") -> dict[str, Any] | None:
    """Load the latest evaluation report."""
    report_path = os.path.join(output_dir, "latest.json")
    if not os.path.exists(report_path):
        return None
    with open(report_path, "r") as f:
        return json.load(f)
