"""调试/健康检查路由：/api/health, /api/ready, /api/debug/*, /api/traces/*"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from security.auth import Actor, require_auth
from tracing import current_trace_id, trace_context
from trace_store import get_trace_store
from llm_config import LLM_PROVIDER, MODEL_FALLBACK, MODEL_FAST, MODEL_QUALITY, llm_fast
from rag.knowledge_base import check_rag_health
from deployment import (
    deployed_commit as current_deployed_commit,
    deployment_environment,
    runtime_config_version as current_runtime_config_version,
    runtime_configuration_errors,
)
from ._shared import trace_meta

router = APIRouter(tags=["debug"])


def latest_eval_report_path() -> Path:
    configured = os.getenv("EDU_AGENT_EVAL_REPORT_PATH")
    if configured:
        return Path(configured).expanduser()

    source_path = Path(__file__).resolve()
    repository_report = source_path.parents[3] / "eval" / "reports" / "latest.json"
    if repository_report.exists():
        return repository_report

    # The backend container flattens backend/ into /app, so keep that layout
    # available for deployments that mount an eval report beside the API.
    return source_path.parents[2] / "eval" / "reports" / "latest.json"


class TraceResponse(BaseModel):
    trace_id: str
    events: list[dict]


@router.get("/api/health")
async def api_health():
    """轻量运行状态检查：不触发 LLM/RAG，供部署平台健康检查使用。"""
    return {"ok": True, "service": "edu-agent-backend"}


@router.get("/api/ready")
async def api_ready(
    collection: str = "history",
    require_rag: bool = False,
    require_external: bool = False,
    require_runtime: bool = False,
):
    """发布前 readiness 聚合：浅检查 DB/LLM 配置/RAG 索引/eval 摘要。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", collection):
        raise HTTPException(status_code=400, detail="Invalid collection")

    checks: dict = {}

    deployed_commit = current_deployed_commit()
    runtime_config_version = current_runtime_config_version()
    rollout_agent_type = os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_AGENT_TYPE", "history_character").strip()[:80]
    runtime_enabled = os.getenv("EDU_AGENT_RUNTIME_V2_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    runtime_mode = "shadow" if os.getenv("EDU_AGENT_RUNTIME_V2_SHADOW_MODE", "true").strip().lower() in {"1", "true", "yes", "on"} else "active"
    checks["deployment"] = {
        "ok": bool(deployed_commit and runtime_config_version) and not runtime_configuration_errors(enabled=runtime_enabled),
        "deployed_commit": deployed_commit or None,
        "runtime_config_version": runtime_config_version or None,
        "environment": deployment_environment(),
        "runtime_configuration_errors": runtime_configuration_errors(enabled=runtime_enabled),
    }

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

    eval_path = latest_eval_report_path()
    try:
        with eval_path.open("r", encoding="utf-8") as fh:
            latest = json.load(fh)
        report_commit = str((latest.get("source_revision") or {}).get("commit_sha") or "")
        generated_at = latest.get("generated_at")
        age_hours = None
        if isinstance(generated_at, str):
            try:
                generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                if generated.tzinfo is None:
                    generated = generated.replace(tzinfo=timezone.utc)
                age_hours = round((datetime.now(timezone.utc) - generated).total_seconds() / 3600, 2)
            except ValueError:
                pass
        revision_matches = bool(deployed_commit and report_commit == deployed_commit)
        fresh = age_hours is not None and 0 <= age_hours <= 168
        checks["latest_eval"] = {
            "ok": bool(latest.get("ok")) and revision_matches and fresh,
            "generated_at": generated_at,
            "age_hours": age_hours,
            "report_commit": report_commit or None,
            "revision_matches": revision_matches,
            "fresh": fresh,
            "summary": latest.get("summary"),
            "failed_suites": latest.get("failed_suites", []),
            "source": "eval_report",
        }
    except FileNotFoundError:
        checks["latest_eval"] = {"ok": False, "missing": True, "reason": "eval report not found"}
    except Exception as exc:
        checks["latest_eval"] = {"ok": False, "error_type": exc.__class__.__name__, "reason": str(exc)[:300]}

    try:
        from agent_runtime.evidence_store import load_release_evidence
        from agent_runtime.readiness import runtime_schema_readiness
        from agent_runtime.rollout_gate import evidence_sha256

        schema = runtime_schema_readiness()
        checks["runtime_schema"] = {"ok": bool(schema.get("schema_ready")), **schema}
        from agent_runtime.rollout_observations import observation_write_health

        observation_health = observation_write_health()
        checks["rollout_observations"] = observation_health
        evidence = load_release_evidence(
            agent_type=rollout_agent_type or None,
            config_version=runtime_config_version or None,
            runtime_mode=runtime_mode,
            deployed_commit=deployed_commit or None,
            environment=deployment_environment(),
        ) if runtime_enabled else None
        profiles = evidence.get("profiles") if isinstance(evidence, dict) and isinstance(evidence.get("profiles"), dict) else {}
        evidence_generated_at = None
        evidence_fresh = False
        if isinstance(evidence, dict) and isinstance(evidence.get("generated_at"), str):
            try:
                evidence_generated_at = datetime.fromisoformat(evidence["generated_at"].replace("Z", "+00:00"))
                if evidence_generated_at.tzinfo is None:
                    evidence_generated_at = evidence_generated_at.replace(tzinfo=timezone.utc)
                evidence_age_hours = (datetime.now(timezone.utc) - evidence_generated_at).total_seconds() / 3600
                evidence_fresh = -0.1 <= evidence_age_hours <= 168
            except ValueError:
                evidence_generated_at = None
        evidence_ok = bool(
            isinstance(evidence, dict)
            and evidence.get("evidence_sha256") == evidence_sha256(evidence)
            and evidence.get("environment") == deployment_environment()
            and evidence_fresh
            and (profiles.get("offline") or {}).get("status") == "pass"
            and (profiles.get("real_llm") or {}).get("status") == "pass"
            and (profiles.get("production_rag") or {}).get("status") == "pass"
        )
        checks["rollout_evidence"] = {
            "ok": evidence_ok,
            "status": "pass" if evidence_ok else ("missing" if runtime_enabled else "disabled"),
            "runtime_enabled": runtime_enabled,
            "runtime_mode": runtime_mode,
            "agent_type": rollout_agent_type or None,
            "evidence_sha256": evidence.get("evidence_sha256") if isinstance(evidence, dict) else None,
            "generated_at": evidence.get("generated_at") if isinstance(evidence, dict) else None,
            "fresh": evidence_fresh,
            "profiles": profiles,
        }
        if not checks["latest_eval"].get("ok") and evidence_ok:
            checks["latest_eval"] = {
                "ok": True,
                "source": "rollout_evidence",
                "report_commit": deployed_commit,
                "revision_matches": True,
                "fresh": True,
                "profiles": profiles,
            }
    except Exception as exc:
        checks["runtime_schema"] = {"ok": False, "error_type": exc.__class__.__name__}
        checks["rollout_evidence"] = {
            "ok": False,
            "status": "unavailable" if runtime_enabled else "disabled",
            "runtime_enabled": runtime_enabled,
            "error_type": exc.__class__.__name__,
        }
        checks["rollout_observations"] = {
            "ok": False,
            "status": "unavailable",
            "error_type": exc.__class__.__name__,
        }

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
    if require_runtime:
        required.extend(["deployment", "runtime_schema", "rollout_evidence", "rollout_observations"])
    ok = all(bool(checks.get(name, {}).get("ok")) for name in required)
    failed_required_checks = [name for name in required if not bool(checks.get(name, {}).get("ok"))]
    warnings = [name for name, payload in checks.items() if name not in required and not payload.get("ok")]
    return {
        "ok": ok,
        "status": "ok" if ok and not warnings else ("degraded" if ok else "failed"),
        "service": "edu-agent-backend",
        "mode": "readiness-shallow",
        "require_rag": require_rag,
        "require_runtime": require_runtime,
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
