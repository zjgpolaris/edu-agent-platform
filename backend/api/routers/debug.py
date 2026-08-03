"""调试/健康检查路由：/api/health, /api/ready, /api/debug/*, /api/traces/*"""
import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from security.auth import Actor, require_auth
from tracing import current_trace_id, trace_context
from trace_store import get_trace_store
from llm_config import LLM_PROVIDER, MODEL_FALLBACK, MODEL_FAST, MODEL_QUALITY, llm_fast
from rag.knowledge_base import check_rag_health
from ._shared import trace_meta

router = APIRouter(tags=["debug"])


class TraceResponse(BaseModel):
    trace_id: str
    events: list[dict]


@router.get("/api/health")
async def api_health():
    """轻量运行状态检查：不触发 LLM/RAG，供部署平台健康检查使用。"""
    return {"ok": True, "service": "edu-agent-backend"}


@router.get("/api/ready")
async def api_ready(collection: str = "history", require_rag: bool = False, require_external: bool = False):
    """发布前 readiness 聚合：浅检查 DB/LLM 配置/RAG 索引/eval 摘要。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", collection):
        raise HTTPException(status_code=400, detail="Invalid collection")

    checks: dict = {}

    try:
        from sqlalchemy import text as sa_text
        from db.engine import engine
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        checks["database"] = {"ok": True, "dialect": engine.dialect.name}
    except Exception as exc:
        checks["database"] = {"ok": False, "error_type": exc.__class__.__name__, "reason": str(exc)[:300]}

    checks["llm_config"] = {
        "ok": bool(LLM_PROVIDER and MODEL_FAST and MODEL_QUALITY),
        "provider": LLM_PROVIDER,
        "fast_model": MODEL_FAST,
        "quality_model": MODEL_QUALITY,
        "fallback_model": MODEL_FALLBACK,
        "mode": "shallow",
        "credentials_configured": bool(
            (LLM_PROVIDER in {"bailian", "dashscope"} and (os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")))
            or (LLM_PROVIDER not in {"bailian", "dashscope"} and (os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")))
        ),
    }

    try:
        rag_payload = await run_in_threadpool(lambda: check_rag_health(collection, deep=False))
        checks["rag"] = {
            "ok": bool(rag_payload.get("ok")),
            "status": rag_payload.get("status"),
            "collection": rag_payload.get("collection"),
            "deep": False,
            "checks": rag_payload.get("checks"),
            "config": rag_payload.get("config"),
        }
    except Exception as exc:
        checks["rag"] = {"ok": False, "error_type": exc.__class__.__name__, "reason": str(exc)[:300], "deep": False}

    import os as _os
    eval_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "eval", "reports", "latest.json")
    try:
        with open(eval_path, "r", encoding="utf-8") as fh:
            latest = json.load(fh)
        checks["latest_eval"] = {"ok": bool(latest.get("ok")), "generated_at": latest.get("generated_at"), "summary": latest.get("summary"), "failed_suites": latest.get("failed_suites", [])}
    except FileNotFoundError:
        checks["latest_eval"] = {"ok": False, "missing": True, "reason": "eval report not found"}
    except Exception as exc:
        checks["latest_eval"] = {"ok": False, "error_type": exc.__class__.__name__, "reason": str(exc)[:300]}

    rag_config = (checks.get("rag") or {}).get("config") if isinstance(checks.get("rag"), dict) else {}
    embedding_config = rag_config.get("embedding") if isinstance(rag_config, dict) else {}
    checks["external_dependencies"] = {
        "ok": bool(checks["llm_config"].get("credentials_configured")) and bool(isinstance(embedding_config, dict) and embedding_config.get("api_key_configured")),
        "mode": "config-only",
        "llm_provider": checks["llm_config"].get("provider"),
        "llm_credentials_configured": bool(checks["llm_config"].get("credentials_configured")),
        "embedding_api_configured": bool(isinstance(embedding_config, dict) and embedding_config.get("api_key_configured")),
        "dependencies": {
            "llm_provider": {"configured": bool(checks["llm_config"].get("credentials_configured")), "provider": checks["llm_config"].get("provider")},
            "embedding_api": {"configured": bool(isinstance(embedding_config, dict) and embedding_config.get("api_key_configured")), "api_base_configured": bool(isinstance(embedding_config, dict) and embedding_config.get("api_base_configured")), "model": embedding_config.get("model") if isinstance(embedding_config, dict) else None},
        },
    }

    required = ["database", "llm_config"] + (["rag"] if require_rag else []) + (["external_dependencies"] if require_external else [])
    ok = all(bool(checks.get(name, {}).get("ok")) for name in required)
    failed_required_checks = [name for name in required if not bool(checks.get(name, {}).get("ok"))]
    warnings = [name for name, payload in checks.items() if name not in required and not payload.get("ok")]
    return {
        "ok": ok,
        "status": "ok" if ok and not warnings else ("degraded" if ok else "failed"),
        "service": "edu-agent-backend",
        "mode": "readiness-shallow",
        "require_rag": require_rag,
        "required_checks": required,
        "failed_required_checks": failed_required_checks,
        "warning_checks": warnings,
        "checks": checks,
        "warnings": warnings,
    }


@router.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str, actor: Actor = Depends(require_auth)):
    store = get_trace_store()
    events = store.get_trace(trace_id)
    return TraceResponse(trace_id=trace_id, events=events)


@router.get("/api/debug/llm/health")
async def llm_health(deep: bool = False, actor: Actor = Depends(require_auth)):
    config = {"provider": LLM_PROVIDER, "quality_model": MODEL_QUALITY, "fast_model": MODEL_FAST, "fallback_model": MODEL_FALLBACK}
    if not deep:
        return {**config, "ok": True, "mode": "shallow", "message": "LLM config loaded; use ?deep=true to test provider connectivity"}
    with trace_context(name="GET /api/debug/llm/health", metadata=trace_meta("llm_health", "/api/debug/llm/health", stream=False)):
        try:
            response = llm_fast.invoke([{"role": "system", "content": "你是健康检查助手，只返回 JSON。"}, {"role": "user", "content": "返回 {\"ok\": true, \"message\": \"pong\"}"}])
            return {**config, "ok": True, "mode": "deep", "content": response.content[:500]}
        except Exception as exc:
            return {**config, "ok": False, "mode": "deep", "error": str(exc)[:1200]}


@router.get("/api/debug/rag/health")
async def rag_health(collection: str = "history", deep: bool = True, actor: Actor = Depends(require_auth)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", collection):
        raise HTTPException(status_code=400, detail="Invalid collection")
    with trace_context(name="GET /api/debug/rag/health", metadata=trace_meta("rag_health", "/api/debug/rag/health", stream=False, collection=collection, deep=deep)):
        try:
            payload = await run_in_threadpool(lambda: check_rag_health(collection, deep=deep))
        except Exception as exc:
            payload = {"ok": False, "status": "failed", "collection": collection, "deep": deep, "checks": {"rag_health": {"ok": False, "error_type": exc.__class__.__name__, "reason": str(exc)[:500]}}}
        return {**payload, "trace_id": current_trace_id()}
