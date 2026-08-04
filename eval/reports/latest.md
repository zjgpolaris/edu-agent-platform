# EduAgent Eval Report

Generated: 2026-08-04T09:07:52.224546+00:00

Overall: PASS
Suites: 49/49 passed
Cases: 244/245 passed
Duration: 66.218s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 0.2s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 3.9s |
| history_character_smoke | agent | smoke | SKIPPED | 0/1 | 0.0s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 4.4s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 0.3s |
| rag_inspector_smoke | rag | smoke | PASSED | n/a | 3.7s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.0s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 3.1s |
| textbook_trace_smoke | rag | smoke | PASSED | n/a | 3.7s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.3s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 3.4s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 3.4s |
| review_system_smoke | student | smoke | PASSED | 6/6 | 0.2s |
| assignment_smoke | teacher | smoke | PASSED | 17/17 | 0.2s |
| assignment_review_loop_smoke | student | smoke | PASSED | 6/6 | 3.2s |
| question_quality_smoke | teacher | smoke | PASSED | 17/17 | 0.1s |
| notification_badges_smoke | teacher | smoke | PASSED | 7/7 | 0.2s |
| quality_dashboard_smoke | teacher | smoke | PASSED | 7/7 | 0.2s |
| pilot_path_smoke | pilot | smoke | PASSED | 8/8 | 3.3s |
| today_plan_smoke | student | smoke | PASSED | 8/8 | 0.2s |
| completion_overview_smoke | teacher | smoke | PASSED | 6/6 | 0.2s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 3.2s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 3.1s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.1s |
| readiness_smoke | observability | smoke | PASSED | 3/3 | 3.4s |
| variant_question_smoke | student | smoke | PASSED | 6/6 | 0.2s |
| lecture_review_smoke | teacher | smoke | PASSED | 6/6 | 0.2s |
| mastery_heatmap_smoke | student | smoke | PASSED | 5/5 | 0.2s |
| difficulty_smoke | teacher | smoke | PASSED | 5/5 | 0.2s |
| calendar_smoke | student | smoke | PASSED | 5/5 | 0.2s |
| urge_notification_smoke | teacher | smoke | PASSED | 6/6 | 0.1s |
| tiered_assignment_smoke | teacher | smoke | PASSED | 6/6 | 0.2s |
| class_wrong_analysis_smoke | teacher | smoke | PASSED | 5/5 | 0.2s |
| tutor_effectiveness_smoke | student | smoke | PASSED | 8/8 | 0.2s |
| check_in_smoke | student | smoke | PASSED | n/a | 0.1s |
| preference_smoke | student | smoke | PASSED | n/a | 0.1s |
| root_cause_smoke | student | smoke | PASSED | n/a | 0.1s |
| class_matrix_smoke | teacher | smoke | PASSED | n/a | 0.1s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.4s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 3.2s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 2.8s |
| agent_job_smoke | ops | smoke | PASSED | n/a | 3.4s |
| material_rag_isolation_smoke | other | eval | PASSED | n/a | 3.3s |
| mcp_server_smoke | other | eval | PASSED | n/a | 2.9s |
| tool_permission_smoke | other | eval | PASSED | n/a | 3.0s |
| weekly_summary_smoke | other | eval | PASSED | 6/6 | 0.1s |

## Metrics

- task_success_rate: 0.9959
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9959
- avg_latency_ms: 270.28

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| ops | 3 | 0 | 0 |
| agent | 3 | 0 | 1 |
| tools | 3 | 0 | 0 |
| rag | 4 | 0 | 0 |
| memory | 3 | 0 | 0 |
| learning | 1 | 0 | 0 |
| teacher | 12 | 0 | 0 |
| student | 10 | 0 | 0 |
| pilot | 1 | 0 | 0 |
| safety | 2 | 0 | 0 |
| observability | 2 | 0 | 0 |
| other | 4 | 0 | 0 |

## Failed suites

None.

## Failed cases

None.

## AgentOps

Status: partial_trace_coverage
Readiness: fail (trace_coverage_below_50_percent, audit_failures_present, learning_failures_present, tool_failures_present)
Trace coverage: 0.485 (97/200 events)
Audit events: 100 total, 10 failed, success_rate=0.9
Learning events: 100 total, 11 failed, success_rate=0.89
Tool calls: 24 total, 7 failed, success_rate=0.708
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: student_profile.read, student_profile.review_plan, tool.allowed, tool.confirmation_required, tool.role_denied, tool.confirmation_confirmed, tool.failed, autotutor.start
Top features: learning_assistant, auto_tutor, pilot_seed
Top tools: search_history_knowledge, delete_demo_memory, get_textbook_lesson, start_timeline_game, suggest_review_plan, recommend_character
LLM models: None
Failing tools: start_timeline_game, delete_demo_memory
