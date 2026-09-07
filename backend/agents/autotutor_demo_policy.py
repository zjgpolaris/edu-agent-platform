"""Explicit local-only Graph policy; never a production rollout permission."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

DEMO_CONFIG = "v1.50-local-graph-demo"
_TRUE = {"1", "true", "yes", "on"}


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("EDU_AGENT_AUTOTUTOR_DEMO_GRAPH_ENABLED", "").lower() in _TRUE


def configuration_errors(env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    if not enabled(env):
        return []
    errors = []
    if env.get("EDU_AGENT_ENVIRONMENT") not in {"local", "test"}:
        errors.append("demo_environment_forbidden")
    if any(env.get(k) for k in ("RENDER", "RENDER_SERVICE_NAME", "RENDER_SERVICE_ID", "RENDER_GIT_COMMIT", "VERCEL", "DYNO", "FLY_APP_NAME", "K_SERVICE")):
        errors.append("demo_hosted_environment_forbidden")
    required = {
        "EDU_AGENT_AUTH_REQUIRED": "true", "EDU_AGENT_DATA_SCOPE": "demo",
        "EDU_AGENT_AUTH_DB_AUTHORITY": "true",
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "legacy", "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "0",
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true", "EDU_AGENT_LLM_DISABLED": "1",
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": DEMO_CONFIG,
    }
    if any(env.get(k) != v for k, v in required.items()):
        errors.append("demo_configuration_invalid")
    if env.get("DATABASE_URL") or env.get("DIRECT_URL"):
        errors.append("demo_external_database_forbidden")
    if any(env.get(k) for k in ("BAILIAN_API_KEY", "OPENAI_API_KEY", "EMBED_API_KEY")) or any(
        env.get(k, "").lower() in _TRUE for k in ("LANGFUSE_ENABLED", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
    ):
        errors.append("demo_external_provider_forbidden")
    try:
        directory = Path(env.get("EDU_AGENT_DEMO_DIR", "")).resolve(strict=True)
        marker = json.loads((directory / "demo.json").read_text())
        if marker != {"schema_version": 1, "profile": "local_demo_graph", "production_evidence": False}:
            raise ValueError("marker")
        db = Path(env["EDU_AGENT_DB_PATH"])
        if not db.is_absolute() or db.resolve() != directory / "demo.sqlite3":
            raise ValueError("database")
    except (KeyError, OSError, ValueError):
        errors.append("demo_database_isolation_required")
    return errors


def validate_configuration() -> None:
    errors = configuration_errors()
    if errors:
        raise RuntimeError(",".join(errors))


def eligibility_reason(student_id: str, *, actor_id: str | None, actor_role: str | None,
                       traffic_source: str = "organic", verification_run_id: str | None = None) -> str | None:
    if not enabled():
        return "demo_graph_disabled"
    errors = configuration_errors()
    if errors:
        return errors[0]
    if os.getenv("EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH", "").lower() in _TRUE:
        return "kill_switch_enabled"
    if traffic_source != "organic" or verification_run_id:
        return "demo_verification_traffic_forbidden"
    if actor_id != student_id or actor_role != "student":
        return "demo_actor_ineligible"
    from security.accounts import get_account
    account = get_account(student_id)
    if not account or account.get("role") != "student" or account.get("account_status") != "active" or account.get("traffic_cohort") != "demo":
        return "demo_actor_ineligible"
    return None


def isolated_context(context):
    from dataclasses import replace
    return replace(context, data_scope="demo", traffic_cohort="demo", rollout_eligible=False,
                   eligibility_reason="demo_actor", internal_force_graph=False,
                   traffic_source="organic", verification_run_id=None)
