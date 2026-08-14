"""Readiness 与 Eval 路由 smoke。

验证：
1. /api/ready 浅检查返回稳定结构，不触发外部 LLM/Embedding。
2. /api/eval/latest 与 /api/eval/run 只注册一份，避免旧 mock/report_generator 路由遮蔽新版 run_core_evals 体系。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-readiness-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from api.main import app  # noqa: E402
from api.routers import debug as debug_router  # noqa: E402
from api.routers.debug import api_ready  # noqa: E402
from api.routers.eval_ops import eval_latest, eval_run, load_eval_runner  # noqa: E402


def run_case(name: str, fn) -> bool:
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        print("FAILED_CASE_DETAIL=" + json.dumps({
            "name": name,
            "reason": f"{exc.__class__.__name__}: {exc}",
        }, ensure_ascii=False))
        return False


async def ready_endpoint_shape() -> None:
    rag_calls: list[tuple[str, bool]] = []

    def fake_rag_health(collection: str, *, deep: bool = False) -> dict:
        rag_calls.append((collection, deep))
        return {
            "ok": True,
            "status": "ok",
            "collection": collection,
            "checks": {},
            "config": {"embedding": {"api_key_configured": False}},
        }

    with patch.object(debug_router, "check_rag_health", fake_rag_health):
        payload = await api_ready()

    assert rag_calls == [("history", False)], rag_calls
    assert "ok" in payload, payload
    assert payload["service"] == "edu-agent-backend", payload
    assert payload["mode"] == "readiness-shallow", payload
    assert isinstance(payload.get("checks"), dict), payload
    assert isinstance(payload.get("required_checks"), list), payload
    assert isinstance(payload.get("failed_required_checks"), list), payload
    assert isinstance(payload.get("warning_checks"), list), payload
    for name in ("database", "llm_config", "rag", "latest_eval"):
        assert name in payload["checks"], payload
    assert "external_dependencies" in payload["checks"], payload
    assert payload["checks"]["llm_config"]["mode"] == "shallow", payload
    assert payload["checks"]["rag"].get("deep") is False, payload
    assert payload["checks"]["latest_eval"].get("missing") is not True, payload
    assert payload["checks"]["external_dependencies"]["mode"] == "config-only", payload


def eval_routes_registered_once() -> None:
    routes = [route for route in app.routes if getattr(route, "path", None) in {"/api/eval/latest", "/api/eval/run"}]
    pairs = [(getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", []) or [])), getattr(route, "endpoint", None).__name__) for route in routes]
    latest = [p for p in pairs if p[0] == "/api/eval/latest" and "GET" in p[1]]
    run = [p for p in pairs if p[0] == "/api/eval/run" and "POST" in p[1]]
    assert latest == [("/api/eval/latest", ("GET",), "eval_latest")], pairs
    assert run == [("/api/eval/run", ("POST",), "eval_run")], pairs


def eval_routes_use_core_runner() -> None:
    runner = load_eval_runner()
    assert hasattr(runner, "LATEST_JSON"), runner
    assert hasattr(runner, "run_suite"), runner
    assert hasattr(runner, "build_json_summary"), runner
    assert eval_latest.__name__ == "eval_latest"
    assert eval_run.__name__ == "eval_run"


def eval_report_quality_contract() -> None:
    runner = load_eval_runner()
    result = runner.SuiteResult(
        name="readiness_smoke",
        command=["python", "eval/readiness_smoke.py"],
        returncode=0,
        duration_sec=0.1,
        stdout="OK report_contract",
        stderr="",
        passed_cases=1,
        failed_cases_count=0,
        total_cases=1,
        metrics={},
        failed_cases=[],
    )
    revision = {"commit_sha": "current", "short_sha": "current", "dirty": False}
    with (
        patch.object(runner, "collect_agent_ops_snapshot", return_value={"status": "ok"}),
        patch.object(runner, "source_revision", return_value=revision),
    ):
        offline = runner.build_json_summary([result], include_output=False, profile="custom")
        assert offline["ok"] is True, offline
        assert offline["llm_execution"]["status"] == "not_observed", offline
        real_model = runner.build_json_summary([result], include_output=False, profile="custom", require_real_llm=True)
        assert real_model["ok"] is False, real_model
        assert real_model["llm_execution"]["status"] == "not_run", real_model
        stale = runner.report_runtime_status({
            "generated_at": "2020-01-01T00:00:00+00:00",
            "source_revision": {"commit_sha": "outdated"},
        })
    assert stale["status"] == "stale", stale
    assert "older_than_7_days" in stale["reasons"], stale


if __name__ == "__main__":
    cases = [
        ("ready_endpoint_shape", ready_endpoint_shape),
        ("eval_routes_registered_once", eval_routes_registered_once),
        ("eval_routes_use_core_runner", eval_routes_use_core_runner),
        ("eval_report_quality_contract", eval_report_quality_contract),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"readiness_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
