"""Build a local, synthetic AutoTutor review pack. Never production evidence.

Default: backend contracts and both browser modes. --backend-only is partial.
CI can run --browser-mode separately and --collect the three current-run packs.
All output destinations must be new directories outside the source checkout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT)]
SUITES = ["autotutor_retention_follow_up_eval", "autotutor_catalog_eval", "autotutor_teaching_quality_eval", "autotutor_teaching_graph_eval",
          "autotutor_demo_graph_policy_smoke", "autotutor_demo_graph_flow_smoke",
          "autotutor_demo_execution_projection_smoke", "auto_tutor_trajectory_eval",
          "demo_evidence_authorization_smoke", "autotutor_session_recovery_smoke"]
STEPS = ("backend", "legacy", "graph")


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_snapshot():
    from run_core_evals import source_revision
    revision = source_revision()
    names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(n for n in names if n)):
        path = ROOT / os.fsdecode(name)
        digest.update(name + b"\0")
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<deleted>")
    return {**revision, "source_sha256": digest.hexdigest()}


def run_process(command, *, env, cwd=ROOT, timeout=300):
    """Bound the complete child process group; keep raw output in private temp files."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        except OSError:
            return {"status": "fail", "reason": "dependency_missing", "returncode": None}, ""
        reason = None
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            reason = "timeout"
        except KeyboardInterrupt:
            reason = "cancelled"
        finally:
            # Also terminate children that outlive a successful parent.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        out.seek(0)
        raw = out.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            reason = "report_too_large"
            raw = b""
        status = "pass" if not reason and process.returncode == 0 else "fail"
        return {"status": status, "reason": reason or (None if status == "pass" else "child_failed"), "returncode": process.returncode}, raw.decode("utf-8", errors="replace")


def parse_eval(raw, revision):
    data = json.loads(raw)
    suites = data["suites"]
    if data["source_revision"] != {k: revision[k] for k in ("commit_sha", "short_sha", "dirty")}:
        raise ValueError("eval_revision_mismatch")
    if sorted(s["name"] for s in suites) != sorted(SUITES):
        raise ValueError("eval_suite_set_mismatch")
    safe = []
    for item in suites:
        counts = {k: item[k] for k in ("passed_cases", "failed_cases_count", "skipped_cases_count", "total_cases")}
        if any(type(v) is not int or v < 0 for v in counts.values()):
            raise ValueError("invalid_eval_counts")
        if sum(counts[k] for k in ("passed_cases", "failed_cases_count", "skipped_cases_count")) != counts["total_cases"]:
            raise ValueError("inconsistent_eval_counts")
        safe.append({"name": item["name"], "status": {"passed": "pass", "failed": "fail", "skipped": "skipped"}.get(item["status"], "not_run"), **counts})
    ok = data["ok"] is True and all(s["status"] == "pass" and s["failed_cases_count"] == s["skipped_cases_count"] == 0 for s in safe)
    return {"status": "pass" if ok else "fail", "suites": safe,
            "passed_suites": sum(s["status"] == "pass" for s in safe), "total_suites": len(safe),
            "cases": {"passed": sum(s["passed_cases"] for s in safe), "failed": sum(s["failed_cases_count"] for s in safe),
                      "skipped": sum(s["skipped_cases_count"] for s in safe), "total": sum(s["total_cases"] for s in safe)}}


def parse_browser(raw):
    data = json.loads(raw)
    stats = data["stats"]
    counts = {k: stats[k] for k in ("expected", "unexpected", "flaky", "skipped")}
    if any(type(v) is not int or v < 0 for v in counts.values()):
        raise ValueError("invalid_browser_counts")
    total = sum(counts.values())
    ok = total > 0 and counts["expected"] == total and not data.get("errors")
    # Do not copy test errors, attachments, paths, request headers or stdout.
    return {"status": "pass" if ok else "fail", "cases": {"passed": counts["expected"],
            "failed": counts["unexpected"], "flaky": counts["flaky"], "skipped": counts["skipped"], "total": total}}


def render_cases(data):
    if data.get("production_evidence") is not False or data.get("input_mode") != "deterministic_fixture":
        raise ValueError("case_scope_invalid")
    expected = {"misconception_reteach_and_exit_correct", "repeated_wrong_targeted_reteach",
                "exit_wrong_teacher_review_consistency", "pollution_boundary_negative_control"}
    if {r["case_id"] for r in data["results"]} != expected or any(r["status"] != "pass" for r in data["results"]):
        raise ValueError("case_results_incomplete")
    from backend.agents.autotutor_demo_execution import project_execution
    lines = ["# 本轮合成教学案例", "", "输入：确定性审核内容。真实本地 Graph；不是 LLM 泛化或生产证据。", ""]
    seen = set()
    for example in data["examples"]:
        scenario = example["scenario"]
        if scenario not in {"misconception_reteach", "exit_correct", "exit_wrong"}:
            raise ValueError("case_scenario_invalid")
        seen.add(scenario)
        execution = project_execution(example["execution"])
        if not execution or execution["selected_executor"] != "graph_active" or not execution["visited_nodes"]:
            raise ValueError("case_execution_missing")
        lines += [f"## {scenario}", "", f"目标：{str(example['objective'])[:160]}", "",
                  f"实际节点：{' → '.join(execution['visited_nodes'])}", ""]
        if scenario == "misconception_reteach":
            lines += ["误区：将历史影响当作失败原因。", "", "重教前：" + str(example["before"])[:1000], "",
                      "重教后：" + str(example["after"])[:1000], ""]
        else:
            lines += [f"独立退出票通过：{example['passed']}；教师掌握结论：{example['mastery']}；薄弱点处理：{example['weakpoint_action']}。", ""]
    if seen != {"misconception_reteach", "exit_correct", "exit_wrong"}:
        raise ValueError("case_examples_incomplete")
    return "\n".join(lines)


def render_planning(data):
    examples = data.get("examples", [])
    if data.get("production_evidence") is not False or {e.get("mode") for e in examples} != {"graph_active", "legacy"}:
        raise ValueError("planning_examples_incomplete")
    lines = ["\n## 内容感知规划案例", "", "本地合成学情；不属于生产证据。", ""]
    for example in examples:
        if (example.get("automatic_target") != "洋务运动目的" or example.get("explicit_target") != "甲午战争影响"
                or example.get("explicit_status") != "needs_content" or example.get("planning_decision", {}).get("skipped_count") != 1):
            raise ValueError("planning_example_invalid")
        lines += [f"- {example['mode']}：自动跳过甲午战争，选择洋务运动目的；显式甲午战争保持原目标并阻断。"]
    return "\n".join(lines) + "\n"


def render_follow_up(data):
    examples = data.get("examples", [])
    if data.get("production_evidence") is not False or len(examples) != 4 or {
        (e.get("mode"), e.get("difficulty")) for e in examples
    } != {(mode, difficulty) for mode in ("legacy", "graph_active") for difficulty in ("easy", "medium")}:
        raise ValueError("follow_up_examples_incomplete")
    if any(e.get("immediate") != "verified" or e.get("follow_up") != "content_blocked" for e in examples):
        raise ValueError("follow_up_example_invalid")
    return "\n## 课后间隔复测\n\nGraph 与 Legacy 的 easy / medium 合成案例：课内独立检验通过，已写入 24 小时排期；到期没有未用过的独立退出票，明确阻断，未改判留存。额外题恢复成功仅在隔离测试夹具中验证，不代表当前题库新增覆盖。\n"


def overall(steps, stable):
    if not stable or any(v["status"] == "fail" for v in steps.values()):
        return "fail"
    return "pass" if all(steps[k]["status"] == "pass" for k in STEPS) else "partial"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def restore_generated_next_env(path, before, mode):
    """Restore only the exact known Next dev import rewrite, never arbitrary edits."""
    dist = ".next-e2e-graph" if mode == "graph" else ".next-e2e"
    expected = re.sub(rb'import "\./\.next[^"\n]*/types/routes\.d\.ts";',
                      f'import "./{dist}/dev/types/routes.d.ts";'.encode(), before)
    if path.is_file() and path.read_bytes() == expected:
        path.write_bytes(before)
        return True
    return False


def finalize(output, manifest):
    manifest["finished_at"] = utc()
    manifest["source_after"] = source_snapshot()
    manifest["source_stable"] = manifest["source_before"] == manifest["source_after"] and bool(manifest["source_before"]["commit_sha"])
    manifest["status"] = overall(manifest["steps"], manifest["source_stable"])
    write_json(output / "manifest.json", manifest)
    lines = ["# AutoTutor 本地验收", "", f"状态：{manifest['status'].upper()}", "",
             f"Commit：{manifest['source_before']['commit_sha']}；dirty={manifest['source_before']['dirty']}；source_stable={manifest['source_stable']}", "",
             "确定性输入；production_evidence=false。网络调用总数 unknown；不代表云端性能或真实模型质量。", "",
             "| 步骤 | 状态 | 原因 |", "|---|---|---|"]
    for name, step in manifest["steps"].items():
        lines.append(f"| {name} | {step['status']} | {step.get('reason') or ''} |")
    lines += ["", "[后端 suite/case 计数](eval-summary.json) · [浏览器 case 计数](browser-summary.json)", "",
              "[本轮教学与失败案例](cases/teaching-example.md)", "",
              "五分钟讲解：目标 → 误区 → Graph 纠正 → 独立退出票 → 教师结论。重现命令见项目 README。"]
    (output / "summary.md").write_text("\n".join(lines) + "\n")


def collect(inputs, output, manifest):
    identity = manifest["source_before"]
    eval_data, browser_data, selected = {"status": "not_run"}, {}, set()
    for folder in inputs:
        source = Path(folder)
        item = json.loads((source / "manifest.json").read_text())
        if item.get("schema_version") != 1 or item["source_before"] != identity or item["source_after"] != identity or not item["source_stable"] or item.get("ci_run") != manifest["ci_run"] or item.get("production_evidence") is not False:
            raise ValueError("collection_source_mismatch")
        for name in STEPS:
            step = item["steps"][name]
            if step["status"] not in {"pass", "fail", "skipped", "not_run"}:
                raise ValueError("collection_step_invalid")
            if step["status"] == "not_run":
                continue
            if name in selected:
                raise ValueError("duplicate_collection_step")
            selected.add(name)
            manifest["steps"][name] = step
            if name == "backend":
                eval_data = json.loads((source / "eval-summary.json").read_text())
                if step["status"] == "pass" and (eval_data.get("status") != "pass" or sorted(s["name"] for s in eval_data["suites"]) != sorted(SUITES)):
                    raise ValueError("collection_eval_incomplete")
                shutil.copyfile(source / "cases/teaching-example.md", output / "cases/teaching-example.md")
            else:
                browser_data[name] = json.loads((source / "browser-summary.json").read_text())[name]
                if step["status"] == "pass" and browser_data[name].get("status") != "pass":
                    raise ValueError("collection_browser_incomplete")
    write_json(output / "eval-summary.json", eval_data)
    write_json(output / "browser-summary.json", browser_data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--backend-only", action="store_true")
    mode.add_argument("--browser-mode", choices=["legacy", "graph"])
    mode.add_argument("--collect", nargs="+")
    parser.add_argument("--timeout", type=int, default=600, help="Maximum seconds per step")
    parser.add_argument("--upstream-result", action="append", choices=["success", "failure", "cancelled", "skipped"], default=[], help="CI dependency result for collection")
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    if output == ROOT or ROOT in output.parents or output.exists() or args.timeout < 1:
        parser.error("output must be a new directory outside checkout; timeout must be positive")
    output.mkdir(parents=True)
    (output / "cases").mkdir()
    (output / "cases/teaching-example.md").write_text("# 教学案例\n\n本轮未生成完整教学案例。\n")
    write_json(output / "eval-summary.json", {"status": "not_run"})
    write_json(output / "browser-summary.json", {k: {"status": "not_run"} for k in ("legacy", "graph")})
    manifest = {"schema_version": 1, "run_id": str(uuid4()), "started_at": utc(),
        "source_before": source_snapshot(), "input_mode": "deterministic_fixture", "production_evidence": False,
        "runtime": {"python": platform.python_version(), "python_executable": Path(sys.executable).name, "node": None},
        "ci_run": {"id": os.getenv("GITHUB_RUN_ID"), "attempt": os.getenv("GITHUB_RUN_ATTEMPT")},
        "network_calls": None, "steps": {k: {"status": "not_run"} for k in STEPS},
        "artifacts": ["summary.md", "eval-summary.json", "browser-summary.json", "cases/teaching-example.md"]}
    active = "backend" if not args.browser_mode else args.browser_mode
    try:
        if args.collect:
            collect(args.collect, output, manifest)
            if args.upstream_result:
                manifest["steps"]["ci_dependencies"] = {"status": "pass" if all(r == "success" for r in args.upstream_result) else "fail", "reason": "upstream_jobs_checked"}
        else:
            if os.getenv("DATABASE_URL") or os.getenv("DIRECT_URL"):
                raise ValueError("external_database_environment_rejected")
            # Whitelist process plumbing only; do not inherit provider keys or developer overrides.
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "SYSTEMROOT", "CI", "PLAYWRIGHT_BROWSERS_PATH", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"}}
            env.update(PYTHONPATH=str(ROOT / "backend"), EDU_AGENT_LLM_DISABLED="1", LANGSMITH_TRACING="false", LANGFUSE_ENABLED="false")
            preflight, _ = run_process([sys.executable, "-c", "import fastapi, sqlalchemy, langgraph, uvicorn"], env=env, timeout=30)
            if preflight["status"] != "pass":
                raise ValueError("python_dependencies_missing")
            with tempfile.TemporaryDirectory(prefix="autotutor-review-private-") as private_dir:
                private = Path(private_dir)
                if not args.browser_mode:
                    env["AUTOTUTOR_REVIEW_CASE_OUTPUT"] = str(private / "cases.json")
                    env["AUTOTUTOR_PLANNING_CASE_OUTPUT"] = str(private / "planning.json")
                    env["AUTOTUTOR_FOLLOW_UP_CASE_OUTPUT"] = str(private / "follow-up.json")
                    command = [sys.executable, str(ROOT / "eval/run_core_evals.py"), "--json", "--no-report"]
                    for suite in SUITES:
                        command += ["--suite", suite]
                    step, raw = run_process(command, env=env, timeout=args.timeout)
                    manifest["steps"]["backend"] = step
                    data = parse_eval(raw, manifest["source_before"])
                    write_json(output / "eval-summary.json", data)
                    if data["status"] != "pass":
                        step.update(status="fail", reason="eval_contract_failed")
                    if step["status"] == "pass":
                        (output / "cases/teaching-example.md").write_text(render_cases(json.loads((private / "cases.json").read_text())) + "\n" + render_planning(json.loads((private / "planning.json").read_text())) + render_follow_up(json.loads((private / "follow-up.json").read_text())))
                browser_data = {k: {"status": "not_run"} for k in ("legacy", "graph")}
                if not args.backend_only:
                    if not shutil.which("node") or not (ROOT / "frontend/node_modules/@playwright/test/cli.js").is_file():
                        active = args.browser_mode or "legacy"
                        raise ValueError("browser_dependencies_missing")
                    node_step, node = run_process(["node", "--version"], env=env, timeout=10)
                    if node_step["status"] != "pass":
                        raise ValueError("node_unavailable")
                    manifest["runtime"]["node"] = node.strip()[:40]
                    for active in ([args.browser_mode] if args.browser_mode else ["legacy", "graph"]):
                        report = private / f"{active}.json"
                        backend_port, frontend_port = free_port(), free_port()
                        while frontend_port == backend_port:
                            frontend_port = free_port()
                        browser_env = {**env, "E2E_PYTHON": sys.executable, "E2E_BACKEND_PORT": backend_port, "E2E_FRONTEND_PORT": frontend_port, "E2E_GRAPH_DEMO": "1" if active == "graph" else "0",
                            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(report), "PLAYWRIGHT_HTML_OPEN": "never",
                            "PLAYWRIGHT_HTML_OUTPUT_DIR": "playwright-graph-report" if active == "graph" else "playwright-report"}
                        generated = ROOT / "frontend/next-env.d.ts"
                        generated_before = generated.read_bytes()
                        try:
                            step, _ = run_process(["node", "node_modules/@playwright/test/cli.js", "test", "--reporter=json,html"], cwd=ROOT / "frontend", env=browser_env, timeout=args.timeout)
                        finally:
                            restore_generated_next_env(generated, generated_before, active)
                        manifest["steps"][active] = step
                        data = parse_browser(report.read_text())
                        browser_data[active] = data
                        write_json(output / "browser-summary.json", browser_data)
                        if data["status"] != "pass":
                            step.update(status="fail", reason="browser_contract_failed")
    except KeyboardInterrupt:
        manifest["steps"][active] = {"status": "fail", "reason": "cancelled"}
    except Exception as exc:
        # Error code only: never copy raw exception text, connection strings or logs.
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum() else "missing_or_invalid_report"
        previous = manifest["steps"][active]
        manifest["steps"][active] = {"status": "fail", "reason": previous.get("reason") if previous.get("status") == "fail" and previous.get("reason") else reason}
    finally:
        finalize(output, manifest)
    print(f"AutoTutor review: {manifest['status']} — {output / 'summary.md'}")
    return 1 if manifest["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
