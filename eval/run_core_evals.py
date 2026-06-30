from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EVAL_DIR = ROOT / "eval"
REPORTS_DIR = EVAL_DIR / "reports"
HISTORY_DIR = REPORTS_DIR / "history"
LATEST_JSON = REPORTS_DIR / "latest.json"
LATEST_MD = REPORTS_DIR / "latest.md"
DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")

CORE_SUITES = [
    "history_character_eval",
    "rag_retrieval_eval",
    "textbook_qa_eval",
    "game_generation_eval",
    "learning_assistant_smoke",
    "material_rag_smoke",
    "student_profile_smoke",
    "homework_grading_smoke",
    "weakpoints_smoke",
    "learning_closure_smoke",
    "teacher_features_smoke",
    "review_system_smoke",
    "tool_registry_smoke",
    "guardrails_smoke",
    "trace_smoke",
    "trajectory_eval",
    "auto_tutor_trajectory_eval",
]
QUICK_SUITES = [
    # Offline-first: these run without LLM/embed and always produce metrics
    "tool_registry_smoke",
    "guardrails_smoke",
    "weakpoints_smoke",
    "learning_closure_smoke",
    "trajectory_eval",
    "auto_tutor_trajectory_eval",
    # LLM/embed-dependent (skipped gracefully when credentials absent)
    "history_character_smoke",
    "rag_retrieval_eval",
    "material_rag_smoke",
    "learning_assistant_smoke",
]
SMOKE_SUITES = [
    "history_character_smoke",
    "learning_assistant_smoke",
    "material_rag_smoke",
    "student_profile_smoke",
    "homework_grading_smoke",
    "weakpoints_smoke",
    "learning_closure_smoke",
    "teacher_features_smoke",
    "review_system_smoke",
    "tool_registry_smoke",
    "guardrails_smoke",
    "trace_smoke",
]
SUITE_FILES = {
    "history_character_smoke": EVAL_DIR / "history_character_smoke.py",
    "history_character_eval": EVAL_DIR / "history_character_eval.py",
    "rag_retrieval_eval": EVAL_DIR / "rag_retrieval_eval.py",
    "textbook_qa_eval": EVAL_DIR / "textbook_qa_eval.py",
    "game_generation_eval": EVAL_DIR / "game_generation_eval.py",
    "learning_assistant_smoke": EVAL_DIR / "learning_assistant_smoke.py",
    "material_rag_smoke": EVAL_DIR / "material_rag_smoke.py",
    "student_profile_smoke": EVAL_DIR / "student_profile_smoke.py",
    "homework_grading_smoke": EVAL_DIR / "homework_grading_smoke.py",
    "weakpoints_smoke": EVAL_DIR / "weakpoints_smoke.py",
    "learning_closure_smoke": EVAL_DIR / "learning_closure_smoke.py",
    "teacher_features_smoke": EVAL_DIR / "teacher_features_smoke.py",
    "review_system_smoke": EVAL_DIR / "review_system_smoke.py",
    "tool_registry_smoke": EVAL_DIR / "tool_registry_smoke.py",
    "guardrails_smoke": EVAL_DIR / "guardrails_smoke.py",
    "ragas_eval": EVAL_DIR / "ragas_eval.py",
    "trace_smoke": EVAL_DIR / "trace_smoke.py",
    "trajectory_eval": EVAL_DIR / "trajectory_eval.py",
    "auto_tutor_trajectory_eval": EVAL_DIR / "auto_tutor_trajectory_eval.py",
    "production_rag_health_smoke": EVAL_DIR / "production_rag_health_smoke.py",
}
SUITE_METADATA: dict[str, dict[str, str]] = {
    "history_character_smoke": {
        "label": "历史人物 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "history_character_eval": {
        "label": "历史人物对话质量",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "rag_retrieval_eval": {
        "label": "历史 RAG 检索质量",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "textbook_qa_eval": {
        "label": "教材问答质量",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "game_generation_eval": {
        "label": "历史游戏生成",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "learning_assistant_smoke": {
        "label": "学习助手工具 Smoke",
        "category": "tools",
        "kind": "smoke",
        "priority": "p0",
    },
    "material_rag_smoke": {
        "label": "材料 RAG Smoke",
        "category": "rag",
        "kind": "smoke",
        "priority": "p0",
    },
    "student_profile_smoke": {
        "label": "学生画像 Smoke",
        "category": "memory",
        "kind": "smoke",
        "priority": "p0",
    },
    "homework_grading_smoke": {
        "label": "作业批改 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "weakpoints_smoke": {
        "label": "错题本 Smoke",
        "category": "memory",
        "kind": "smoke",
        "priority": "p0",
    },
    "learning_closure_smoke": {
        "label": "学习闭环 Smoke",
        "category": "memory",
        "kind": "smoke",
        "priority": "p0",
    },
    "teacher_features_smoke": {
        "label": "教师功能 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p0",
    },
    "review_system_smoke": {
        "label": "复习系统 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p0",
    },
    "tool_registry_smoke": {
        "label": "工具注册与治理 Smoke",
        "category": "tools",
        "kind": "smoke",
        "priority": "p1",
    },
    "guardrails_smoke": {
        "label": "Guardrails Smoke",
        "category": "safety",
        "kind": "smoke",
        "priority": "p3",
    },
    "trace_smoke": {
        "label": "Agent Runtime Trace Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p1",
    },
    "trajectory_eval": {
        "label": "工具调用轨迹准确率",
        "category": "tools",
        "kind": "quality",
        "priority": "p0",
    },
    "auto_tutor_trajectory_eval": {
        "label": "AutoTutor 自主辅导轨迹",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "ragas_eval": {
        "label": "Ragas 语义质量",
        "category": "rag",
        "kind": "quality",
        "priority": "p1",
    },
    "production_rag_health_smoke": {
        "label": "生产 RAG 健康检查 Smoke",
        "category": "rag",
        "kind": "production_smoke",
        "priority": "p0",
    },
}
METRIC_RE = re.compile(r"^([a-zA-Z0-9_]+)=(\d+)/(\d+)$")
FLOAT_METRIC_RE = re.compile(r"^([a-zA-Z0-9_]+)=(\d+(?:\.\d+)?)$")
FAILED_CASES_RE = re.compile(r"failed cases:\s*(.+)", re.IGNORECASE)
FAILED_CASE_DETAIL_PREFIX = "FAILED_CASE_DETAIL="
FAILED_CASES_JSON_PREFIX = "FAILED_CASES_JSON="
FailedCase: TypeAlias = dict[str, Any]


def normalize_failed_case(value: Any) -> FailedCase:
    if isinstance(value, dict):
        name = value.get("name") or value.get("case") or value.get("id") or "unknown_case"
        payload = {k: v for k, v in value.items() if v is not None and k not in {"name", "case", "id"}}
        return {"name": str(name), **payload}
    return {"name": str(value)}


def failed_case_label(value: Any) -> str:
    item = normalize_failed_case(value)
    label = str(item.get("name") or "unknown_case")
    reason = item.get("reason")
    return f"{label} ({reason})" if reason else label


def llm_judge_answer(case: dict, answer: str) -> dict:
    """Use LLM-as-a-judge to evaluate answer quality."""
    try:
        sys.path.insert(0, str(BACKEND))
        from llm_config import llm_fast
        from structured_output import invoke_structured

        must_contain = case.get("expected_response_keywords", [])
        must_not_contain = case.get("must_not_contain", [])
        character = case.get("character", "")
        question = case.get("message", "")

        prompt = (
            f"你是历史教学质量评审员。请对以下历史人物模拟回答打分（1-5分），输出JSON。\n"
            f"字段：factual_accuracy（事实准确性）、educational_value（教学价值）、"
            f"hallucination_risk（幻觉风险，1=低风险，5=高风险）、comment（一句话评语）\n\n"
            f"人物：{character}\n问题：{question}\n"
            f"必须包含关键词：{must_contain}\n"
            f"不得出现关键词：{must_not_contain}\n\n"
            f"回答：\n{answer[:800]}"
        )
        result = invoke_structured(
            llm_fast,
            [{"role": "user", "content": prompt}],
            fallback={"factual_accuracy": 0, "educational_value": 0, "hallucination_risk": 5, "comment": "评审失败"},
        )
        return result
    except Exception:
        return {"factual_accuracy": 0, "educational_value": 0, "hallucination_risk": 5, "comment": "评审失败"}


@dataclass
class SuiteResult:
    name: str
    command: list[str]
    returncode: int
    duration_sec: float
    stdout: str
    stderr: str
    passed_cases: int
    failed_cases_count: int
    total_cases: int
    metrics: dict[str, dict[str, int | float]]
    failed_cases: list[FailedCase]
    skipped_cases_count: int = 0
    skipped_cases: list[str] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def status(self) -> str:
        if self.returncode == 0 and self.skipped_cases_count and not self.passed_cases and not self.failed_cases_count:
            return "skipped"
        return "passed" if self.ok else "failed"

    def to_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        metadata = suite_metadata(self.name)
        payload: dict[str, Any] = {
            "name": self.name,
            "label": metadata["label"],
            "category": metadata["category"],
            "kind": metadata["kind"],
            "priority": metadata["priority"],
            "status": self.status,
            "ok": self.ok,
            "returncode": self.returncode,
            "duration_sec": round(self.duration_sec, 3),
            "command": " ".join(self.command),
            "passed_cases": self.passed_cases,
            "failed_cases_count": self.failed_cases_count,
            "skipped_cases_count": self.skipped_cases_count,
            "total_cases": self.total_cases,
            "metrics": self.metrics,
            "failed_cases": self.failed_cases,
            "skipped_cases": self.skipped_cases or [],
        }
        if self.error:
            payload["error"] = self.error
        if include_output:
            payload["stdout"] = self.stdout
            payload["stderr"] = self.stderr
        return payload


def suite_metadata(name: str) -> dict[str, str]:
    return {
        "id": name,
        "label": name.replace("_", " "),
        "category": "other",
        "kind": "eval",
        "priority": "p0",
        **SUITE_METADATA.get(name, {}),
    }


def list_suite_metadata() -> list[dict[str, str]]:
    return [suite_metadata(name) for name in SUITE_FILES]


def parse_output(stdout: str, stderr: str) -> tuple[int, int, int, dict[str, dict[str, int | float]], list[FailedCase], int, list[str]]:
    passed = 0
    failed = 0
    skipped = 0
    metrics: dict[str, dict[str, int | float]] = {}
    failed_cases: list[FailedCase] = []
    skipped_cases: list[str] = []

    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("OK "):
            passed += 1
        elif stripped.startswith("FAIL "):
            failed += 1
        elif stripped.startswith("SKIP "):
            skipped += 1
            skipped_cases.append(stripped.removeprefix("SKIP ").strip())

        metric_match = METRIC_RE.match(stripped)
        if metric_match:
            name, count, total = metric_match.groups()
            metrics[name] = {"passed": int(count), "total": int(total)}
            continue

        float_metric_match = FLOAT_METRIC_RE.match(stripped)
        if float_metric_match:
            name, value = float_metric_match.groups()
            metrics[name] = {"value": float(value)}

        if stripped.startswith(FAILED_CASE_DETAIL_PREFIX):
            try:
                failed_cases.append(normalize_failed_case(json.loads(stripped.removeprefix(FAILED_CASE_DETAIL_PREFIX))))
            except Exception:
                failed_cases.append({"name": "malformed_failed_case_detail", "reason": stripped})
        elif stripped.startswith(FAILED_CASES_JSON_PREFIX):
            try:
                detail = json.loads(stripped.removeprefix(FAILED_CASES_JSON_PREFIX))
                if isinstance(detail, list):
                    failed_cases.extend(normalize_failed_case(item) for item in detail)
                else:
                    failed_cases.append(normalize_failed_case(detail))
            except Exception:
                failed_cases.append({"name": "malformed_failed_cases_json", "reason": stripped})

    combined = "\n".join([stdout, stderr])
    failed_match = FAILED_CASES_RE.search(combined)
    if failed_match and not failed_cases:
        failed_cases = [normalize_failed_case(item.strip()) for item in failed_match.group(1).split(",") if item.strip()]

    total = passed + failed + skipped
    if total == 0 and metrics:
        count_metrics = [item for item in metrics.values() if "total" in item and "passed" in item]
        totals = [int(item["total"]) for item in count_metrics]
        total = max(totals) if totals else 0
        passed = min((int(item["passed"]) for item in count_metrics), default=0)
        failed = max(total - passed, 0)

    return passed, failed, total, metrics, failed_cases, skipped, skipped_cases


def run_suite(name: str, *, verbose: bool = False) -> SuiteResult:
    script = SUITE_FILES[name]
    env = os.environ.copy()
    if not env.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
        env["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)
    pythonpath_parts = [str(BACKEND)]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    command = [sys.executable, str(script)]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    duration = time.monotonic() - started
    passed, failed, total, metrics, failed_cases, skipped, skipped_cases = parse_output(result.stdout, result.stderr)
    if result.returncode != 0 and total == 0:
        failed = 1
        total = 1
        if not failed_cases:
            failed_cases = [{"name": "suite_process_failed", "reason": result.stderr.strip() or result.stdout.strip() or "suite exited non-zero"}]

    suite_result = SuiteResult(
        name=name,
        command=command,
        returncode=result.returncode,
        duration_sec=duration,
        stdout=result.stdout,
        stderr=result.stderr,
        passed_cases=passed,
        failed_cases_count=failed,
        total_cases=total,
        metrics=metrics,
        failed_cases=failed_cases,
        skipped_cases_count=skipped,
        skipped_cases=skipped_cases,
    )
    if verbose:
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
    return suite_result


def selected_suites(args: argparse.Namespace) -> list[str]:
    if args.suite:
        unknown = [name for name in args.suite if name not in SUITE_FILES]
        if unknown:
            raise SystemExit(f"unknown suite: {', '.join(unknown)}")
        return args.suite
    return QUICK_SUITES if args.quick else SMOKE_SUITES if args.smoke else CORE_SUITES


def print_text_summary(results: list[SuiteResult]) -> None:
    width = max(len(result.name) for result in results) if results else 0
    for result in results:
        status = result.status.upper()
        case_summary = f"{result.passed_cases}/{result.total_cases}" if result.total_cases else "n/a"
        print(f"[{status}] {result.name:<{width}}  {case_summary}  {result.duration_sec:.1f}s")
        if not result.ok and result.failed_cases:
            print(f"       failed cases: {', '.join(failed_case_label(item) for item in result.failed_cases)}")
        if result.error:
            print(f"       error: {result.error}")

    total_cases = sum(result.total_cases for result in results)
    passed_cases = sum(result.passed_cases for result in results)
    failed_suites = [result.name for result in results if not result.ok]
    print()
    if total_cases:
        print(f"Total cases: {passed_cases}/{total_cases} passed")
    print(f"Suites: {len(results) - len(failed_suites)}/{len(results)} passed")
    if failed_suites:
        print(f"Failed suites: {', '.join(failed_suites)}")


def collect_agent_ops_snapshot(limit: int = 100) -> dict[str, Any]:
    try:
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        from agent_ops import build_agent_ops_summary

        return build_agent_ops_summary(limit=limit)
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def _safe_rate(passed: int | float, total: int | float) -> float:
    return round(float(passed) / float(total), 4) if total else 0.0


def _suite_pass_rate(results: list[SuiteResult], category: str | None = None) -> float:
    scoped = [result for result in results if category is None or suite_metadata(result.name)["category"] == category]
    passed = sum(result.passed_cases for result in scoped)
    total = sum(result.total_cases for result in scoped)
    return _safe_rate(passed, total)


def _count_metric_rate(results: list[SuiteResult], metric_name: str, fallback: float) -> float:
    for result in results:
        metric = result.metrics.get(metric_name)
        if metric and "passed" in metric and "total" in metric:
            return _safe_rate(float(metric["passed"]), float(metric["total"]))
        if metric and "value" in metric:
            return round(float(metric["value"]), 4)
    return fallback


def _category_summary(results: list[SuiteResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        category = suite_metadata(result.name)["category"]
        bucket = summary.setdefault(category, {"passed": 0, "failed": 0, "skipped": 0})
        if result.status == "skipped":
            bucket["skipped"] += 1
        elif result.ok:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    return summary


def _summary_metrics(results: list[SuiteResult], *, passed_cases: int, total_cases: int, duration_sec: float) -> dict[str, float]:
    task_success = _safe_rate(passed_cases, total_cases)
    rag_rate = _suite_pass_rate(results, "rag")
    tools_rate = _suite_pass_rate(results, "tools")
    safety_rate = _suite_pass_rate(results, "safety")
    return {
        "task_success_rate": task_success,
        "retrieval_hit_rate": _count_metric_rate(results, "retrieval_hit_rate", rag_rate),
        "source_correctness": _count_metric_rate(results, "source_correctness", rag_rate),
        "tool_schema_validity": _count_metric_rate(results, "tool_governance", tools_rate),
        "guardrail_pass_rate": _count_metric_rate(results, "guardrail_pass_rate", safety_rate),
        "format_validity": _count_metric_rate(results, "format_validity", task_success),
        "avg_latency_ms": round(duration_sec * 1000 / total_cases, 2) if total_cases else 0.0,
    }


def build_json_summary(results: list[SuiteResult], *, include_output: bool) -> dict[str, Any]:
    failed_suites = [result.name for result in results if not result.ok]
    total_cases = sum(result.total_cases for result in results)
    passed_cases = sum(result.passed_cases for result in results)
    failed_cases = sum(result.failed_cases_count for result in results)
    skipped_cases = sum(result.skipped_cases_count for result in results)
    total_suites = len(results)
    passed_suites = total_suites - len(failed_suites)
    duration_sec = round(sum(result.duration_sec for result in results), 3)
    return {
        "schema_version": 2,
        "failed_case_schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": not failed_suites,
        "summary": {
            "total": total_cases,
            "passed": passed_cases,
            "failed": failed_cases,
            "skipped": skipped_cases,
            "pass_rate": _safe_rate(passed_cases, total_cases),
        },
        "metrics": _summary_metrics(results, passed_cases=passed_cases, total_cases=total_cases, duration_sec=duration_sec),
        "category_summary": _category_summary(results),
        "total_suites": total_suites,
        "passed_suites": passed_suites,
        "failed_suites": failed_suites,
        "passed": passed_suites,
        "total": total_suites,
        "passed_cases": passed_cases,
        "total_cases": total_cases,
        "duration_sec": duration_sec,
        "agent_ops": collect_agent_ops_snapshot(),
        "suites": [result.to_dict(include_output=include_output) for result in results],
    }


def build_markdown_report(summary: dict[str, Any]) -> str:
    status = "PASS" if summary["ok"] else "FAIL"
    lines = [
        "# EduAgent Eval Report",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        f"Overall: {status}",
        f"Suites: {summary['passed_suites']}/{summary['total_suites']} passed",
        f"Cases: {summary['passed_cases']}/{summary['total_cases']} passed",
        f"Duration: {summary['duration_sec']}s",
        "",
        "| Suite | Category | Kind | Status | Cases | Duration |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for suite in summary["suites"]:
        cases = f"{suite.get('passed_cases', 0)}/{suite.get('total_cases', 0)}" if suite.get("total_cases") else "n/a"
        lines.append(
            "| {name} | {category} | {kind} | {status} | {cases} | {duration:.1f}s |".format(
                name=suite.get("name", "unknown"),
                category=suite.get("category", "other"),
                kind=suite.get("kind", "eval"),
                status=str(suite.get("status", "failed")).upper(),
                cases=cases,
                duration=float(suite.get("duration_sec") or 0),
            )
        )

    lines.extend(["", "## Metrics", ""])
    for name, value in (summary.get("metrics") or {}).items():
        lines.append(f"- {name}: {value}")

    lines.extend(["", "## Category summary", ""])
    category_summary = summary.get("category_summary") or {}
    if category_summary:
        lines.extend(["| Category | Passed | Failed | Skipped |", "| --- | ---: | ---: | ---: |"])
        for category, counts in category_summary.items():
            lines.append(f"| {category} | {counts.get('passed', 0)} | {counts.get('failed', 0)} | {counts.get('skipped', 0)} |")
    else:
        lines.append("None.")

    lines.extend(["", "## Failed suites", ""])
    if summary["failed_suites"]:
        lines.extend(f"- {name}" for name in summary["failed_suites"])
    else:
        lines.append("None.")

    lines.extend(["", "## Failed cases", ""])
    failed_case_rows = []
    for suite in summary.get("suites") or []:
        for item in suite.get("failed_cases") or []:
            case = normalize_failed_case(item)
            failed_case_rows.append((suite.get("name", "unknown"), case))
    if failed_case_rows:
        for suite_name, case in failed_case_rows:
            label = failed_case_label(case)
            lines.append(f"- {suite_name}: {label}")
    else:
        lines.append("None.")

    agent_ops = summary.get("agent_ops") or {}
    trace = agent_ops.get("trace_correlation") or {}
    audit = agent_ops.get("audit") or {}
    learning = agent_ops.get("learning") or {}
    tools = agent_ops.get("tools") or {}
    lines.extend([
        "",
        "## AgentOps",
        "",
        f"Status: {agent_ops.get('status', 'unknown')}",
        f"Trace coverage: {trace.get('coverage_rate', 0)} ({trace.get('audit_with_trace', 0) + trace.get('learning_with_trace', 0)}/{trace.get('audit_total', 0) + trace.get('learning_total', 0)} events)",
        f"Audit events: {audit.get('total', 0)} total, {audit.get('failure', 0)} failed",
        f"Learning events: {learning.get('total', 0)} total, {learning.get('failure', 0)} failed",
        f"Top actions: {', '.join((audit.get('by_action') or {}).keys()) or 'None'}",
        f"Top features: {', '.join((learning.get('by_feature') or {}).keys()) or 'None'}",
        f"Top tools: {', '.join((tools.get('by_tool_name') or {}).keys()) or 'None'}",
        "",
    ])
    return "\n".join(lines)


def write_reports(summary: dict[str, Any]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": str(LATEST_JSON.relative_to(ROOT)),
        "markdown": str(LATEST_MD.relative_to(ROOT)),
    }
    summary["report_paths"] = paths
    LATEST_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_MD.write_text(build_markdown_report(summary), encoding="utf-8")
    _save_history_snapshot(summary)
    return paths


def _save_history_snapshot(summary: dict[str, Any]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = summary.get("generated_at", datetime.now(timezone.utc).isoformat()).replace(":", "-").replace("+", "Z")[:23]
    snapshot = {
        "generated_at": summary.get("generated_at"),
        "ok": summary.get("ok"),
        "passed_cases": summary.get("passed_cases"),
        "total_cases": summary.get("total_cases"),
        "passed_suites": summary.get("passed_suites"),
        "total_suites": summary.get("total_suites"),
        "duration_sec": summary.get("duration_sec"),
        "metrics": {k: v for k, v in (summary.get("metrics") or {}).items() if not isinstance(v, dict) or "value" in v},
        "summary": summary.get("summary"),
    }
    (HISTORY_DIR / f"{ts}.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    # keep last 30 snapshots
    snapshots = sorted(HISTORY_DIR.glob("*.json"))
    for old in snapshots[:-30]:
        old.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EduAgent core eval suites.")
    parser.add_argument("--quick", action="store_true", help="Run a smaller quick suite set.")
    parser.add_argument("--smoke", action="store_true", help="Run smoke suites only.")
    parser.add_argument("--json", action="store_true", help="Output JSON summary.")
    parser.add_argument("--suite", action="append", choices=sorted(SUITE_FILES), help="Run one suite; can be repeated.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed suite.")
    parser.add_argument("--verbose", action="store_true", help="Print each suite's raw output.")
    parser.add_argument("--include-output", action="store_true", help="Include raw stdout/stderr in JSON output.")
    parser.add_argument("--no-report", action="store_true", help="Do not write eval/reports/latest.* artifacts.")
    args = parser.parse_args()

    results: list[SuiteResult] = []
    for suite in selected_suites(args):
        result = run_suite(suite, verbose=args.verbose and not args.json)
        results.append(result)
        if args.fail_fast and not result.ok:
            break

    summary = build_json_summary(results, include_output=args.include_output)
    if not args.no_report:
        write_reports(summary)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_text_summary(results)
        if not args.no_report:
            print(f"Reports: {summary['report_paths']['json']}, {summary['report_paths']['markdown']}")

    if any(not result.ok for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
