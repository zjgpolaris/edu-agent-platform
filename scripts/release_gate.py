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


def _ensure_project_python() -> None:
    """Use the configured/project virtualenv locally while preserving CI Python."""
    configured = os.getenv("PYTHON_BIN", "").strip()
    candidate = Path(configured).expanduser() if configured else ROOT / ".venv" / "bin" / "python"
    if configured and not candidate.is_file():
        raise SystemExit(f"PYTHON_BIN does not exist: {candidate}")
    if not candidate.is_file() or candidate.absolute() == Path(sys.executable).absolute():
        return
    os.execve(str(candidate), [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]], os.environ.copy())

PY_COMPILE_TARGETS = [
    "scripts/verify_core.py",
    "scripts/release_gate.py",
    "backend/api/main.py",
    "backend/llm/capability_manifest.py",
    "backend/llm/capability_store.py",
    "backend/llm/capability_probe.py",
    "backend/db/schema.py",
    "backend/agent_ops.py",
    "backend/agent_runtime/rollout_gate.py",
    "backend/student_profile.py",
    "backend/security/audit_log.py",
    "backend/agents/learning_assistant.py",
    "backend/agents/answer_verifier.py",
    "backend/agents/learning_assistant_router.py",
    "backend/agents/learning_assistant_rollout.py",
    "backend/agents/learning_assistant_planner.py",
    "backend/agents/learning_assistant_runtime.py",
    "backend/rag/history_query.py",
    "backend/rag/history_documents.py",
    "backend/rag/rerank.py",
    "backend/tools/history_search.py",
    "backend/services/teacher_today_queue.py",
    "scripts/build_history_entity_catalog.py",
    "scripts/build_history_documents.py",
    "scripts/history_retrieval_review.py",
    "scripts/validate_history_corpus.py",
    "scripts/build_pgvector_index.py",
    "eval/run_core_evals.py",
    "eval/alembic_transaction_boundary_smoke.py",
    "eval/backend_startup_migration_smoke.py",
    "eval/backend_startup_migration_failure_smoke.py",
    "eval/intent_accuracy_eval.py",
    "eval/trajectory_eval.py",
    "eval/answer_groundedness_eval.py",
    "eval/history_query_eval.py",
    "eval/history_retrieval_contract_smoke.py",
    "eval/history_retrieval_review_smoke.py",
    "eval/history_no_answer_eval.py",
    "eval/history_answer_grounding_eval.py",
    "eval/history_retrieval_quality_eval.py",
    "eval/eval_run_evidence_smoke.py",
    "eval/agent_ops_scope_smoke.py",
    "eval/agent_runtime_rollout_gate_smoke.py",
    "eval/agent_runtime_latency_baseline_smoke.py",
    "eval/rollout_evidence_supply_chain_smoke.py",
    "eval/postgres_schema_smoke.py",
    "eval/postgres_upgrade_rehearsal.py",
    "eval/postgres_migration_lock_smoke.py",
    "backend/start_backend.py",
    "scripts/build_rollout_evidence.py",
    "scripts/persist_llm_capability_manifest.py",
    "scripts/write_evidence_status.py",
    "scripts/validate_evidence_statuses.py",
    "scripts/verify_deployed_commit.py",
    "scripts/validate_rollout_gate.py",
    "scripts/validate_runtime_rollout_config.py",
    "scripts/bootstrap_admin.py",
    "scripts/set_rollout_cohort.py",
    "eval/agent_runtime_rollout_status_smoke.py",
    "eval/runtime_rollout_config_smoke.py",
    "eval/production_auth_trusted_rollout_smoke.py",
    "eval/learning_assistant_rollout_smoke.py",
    "eval/learning_assistant_dataset_schema.py",
    "eval/learning_assistant_blind_eval.py",
    "eval/learning_assistant_semantic_router_eval.py",
    "eval/llm_capability_manifest_smoke.py",
    "eval/llm_capability_manifest_provenance_smoke.py",
    "eval/llm_capability_gate_smoke.py",
    "eval/llm_capability_api_smoke.py",
    "eval/llm_release_evidence_v2_smoke.py",
    "eval/llm_profile_coverage_smoke.py",
    "eval/llm_fallback_capability_smoke.py",
    "eval/llm_capability_test_support.py",
    "eval/llm_capability_store_smoke.py",
    "eval/llm_capability_runtime_resolution_smoke.py",
    "eval/learning_assistant_external_ood_eval.py",
    "eval/production_rag_health_smoke.py",
    "eval/demo_contract_smoke.py",
    "eval/demo_trace_projection_smoke.py",
    "eval/demo_trace_authorization_smoke.py",
    "eval/demo_evidence_authorization_smoke.py",
    "eval/autotutor_langchain_provenance_smoke.py",
    "eval/autotutor_langgraph_shadow_parity_smoke.py",
    "backend/agents/autotutor_demo_trace.py",
    "backend/agents/autotutor_evidence.py",
    "backend/agents/autotutor_domain.py",
    "backend/agents/autotutor_graph.py",
    "backend/agents/autotutor_provenance.py",
    "backend/agents/autotutor_shadow.py",
    "backend/llm/managed_model.py",
    "backend/structured_output.py",
]
PY_COMPILE_TARGETS.extend(
    str(path.relative_to(ROOT))
    for path in sorted((ROOT / "backend" / "agent_runtime").glob("*.py"))
)
PY_COMPILE_TARGETS.extend(
    [
        "backend/alembic/versions/007_agent_runtime_v2.py",
        "backend/alembic/versions/008_agent_side_effect_ledger.py",
        "backend/alembic/versions/012_auth_trusted_rollout.py",
        "backend/alembic/versions/013_llm_capability_manifest_store.py",
        "backend/api/routers/agent_runtime.py",
    ]
)

FAST_SUITES = [
    "llm_provider_contract_smoke",
    "autotutor_langchain_provenance_smoke",
    "autotutor_langgraph_shadow_parity_smoke",
    "llm_capability_manifest_smoke",
    "llm_capability_manifest_provenance_smoke",
    "llm_capability_gate_smoke",
    "llm_capability_api_smoke",
    "llm_release_evidence_v2_smoke",
    "llm_profile_coverage_smoke",
    "llm_fallback_capability_smoke",
    "llm_capability_store_smoke",
    "llm_capability_runtime_resolution_smoke",
    "alembic_transaction_boundary_smoke",
    "backend_startup_migration_smoke",
    "backend_startup_migration_failure_smoke",
    "answer_groundedness_eval",
    "history_query_eval",
    "history_retrieval_contract_smoke",
    "history_retrieval_review_smoke",
    "history_no_answer_eval",
    "history_answer_grounding_eval",
    "eval_run_evidence_smoke",
    "agent_ops_smoke",
    "agent_ops_scope_smoke",
    "autotutor_session_recovery_smoke",
    "learning_assistant_multiturn_smoke",
    "learning_assistant_rollout_smoke",
    "autotutor_question_handoff_smoke",
    "intent_accuracy_eval",
    "trajectory_eval",
    "auto_tutor_trajectory_eval",
    "autotutor_teaching_quality_eval",
    "pilot_path_smoke",
    "release_gate_smoke",
    "teacher_features_smoke",
    "today_plan_smoke",
    "completion_overview_smoke",
    "quality_dashboard_smoke",
    "weakpoints_smoke",
    "readiness_smoke",
    "demo_contract_smoke",
    "demo_trace_projection_smoke",
    "demo_trace_authorization_smoke",
    "demo_evidence_authorization_smoke",
    "agent_runtime_contract_smoke",
    "agent_runtime_checkpoint_smoke",
    "agent_runtime_concurrency_smoke",
    "agent_runtime_lifecycle_smoke",
    "agent_runtime_idempotency_smoke",
    "history_character_runtime_smoke",
    "agent_runtime_stream_parity_smoke",
    "agent_runtime_security_smoke",
    "agent_runtime_confirmation_smoke",
    "agent_runtime_product_routes_smoke",
    "agent_runtime_rollout_gate_smoke",
    "agent_runtime_latency_baseline_smoke",
    "rollout_evidence_supply_chain_smoke",
    "agent_runtime_migration_smoke",
    "production_auth_trusted_rollout_smoke",
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
        [
            sys.executable,
            "eval/run_core_evals.py",
            "--suite",
            "production_rag_health_smoke",
            "--suite",
            "history_retrieval_quality_eval",
            "--no-report",
        ],
        env={"PRODUCTION_SMOKE_STRICT": "1", "HISTORY_RETRIEVAL_PRODUCTION_EVAL": "1"},
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


def run_ready_check(
    url: str,
    *,
    require_rag: bool = False,
    require_external: bool = False,
    require_runtime: bool = False,
) -> None:
    url = _with_query(
        url,
        {
            "require_rag": "true" if require_rag else "false",
            "require_external": "true" if require_external else "false",
            "require_runtime": "true" if require_runtime else "false",
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
    _ensure_project_python()
    parser = argparse.ArgumentParser(description="Run EduAgent release readiness checks.")
    parser.add_argument("--fast", action="store_true", help="Run a smaller critical smoke subset instead of full smoke.")
    parser.add_argument("--production", action="store_true", help="Also run production RAG health smoke with strict API_BASE requirements.")
    parser.add_argument("--ready-url", help="Optional deployed /api/ready URL to check after local gates, e.g. https://host/api/ready.")
    parser.add_argument("--ready-require-rag", action="store_true", help="When checking --ready-url, require RAG to pass as a blocking readiness check.")
    parser.add_argument("--ready-require-external", action="store_true", help="When checking --ready-url, require external dependency configuration to pass as a blocking readiness check.")
    parser.add_argument("--ready-require-runtime", action="store_true", help="When checking --ready-url, require deployment provenance, Runtime schema and rollout evidence.")
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
            require_runtime=args.ready_require_runtime,
        )

    profile = "fast" if args.fast else "full"
    prod = "+ production" if args.production else ""
    ready = "+ ready" if args.ready_url else ""
    ready_scope = " ready_scope=rag" if args.ready_url and (args.ready_require_rag or args.production) else (" ready_scope=core" if args.ready_url else "")
    ready_external = " ready_external=required" if args.ready_url and (args.ready_require_external or args.production) else (" ready_external=optional" if args.ready_url else "")
    ready_runtime = " ready_runtime=required" if args.ready_url and args.ready_require_runtime else (" ready_runtime=optional" if args.ready_url else "")
    frontend = "frontend skipped" if args.skip_frontend else "frontend built"
    print(f"release_gate=ok profile={profile}{prod}{ready}{ready_scope}{ready_external}{ready_runtime} {frontend}", flush=True)


if __name__ == "__main__":
    main()
