"""调试/健康检查路由：/api/health, /api/ready, /api/debug/*, /api/traces/*"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from security.auth import Actor, require_admin, require_auth
from tracing import current_trace_id, trace_context
from trace_store import get_trace_store
from llm_config import (
    LLM_PROVIDER,
    MODEL_FALLBACK,
    MODEL_FAST,
    MODEL_QUALITY,
    llm_configuration_status,
    llm_fast,
)
from rag.knowledge_base import check_rag_health
from deployment import (
    auth_configuration_status,
    deployed_commit as current_deployed_commit,
    deployment_image_digest,
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

    checks["auth_configuration"] = auth_configuration_status()

    deployed_commit = current_deployed_commit()
    image_digest = deployment_image_digest()
    runtime_config_version = current_runtime_config_version()
    require_evidence_v2 = os.getenv("EDU_AGENT_REQUIRE_LLM_EVIDENCE_V2", "").strip().lower() in {"1", "true", "yes", "on"}
    rollout_agent_type = os.getenv("EDU_AGENT_RUNTIME_ROLLOUT_AGENT_TYPE", "history_character").strip()[:80]
    runtime_enabled = os.getenv("EDU_AGENT_RUNTIME_V2_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    runtime_mode = "shadow" if os.getenv("EDU_AGENT_RUNTIME_V2_SHADOW_MODE", "true").strip().lower() in {"1", "true", "yes", "on"} else "active"
    deployment_errors = runtime_configuration_errors(enabled=runtime_enabled)
    if require_evidence_v2:
        if not image_digest:
            deployment_errors.append("image_digest_missing")
        elif not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            deployment_errors.append("image_digest_invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", deployed_commit):
            deployment_errors.append("deployed_commit_not_full_sha")
    deployment_applicable = runtime_enabled or require_runtime
    checks["deployment"] = {
        "ok": (not deployment_applicable) or (bool(deployed_commit and runtime_config_version) and not deployment_errors),
        "applicable": deployment_applicable,
        "status": "not_applicable" if not deployment_applicable else ("pass" if bool(deployed_commit and runtime_config_version) and not deployment_errors else "fail"),
        "deployed_commit": deployed_commit or None,
        "image_digest": image_digest or None,
        "runtime_config_version": runtime_config_version or None,
        "environment": deployment_environment(),
        "runtime_configuration_errors": deployment_errors,
    }

    try:
        from sqlalchemy import text as sa_text
        from db.engine import engine
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        checks["database"] = {"ok": True, "dialect": engine.dialect.name}
    except Exception as exc:
        checks["database"] = {"ok": False, "error_type": exc.__class__.__name__, "reason": str(exc)[:300]}

    llm_status = llm_configuration_status()
    non_credential_errors = [error for error in llm_status.get("errors", []) if "API_KEY" not in error]
    checks["llm_config"] = {
        "ok": bool(LLM_PROVIDER and MODEL_FAST and MODEL_QUALITY) and not non_credential_errors,
        "provider": LLM_PROVIDER,
        "transport": llm_status.get("transport"),
        "fast_model": MODEL_FAST,
        "quality_model": MODEL_QUALITY,
        "fallback_model": MODEL_FALLBACK,
        "mode": "shallow",
        "credentials_configured": bool(llm_status.get("credentials_configured")),
        "configuration_errors": non_credential_errors,
        "profiles": llm_status.get("profiles", {}),
        "capability_manifest": llm_status.get("capability_manifest", {}),
    }
    capability_manifest = checks["llm_config"]["capability_manifest"]
    capability_status = capability_manifest.get("status") if isinstance(capability_manifest, dict) else "unavailable"
    capability_applicable = require_runtime or capability_status not in {"missing", "unavailable", None}
    checks["llm_capabilities"] = {
        "ok": (not capability_applicable) or (isinstance(capability_manifest, dict) and capability_status == "pass"),
        "applicable": capability_applicable,
        **(capability_manifest if isinstance(capability_manifest, dict) else {"status": "unavailable"}),
    }
    if not capability_applicable:
        checks["llm_capabilities"]["status"] = "not_applicable"
        checks["llm_capabilities"]["reason"] = "runtime_and_optional_capabilities_disabled"

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
            "applicable": False,
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
        checks["latest_eval"] = {
            "ok": True,
            "applicable": False,
            "status": "not_available",
            "missing": True,
            "reason": "eval report not bundled with demo runtime",
        }
    except Exception as exc:
        checks["latest_eval"] = {
            "ok": False,
            "applicable": False,
            "status": "not_available",
            "error_type": exc.__class__.__name__,
            "reason": str(exc)[:300],
        }

    try:
        from agent_runtime.evidence_store import load_release_evidence
        from agent_runtime.readiness import runtime_schema_readiness
        from agent_runtime.rollout_gate import evidence_sha256

        schema = runtime_schema_readiness()
        runtime_checks_applicable = runtime_enabled or require_runtime
        checks["runtime_schema"] = {
            "ok": bool(schema.get("schema_ready")) if runtime_checks_applicable else True,
            "applicable": runtime_checks_applicable,
            **schema,
        }
        from agent_runtime.rollout_observations import observation_write_health

        observation_health = observation_write_health()
        checks["rollout_observations"] = {
            **observation_health,
            "ok": bool(observation_health.get("ok")) if runtime_checks_applicable else True,
            "applicable": runtime_checks_applicable,
            "status": observation_health.get("status") if runtime_checks_applicable else "not_applicable",
        }
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
        evidence_schema = int((evidence or {}).get("schema_version") or 1) if isinstance(evidence, dict) else 1
        required_profile_names = (
            ("offline", "real_llm", "production_rag")
            if evidence_schema == 1
            else ("offline", "real_llm_business_eval", "production_rag", "llm_capabilities")
        )
        evidence_ok = bool(
            isinstance(evidence, dict)
            and evidence.get("evidence_sha256") == evidence_sha256(evidence)
            and evidence.get("environment") == deployment_environment()
            and evidence_fresh
            and (not require_evidence_v2 or evidence_schema == 2)
            and (
                evidence_schema != 2
                or not deployment_image_digest()
                or evidence.get("image_digest") == deployment_image_digest()
            )
            and all((profiles.get(name) or {}).get("status") == "pass" for name in required_profile_names)
        )
        rollout_evidence_applicable = runtime_enabled or require_runtime
        checks["rollout_evidence"] = {
            "ok": evidence_ok if rollout_evidence_applicable else True,
            "applicable": rollout_evidence_applicable,
            "status": "pass" if evidence_ok else ("missing" if rollout_evidence_applicable else "not_applicable"),
            "runtime_enabled": runtime_enabled,
            "runtime_mode": runtime_mode,
            "agent_type": rollout_agent_type or None,
            "evidence_sha256": evidence.get("evidence_sha256") if isinstance(evidence, dict) else None,
            "schema_version": evidence_schema if isinstance(evidence, dict) else None,
            "required_schema_version": 2 if require_evidence_v2 else 1,
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
        runtime_checks_applicable = runtime_enabled or require_runtime
        checks["runtime_schema"] = {
            "ok": False if runtime_checks_applicable else True,
            "applicable": runtime_checks_applicable,
            "status": "unavailable" if runtime_checks_applicable else "not_applicable",
            "error_type": exc.__class__.__name__,
        }
        rollout_evidence_applicable = runtime_enabled or require_runtime
        checks["rollout_evidence"] = {
            "ok": False if rollout_evidence_applicable else True,
            "applicable": rollout_evidence_applicable,
            "status": "unavailable" if rollout_evidence_applicable else "not_applicable",
            "runtime_enabled": runtime_enabled,
            "error_type": exc.__class__.__name__,
        }
        checks["rollout_observations"] = {
            "ok": False if runtime_checks_applicable else True,
            "applicable": runtime_checks_applicable,
            "status": "unavailable" if runtime_checks_applicable else "not_applicable",
            "error_type": exc.__class__.__name__,
        }

    rag_config = (checks.get("rag") or {}).get("config") if isinstance(checks.get("rag"), dict) else {}
    embedding_config = rag_config.get("embedding") if isinstance(rag_config, dict) else {}
    checks["external_dependencies"] = {
        "ok": bool(checks["llm_config"].get("credentials_configured")) and bool(isinstance(embedding_config, dict) and embedding_config.get("api_key_configured")),
        "applicable": require_external,
        "mode": "config-only",
        "llm_provider": checks["llm_config"].get("provider"),
        "llm_credentials_configured": bool(checks["llm_config"].get("credentials_configured")),
        "embedding_api_configured": bool(isinstance(embedding_config, dict) and embedding_config.get("api_key_configured")),
        "dependencies": {
            "llm_provider": {"configured": bool(checks["llm_config"].get("credentials_configured")), "provider": checks["llm_config"].get("provider")},
            "embedding_api": {"configured": bool(isinstance(embedding_config, dict) and embedding_config.get("api_key_configured")), "api_base_configured": bool(isinstance(embedding_config, dict) and embedding_config.get("api_base_configured")), "model": embedding_config.get("model") if isinstance(embedding_config, dict) else None},
        },
    }

    required = (["auth_configuration"] if deployment_environment() == "production" else []) + ["database", "llm_config"] + (["rag"] if require_rag else []) + (["external_dependencies"] if require_external else [])
    if require_runtime:
        required.extend(["deployment", "runtime_schema", "llm_capabilities", "rollout_evidence", "rollout_observations"])
    ok = all(bool(checks.get(name, {}).get("ok")) for name in required)
    failed_required_checks = [name for name in required if not bool(checks.get(name, {}).get("ok"))]
    warnings = [
        name
        for name, payload in checks.items()
        if name not in required and payload.get("applicable", True) is not False and not payload.get("ok")
    ]
    not_applicable = [name for name, payload in checks.items() if payload.get("applicable") is False]
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
        "not_applicable_checks": not_applicable,
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
    status = llm_configuration_status()
    config = {
        "provider": LLM_PROVIDER,
        "transport": status.get("transport"),
        "quality_model": MODEL_QUALITY,
        "fast_model": MODEL_FAST,
        "fallback_model": MODEL_FALLBACK,
        "credentials_configured": status.get("credentials_configured"),
        "profiles": status.get("profiles", {}),
        "capability_manifest": status.get("capability_manifest", {}),
    }
    if not deep:
        return {**config, "ok": True, "mode": "shallow", "message": "LLM config loaded; use ?deep=true to test provider connectivity"}
    with trace_context(name="GET /api/debug/llm/health", metadata=trace_meta("llm_health", "/api/debug/llm/health", stream=False)):
        try:
            response = llm_fast.invoke([{"role": "system", "content": "你是健康检查助手，只返回 JSON。"}, {"role": "user", "content": "返回 {\"ok\": true, \"message\": \"pong\"}"}])
            return {
                **config,
                "ok": True,
                "mode": "deep",
                "scope": "fast_connectivity_only",
                "proves": ["credentials", "endpoint_connectivity", "fast_invoke"],
                "does_not_prove": [
                    "all_profiles", "vision", "tool_calling", "native_structured_output", "business_quality"
                ],
                "content": response.content[:500],
            }
        except Exception as exc:
            return {
                **config,
                "ok": False,
                "mode": "deep",
                "scope": "fast_connectivity_only",
                "proves": [],
                "does_not_prove": [
                    "all_profiles", "vision", "tool_calling", "native_structured_output", "business_quality"
                ],
                "error_type": exc.__class__.__name__,
            }


@router.get("/api/admin/llm/capabilities")
async def llm_capabilities(actor: Actor = Depends(require_admin)):
    """Return content-free, deployment-bound LLM capability evidence."""
    from llm.registry import get_default_registry

    return get_default_registry().capability_status()


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
