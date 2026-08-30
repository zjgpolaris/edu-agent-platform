from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EVAL_DIR = ROOT / "eval"
REPORTS_DIR = EVAL_DIR / "reports"
HISTORY_DIR = REPORTS_DIR / "history"
LATEST_JSON = REPORTS_DIR / "latest.json"
LATEST_MD = REPORTS_DIR / "latest.md"
DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")
DEFAULT_SUITE_TIMEOUT_SECONDS = 300
SUITE_TIMEOUT_SECONDS = {
    # 45 quality cases exercise retrieval, generation, verification, fact-card
    # extraction and LLM judging. They run with bounded concurrency.
    "history_character_eval": 1200,
    # This suite intentionally exercises a long multi-step tutoring session.
    "auto_tutor_trajectory_eval": 900,
}
OFFLINE_DETERMINISTIC_SUITES = {
    # These suites validate routing/trajectory and explicitly provide rule-based
    # fallbacks. Credentials in a developer shell must not turn them into slow,
    # quota-dependent integration tests.
    "learning_assistant_smoke",
    "intent_accuracy_eval",
    "trajectory_eval",
    "auto_tutor_trajectory_eval",
    "autotutor_teaching_quality_eval",
    "autotutor_objective_alignment_eval",
    "autotutor_assessment_validity_eval",
    "autotutor_false_mastery_smoke",
    "autotutor_content_blocked_api_smoke",
    "autotutor_exit_ticket_independence_eval",
}
EXTERNAL_QUOTA_ERROR_MARKERS = (
    "allocationquota.freetieronly",
    "free quota has been exhausted",
    "insufficient_quota",
    "quota exceeded",
)
OPTIONAL_SKIP_SUITES = {
    # This is an integration smoke for real LLM + RAG availability. In local
    # and CI smoke gates without credentials it should report the gap without
    # failing the deterministic release gate.
    "history_character_smoke",
    # This quality suite needs a usable external verifier/judge. When absent,
    # product code remains fail-closed and the deterministic runtime contract is
    # covered by history_character_runtime_smoke.
    "history_character_eval",
}

# These suites validate infrastructure that the generic offline release gate
# does not provision. They remain discoverable through --suite and are run by
# dedicated CI jobs with their required services.
DEDICATED_INTEGRATION_SUITES = {
    "postgres_migration_lock_smoke",
    "postgres_schema_smoke",
}

CORE_SUITES = [
    "eval_run_evidence_smoke",
    "alembic_transaction_boundary_smoke",
    "backend_startup_migration_smoke",
    "backend_startup_migration_failure_smoke",
    "answer_groundedness_eval",
    "history_query_eval",
    "history_retrieval_contract_smoke",
    "history_retrieval_review_smoke",
    "history_no_answer_eval",
    "history_answer_grounding_eval",
    "history_character_eval",
    "rag_retrieval_eval",
    "rag_groundedness_eval",
    "textbook_qa_eval",
    "game_generation_eval",
    "agent_ops_smoke",
    "agent_ops_scope_smoke",
    "readiness_smoke",
    "autotutor_session_recovery_smoke",
    "learning_assistant_multiturn_smoke",
    "autotutor_question_handoff_smoke",
    "autotutor_handoff_public_contract_smoke",
    "learning_assistant_smoke",
    "learning_assistant_rollout_smoke",
    "intent_accuracy_eval",
    "material_rag_smoke",
    "release_gate_smoke",
    "student_profile_smoke",
    "homework_grading_smoke",
    "weakpoints_smoke",
    "knowledge_graph_smoke",
    "learning_closure_smoke",
    "teacher_features_smoke",
    "review_system_smoke",
    "adaptive_review_question_quality_eval",
    "review_mastery_evidence_eval",
    "review_retention_scheduler_smoke",
    "review_mastery_migration_smoke",
    "tool_registry_smoke",
    "guardrails_smoke",
    "agent_safety_eval",
    "trace_smoke",
    "trajectory_eval",
    "auto_tutor_trajectory_eval",
    "autotutor_teaching_quality_eval",
    "autotutor_objective_alignment_eval",
    "autotutor_assessment_validity_eval",
    "autotutor_false_mastery_smoke",
    "autotutor_content_blocked_api_smoke",
    "autotutor_exit_ticket_independence_eval",
    "autotutor_adaptive_difficulty_eval",
    "autotutor_transition_idempotency_smoke",
    "autotutor_finalize_fault_injection_smoke",
    "tutor_effectiveness_smoke",
    "debate_multi_agent_smoke",
    "mcp_client_smoke",
    "agent_job_smoke",
    "agent_runtime_contract_smoke",
    "agent_runtime_migration_smoke",
    "agent_runtime_checkpoint_smoke",
    "agent_runtime_concurrency_smoke",
    "agent_runtime_recovery_smoke",
    "agent_runtime_lifecycle_smoke",
    "agent_runtime_idempotency_smoke",
    "history_character_runtime_smoke",
    "essay_grader_runtime_smoke",
    "agent_runtime_stream_parity_smoke",
    "agent_runtime_security_smoke",
    "agent_runtime_confirmation_smoke",
    "agent_runtime_adapter_smoke",
    "agent_runtime_product_routes_smoke",
    "agent_runtime_autotutor_resume_smoke",
    "agent_runtime_essay_resume_smoke",
    "agent_runtime_schema_readiness_smoke",
    "agent_runtime_rollout_gate_smoke",
    "agent_runtime_latency_baseline_smoke",
    "rollout_evidence_supply_chain_smoke",
    "runtime_evidence_workflow_smoke",
    "production_auth_trusted_rollout_smoke",
    "agent_runtime_non_tool_policy_smoke",
    "agent_runtime_learning_assistant_api_smoke",
]
QUICK_SUITES = [
    "eval_run_evidence_smoke",
    "alembic_transaction_boundary_smoke",
    "backend_startup_migration_smoke",
    "backend_startup_migration_failure_smoke",
    "answer_groundedness_eval",
    "history_query_eval",
    "history_retrieval_contract_smoke",
    "history_retrieval_review_smoke",
    "history_no_answer_eval",
    "history_answer_grounding_eval",
    # Offline-first: these run without LLM/embed and always produce metrics
    "agent_ops_smoke",
    "agent_ops_scope_smoke",
    "readiness_smoke",
    "autotutor_session_recovery_smoke",
    "learning_assistant_multiturn_smoke",
    "autotutor_question_handoff_smoke",
    "autotutor_handoff_public_contract_smoke",
    "release_gate_smoke",
    "tool_registry_smoke",
    "guardrails_smoke",
    "agent_safety_eval",
    "weakpoints_smoke",
    "learning_closure_smoke",
    "adaptive_review_question_quality_eval",
    "review_mastery_evidence_eval",
    "review_retention_scheduler_smoke",
    "review_mastery_migration_smoke",
    "trajectory_eval",
    "auto_tutor_trajectory_eval",
    "autotutor_teaching_quality_eval",
    "autotutor_objective_alignment_eval",
    "autotutor_assessment_validity_eval",
    "autotutor_false_mastery_smoke",
    "autotutor_content_blocked_api_smoke",
    "autotutor_exit_ticket_independence_eval",
    "autotutor_adaptive_difficulty_eval",
    "autotutor_transition_idempotency_smoke",
    "autotutor_finalize_fault_injection_smoke",
    "tutor_effectiveness_smoke",
    "debate_multi_agent_smoke",
    "rag_groundedness_eval",
    "mcp_client_smoke",
    "agent_job_smoke",
    "agent_runtime_contract_smoke",
    "agent_runtime_migration_smoke",
    "agent_runtime_checkpoint_smoke",
    "agent_runtime_concurrency_smoke",
    "agent_runtime_recovery_smoke",
    "agent_runtime_lifecycle_smoke",
    "agent_runtime_idempotency_smoke",
    "history_character_runtime_smoke",
    "essay_grader_runtime_smoke",
    "agent_runtime_stream_parity_smoke",
    "agent_runtime_security_smoke",
    "agent_runtime_confirmation_smoke",
    "agent_runtime_adapter_smoke",
    "agent_runtime_product_routes_smoke",
    "agent_runtime_autotutor_resume_smoke",
    "agent_runtime_essay_resume_smoke",
    "agent_runtime_schema_readiness_smoke",
    "agent_runtime_rollout_gate_smoke",
    "agent_runtime_latency_baseline_smoke",
    "rollout_evidence_supply_chain_smoke",
    "runtime_evidence_workflow_smoke",
    "production_auth_trusted_rollout_smoke",
    "agent_runtime_non_tool_policy_smoke",
    "agent_runtime_learning_assistant_api_smoke",
    # LLM/embed-dependent (skipped gracefully when credentials absent)
    "history_character_smoke",
    "rag_inspector_smoke",
    "rag_retrieval_eval",
    "textbook_trace_smoke",
    "material_rag_smoke",
    "learning_assistant_smoke",
    "learning_assistant_rollout_smoke",
]
SMOKE_SUITES = [
    "eval_run_evidence_smoke",
    "alembic_transaction_boundary_smoke",
    "backend_startup_migration_smoke",
    "backend_startup_migration_failure_smoke",
    "answer_groundedness_eval",
    "history_query_eval",
    "history_retrieval_contract_smoke",
    "history_retrieval_review_smoke",
    "history_no_answer_eval",
    "history_answer_grounding_eval",
    "agent_ops_smoke",
    "agent_ops_scope_smoke",
    "autotutor_session_recovery_smoke",
    "history_character_smoke",
    "learning_assistant_smoke",
    "learning_assistant_rollout_smoke",
    "material_rag_smoke",
    "rag_inspector_smoke",
    "release_gate_smoke",
    "student_profile_smoke",
    "textbook_trace_smoke",
    "homework_grading_smoke",
    "weakpoints_smoke",
    "knowledge_graph_smoke",
    "learning_closure_smoke",
    "teacher_features_smoke",
    "review_system_smoke",
    "adaptive_review_question_quality_eval",
    "review_mastery_evidence_eval",
    "review_retention_scheduler_smoke",
    "review_mastery_migration_smoke",
    "assignment_smoke",
    "assignment_review_loop_smoke",
    "question_quality_smoke",
    "notification_badges_smoke",
    "quality_dashboard_smoke",
    "pilot_path_smoke",
    "today_plan_smoke",
    "completion_overview_smoke",
    "tool_registry_smoke",
    "guardrails_smoke",
    "agent_safety_eval",
    "trace_smoke",
    "readiness_smoke",
    "variant_question_smoke",
    "lecture_review_smoke",
    "mastery_heatmap_smoke",
    "difficulty_smoke",
    "calendar_smoke",
    "urge_notification_smoke",
    "tiered_assignment_smoke",
    "class_wrong_analysis_smoke",
    "tutor_effectiveness_smoke",
    "check_in_smoke",
    "preference_smoke",
    "root_cause_smoke",
    "class_matrix_smoke",
    "debate_multi_agent_smoke",
    "rag_groundedness_eval",
    "mcp_client_smoke",
    "agent_job_smoke",
    "agent_runtime_contract_smoke",
    "agent_runtime_migration_smoke",
    "agent_runtime_checkpoint_smoke",
    "agent_runtime_concurrency_smoke",
    "agent_runtime_recovery_smoke",
    "agent_runtime_lifecycle_smoke",
    "agent_runtime_idempotency_smoke",
    "history_character_runtime_smoke",
    "essay_grader_runtime_smoke",
    "agent_runtime_stream_parity_smoke",
    "agent_runtime_security_smoke",
    "agent_runtime_confirmation_smoke",
    "agent_runtime_adapter_smoke",
    "agent_runtime_product_routes_smoke",
    "agent_runtime_autotutor_resume_smoke",
    "agent_runtime_essay_resume_smoke",
    "agent_runtime_schema_readiness_smoke",
    "agent_runtime_rollout_gate_smoke",
    "agent_runtime_latency_baseline_smoke",
    "rollout_evidence_supply_chain_smoke",
    "runtime_evidence_workflow_smoke",
    "production_auth_trusted_rollout_smoke",
    "agent_runtime_learning_assistant_api_smoke",
]
SUITE_FILES = {
    "eval_run_evidence_smoke": EVAL_DIR / "eval_run_evidence_smoke.py",
    "alembic_transaction_boundary_smoke": EVAL_DIR / "alembic_transaction_boundary_smoke.py",
    "backend_startup_migration_smoke": EVAL_DIR / "backend_startup_migration_smoke.py",
    "backend_startup_migration_failure_smoke": EVAL_DIR / "backend_startup_migration_failure_smoke.py",
    "answer_groundedness_eval": EVAL_DIR / "answer_groundedness_eval.py",
    "history_query_eval": EVAL_DIR / "history_query_eval.py",
    "history_retrieval_contract_smoke": EVAL_DIR / "history_retrieval_contract_smoke.py",
    "history_retrieval_review_smoke": EVAL_DIR / "history_retrieval_review_smoke.py",
    "history_no_answer_eval": EVAL_DIR / "history_no_answer_eval.py",
    "history_answer_grounding_eval": EVAL_DIR / "history_answer_grounding_eval.py",
    "history_retrieval_quality_eval": EVAL_DIR / "history_retrieval_quality_eval.py",
    "agent_ops_smoke": EVAL_DIR / "agent_ops_smoke.py",
    "agent_ops_scope_smoke": EVAL_DIR / "agent_ops_scope_smoke.py",
    "autotutor_session_recovery_smoke": EVAL_DIR / "autotutor_session_recovery_smoke.py",
    "learning_assistant_multiturn_smoke": EVAL_DIR / "learning_assistant_multiturn_smoke.py",
    "autotutor_question_handoff_smoke": EVAL_DIR / "autotutor_question_handoff_smoke.py",
    "history_character_smoke": EVAL_DIR / "history_character_smoke.py",
    "history_character_eval": EVAL_DIR / "history_character_eval.py",
    "rag_retrieval_eval": EVAL_DIR / "rag_retrieval_eval.py",
    "rag_groundedness_eval": EVAL_DIR / "rag_groundedness_eval.py",
    "rag_inspector_smoke": EVAL_DIR / "rag_inspector_smoke.py",
    "release_gate_smoke": EVAL_DIR / "release_gate_smoke.py",
    "textbook_qa_eval": EVAL_DIR / "textbook_qa_eval.py",
    "textbook_trace_smoke": EVAL_DIR / "textbook_trace_smoke.py",
    "game_generation_eval": EVAL_DIR / "game_generation_eval.py",
    "learning_assistant_smoke": EVAL_DIR / "learning_assistant_smoke.py",
    "learning_assistant_rollout_smoke": EVAL_DIR / "learning_assistant_rollout_smoke.py",
    "learning_assistant_blind_eval": EVAL_DIR / "learning_assistant_blind_eval.py",
    "learning_assistant_semantic_router_eval": EVAL_DIR / "learning_assistant_semantic_router_eval.py",
    "learning_assistant_external_ood_eval": EVAL_DIR / "learning_assistant_external_ood_eval.py",
    "intent_accuracy_eval": EVAL_DIR / "intent_accuracy_eval.py",
    "material_rag_smoke": EVAL_DIR / "material_rag_smoke.py",
    "student_profile_smoke": EVAL_DIR / "student_profile_smoke.py",
    "homework_grading_smoke": EVAL_DIR / "homework_grading_smoke.py",
    "weakpoints_smoke": EVAL_DIR / "weakpoints_smoke.py",
    "learning_closure_smoke": EVAL_DIR / "learning_closure_smoke.py",
    "teacher_features_smoke": EVAL_DIR / "teacher_features_smoke.py",
    "review_system_smoke": EVAL_DIR / "review_system_smoke.py",
    "adaptive_review_question_quality_eval": EVAL_DIR / "adaptive_review_question_quality_eval.py",
    "review_mastery_evidence_eval": EVAL_DIR / "review_mastery_evidence_eval.py",
    "review_retention_scheduler_smoke": EVAL_DIR / "review_retention_scheduler_smoke.py",
    "review_mastery_migration_smoke": EVAL_DIR / "review_mastery_migration_smoke.py",
    "assignment_smoke": EVAL_DIR / "assignment_smoke.py",
    "assignment_review_loop_smoke": EVAL_DIR / "assignment_review_loop_smoke.py",
    "question_quality_smoke": EVAL_DIR / "question_quality_smoke.py",
    "notification_badges_smoke": EVAL_DIR / "notification_badges_smoke.py",
    "quality_dashboard_smoke": EVAL_DIR / "quality_dashboard_smoke.py",
    "pilot_path_smoke": EVAL_DIR / "pilot_path_smoke.py",
    "today_plan_smoke": EVAL_DIR / "today_plan_smoke.py",
    "completion_overview_smoke": EVAL_DIR / "completion_overview_smoke.py",
    "tool_registry_smoke": EVAL_DIR / "tool_registry_smoke.py",
    "guardrails_smoke": EVAL_DIR / "guardrails_smoke.py",
    "agent_safety_eval": EVAL_DIR / "agent_safety_eval.py",
    "ragas_eval": EVAL_DIR / "ragas_eval.py",
    "trace_smoke": EVAL_DIR / "trace_smoke.py",
    "readiness_smoke": EVAL_DIR / "readiness_smoke.py",
    "trajectory_eval": EVAL_DIR / "trajectory_eval.py",
    "auto_tutor_trajectory_eval": EVAL_DIR / "auto_tutor_trajectory_eval.py",
    "autotutor_teaching_quality_eval": EVAL_DIR / "autotutor_teaching_quality_eval.py",
    "autotutor_objective_alignment_eval": EVAL_DIR / "autotutor_objective_alignment_eval.py",
    "autotutor_assessment_validity_eval": EVAL_DIR / "autotutor_assessment_validity_eval.py",
    "autotutor_false_mastery_smoke": EVAL_DIR / "autotutor_false_mastery_smoke.py",
    "autotutor_content_blocked_api_smoke": EVAL_DIR / "autotutor_content_blocked_api_smoke.py",
    "autotutor_exit_ticket_independence_eval": EVAL_DIR / "autotutor_exit_ticket_independence_eval.py",
    "autotutor_adaptive_difficulty_eval": EVAL_DIR / "autotutor_adaptive_difficulty_eval.py",
    "autotutor_handoff_public_contract_smoke": EVAL_DIR / "autotutor_handoff_public_contract_smoke.py",
    "autotutor_transition_idempotency_smoke": EVAL_DIR / "autotutor_transition_idempotency_smoke.py",
    "autotutor_finalize_fault_injection_smoke": EVAL_DIR / "autotutor_finalize_fault_injection_smoke.py",
    "debate_multi_agent_smoke": EVAL_DIR / "debate_multi_agent_smoke.py",
    "mcp_client_smoke": EVAL_DIR / "mcp_client_smoke.py",
    "agent_job_smoke": EVAL_DIR / "agent_job_smoke.py",
    "agent_runtime_contract_smoke": EVAL_DIR / "agent_runtime_contract_smoke.py",
    "agent_runtime_migration_smoke": EVAL_DIR / "agent_runtime_migration_smoke.py",
    "agent_runtime_checkpoint_smoke": EVAL_DIR / "agent_runtime_checkpoint_smoke.py",
    "agent_runtime_concurrency_smoke": EVAL_DIR / "agent_runtime_concurrency_smoke.py",
    "agent_runtime_recovery_smoke": EVAL_DIR / "agent_runtime_recovery_smoke.py",
    "agent_runtime_lifecycle_smoke": EVAL_DIR / "agent_runtime_lifecycle_smoke.py",
    "agent_runtime_idempotency_smoke": EVAL_DIR / "agent_runtime_idempotency_smoke.py",
    "history_character_runtime_smoke": EVAL_DIR / "history_character_runtime_smoke.py",
    "essay_grader_runtime_smoke": EVAL_DIR / "essay_grader_runtime_smoke.py",
    "agent_runtime_stream_parity_smoke": EVAL_DIR / "agent_runtime_stream_parity_smoke.py",
    "agent_runtime_security_smoke": EVAL_DIR / "agent_runtime_security_smoke.py",
    "agent_runtime_confirmation_smoke": EVAL_DIR / "agent_runtime_confirmation_smoke.py",
    "agent_runtime_adapter_smoke": EVAL_DIR / "agent_runtime_adapter_smoke.py",
    "agent_runtime_product_routes_smoke": EVAL_DIR / "agent_runtime_product_routes_smoke.py",
    "agent_runtime_autotutor_resume_smoke": EVAL_DIR / "agent_runtime_autotutor_resume_smoke.py",
    "agent_runtime_essay_resume_smoke": EVAL_DIR / "agent_runtime_essay_resume_smoke.py",
    "agent_runtime_schema_readiness_smoke": EVAL_DIR / "agent_runtime_schema_readiness_smoke.py",
    "agent_runtime_rollout_gate_smoke": EVAL_DIR / "agent_runtime_rollout_gate_smoke.py",
    "agent_runtime_latency_baseline_smoke": EVAL_DIR / "agent_runtime_latency_baseline_smoke.py",
    "rollout_evidence_supply_chain_smoke": EVAL_DIR / "rollout_evidence_supply_chain_smoke.py",
    "runtime_evidence_workflow_smoke": EVAL_DIR / "runtime_evidence_workflow_smoke.py",
    "production_auth_trusted_rollout_smoke": EVAL_DIR / "production_auth_trusted_rollout_smoke.py",
    "agent_runtime_non_tool_policy_smoke": EVAL_DIR / "agent_runtime_non_tool_policy_smoke.py",
    "agent_runtime_learning_assistant_api_smoke": EVAL_DIR / "agent_runtime_learning_assistant_api_smoke.py",
    "production_rag_health_smoke": EVAL_DIR / "production_rag_health_smoke.py",
    "variant_question_smoke": EVAL_DIR / "variant_question_smoke.py",
    "lecture_review_smoke": EVAL_DIR / "lecture_review_smoke.py",
    "mastery_heatmap_smoke": EVAL_DIR / "mastery_heatmap_smoke.py",
    "difficulty_smoke": EVAL_DIR / "difficulty_smoke.py",
    "calendar_smoke": EVAL_DIR / "calendar_smoke.py",
    "urge_notification_smoke": EVAL_DIR / "urge_notification_smoke.py",
    "tiered_assignment_smoke": EVAL_DIR / "tiered_assignment_smoke.py",
    "class_wrong_analysis_smoke": EVAL_DIR / "class_wrong_analysis_smoke.py",
    "tutor_effectiveness_smoke": EVAL_DIR / "tutor_effectiveness_smoke.py",
    "check_in_smoke": EVAL_DIR / "check_in_smoke.py",
    "preference_smoke": EVAL_DIR / "preference_smoke.py",
    "root_cause_smoke": EVAL_DIR / "root_cause_smoke.py",
    "class_matrix_smoke": EVAL_DIR / "class_matrix_smoke.py",
    "knowledge_graph_smoke": EVAL_DIR / "knowledge_graph_smoke.py",
}

# ── 自动补全：glob 发现磁盘上存在但未手动注册的 *_smoke.py / *_eval.py ────────
# 新增 smoke 测试时只需创建文件，无需修改本列表。
# 手动注册的条目优先（超时/元数据配置仍需手动添加）。
for _p in sorted(EVAL_DIR.glob("*_smoke.py")) + sorted(EVAL_DIR.glob("*_eval.py")):
    _key = _p.stem
    if _key not in SUITE_FILES:
        SUITE_FILES[_key] = _p
        # 新发现的 suite 默认追加到 SMOKE_SUITES（不进 CORE_SUITES/QUICK_SUITES，保持稳定）。
        # 需要专用基础设施的集成套件只由对应 CI job 显式运行。
        if _key not in SMOKE_SUITES and _key not in DEDICATED_INTEGRATION_SUITES:
            SMOKE_SUITES.append(_key)

SUITE_METADATA: dict[str, dict[str, str]] = {
    "eval_run_evidence_smoke": {
        "label": "Eval Run 证据与封印 Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p0",
    },
    "answer_groundedness_eval": {
        "label": "回答证据化完成评测",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "history_query_eval": {
        "label": "历史查询实体与维度评测",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "history_retrieval_contract_smoke": {
        "label": "历史 RRF 与证据充分性 Smoke",
        "category": "rag",
        "kind": "smoke",
        "priority": "p0",
    },
    "history_retrieval_review_smoke": {
        "label": "历史检索人工相关性复核契约 Smoke",
        "category": "rag",
        "kind": "smoke",
        "priority": "p0",
    },
    "history_no_answer_eval": {
        "label": "历史问答无依据拒答评测",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "history_answer_grounding_eval": {
        "label": "历史问答证据门控评测",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "history_retrieval_quality_eval": {
        "label": "历史检索真实依赖质量评测",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "agent_ops_smoke": {
        "label": "AgentOps 聚合 Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p1",
    },
    "agent_ops_scope_smoke": {
        "label": "AgentOps 数据分域 Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p0",
    },
    "autotutor_session_recovery_smoke": {
        "label": "AutoTutor 会话恢复 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p1",
    },
    "learning_assistant_multiturn_smoke": {
        "label": "随问多轮会话 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "autotutor_question_handoff_smoke": {
        "label": "AutoTutor 随问协同 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "history_character_smoke": {
        "label": "历史人物 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "history_character_eval": {
        "label": "历史人物对话质量",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "rag_retrieval_eval": {
        "label": "历史 RAG 检索质量",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "intent_accuracy_eval": {
        "label": "意图识别准确率",
        "category": "agent",
        "kind": "quality",
        "priority": "p1",
    },
    "rag_inspector_smoke": {
        "label": "RAG Inspector Smoke",
        "category": "rag",
        "kind": "smoke",
        "priority": "p1",
    },
    "release_gate_smoke": {
        "label": "Release Gate Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p1",
    },
    "textbook_qa_eval": {
        "label": "教材问答质量",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
    "textbook_trace_smoke": {
        "label": "教材问答 Trace Smoke",
        "category": "rag",
        "kind": "smoke",
        "priority": "p1",
    },
    "game_generation_eval": {
        "label": "历史游戏生成",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "learning_assistant_smoke": {
        "label": "学习助手工具 Smoke",
        "category": "tools",
        "kind": "smoke",
        "priority": "p0",
    },
    "learning_assistant_rollout_smoke": {
        "label": "学习助手稳定灰度 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "learning_assistant_blind_eval": {
        "label": "学习助手私有盲测",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "learning_assistant_semantic_router_eval": {
        "label": "学习助手真实语义路由评测",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "learning_assistant_external_ood_eval": {
        "label": "学习助手外部真实学生 OOD 评测",
        "category": "agent",
        "kind": "quality",
        "priority": "p1",
    },
    "material_rag_smoke": {
        "label": "材料 RAG Smoke",
        "category": "rag",
        "kind": "smoke",
        "priority": "p0",
    },
    "student_profile_smoke": {
        "label": "学生画像 Smoke",
        "category": "memory",
        "kind": "smoke",
        "priority": "p0",
    },
    "homework_grading_smoke": {
        "label": "作业批改 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "weakpoints_smoke": {
        "label": "错题本 Smoke",
        "category": "memory",
        "kind": "smoke",
        "priority": "p0",
    },
    "learning_closure_smoke": {
        "label": "学习闭环 Smoke",
        "category": "memory",
        "kind": "smoke",
        "priority": "p0",
    },
    "teacher_features_smoke": {
        "label": "教师功能 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p0",
    },
    "review_system_smoke": {
        "label": "复习系统 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p0",
    },
    "adaptive_review_question_quality_eval": {
        "label": "自适应复习题内容质量评测",
        "category": "student",
        "kind": "quality",
        "priority": "p0",
    },
    "review_mastery_evidence_eval": {
        "label": "复习独立掌握证据评测",
        "category": "student",
        "kind": "quality",
        "priority": "p0",
    },
    "review_retention_scheduler_smoke": {
        "label": "复习保持题调度 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p0",
    },
    "review_mastery_migration_smoke": {
        "label": "复习掌握证据迁移 Smoke",
        "category": "runtime",
        "kind": "smoke",
        "priority": "p0",
    },
    "assignment_smoke": {
        "label": "布置作业工作流 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p0",
    },
    "assignment_review_loop_smoke": {
        "label": "作业错题-复习-辅导闭环 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p0",
    },
    "question_quality_smoke": {
        "label": "AI 出题结构质检 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "notification_badges_smoke": {
        "label": "通知徽标聚合 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "quality_dashboard_smoke": {
        "label": "命题质量看板 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "pilot_path_smoke": {
        "label": "Pilot 演示路径 Smoke",
        "category": "pilot",
        "kind": "smoke",
        "priority": "p0",
    },
    "today_plan_smoke": {
        "label": "学生今日计划 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "completion_overview_smoke": {
        "label": "班级完成情况 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "variant_question_smoke": {
        "label": "错题变式生成 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "lecture_review_smoke": {
        "label": "讲评课 AI 辅助 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "mastery_heatmap_smoke": {
        "label": "掌握度热力图 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "difficulty_smoke": {
        "label": "出题难度维度 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "calendar_smoke": {
        "label": "学习日历 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "urge_notification_smoke": {
        "label": "催办通知 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "tiered_assignment_smoke": {
        "label": "分层作业 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "class_wrong_analysis_smoke": {
        "label": "班级错题聚合 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "tutor_effectiveness_smoke": {
        "label": "AI辅导效果追踪 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p0",
    },
    "check_in_smoke": {
        "label": "每日签卡挑战 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "preference_smoke": {
        "label": "学习偏好配置 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "root_cause_smoke": {
        "label": "薄弱点根因诊断 Smoke",
        "category": "student",
        "kind": "smoke",
        "priority": "p1",
    },
    "class_matrix_smoke": {
        "label": "班级知识矩阵 Smoke",
        "category": "teacher",
        "kind": "smoke",
        "priority": "p1",
    },
    "tool_registry_smoke": {
        "label": "工具注册与治理 Smoke",
        "category": "tools",
        "kind": "smoke",
        "priority": "p1",
    },
    "mcp_client_smoke": {
        "label": "MCP Client 发现与调用 Smoke",
        "category": "tools",
        "kind": "smoke",
        "priority": "p1",
    },
    "agent_job_smoke": {
        "label": "Durable Agent Job Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p1",
    },
    "guardrails_smoke": {
        "label": "Guardrails Smoke",
        "category": "safety",
        "kind": "smoke",
        "priority": "p3",
    },
    "trace_smoke": {
        "label": "Agent Runtime Trace Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p1",
    },
    "readiness_smoke": {
        "label": "Readiness / Eval 路由 Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p0",
    },
    "backend_startup_migration_smoke": {
        "label": "Backend 启动迁移 Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p0",
    },
    "alembic_transaction_boundary_smoke": {
        "label": "Alembic 迁移事务边界 Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p0",
    },
    "backend_startup_migration_failure_smoke": {
        "label": "Backend 迁移失败拒绝启动 Smoke",
        "category": "ops",
        "kind": "smoke",
        "priority": "p0",
    },
    "agent_runtime_rollout_gate_smoke": {
        "label": "Agent Runtime 灰度门禁 Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p0",
    },
    "agent_runtime_latency_baseline_smoke": {
        "label": "Agent Runtime 延迟基线 Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p0",
    },
    "rollout_evidence_supply_chain_smoke": {
        "label": "Agent Runtime 发布证据供应链 Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p0",
    },
    "runtime_evidence_workflow_smoke": {
        "label": "Runtime 发布证据工作流 Smoke",
        "category": "observability",
        "kind": "smoke",
        "priority": "p0",
    },
    "production_auth_trusted_rollout_smoke": {
        "label": "生产认证与可信灰度 Smoke",
        "category": "security",
        "kind": "smoke",
        "priority": "p0",
    },
    "knowledge_graph_smoke": {
        "label": "知识图谱前置依赖 Smoke",
        "category": "learning",
        "kind": "smoke",
        "priority": "p1",
    },
    "trajectory_eval": {
        "label": "工具调用轨迹准确率",
        "category": "tools",
        "kind": "quality",
        "priority": "p0",
    },
    "auto_tutor_trajectory_eval": {
        "label": "AutoTutor 自主辅导轨迹",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "autotutor_teaching_quality_eval": {
        "label": "AutoTutor 教学内容质量",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "autotutor_objective_alignment_eval": {
        "label": "AutoTutor 目标与内容一致性",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "autotutor_assessment_validity_eval": {
        "label": "AutoTutor 题目有效性",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "autotutor_false_mastery_smoke": {
        "label": "AutoTutor False Mastery Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "autotutor_content_blocked_api_smoke": {
        "label": "AutoTutor Content Blocked API Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "autotutor_exit_ticket_independence_eval": {
        "label": "AutoTutor 退出票独立性",
        "category": "agent",
        "kind": "quality",
        "priority": "p0",
    },
    "debate_multi_agent_smoke": {
        "label": "历史辩论多 Agent 轨迹 Smoke",
        "category": "agent",
        "kind": "smoke",
        "priority": "p0",
    },
    "agent_safety_eval": {
        "label": "Agent RAG / Tool Safety Eval",
        "category": "safety",
        "kind": "quality",
        "priority": "p0",
    },
    "ragas_eval": {
        "label": "Ragas 语义质量",
        "category": "rag",
        "kind": "quality",
        "priority": "p1",
    },
    "production_rag_health_smoke": {
        "label": "生产 RAG 健康检查 Smoke",
        "category": "rag",
        "kind": "production_smoke",
        "priority": "p0",
    },
    "rag_groundedness_eval": {
        "label": "RAG 引用 Groundedness",
        "category": "rag",
        "kind": "quality",
        "priority": "p0",
    },
}
METRIC_RE = re.compile(r"^([a-zA-Z0-9_]+)=(\d+)/(\d+)$")
FLOAT_METRIC_RE = re.compile(r"^([a-zA-Z0-9_]+)=(\d+(?:\.\d+)?)$")
FAILED_CASES_RE = re.compile(r"failed cases:\s*(.+)", re.IGNORECASE)
FAILED_CASE_DETAIL_PREFIX = "FAILED_CASE_DETAIL="
FAILED_CASES_JSON_PREFIX = "FAILED_CASES_JSON="
FailedCase: TypeAlias = dict[str, Any]


def normalize_failed_case(value: Any) -> FailedCase:
    if isinstance(value, dict):
        name = value.get("name") or value.get("case") or value.get("id") or "unknown_case"
        payload = {k: v for k, v in value.items() if v is not None and k not in {"name", "case", "id"}}
        return {"name": str(name), **payload}
    return {"name": str(value)}


def failed_case_label(value: Any) -> str:
    item = normalize_failed_case(value)
    label = str(item.get("name") or "unknown_case")
    reason = item.get("reason")
    return f"{label} ({reason})" if reason else label


def llm_judge_answer(case: dict, answer: str) -> dict:
    """Use LLM-as-a-judge to evaluate answer quality."""
    try:
        sys.path.insert(0, str(BACKEND))
        from llm_config import llm_fast
        from structured_output import invoke_structured

        must_contain = case.get("expected_response_keywords", [])
        must_not_contain = case.get("must_not_contain", [])
        character = case.get("character", "")
        question = case.get("message", "")

        prompt = (
            f"你是历史教学质量评审员。请对以下历史人物模拟回答打分（1-5分），输出JSON。\n"
            f"字段：factual_accuracy（事实准确性）、educational_value（教学价值）、"
            f"hallucination_risk（幻觉风险，1=低风险，5=高风险）、comment（一句话评语）\n\n"
            f"人物：{character}\n问题：{question}\n"
            f"必须包含关键词：{must_contain}\n"
            f"不得出现关键词：{must_not_contain}\n\n"
            f"回答：\n{answer[:800]}"
        )
        result = invoke_structured(
            llm_fast,
            [{"role": "user", "content": prompt}],
            fallback={"factual_accuracy": 0, "educational_value": 0, "hallucination_risk": 5, "comment": "评审失败"},
        )
        return result
    except Exception:
        return {"factual_accuracy": 0, "educational_value": 0, "hallucination_risk": 5, "comment": "评审失败"}


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:[a-z0-9_.-]*)(?:api[_-]?key|auth[_-]?token|access[_-]?token|password|client[_-]?secret))"
    r"(\s*[:=]\s*)([^\s,;\"']+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}")
_KEY_PREFIX_RE = re.compile(r"\b(?:sk|sk-ant|dashscope)-[A-Za-z0-9_-]{8,}\b")
_PRIVATE_PROMPT_RE = re.compile(r"(?im)\b(?:private|blind)[_-]?prompt\s*[:=].*$")


def redact_sensitive_report_text(value: str) -> str:
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", str(value or ""))
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", redacted)
    redacted = _KEY_PREFIX_RE.sub("[REDACTED_API_KEY]", redacted)
    return _PRIVATE_PROMPT_RE.sub("PRIVATE_PROMPT=[REDACTED]", redacted)


def sanitize_report_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_report_text(value)
    if isinstance(value, list):
        return [sanitize_report_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_report_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_report_value(item) for key, item in value.items()}
    return value


@dataclass
class SuiteResult:
    name: str
    command: list[str]
    returncode: int
    duration_sec: float
    stdout: str
    stderr: str
    passed_cases: int
    failed_cases_count: int
    total_cases: int
    metrics: dict[str, dict[str, int | float]]
    failed_cases: list[FailedCase]
    skipped_cases_count: int = 0
    skipped_cases: list[str] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.failed_cases_count == 0

    @property
    def status(self) -> str:
        if self.returncode == 0 and self.skipped_cases_count and not self.passed_cases and not self.failed_cases_count:
            return "skipped"
        return "passed" if self.ok else "failed"

    def to_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        metadata = suite_metadata(self.name)
        private_eval = self.name == "learning_assistant_blind_eval"
        failed_cases = (
            [{"name": str(normalize_failed_case(item).get("name") or "private_eval_failure"), "reason": "private_eval_aggregate_only"} for item in self.failed_cases]
            if private_eval
            else sanitize_report_value(self.failed_cases)
        )
        payload: dict[str, Any] = {
            "name": self.name,
            "label": metadata["label"],
            "category": metadata["category"],
            "kind": metadata["kind"],
            "priority": metadata["priority"],
            "status": self.status,
            "ok": self.ok,
            "returncode": self.returncode,
            "duration_sec": round(self.duration_sec, 3),
            "command": " ".join(self.command),
            "passed_cases": self.passed_cases,
            "failed_cases_count": self.failed_cases_count,
            "skipped_cases_count": self.skipped_cases_count,
            "total_cases": self.total_cases,
            "metrics": self.metrics,
            "failed_cases": failed_cases,
            "skipped_cases": sanitize_report_value(self.skipped_cases or []),
        }
        if self.error:
            payload["error"] = "private_eval_failure" if private_eval else redact_sensitive_report_text(self.error)
        if include_output:
            if private_eval:
                payload["stdout"] = "[REDACTED_PRIVATE_EVAL_OUTPUT]"
                payload["stderr"] = "[REDACTED_PRIVATE_EVAL_OUTPUT]" if self.stderr else ""
            else:
                payload["stdout"] = redact_sensitive_report_text(self.stdout)
                payload["stderr"] = redact_sensitive_report_text(self.stderr)
        return payload


def suite_metadata(name: str) -> dict[str, str]:
    return {
        "id": name,
        "label": name.replace("_", " "),
        "category": "other",
        "kind": "eval",
        "priority": "p0",
        **SUITE_METADATA.get(name, {}),
    }


def list_suite_metadata() -> list[dict[str, str]]:
    return [suite_metadata(name) for name in SUITE_FILES]


def parse_output(stdout: str, stderr: str) -> tuple[int, int, int, dict[str, dict[str, int | float]], list[FailedCase], int, list[str]]:
    passed = 0
    failed = 0
    skipped = 0
    metrics: dict[str, dict[str, int | float]] = {}
    failed_cases: list[FailedCase] = []
    plain_failed_cases: list[FailedCase] = []
    skipped_cases: list[str] = []

    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("OK "):
            passed += 1
        elif stripped.startswith("FAIL "):
            failed += 1
            label, separator, reason = stripped.removeprefix("FAIL ").partition(":")
            plain_failed_cases.append({
                "name": label.strip() or "unnamed_failure",
                "reason": reason.strip() if separator else "case failed",
            })
        elif stripped.startswith("SKIP "):
            skipped += 1
            skipped_cases.append(stripped.removeprefix("SKIP ").strip())

        metric_match = METRIC_RE.match(stripped)
        if metric_match:
            name, count, total = metric_match.groups()
            metrics[name] = {"passed": int(count), "total": int(total)}
            continue

        float_metric_match = FLOAT_METRIC_RE.match(stripped)
        if float_metric_match:
            name, value = float_metric_match.groups()
            metrics[name] = {"value": float(value)}

        if stripped.startswith(FAILED_CASE_DETAIL_PREFIX):
            try:
                failed_cases.append(normalize_failed_case(json.loads(stripped.removeprefix(FAILED_CASE_DETAIL_PREFIX))))
            except Exception:
                failed_cases.append({"name": "malformed_failed_case_detail", "reason": stripped})
        elif stripped.startswith(FAILED_CASES_JSON_PREFIX):
            try:
                detail = json.loads(stripped.removeprefix(FAILED_CASES_JSON_PREFIX))
                if isinstance(detail, list):
                    failed_cases.extend(normalize_failed_case(item) for item in detail)
                else:
                    failed_cases.append(normalize_failed_case(detail))
            except Exception:
                failed_cases.append({"name": "malformed_failed_cases_json", "reason": stripped})

    combined = "\n".join([stdout, stderr])
    failed_match = FAILED_CASES_RE.search(combined)
    if failed_match and not failed_cases:
        failed_cases = [normalize_failed_case(item.strip()) for item in failed_match.group(1).split(",") if item.strip()]
    if plain_failed_cases and not failed_cases:
        failed_cases = plain_failed_cases

    total = passed + failed + skipped
    if total == 0 and metrics:
        count_metrics = [item for item in metrics.values() if "total" in item and "passed" in item]
        totals = [int(item["total"]) for item in count_metrics]
        total = max(totals) if totals else 0
        passed = min((int(item["passed"]) for item in count_metrics), default=0)
        failed = max(total - passed, 0)

    return passed, failed, total, metrics, failed_cases, skipped, skipped_cases


def run_suite(name: str, *, verbose: bool = False, eval_run_id: str | None = None) -> SuiteResult:
    script = SUITE_FILES[name]
    env = os.environ.copy()
    if not env.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
        env["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)
    pythonpath_parts = [str(BACKEND)]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env["EDU_AGENT_DATA_SCOPE"] = "eval"
    if eval_run_id:
        env["EDU_AGENT_EVAL_RUN_ID"] = eval_run_id
    if name in OFFLINE_DETERMINISTIC_SUITES:
        env["EDU_AGENT_LLM_DISABLED"] = "1"
        # Keep routing/trajectory checks isolated from a developer's remote
        # Postgres connection; each suite already provisions its own SQLite DB.
        env.pop("DATABASE_URL", None)
    if name == "history_character_eval":
        # CORE runs one deterministic case per character (9 total). Set this
        # variable explicitly to 0 for the extended 45-case quality sweep.
        env.setdefault("HISTORY_CHARACTER_EVAL_LIMIT", "9")

    command = [sys.executable, str(script)]
    started = time.monotonic()
    configured_timeout = os.getenv("EVAL_SUITE_TIMEOUT_SECONDS")
    timeout_seconds = max(
        1,
        int(configured_timeout) if configured_timeout else SUITE_TIMEOUT_SECONDS.get(name, DEFAULT_SUITE_TIMEOUT_SECONDS),
    )
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        combined_output = f"{stdout}\n{stderr}".lower()
        if any(marker in combined_output for marker in EXTERNAL_QUOTA_ERROR_MARKERS):
            reason = (
                "external model quota exhausted; "
                f"suite timed out after {timeout_seconds}s while waiting for a usable model"
            )
            failure_name = "external_model_quota_exhausted"
        else:
            reason = f"suite timed out after {timeout_seconds}s"
            failure_name = "suite_timeout"
        return SuiteResult(
            name=name,
            command=command,
            returncode=124,
            duration_sec=duration,
            stdout=stdout,
            stderr=stderr,
            passed_cases=0,
            failed_cases_count=1,
            total_cases=1,
            metrics={},
            failed_cases=[{"name": failure_name, "reason": reason}],
            error=reason,
        )
    duration = time.monotonic() - started
    passed, failed, total, metrics, failed_cases, skipped, skipped_cases = parse_output(result.stdout, result.stderr)
    if result.returncode != 0 and total == 0:
        failed = 1
        total = 1
        if not failed_cases:
            failed_cases = [{"name": "suite_process_failed", "reason": result.stderr.strip() or result.stdout.strip() or "suite exited non-zero"}]

    suite_result = SuiteResult(
        name=name,
        command=command,
        returncode=result.returncode,
        duration_sec=duration,
        stdout=result.stdout,
        stderr=result.stderr,
        passed_cases=passed,
        failed_cases_count=failed,
        total_cases=total,
        metrics=metrics,
        failed_cases=failed_cases,
        skipped_cases_count=skipped,
        skipped_cases=skipped_cases,
    )
    if verbose:
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
    return suite_result


def selected_suites(args: argparse.Namespace) -> list[str]:
    if args.suite:
        unknown = [name for name in args.suite if name not in SUITE_FILES]
        if unknown:
            raise SystemExit(f"unknown suite: {', '.join(unknown)}")
        return args.suite
    if args.require_release_seal:
        return [*CORE_SUITES, "learning_assistant_blind_eval", "learning_assistant_semantic_router_eval"]
    if args.profile == "blind":
        return ["learning_assistant_blind_eval"]
    if args.profile == "real_llm":
        return ["learning_assistant_semantic_router_eval"]
    return QUICK_SUITES if args.quick else SMOKE_SUITES if args.smoke else CORE_SUITES


def print_text_summary(results: list[SuiteResult]) -> None:
    width = max(len(result.name) for result in results) if results else 0
    for result in results:
        status = result.status.upper()
        case_summary = f"{result.passed_cases}/{result.total_cases}" if result.total_cases else "n/a"
        print(f"[{status}] {result.name:<{width}}  {case_summary}  {result.duration_sec:.1f}s")
        if not result.ok and result.failed_cases:
            print(f"       failed cases: {', '.join(failed_case_label(item) for item in result.failed_cases)}")
        if result.error:
            print(f"       error: {result.error}")

    total_cases = sum(result.total_cases for result in results)
    passed_cases = sum(result.passed_cases for result in results)
    failed_suites = [result.name for result in results if result.status == "failed"]
    skipped_suites = [result.name for result in results if result.status == "skipped"]
    passed_suites = [result.name for result in results if result.status == "passed"]
    print()
    if total_cases:
        print(f"Total cases: {passed_cases}/{total_cases} passed")
    print(f"Suites: {len(passed_suites)}/{len(results)} passed")
    if failed_suites:
        print(f"Failed suites: {', '.join(failed_suites)}")
    if skipped_suites:
        print(f"Skipped suites: {', '.join(skipped_suites)}")


def collect_agent_ops_snapshot(limit: int = 100, *, scope: str = "eval") -> dict[str, Any]:
    try:
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        from agent_ops import build_agent_ops_summary

        return build_agent_ops_summary(limit=limit, scope=scope)
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def _safe_rate(passed: int | float, total: int | float) -> float:
    return round(float(passed) / float(total), 4) if total else 0.0


def _suite_pass_rate(results: list[SuiteResult], category: str | None = None) -> float:
    scoped = [result for result in results if category is None or suite_metadata(result.name)["category"] == category]
    passed = sum(result.passed_cases for result in scoped)
    total = sum(result.total_cases for result in scoped)
    return _safe_rate(passed, total)


def _count_metric_rate(results: list[SuiteResult], metric_name: str, fallback: float) -> float:
    for result in results:
        metric = result.metrics.get(metric_name)
        if metric and "passed" in metric and "total" in metric:
            return _safe_rate(float(metric["passed"]), float(metric["total"]))
        if metric and "value" in metric:
            return round(float(metric["value"]), 4)
    return fallback


def _category_summary(results: list[SuiteResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        category = suite_metadata(result.name)["category"]
        bucket = summary.setdefault(category, {"passed": 0, "failed": 0, "skipped": 0})
        if result.status == "skipped":
            bucket["skipped"] += 1
        elif result.ok:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    return summary


def _summary_metrics(results: list[SuiteResult], *, passed_cases: int, total_cases: int, duration_sec: float) -> dict[str, float]:
    task_success = _safe_rate(passed_cases, total_cases)
    rag_rate = _suite_pass_rate(results, "rag")
    tools_rate = _suite_pass_rate(results, "tools")
    safety_rate = _suite_pass_rate(results, "safety")
    return {
        "task_success_rate": task_success,
        "retrieval_hit_rate": _count_metric_rate(results, "retrieval_hit_rate", rag_rate),
        "source_correctness": _count_metric_rate(results, "source_correctness", rag_rate),
        "tool_schema_validity": _count_metric_rate(results, "tool_governance", tools_rate),
        "guardrail_pass_rate": _count_metric_rate(results, "guardrail_pass_rate", safety_rate),
        "format_validity": _count_metric_rate(results, "format_validity", task_success),
        "avg_latency_ms": round(duration_sec * 1000 / total_cases, 2) if total_cases else 0.0,
    }


def source_revision() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip())
        return {"commit_sha": commit, "short_sha": commit[:12], "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit_sha": None, "short_sha": None, "dirty": None}


def new_eval_run_id() -> str:
    return f"eval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:12]}"


def _dataset_versions(evidence_profile: str) -> dict[str, str]:
    candidates = {
        "learning_assistant_cases": EVAL_DIR / "datasets" / "learning_assistant_cases.json",
        "learning_assistant_reviewed_public_v1": EVAL_DIR / "datasets" / "learning_assistant_reviewed_public_v1.jsonl",
    }
    versions: dict[str, str] = {}
    for name, path in candidates.items():
        if path.exists():
            versions[name] = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}"
    blind_path = os.getenv("EDU_AGENT_BLIND_EVAL_PATH")
    if blind_path and Path(blind_path).is_file():
        versions["learning_assistant_blind"] = f"sha256:{hashlib.sha256(Path(blind_path).read_bytes()).hexdigest()[:16]}"
    elif evidence_profile == "blind":
        versions["learning_assistant_blind"] = "not_available"
    external_ood_path = os.getenv("EDU_AGENT_EXTERNAL_OOD_PATH")
    if external_ood_path and Path(external_ood_path).is_file():
        versions["eedi_qatd_2k_test"] = f"sha256:{hashlib.sha256(Path(external_ood_path).read_bytes()).hexdigest()[:16]}"
    return versions


def _environment_fingerprint(*, evidence_profile: str, provider: str, model: str) -> str:
    payload = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "profile": evidence_profile,
        "provider": provider,
        "model": model,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()[:20]}"


def _metric_count(result: SuiteResult, names: set[str]) -> int:
    observed: list[int] = []
    for name, metric in result.metrics.items():
        if name not in names or not isinstance(metric, dict):
            continue
        if "passed" in metric:
            observed.append(int(metric.get("passed") or 0))
        elif "value" in metric:
            observed.append(int(metric.get("value") or 0))
    # A suite can emit both a rate and a count for the same calls. Use the
    # strongest run-local observation rather than summing duplicates.
    return max(observed, default=0)


def report_runtime_status(summary: dict[str, Any]) -> dict[str, Any]:
    current = source_revision()
    generated_at = summary.get("generated_at")
    age_hours: float | None = None
    if isinstance(generated_at, str):
        try:
            generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            age_hours = round((datetime.now(timezone.utc) - generated).total_seconds() / 3600, 2)
        except ValueError:
            pass
    report_commit = (summary.get("source_revision") or {}).get("commit_sha")
    current_commit = current.get("commit_sha")
    commit_mismatch = bool(report_commit and current_commit and report_commit != current_commit)
    too_old = age_hours is not None and age_hours > 168
    reasons = (["commit_mismatch"] if commit_mismatch else []) + (["older_than_7_days"] if too_old else [])
    return {
        "status": "stale" if reasons else "fresh",
        "generated_at": generated_at,
        "age_hours": age_hours,
        "stale_after_hours": 168,
        "reasons": reasons,
        "current_revision": current,
    }


def build_json_summary(
    results: list[SuiteResult],
    *,
    include_output: bool,
    profile: str = "custom",
    require_real_llm: bool = False,
    require_clean_revision: bool = False,
    require_release_seal: bool = False,
    evidence_profile: str = "offline",
    eval_run_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    failed_suites = [result.name for result in results if not result.ok]
    skipped_suites = [result.name for result in results if result.status == "skipped" or result.skipped_cases_count > 0]
    allowed_skipped_suites = [
        result.name
        for result in results
        if result.status == "skipped" and result.name in OPTIONAL_SKIP_SUITES
    ]
    blocking_skipped_suites = [name for name in skipped_suites if name not in allowed_skipped_suites]
    required_by_profile = {"core": CORE_SUITES, "quick": QUICK_SUITES, "smoke": SMOKE_SUITES}
    expected_suites = required_by_profile.get(profile, [result.name for result in results])
    result_names = {result.name for result in results}
    not_run_suites = [name for name in expected_suites if name not in result_names]
    infra_markers = ("quota", "timeout", "credential", "connection", "infra", "provider")
    infra_failed_suites = [
        result.name for result in results
        if not result.ok and any(marker in str(result.error or result.stderr or "").lower() for marker in infra_markers)
    ]
    quality_failed_suites = [name for name in failed_suites if name not in infra_failed_suites]
    total_cases = sum(result.total_cases for result in results)
    passed_cases = sum(result.passed_cases for result in results)
    failed_cases = sum(result.failed_cases_count for result in results)
    skipped_cases = sum(result.skipped_cases_count for result in results)
    total_suites = len(results)
    passed_suites = sum(1 for result in results if result.ok and result.name not in skipped_suites)
    duration_sec = round(sum(result.duration_sec for result in results), 3)
    agent_ops = collect_agent_ops_snapshot(scope="eval")
    observed_llm_calls = sum(
        _metric_count(result, {"llm_generation_rate", "real_llm_call_rate", "real_llm_calls"})
        for result in results
    )
    fallback_calls = sum(
        _metric_count(result, {"fallback_call_count", "fallback_calls"})
        for result in results
    )
    provider = os.getenv("LLM_PROVIDER", "unknown").strip().lower() or "unknown"
    model = os.getenv("LLM_MODEL_QUALITY") or os.getenv("ANTHROPIC_MODEL_QUALITY") or "unknown"
    llm_p95_values = [
        float(metric.get("value") or 0)
        for result in results
        for name, metric in result.metrics.items()
        if name == "llm_p95_ms" and isinstance(metric, dict) and "value" in metric
    ]
    generated_at = datetime.now(timezone.utc).isoformat()
    revision = source_revision()
    dataset_versions = _dataset_versions(evidence_profile)
    run_id = eval_run_id or new_eval_run_id()
    clean_revision = revision.get("dirty") is False
    commit_matches = bool(revision.get("commit_sha"))
    base_ok = not failed_suites and not blocking_skipped_suites and not not_run_suites
    result_by_name = {result.name: result for result in results}
    offline_core_passed = all(
        name in result_by_name and result_by_name[name].status == "passed"
        for name in CORE_SUITES
    )
    blind_passed = any(
        result.name == "learning_assistant_blind_eval" and result.status == "passed"
        for result in results
    )
    real_llm_passed = any(
        result.name == "learning_assistant_semantic_router_eval" and result.status == "passed"
        for result in results
    ) and observed_llm_calls > 0
    required_profiles_passed = []
    if offline_core_passed:
        required_profiles_passed.append("offline")
    if blind_passed:
        required_profiles_passed.append("blind")
    if evidence_profile == "real_llm" and real_llm_passed:
        required_profiles_passed.append("real_llm")

    seal_reasons: list[str] = []
    if require_release_seal:
        if not clean_revision:
            seal_reasons.append("working_tree_dirty")
        if not commit_matches:
            seal_reasons.append("source_revision_unavailable")
        if failed_suites:
            seal_reasons.append("required_suite_failed")
        if skipped_suites or not_run_suites:
            seal_reasons.append("required_suite_incomplete")
        if "offline" not in required_profiles_passed:
            seal_reasons.append("offline_core_not_proven")
        if "blind" not in required_profiles_passed:
            seal_reasons.append("blind_profile_not_proven")
        if "real_llm" not in required_profiles_passed:
            seal_reasons.append("real_llm_profile_not_proven")
        if observed_llm_calls <= 0:
            seal_reasons.append("run_scoped_real_llm_not_observed")
        if provider == "unknown" or model == "unknown":
            seal_reasons.append("model_provenance_incomplete")
    release_seal = {
        "status": ("fail" if seal_reasons else "pass") if require_release_seal else "not_applicable",
        "reasons": seal_reasons,
        "commit_matches": commit_matches,
        "clean_revision": clean_revision,
        "real_llm_observed": observed_llm_calls > 0,
        "required_profiles_passed": required_profiles_passed,
    }
    requirements_ok = (not require_real_llm or observed_llm_calls > 0) and (not require_clean_revision or clean_revision)
    seal_ok = not require_release_seal or release_seal["status"] == "pass"
    return {
        "schema_version": 3,
        "failed_case_schema_version": 1,
        "generated_at": generated_at,
        "evaluation_profile": profile,
        "eval_run": {
            "run_id": run_id,
            "profile": evidence_profile,
            "suite_profile": profile,
            "started_at": started_at or generated_at,
            "finished_at": generated_at,
            "dataset_versions": dataset_versions,
            "source_revision": revision,
            "environment_fingerprint": _environment_fingerprint(evidence_profile=evidence_profile, provider=provider, model=model),
        },
        "source_revision": revision,
        "provenance": {
            "report_commit_sha": revision.get("commit_sha"),
            "commit_matches_current_head": commit_matches,
            "provider": provider,
            "model": model,
            "dataset_versions": dataset_versions,
        },
        "report_freshness": {"status": "fresh", "generated_at": generated_at, "stale_after_hours": 168},
        "llm_execution": {
            "status": "observed" if observed_llm_calls else "not_run" if require_real_llm else "not_observed",
            "required": require_real_llm,
            "calls": observed_llm_calls,
            "run_scoped_calls": observed_llm_calls,
            "fallback_calls": fallback_calls,
            "models": {model: observed_llm_calls} if observed_llm_calls and model != "unknown" else {},
            "provider": provider,
            "p95_ms": max(llm_p95_values) if llm_p95_values else None,
            "note": "检测到真实 LLM 执行证据" if observed_llm_calls else "本次报告未检测到真实 LLM 执行证据；离线 profile 不把 fallback 等同于真实模型质量",
        },
        "release_seal": release_seal,
        "ok": base_ok and requirements_ok and seal_ok,
        "summary": {
            "total": total_cases,
            "passed": passed_cases,
            "failed": failed_cases,
            "skipped": skipped_cases,
            "pass_rate": _safe_rate(passed_cases, total_cases),
        },
        "metrics": _summary_metrics(results, passed_cases=passed_cases, total_cases=total_cases, duration_sec=duration_sec),
        "category_summary": _category_summary(results),
        "total_suites": total_suites,
        "passed_suites": passed_suites,
        "failed_suites": failed_suites,
        "quality_failed_suites": quality_failed_suites,
        "infra_failed_suites": infra_failed_suites,
        "skipped_suites": skipped_suites,
        "allowed_skipped_suites": allowed_skipped_suites,
        "blocking_skipped_suites": blocking_skipped_suites,
        "not_run_suites": not_run_suites,
        "required_suites": list(expected_suites),
        "passed": passed_suites,
        "total": total_suites,
        "passed_cases": passed_cases,
        "total_cases": total_cases,
        "duration_sec": duration_sec,
        "agent_ops": agent_ops,
        "suites": [result.to_dict(include_output=include_output) for result in results],
    }


def build_markdown_report(summary: dict[str, Any]) -> str:
    status = "PASS" if summary["ok"] else "FAIL"
    eval_run = summary.get("eval_run") or {}
    release_seal = summary.get("release_seal") or {}
    provenance = summary.get("provenance") or {}
    dataset_versions = provenance.get("dataset_versions") or {}
    lines = [
        "# EduAgent Eval Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Eval run: {eval_run.get('run_id', 'unknown')}",
        f"Evidence profile: {eval_run.get('profile', 'offline')}",
        f"Profile: {summary.get('evaluation_profile', 'custom')}",
        f"Revision: {(summary.get('source_revision') or {}).get('short_sha') or 'unknown'}{' (dirty)' if (summary.get('source_revision') or {}).get('dirty') else ''}",
        f"LLM execution: {(summary.get('llm_execution') or {}).get('status', 'unknown')} ({(summary.get('llm_execution') or {}).get('calls', 0)} calls)",
        f"Model provenance: {provenance.get('provider', 'unknown')} / {provenance.get('model', 'unknown')}",
        f"Dataset versions: {', '.join(f'{name}={version}' for name, version in dataset_versions.items()) or 'None'}",
        f"Release seal: {release_seal.get('status', 'not_applicable')} ({', '.join(release_seal.get('reasons') or []) or 'no reasons'})",
        "",
        f"Overall: {status}",
        f"Suites: {summary['passed_suites']}/{summary['total_suites']} passed",
        f"Cases: {summary['passed_cases']}/{summary['total_cases']} passed",
        f"Duration: {summary['duration_sec']}s",
        "",
        "| Suite | Category | Kind | Status | Cases | Duration |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for suite in summary["suites"]:
        cases = f"{suite.get('passed_cases', 0)}/{suite.get('total_cases', 0)}" if suite.get("total_cases") else "n/a"
        lines.append(
            "| {name} | {category} | {kind} | {status} | {cases} | {duration:.1f}s |".format(
                name=suite.get("name", "unknown"),
                category=suite.get("category", "other"),
                kind=suite.get("kind", "eval"),
                status=str(suite.get("status", "failed")).upper(),
                cases=cases,
                duration=float(suite.get("duration_sec") or 0),
            )
        )

    lines.extend(["", "## Metrics", ""])
    for name, value in (summary.get("metrics") or {}).items():
        lines.append(f"- {name}: {value}")

    lines.extend(["", "## Category summary", ""])
    category_summary = summary.get("category_summary") or {}
    if category_summary:
        lines.extend(["| Category | Passed | Failed | Skipped |", "| --- | ---: | ---: | ---: |"])
        for category, counts in category_summary.items():
            lines.append(f"| {category} | {counts.get('passed', 0)} | {counts.get('failed', 0)} | {counts.get('skipped', 0)} |")
    else:
        lines.append("None.")

    lines.extend(["", "## Failed suites", ""])
    if summary["failed_suites"]:
        lines.extend(f"- {name}" for name in summary["failed_suites"])
    else:
        lines.append("None.")

    lines.extend(["", "## Incomplete suites", ""])
    incomplete = [
        *(f"SKIPPED: {name}" for name in summary.get("skipped_suites") or []),
        *(f"NOT_RUN: {name}" for name in summary.get("not_run_suites") or []),
        *(f"INFRA_FAILED: {name}" for name in summary.get("infra_failed_suites") or []),
        *(f"QUALITY_FAILED: {name}" for name in summary.get("quality_failed_suites") or []),
    ]
    lines.extend(f"- {item}" for item in incomplete) if incomplete else lines.append("None.")

    lines.extend(["", "## Failed cases", ""])
    failed_case_rows = []
    for suite in summary.get("suites") or []:
        for item in suite.get("failed_cases") or []:
            case = normalize_failed_case(item)
            failed_case_rows.append((suite.get("name", "unknown"), case))
    if failed_case_rows:
        for suite_name, case in failed_case_rows:
            label = failed_case_label(case)
            lines.append(f"- {suite_name}: {label}")
    else:
        lines.append("None.")

    agent_ops = summary.get("agent_ops") or {}
    trace = agent_ops.get("trace_correlation") or {}
    audit = agent_ops.get("audit") or {}
    learning = agent_ops.get("learning") or {}
    tools = agent_ops.get("tools") or {}
    production = agent_ops.get("production") or {}
    latency = production.get("latency") or {}
    llm = production.get("llm") or {}
    rag = production.get("rag") or {}
    cost = production.get("cost") or {}
    readiness = agent_ops.get("readiness") or {}
    data_scope = agent_ops.get("data_scope") or {}
    lines.extend([
        "",
        "## AgentOps",
        "",
        f"Status: {agent_ops.get('status', 'unknown')}",
        f"Data scope: active={data_scope.get('active', 'runtime')}, audit={data_scope.get('audit', {})}, learning={data_scope.get('learning', {})}",
        f"Readiness: {readiness.get('status', 'unknown')} ({', '.join(readiness.get('reasons') or []) or 'no blocking reasons'})",
        f"Trace coverage: {trace.get('coverage_rate', 0)} ({trace.get('audit_with_trace', 0) + trace.get('learning_with_trace', 0)}/{trace.get('audit_total', 0) + trace.get('learning_total', 0)} events)",
        f"Audit events: {audit.get('total', 0)} total, {audit.get('failure', 0)} failed, success_rate={audit.get('success_rate', 0)}",
        f"Learning events: {learning.get('total', 0)} total, {learning.get('failure', 0)} failed, success_rate={learning.get('success_rate', 0)}",
        f"Tool calls: {tools.get('total', 0)} total, {tools.get('failure', 0)} failed, success_rate={tools.get('success_rate', 0)}",
        f"Latency: p50={latency.get('p50_ms', 'n/a')}ms, p95={latency.get('p95_ms', 'n/a')}ms, llm_p95={latency.get('llm_p95_ms', 'n/a')}ms",
        f"LLM: calls={llm.get('calls', 0)}, fallback_count={llm.get('fallback_count', 0)}, error_count={llm.get('error_count', 0)}",
        f"RAG diagnosis: {', '.join(f'{k}={v}' for k, v in (rag.get('diagnosis') or {}).items()) or 'None'}",
        f"RAG failure stage: {', '.join(f'{k}={v}' for k, v in (rag.get('failure_stage') or {}).items()) or 'None'}",
        f"Cost estimate: total_usd={cost.get('total_usd_estimated', 0)}, avg_usd_per_llm_call={cost.get('avg_usd_per_llm_call_estimated', 0)}",
        f"Top actions: {', '.join((audit.get('by_action') or {}).keys()) or 'None'}",
        f"Top features: {', '.join((learning.get('by_feature') or {}).keys()) or 'None'}",
        f"Top tools: {', '.join((tools.get('by_tool_name') or {}).keys()) or 'None'}",
        f"LLM models: {', '.join((llm.get('models') or {}).keys()) or 'None'}",
        f"Failing tools: {', '.join((tools.get('by_failure') or {}).keys()) or 'None'}",
        "",
    ])
    return "\n".join(lines)


def write_reports(summary: dict[str, Any]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": str(LATEST_JSON.relative_to(ROOT)),
        "markdown": str(LATEST_MD.relative_to(ROOT)),
    }
    summary["report_paths"] = paths
    LATEST_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_MD.write_text(build_markdown_report(summary), encoding="utf-8")
    _save_history_snapshot(summary)
    return paths


def _save_history_snapshot(summary: dict[str, Any]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = summary.get("generated_at", datetime.now(timezone.utc).isoformat()).replace(":", "-").replace("+", "Z")[:23]
    snapshot = {
        "generated_at": summary.get("generated_at"),
        "ok": summary.get("ok"),
        "passed_cases": summary.get("passed_cases"),
        "total_cases": summary.get("total_cases"),
        "passed_suites": summary.get("passed_suites"),
        "total_suites": summary.get("total_suites"),
        "duration_sec": summary.get("duration_sec"),
        "metrics": {k: v for k, v in (summary.get("metrics") or {}).items() if not isinstance(v, dict) or "value" in v},
        "summary": summary.get("summary"),
    }
    (HISTORY_DIR / f"{ts}.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    # keep last 30 snapshots
    snapshots = sorted(HISTORY_DIR.glob("*.json"))
    for old in snapshots[:-30]:
        old.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EduAgent core eval suites.")
    parser.add_argument("--quick", action="store_true", help="Run a smaller quick suite set.")
    parser.add_argument("--smoke", action="store_true", help="Run smoke suites only.")
    parser.add_argument("--json", action="store_true", help="Output JSON summary.")
    parser.add_argument("--suite", action="append", choices=sorted(SUITE_FILES), help="Run one suite; can be repeated.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed suite.")
    parser.add_argument("--verbose", action="store_true", help="Print each suite's raw output.")
    parser.add_argument("--include-output", action="store_true", help="Include raw stdout/stderr in JSON output.")
    parser.add_argument("--no-report", action="store_true", help="Do not write eval/reports/latest.* artifacts.")
    parser.add_argument("--profile", choices=["offline", "blind", "real_llm", "production_canary"], default="offline", help="Evidence profile recorded in the run manifest.")
    parser.add_argument("--require-real-llm", action="store_true", help="Require observable real-model execution; zero LLM calls makes the report NOT_RUN/failing.")
    parser.add_argument("--require-clean-revision", action="store_true", help="Fail when the current working tree is dirty.")
    parser.add_argument("--require-release-seal", action="store_true", help="Require all release-seal evidence; intended for release workflows.")
    args = parser.parse_args()

    eval_run_id = new_eval_run_id()
    started_at = datetime.now(timezone.utc).isoformat()
    results: list[SuiteResult] = []
    for suite in selected_suites(args):
        result = run_suite(suite, verbose=args.verbose and not args.json, eval_run_id=eval_run_id)
        results.append(result)
        if args.fail_fast and not result.ok:
            break

    profile = "custom" if args.suite or (args.profile != "offline" and not args.require_release_seal) else "smoke" if args.smoke else "quick" if args.quick else "core"
    summary = build_json_summary(
        results,
        include_output=args.include_output,
        profile=profile,
        require_real_llm=args.require_real_llm,
        require_clean_revision=args.require_clean_revision,
        require_release_seal=args.require_release_seal,
        evidence_profile=args.profile,
        eval_run_id=eval_run_id,
        started_at=started_at,
    )
    if not args.no_report:
        write_reports(summary)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_text_summary(results)
        if args.require_release_seal:
            seal = summary.get("release_seal") or {}
            reasons = ", ".join(seal.get("reasons") or []) or "none"
            print(f"Release seal: {seal.get('status', 'unknown')} ({reasons})")
            print(f"Eval run: {summary['eval_run']['run_id']}")
        if not args.no_report:
            print(f"Reports: {summary['report_paths']['json']}, {summary['report_paths']['markdown']}")

    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
