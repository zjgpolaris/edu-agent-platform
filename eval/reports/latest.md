# EduAgent Eval Report

Generated: 2026-07-14T04:22:40.614120+00:00

Overall: FAIL
Suites: 18/24 passed
Cases: 102/110 passed
Duration: 1831.009s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| history_character_eval | agent | quality | FAILED | 0/1 | 300.0s |
| rag_retrieval_eval | rag | quality | PASSED | 5/5 | 39.8s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 4.1s |
| textbook_qa_eval | rag | quality | PASSED | 3/3 | 94.9s |
| game_generation_eval | agent | quality | PASSED | 4/4 | 229.2s |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 14.0s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 52.5s |
| learning_assistant_smoke | tools | smoke | FAILED | 0/1 | 300.0s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 43.7s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.0s |
| student_profile_smoke | memory | smoke | FAILED | 3/6 | 33.9s |
| homework_grading_smoke | agent | smoke | FAILED | 2/3 | 17.8s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 3.6s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 3.4s |
| review_system_smoke | student | smoke | PASSED | 4/4 | 0.1s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 79.5s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 4/4 | 12.4s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.1s |
| trajectory_eval | tools | quality | FAILED | 0/1 | 300.0s |
| auto_tutor_trajectory_eval | agent | quality | FAILED | 0/1 | 300.0s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.5s |

## Metrics

- task_success_rate: 0.9273
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9273
- avg_latency_ms: 16645.54

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| agent | 3 | 3 | 0 |
| rag | 4 | 0 | 0 |
| ops | 2 | 0 | 0 |
| tools | 1 | 2 | 0 |
| memory | 2 | 1 | 0 |
| learning | 1 | 0 | 0 |
| teacher | 1 | 0 | 0 |
| student | 1 | 0 | 0 |
| safety | 2 | 0 | 0 |
| observability | 1 | 0 | 0 |

## Failed suites

- history_character_eval
- learning_assistant_smoke
- student_profile_smoke
- homework_grading_smoke
- trajectory_eval
- auto_tutor_trajectory_eval

## Failed cases

- history_character_eval: suite_timeout (suite timed out after 300s)
- learning_assistant_smoke: suite_timeout (suite timed out after 300s)
- trajectory_eval: suite_timeout (suite timed out after 300s)
- auto_tutor_trajectory_eval: suite_timeout (suite timed out after 300s)

## AgentOps

Status: ok
Readiness: fail (audit_failures_present, learning_failures_present, tool_failures_present)
Trace coverage: 0.525 (105/200 events)
Audit events: 100 total, 8 failed, success_rate=0.92
Learning events: 100 total, 6 failed, success_rate=0.94
Tool calls: 27 total, 3 failed, success_rate=0.889
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: student_profile.read, tool.allowed, student_profile.review_plan, memory.entries_read, tool.confirmation_required, student_profile.learning_path, history_character.rag_retrieve, tool.failed
Top features: learning_assistant, textbook_learning, quiz_practice
Top tools: search_history_knowledge, delete_demo_memory, start_timeline_game, suggest_review_plan, get_textbook_lesson, generate_quiz
LLM models: None
Failing tools: delete_demo_memory
