#!/usr/bin/env python3
"""Release gate：发布前统一验证入口。

默认执行本地完整 gate：Python 语法检查、后端 smoke、前端 build。
使用 --fast 可只跑主路径关键 smoke，适合本地快速回归。
使用 --production 会追加生产 RAG smoke，并要求 API_BASE 与认证信息可用。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PY_COMPILE_TARGETS = [
    "scripts/verify_core.py",
    "scripts/release_gate.py",
    "backend/api/main.py",
    "backend/db/schema.py",
    "backend/services/teacher_today_queue.py",
    "eval/run_core_evals.py",
    "eval/production_rag_health_smoke.py",
]

FAST_SUITES = [
    "agent_ops_smoke",
    "autotutor_session_recovery_smoke",
    "pilot_path_smoke",
    "release_gate_smoke",
    "teacher_features_smoke",
    "today_plan_smoke",
    "completion_overview_smoke",
    "quality_dashboard_smoke",
    "weakpoints_smoke",
    "readiness_smoke",
]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("$ " + " ".join(command), flush=True)
    merged_env = os.environ.copy()
    merged_env["PYTHONPATH"] = "backend"
    if env:
        merged_env.update(env)
    subprocess.run(command, cwd=ROOT, env=merged_env, check=True)


def run_py_compile() -> None:
    run([sys.executable, "-m", "py_compile", *PY_COMPILE_TARGETS])


def run_backend_eval(*, fast: bool) -> None:
    if fast:
        cmd = [sys.executable, "eval/run_core_evals.py"]
        for suite in FAST_SUITES:
            cmd.extend(["--suite", suite])
        cmd.append("--no-report")
        run(cmd)
        return
    run([sys.executable, "scripts/verify_core.py", "--smoke", "--no-report"])


def run_frontend_build() -> None:
    run(["npm", "run", "build", "--prefix", "frontend"])


def run_production_rag() -> None:
    run(
        [sys.executable, "eval/run_core_evals.py", "--suite", "production_rag_health_smoke", "--no-report"],
        env={"PRODUCTION_SMOKE_STRICT": "1"},
    )


def _with_query(url: str, params: dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in params.items() if value != ""})
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _join_names(values: list[str] | None) -> str:
    items = [value for value in (values or []) if value]
    return ",".join(items) if items else "none"


def _ready_summary(payload: dict[str, object]) -> str:
    return " ".join(
        [
            f"status={payload.get('status', 'unknown')}",
            f"mode={payload.get('mode', 'unknown')}",
            f"required={_join_names(payload.get('required_checks') if isinstance(payload.get('required_checks'), list) else [])}",
            f"failed={_join_names(payload.get('failed_required_checks') if isinstance(payload.get('failed_required_checks'), list) else [])}",
            f"warnings={_join_names(payload.get('warning_checks') if isinstance(payload.get('warning_checks'), list) else [])}",
        ]
    )


def run_ready_check(url: str, *, require_rag: bool = False, require_external: bool = False) -> None:
    url = _with_query(
        url,
        {
            "require_rag": "true" if require_rag else "false",
            "require_external": "true" if require_external else "false",
        },
    )
    print(f"$ GET {url}", flush=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "edu-agent-platform-release-gate/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8") or "{}")
    if payload.get("ok") is not True:
        print("READY_CHECK_DETAIL=" + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
        raise SystemExit("readiness check failed")
    print(f"ready_check=ok {_ready_summary(payload)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EduAgent release readiness checks.")
    parser.add_argument("--fast", action="store_true", help="Run a smaller critical smoke subset instead of full smoke.")
    parser.add_argument("--production", action="store_true", help="Also run production RAG health smoke with strict API_BASE requirements.")
    parser.add_argument("--ready-url", help="Optional deployed /api/ready URL to check after local gates, e.g. https://host/api/ready.")
    parser.add_argument("--ready-require-rag", action="store_true", help="When checking --ready-url, require RAG to pass as a blocking readiness check.")
    parser.add_argument("--ready-require-external", action="store_true", help="When checking --ready-url, require external dependency configuration to pass as a blocking readiness check.")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend build (use only when already verified separately).")
    args = parser.parse_args()

    run_py_compile()
    run_backend_eval(fast=args.fast)
    if not args.skip_frontend:
        run_frontend_build()
    if args.production:
        run_production_rag()
    if args.ready_url:
        run_ready_check(
            args.ready_url,
            require_rag=args.ready_require_rag or args.production,
            require_external=args.ready_require_external or args.production,
        )

    profile = "fast" if args.fast else "full"
    prod = "+ production" if args.production else ""
    ready = "+ ready" if args.ready_url else ""
    ready_scope = " ready_scope=rag" if args.ready_url and (args.ready_require_rag or args.production) else (" ready_scope=core" if args.ready_url else "")
    ready_external = " ready_external=required" if args.ready_url and (args.ready_require_external or args.production) else (" ready_external=optional" if args.ready_url else "")
    frontend = "frontend skipped" if args.skip_frontend else "frontend built"
    print(f"release_gate=ok profile={profile}{prod}{ready}{ready_scope}{ready_external} {frontend}", flush=True)


if __name__ == "__main__":
    main()
