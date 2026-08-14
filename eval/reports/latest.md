# EduAgent Eval Report

Generated: 2026-08-14T05:57:39.754180+00:00
Eval run: eval_20260814T055620Z_d669f20ce9a8
Evidence profile: offline
Profile: core
Revision: 060c166dbc89 (dirty)
LLM execution: not_observed (0 calls)
Model provenance: unknown / unknown
Dataset versions: learning_assistant_cases=sha256:6ebd6333b2e140c2
Release seal: not_applicable (no reasons)

Overall: PASS
Suites: 35/35 passed
Cases: 462/462 passed
Duration: 78.727s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| eval_run_evidence_smoke | ops | smoke | PASSED | n/a | 0.0s |
| answer_groundedness_eval | agent | quality | PASSED | 9/9 | 0.1s |
| history_character_eval | agent | quality | PASSED | 9/9 | 4.1s |
| rag_retrieval_eval | rag | quality | PASSED | 5/5 | 3.9s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 3.3s |
| textbook_qa_eval | rag | quality | PASSED | 3/3 | 4.6s |
| game_generation_eval | agent | quality | PASSED | 4/4 | 3.5s |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 0.2s |
| agent_ops_scope_smoke | ops | smoke | PASSED | n/a | 0.5s |
| readiness_smoke | observability | smoke | PASSED | 4/4 | 3.6s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 3.3s |
| learning_assistant_multiturn_smoke | agent | smoke | PASSED | n/a | 3.3s |
| autotutor_question_handoff_smoke | agent | smoke | PASSED | n/a | 3.4s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 4.5s |
| learning_assistant_rollout_smoke | agent | smoke | PASSED | n/a | 0.2s |
| intent_accuracy_eval | agent | quality | PASSED | 300/300 | 0.1s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 0.3s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.0s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 3.2s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.3s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 3.4s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 3.6s |
| review_system_smoke | student | smoke | PASSED | 6/6 | 0.2s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 3.7s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 3.7s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.2s |
| trajectory_eval | tools | quality | PASSED | 5/5 | 4.9s |
| auto_tutor_trajectory_eval | agent | quality | PASSED | 11/11 | 5.2s |
| autotutor_teaching_quality_eval | agent | quality | PASSED | 5/5 | 3.1s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.4s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 2.9s |
| agent_job_smoke | ops | smoke | PASSED | n/a | 3.7s |

## Metrics

- task_success_rate: 1.0
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 1.0
- avg_latency_ms: 170.4

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| ops | 5 | 0 | 0 |
| agent | 12 | 0 | 0 |
| rag | 4 | 0 | 0 |
| observability | 2 | 0 | 0 |
| tools | 4 | 0 | 0 |
| memory | 3 | 0 | 0 |
| learning | 1 | 0 | 0 |
| teacher | 1 | 0 | 0 |
| student | 1 | 0 | 0 |
| safety | 2 | 0 | 0 |

## Failed suites

None.

## Incomplete suites

None.

## Failed cases

None.

## AgentOps

Status: ok
Data scope: active=eval, audit={'runtime': 432, 'eval': 367, 'demo': 0}, learning={'runtime': 1282, 'eval': 1018, 'demo': 0}
Readiness: not_applicable (readiness_is_runtime_only)
Trace coverage: 0.575 (115/200 events)
Audit events: 100 total, 7 failed, success_rate=0.929
Learning events: 100 total, 8 failed, success_rate=0.919
Tool calls: 23 total, 3 failed, success_rate=0.87
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: tool.allowed, history_character.rag_retrieve, tool.failed, tool.confirmation_required, tool.confirmation_confirmed
Top features: learning_assistant, auto_tutor
Top tools: search_history_knowledge, get_textbook_lesson, start_timeline_game, delete_demo_memory, recommend_character, generate_quiz, suggest_review_plan
LLM models: None
Failing tools: start_timeline_game, generate_quiz
