# EduAgent Eval Report

Generated: 2026-08-13T09:30:21.469093+00:00
Profile: core
Revision: d8928296fa7f (dirty)
LLM execution: not_observed (0 calls)

Overall: PASS
Suites: 31/31 passed
Cases: 453/453 passed
Duration: 75.378s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| history_character_eval | agent | quality | PASSED | 9/9 | 4.8s |
| rag_retrieval_eval | rag | quality | PASSED | 5/5 | 3.9s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 3.3s |
| textbook_qa_eval | rag | quality | PASSED | 3/3 | 4.6s |
| game_generation_eval | agent | quality | PASSED | 4/4 | 3.5s |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 0.2s |
| readiness_smoke | observability | smoke | PASSED | 4/4 | 3.6s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 3.3s |
| learning_assistant_multiturn_smoke | agent | smoke | PASSED | n/a | 3.4s |
| autotutor_question_handoff_smoke | agent | smoke | PASSED | n/a | 3.8s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 4.5s |
| intent_accuracy_eval | agent | quality | PASSED | 300/300 | 0.1s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 0.3s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.0s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 3.1s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.3s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 3.3s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 3.4s |
| review_system_smoke | student | smoke | PASSED | 6/6 | 0.1s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 3.2s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 3.1s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.1s |
| trajectory_eval | tools | quality | PASSED | 5/5 | 4.1s |
| auto_tutor_trajectory_eval | agent | quality | PASSED | 11/11 | 4.6s |
| autotutor_teaching_quality_eval | agent | quality | PASSED | 5/5 | 3.0s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.4s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 2.8s |
| agent_job_smoke | ops | smoke | PASSED | n/a | 3.3s |

## Metrics

- task_success_rate: 1.0
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 1.0
- avg_latency_ms: 166.4

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| agent | 10 | 0 | 0 |
| rag | 4 | 0 | 0 |
| ops | 3 | 0 | 0 |
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

Status: partial_trace_coverage
Data scope: active=runtime, audit={'eval': 49, 'runtime': 51}, learning={'eval': 100}
Readiness: fail (trace_coverage_below_50_percent, audit_failures_present)
Trace coverage: 0.471 (24/51 events)
Audit events: 51 total, 7 failed, success_rate=0.863
Learning events: 0 total, 0 failed, success_rate=0.0
Tool calls: 0 total, 0 failed, success_rate=0.0
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: tool.allowed, history_character.rag_retrieve, tool.failed, learning_assistant.chat, student_profile.read, tool.confirmation_required, tool.confirmation_confirmed
Top features: None
Top tools: None
LLM models: None
Failing tools: None
