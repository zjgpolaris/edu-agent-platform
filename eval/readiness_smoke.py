"""Readiness 与 Eval 路由 smoke。

验证：
1. /api/ready 浅检查返回稳定结构，不触发外部 LLM/Embedding。
2. /api/eval/latest 与 /api/eval/run 只注册一份，避免旧 mock/report_generator 路由遮蔽新版 run_core_evals 体系。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-readiness-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.api.main import api_ready, app, eval_latest, eval_run, load_eval_runner  # noqa: E402


def run_case(name: str, fn) -> bool:
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


async def ready_endpoint_shape() -> None:
    payload = await api_ready()
    assert "ok" in payload, payload
    assert payload["service"] == "edu-agent-backend", payload
    assert payload["mode"] == "readiness-shallow", payload
    assert isinstance(payload.get("checks"), dict), payload
    for name in ("database", "llm_config", "rag", "latest_eval"):
        assert name in payload["checks"], payload
    assert payload["checks"]["llm_config"]["mode"] == "shallow", payload
    assert payload["checks"]["rag"].get("deep") is False, payload


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


if __name__ == "__main__":
    cases = [
        ("ready_endpoint_shape", ready_endpoint_shape),
        ("eval_routes_registered_once", eval_routes_registered_once),
        ("eval_routes_use_core_runner", eval_routes_use_core_runner),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"readiness_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
