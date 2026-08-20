# EduAgent Eval Report

Generated: 2026-08-20T04:30:55.792844+00:00
Eval run: eval_20260820T043030Z_99d36ee14358
Evidence profile: offline
Profile: core
Revision: dbf5ff16a9cb (dirty)
LLM execution: not_observed (0 calls)
Model provenance: unknown / unknown
Dataset versions: learning_assistant_cases=sha256:6ebd6333b2e140c2
Release seal: not_applicable (no reasons)

Overall: PASS
Suites: 53/54 passed
Cases: 584/593 passed
Duration: 25.595s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| eval_run_evidence_smoke | ops | smoke | PASSED | n/a | 0.0s |
| answer_groundedness_eval | agent | quality | PASSED | 9/9 | 0.1s |
| history_query_eval | rag | quality | PASSED | 120/120 | 0.3s |
| history_retrieval_contract_smoke | rag | smoke | PASSED | n/a | 0.5s |
| history_retrieval_review_smoke | rag | smoke | PASSED | 11/11 | 0.2s |
| history_no_answer_eval | rag | quality | PASSED | n/a | 0.2s |
| history_answer_grounding_eval | rag | quality | PASSED | n/a | 0.1s |
| history_character_eval | agent | quality | SKIPPED | 0/9 | 1.9s |
| rag_retrieval_eval | rag | quality | PASSED | 5/5 | 1.5s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 0.4s |
| textbook_qa_eval | rag | quality | PASSED | 3/3 | 1.5s |
| game_generation_eval | agent | quality | PASSED | 4/4 | 0.7s |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 0.1s |
| agent_ops_scope_smoke | ops | smoke | PASSED | n/a | 0.5s |
| readiness_smoke | observability | smoke | PASSED | 4/4 | 0.3s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 0.6s |
| learning_assistant_multiturn_smoke | agent | smoke | PASSED | n/a | 0.4s |
| autotutor_question_handoff_smoke | agent | smoke | PASSED | n/a | 0.6s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 1.4s |
| learning_assistant_rollout_smoke | agent | smoke | PASSED | n/a | 0.1s |
| intent_accuracy_eval | agent | quality | PASSED | 300/300 | 0.1s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 0.3s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.0s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 0.3s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.2s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.1s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 0.4s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 0.4s |
| review_system_smoke | student | smoke | PASSED | 6/6 | 0.1s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 0.5s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 0.3s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.1s |
| trajectory_eval | tools | quality | PASSED | 5/5 | 1.3s |
| auto_tutor_trajectory_eval | agent | quality | PASSED | 11/11 | 1.4s |
| autotutor_teaching_quality_eval | agent | quality | PASSED | 5/5 | 0.2s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.3s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 0.3s |
| agent_job_smoke | ops | smoke | PASSED | n/a | 0.4s |
| agent_runtime_contract_smoke | other | eval | PASSED | n/a | 0.2s |
| agent_runtime_migration_smoke | other | eval | PASSED | n/a | 1.4s |
| agent_runtime_checkpoint_smoke | other | eval | PASSED | n/a | 0.1s |
| agent_runtime_concurrency_smoke | other | eval | PASSED | n/a | 0.5s |
| agent_runtime_recovery_smoke | other | eval | PASSED | n/a | 0.1s |
| history_character_runtime_smoke | other | eval | PASSED | n/a | 0.4s |
| essay_grader_runtime_smoke | other | eval | PASSED | n/a | 0.3s |
| agent_runtime_stream_parity_smoke | other | eval | PASSED | n/a | 0.2s |
| agent_runtime_security_smoke | other | eval | PASSED | n/a | 0.6s |
| agent_runtime_confirmation_smoke | other | eval | PASSED | n/a | 0.3s |
| agent_runtime_adapter_smoke | other | eval | PASSED | n/a | 0.2s |
| agent_runtime_product_routes_smoke | other | eval | PASSED | n/a | 0.6s |
| agent_runtime_autotutor_resume_smoke | other | eval | PASSED | n/a | 0.6s |
| agent_runtime_essay_resume_smoke | other | eval | PASSED | n/a | 0.6s |

## Metrics

- task_success_rate: 0.9848
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9848
- avg_latency_ms: 43.16

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| ops | 5 | 0 | 0 |
| agent | 11 | 0 | 1 |
| rag | 9 | 0 | 0 |
| observability | 2 | 0 | 0 |
| tools | 4 | 0 | 0 |
| memory | 3 | 0 | 0 |
| learning | 1 | 0 | 0 |
| teacher | 1 | 0 | 0 |
| student | 1 | 0 | 0 |
| safety | 2 | 0 | 0 |
| other | 14 | 0 | 0 |

## Failed suites

None.

## Incomplete suites

- SKIPPED: history_character_eval

## Failed cases

None.

## AgentOps

Status: ok
Data scope: active=eval, audit={'runtime': 103, 'eval': 308, 'demo': 0}, learning={'runtime': 108, 'eval': 647, 'demo': 0}
Readiness: not_applicable (readiness_is_runtime_only)
Trace coverage: 0.625 (125/200 events)
Audit events: 100 total, 6 failed, success_rate=0.936
Learning events: 100 total, 7 failed, success_rate=0.929
Tool calls: 23 total, 3 failed, success_rate=0.87
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: tool.allowed, history_character.rag_retrieve, tool.failed, tool.confirmation_required, tool.confirmation_confirmed, tool.role_denied
Top features: learning_assistant, auto_tutor
Top tools: search_history_knowledge, get_textbook_lesson, start_timeline_game, delete_demo_memory, recommend_character, generate_quiz, suggest_review_plan
LLM models: None
Failing tools: start_timeline_game, generate_quiz
