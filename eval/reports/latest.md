# EduAgent Eval Report

Generated: 2026-09-02T03:43:48.549560+00:00
Eval run: eval_20260902T034244Z_b510e95831b6
Evidence profile: offline
Profile: smoke
Revision: fb9d3bc53ee2 (dirty)
LLM execution: not_observed (0 calls)
Model provenance: bailian / qwen3.7-plus
Dataset versions: learning_assistant_cases=sha256:c818f2fc541406e8
Release seal: not_applicable (no reasons)

Overall: PASS
Suites: 113/114 passed
Cases: 513/514 passed
Duration: 63.875s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| eval_run_evidence_smoke | ops | smoke | PASSED | n/a | 0.1s |
| alembic_transaction_boundary_smoke | ops | smoke | PASSED | n/a | 0.1s |
| backend_startup_migration_smoke | ops | smoke | PASSED | n/a | 0.5s |
| backend_startup_migration_failure_smoke | ops | smoke | PASSED | n/a | 0.3s |
| answer_groundedness_eval | agent | quality | PASSED | 9/9 | 0.1s |
| history_query_eval | rag | quality | PASSED | 121/121 | 0.3s |
| history_retrieval_contract_smoke | rag | smoke | PASSED | n/a | 0.4s |
| history_retrieval_review_smoke | rag | smoke | PASSED | 11/11 | 0.3s |
| history_no_answer_eval | rag | quality | PASSED | n/a | 0.4s |
| history_answer_grounding_eval | rag | quality | PASSED | n/a | 0.1s |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 0.5s |
| agent_ops_scope_smoke | ops | smoke | PASSED | n/a | 0.9s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 0.9s |
| autotutor_langchain_provenance_smoke | agent | smoke | PASSED | n/a | 0.2s |
| autotutor_langgraph_shadow_parity_smoke | agent | smoke | PASSED | n/a | 0.5s |
| autotutor_langgraph_shadow_isolation_smoke | agent | smoke | PASSED | n/a | 1.1s |
| history_character_smoke | agent | smoke | SKIPPED | 0/1 | 0.1s |
| learning_assistant_smoke | tools | smoke | PASSED | 11/11 | 2.2s |
| learning_assistant_rollout_smoke | agent | smoke | PASSED | n/a | 0.2s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 0.5s |
| rag_inspector_smoke | rag | smoke | PASSED | n/a | 1.5s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.1s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 0.4s |
| textbook_trace_smoke | rag | smoke | PASSED | n/a | 1.2s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.4s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 0.6s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 0.7s |
| review_system_smoke | student | smoke | PASSED | 7/7 | 0.2s |
| adaptive_review_question_quality_eval | student | quality | PASSED | 8/8 | 0.3s |
| review_mastery_evidence_eval | student | quality | PASSED | 3/3 | 0.3s |
| review_retention_scheduler_smoke | student | smoke | PASSED | n/a | 0.3s |
| review_mastery_migration_smoke | runtime | smoke | PASSED | n/a | 1.0s |
| assignment_smoke | teacher | smoke | PASSED | 17/17 | 0.2s |
| assignment_review_loop_smoke | student | smoke | PASSED | 6/6 | 0.7s |
| question_quality_smoke | teacher | smoke | PASSED | 17/17 | 0.1s |
| notification_badges_smoke | teacher | smoke | PASSED | 7/7 | 0.2s |
| quality_dashboard_smoke | teacher | smoke | PASSED | 7/7 | 0.2s |
| pilot_path_smoke | pilot | smoke | PASSED | 8/8 | 4.3s |
| today_plan_smoke | student | smoke | PASSED | 8/8 | 0.2s |
| completion_overview_smoke | teacher | smoke | PASSED | 6/6 | 0.2s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 0.7s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 0.4s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.2s |
| readiness_smoke | observability | smoke | PASSED | 4/4 | 0.5s |
| demo_contract_smoke | product | smoke | PASSED | n/a | 4.3s |
| demo_trace_projection_smoke | observability | smoke | PASSED | n/a | 0.0s |
| demo_trace_authorization_smoke | safety | smoke | PASSED | n/a | 0.5s |
| demo_evidence_authorization_smoke | safety | smoke | PASSED | n/a | 0.5s |
| variant_question_smoke | student | smoke | PASSED | 6/6 | 0.2s |
| lecture_review_smoke | teacher | smoke | PASSED | 6/6 | 0.3s |
| mastery_heatmap_smoke | student | smoke | PASSED | 5/5 | 0.2s |
| difficulty_smoke | teacher | smoke | PASSED | 5/5 | 0.2s |
| calendar_smoke | student | smoke | PASSED | 5/5 | 0.3s |
| urge_notification_smoke | teacher | smoke | PASSED | 6/6 | 0.2s |
| tiered_assignment_smoke | teacher | smoke | PASSED | 6/6 | 0.2s |
| class_wrong_analysis_smoke | teacher | smoke | PASSED | 5/5 | 0.2s |
| tutor_effectiveness_smoke | student | smoke | PASSED | 9/9 | 0.2s |
| check_in_smoke | student | smoke | PASSED | n/a | 0.2s |
| preference_smoke | student | smoke | PASSED | n/a | 0.2s |
| root_cause_smoke | student | smoke | PASSED | n/a | 0.3s |
| class_matrix_smoke | teacher | smoke | PASSED | n/a | 0.2s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 4/4 | 0.8s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 0.6s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 0.5s |
| agent_job_smoke | ops | smoke | PASSED | n/a | 0.7s |
| agent_runtime_contract_smoke | other | eval | PASSED | n/a | 0.4s |
| agent_runtime_migration_smoke | other | eval | PASSED | n/a | 1.8s |
| agent_runtime_checkpoint_smoke | other | eval | PASSED | n/a | 0.4s |
| agent_runtime_concurrency_smoke | other | eval | PASSED | n/a | 0.8s |
| agent_runtime_recovery_smoke | other | eval | PASSED | n/a | 0.4s |
| agent_runtime_lifecycle_smoke | other | eval | PASSED | n/a | 0.4s |
| agent_runtime_idempotency_smoke | other | eval | PASSED | n/a | 0.6s |
| history_character_runtime_smoke | other | eval | PASSED | n/a | 0.7s |
| essay_grader_runtime_smoke | other | eval | PASSED | n/a | 0.5s |
| agent_runtime_stream_parity_smoke | other | eval | PASSED | n/a | 0.4s |
| agent_runtime_security_smoke | other | eval | PASSED | n/a | 1.0s |
| agent_runtime_confirmation_smoke | other | eval | PASSED | n/a | 0.5s |
| agent_runtime_adapter_smoke | other | eval | PASSED | n/a | 0.3s |
| agent_runtime_product_routes_smoke | other | eval | PASSED | n/a | 1.1s |
| agent_runtime_autotutor_resume_smoke | other | eval | PASSED | n/a | 0.9s |
| agent_runtime_essay_resume_smoke | other | eval | PASSED | n/a | 0.9s |
| agent_runtime_schema_readiness_smoke | other | eval | PASSED | n/a | 0.4s |
| agent_runtime_rollout_gate_smoke | observability | smoke | PASSED | n/a | 0.8s |
| agent_runtime_latency_baseline_smoke | observability | smoke | PASSED | n/a | 0.4s |
| rollout_evidence_supply_chain_smoke | observability | smoke | PASSED | n/a | 0.4s |
| production_auth_trusted_rollout_smoke | security | smoke | PASSED | n/a | 2.2s |
| agent_runtime_learning_assistant_api_smoke | other | eval | PASSED | n/a | 0.8s |
| agent_runtime_rollout_status_smoke | other | eval | PASSED | n/a | 0.9s |
| autotutor_langgraph_active_recovery_smoke | other | eval | PASSED | n/a | 1.0s |
| autotutor_langgraph_active_routing_smoke | other | eval | PASSED | n/a | 0.1s |
| autotutor_langgraph_active_transaction_smoke | other | eval | PASSED | n/a | 1.2s |
| autotutor_observation_provider_smoke | other | eval | PASSED | n/a | 0.4s |
| history_map_stream_smoke | other | eval | PASSED | n/a | 0.6s |
| history_search_relevance_smoke | other | eval | PASSED | n/a | 0.4s |
| llm_capability_api_smoke | other | eval | PASSED | n/a | 0.4s |
| llm_capability_gate_smoke | other | eval | PASSED | n/a | 0.3s |
| llm_capability_manifest_provenance_smoke | other | eval | PASSED | n/a | 0.2s |
| llm_capability_manifest_smoke | other | eval | PASSED | n/a | 0.2s |
| llm_capability_runtime_resolution_smoke | other | eval | PASSED | n/a | 0.3s |
| llm_capability_store_smoke | other | eval | PASSED | n/a | 0.3s |
| llm_fallback_capability_smoke | other | eval | PASSED | n/a | 0.2s |
| llm_profile_coverage_smoke | other | eval | PASSED | n/a | 0.2s |
| llm_release_evidence_v2_smoke | other | eval | PASSED | n/a | 0.4s |
| material_rag_isolation_smoke | other | eval | PASSED | n/a | 0.5s |
| mcp_server_smoke | other | eval | PASSED | n/a | 0.8s |
| render_container_contract_smoke | other | eval | PASSED | n/a | 0.0s |
| runtime_rollout_config_smoke | other | eval | PASSED | n/a | 0.4s |
| textbook_quiz_smoke | other | eval | PASSED | 3/3 | 0.4s |
| tool_permission_smoke | other | eval | PASSED | n/a | 0.3s |
| weekly_summary_smoke | other | eval | PASSED | 6/6 | 0.2s |
| autotutor_langgraph_full_outcome_parity_eval | other | eval | PASSED | 108/108 | 1.6s |

## Metrics

- task_success_rate: 0.9981
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9981
- avg_latency_ms: 124.27

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| ops | 8 | 0 | 0 |
| agent | 8 | 0 | 1 |
| rag | 9 | 0 | 0 |
| tools | 3 | 0 | 0 |
| memory | 3 | 0 | 0 |
| learning | 1 | 0 | 0 |
| teacher | 12 | 0 | 0 |
| student | 13 | 0 | 0 |
| runtime | 1 | 0 | 0 |
| pilot | 1 | 0 | 0 |
| safety | 4 | 0 | 0 |
| observability | 6 | 0 | 0 |
| product | 1 | 0 | 0 |
| other | 42 | 0 | 0 |
| security | 1 | 0 | 0 |

## Failed suites

None.

## Incomplete suites

- SKIPPED: history_character_smoke

## Failed cases

None.

## AgentOps

Status: ok
Data scope: active=eval, audit={'runtime': 15, 'eval': 67, 'demo': 0}, learning={'runtime': 10, 'eval': 484, 'demo': 0}
Readiness: not_applicable (readiness_is_runtime_only)
Trace coverage: 0.964 (161/167 events)
Audit events: 67 total, 9 failed, success_rate=0.847
Learning events: 100 total, 4 failed, success_rate=0.959
Tool calls: 25 total, 2 failed, success_rate=0.92
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: tool.allowed, tool.failed, tool.confirmation_required, tool.role_denied, tool.confirmation_confirmed
Top features: learning_assistant
Top tools: search_history_knowledge, delete_demo_memory, suggest_review_plan, get_textbook_lesson, start_timeline_game
LLM models: None
Failing tools: start_timeline_game
