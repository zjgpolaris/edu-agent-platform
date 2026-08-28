from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection
from deployment import deployed_commit, deployment_environment, runtime_config_version

VALID_MODES = {"control", "shadow", "active"}
VALID_SCOPES = {"runtime", "eval", "demo"}
BASELINE_STATUSES = {"completed", "partial", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(float(ordered[index]), 2)


def deployment_metadata() -> dict[str, str]:
    return {
        "deployed_commit": deployed_commit(),
        "config_version": runtime_config_version(),
        "environment": deployment_environment(),
    }


def record_rollout_observation(
    *,
    agent_type: str,
    runtime_mode: str,
    status: str,
    latency_ms: int,
    trace_id: str | None,
    data_scope: str | None = None,
    config_version: str | None = None,
    deployed_commit: str | None = None,
    environment: str | None = None,
) -> str:
    if runtime_mode not in VALID_MODES:
        raise ValueError("runtime_mode must be control, shadow or active")
    metadata = deployment_metadata()
    config = (config_version or metadata["config_version"]).strip()[:120]
    commit = (deployed_commit or metadata["deployed_commit"]).strip()[:120]
    target_environment = (environment or metadata["environment"]).strip()[:80]
    scope = (data_scope or os.getenv("EDU_AGENT_DATA_SCOPE", "runtime")).strip().lower()
    if scope == "demo_seed":
        scope = "demo"
    if scope not in VALID_SCOPES:
        scope = "runtime"
    if not config or not commit:
        raise ValueError("deployment commit and runtime config version are required")
    observation_id = f"obs_{uuid4().hex}"
    with get_connection() as conn:
        if "agent_rollout_observations" not in set(sa_inspect(conn).get_table_names()):
            raise LookupError("rollout observation schema is not migrated")
        conn.execute(text("""INSERT INTO agent_rollout_observations (
            observation_id, agent_type, config_version, runtime_mode, deployed_commit,
            environment, status, latency_ms, trace_id, data_scope, created_at
        ) VALUES (
            :observation_id, :agent_type, :config_version, :runtime_mode, :deployed_commit,
            :environment, :status, :latency_ms, :trace_id, :data_scope, :created_at
        )"""), {
            "observation_id": observation_id,
            "agent_type": agent_type[:80],
            "config_version": config,
            "runtime_mode": runtime_mode,
            "deployed_commit": commit,
            "environment": target_environment,
            "status": status[:40],
            "latency_ms": max(0, int(latency_ms)),
            "trace_id": trace_id[:160] if trace_id else None,
            "data_scope": scope,
            "created_at": _now(),
        })
    return observation_id


def try_record_rollout_observation(**kwargs: Any) -> str | None:
    try:
        return record_rollout_observation(**kwargs)
    except Exception:
        return None


def aggregate_control_baseline(
    *,
    agent_type: str,
    config_version: str,
    deployed_commit: str,
    environment: str,
    minimum_samples: int = 100,
    data_scope: str = "runtime",
) -> dict[str, Any]:
    with get_connection() as conn:
        if "agent_rollout_observations" not in set(sa_inspect(conn).get_table_names()):
            raise LookupError("rollout observation schema is not migrated")
        rows = conn.execute(text("""SELECT latency_ms, status, created_at FROM agent_rollout_observations
            WHERE agent_type=:agent_type AND config_version=:config_version
              AND runtime_mode='control' AND deployed_commit=:deployed_commit
              AND environment=:environment AND data_scope=:data_scope
            ORDER BY created_at ASC"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "deployed_commit": deployed_commit,
                "environment": environment,
                "data_scope": data_scope,
            }).mappings().all()
    durations = [int(row["latency_ms"]) for row in rows if str(row["status"]) in BASELINE_STATUSES]
    included_rows = [row for row in rows if str(row["status"]) in BASELINE_STATUSES]
    if len(durations) < max(1, int(minimum_samples)):
        raise ValueError(f"control baseline requires {minimum_samples} samples; observed {len(durations)}")
    return {
        "agent_type": agent_type,
        "commit": deployed_commit,
        "config_version": config_version,
        "environment": environment,
        "sample_count": len(durations),
        "p50_ms": _percentile(durations, 0.50),
        "p95_ms": _percentile(durations, 0.95),
        "source": "server_trace_aggregate",
        "observed_from": included_rows[0]["created_at"],
        "observed_to": included_rows[-1]["created_at"],
    }


def observation_summary(*, agent_type: str, config_version: str, data_scope: str = "runtime") -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT runtime_mode, status, COUNT(*) AS count
            FROM agent_rollout_observations
            WHERE agent_type=:agent_type AND config_version=:config_version AND data_scope=:data_scope
            GROUP BY runtime_mode, status"""), {
                "agent_type": agent_type,
                "config_version": config_version,
                "data_scope": data_scope,
            }).mappings().all()
    return {"agent_type": agent_type, "config_version": config_version, "groups": [dict(row) for row in rows]}
