# EduAgent Eval Report

Generated: 2026-08-03T09:22:51.453694+00:00

Overall: PASS
Suites: 20/20 passed
Cases: 85/86 passed
Duration: 52.593s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 0.2s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 3.5s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.0s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 3.7s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 3.5s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 3.9s |
| trajectory_eval | tools | quality | PASSED | 5/5 | 4.6s |
| auto_tutor_trajectory_eval | agent | quality | PASSED | 11/11 | 5.0s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.5s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 3.9s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 3.0s |
| agent_job_smoke | ops | smoke | PASSED | n/a | 3.7s |
| history_character_smoke | agent | smoke | SKIPPED | 0/1 | 0.0s |
| rag_inspector_smoke | rag | smoke | PASSED | n/a | 4.1s |
| rag_retrieval_eval | rag | quality | PASSED | 5/5 | 4.0s |
| textbook_trace_smoke | rag | smoke | PASSED | n/a | 3.8s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 0.3s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 4.8s |

## Metrics

- task_success_rate: 0.9884
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9884
- avg_latency_ms: 611.55

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| ops | 3 | 0 | 0 |
| agent | 3 | 0 | 1 |
| tools | 4 | 0 | 0 |
| safety | 2 | 0 | 0 |
| memory | 2 | 0 | 0 |
| rag | 5 | 0 | 0 |

## Failed suites

None.

## Failed cases

None.

## AgentOps

Status: ok
Readiness: fail (audit_failures_present, learning_failures_present, tool_failures_present)
Trace coverage: 0.65 (104/160 events)
Audit events: 70 total, 10 failed, success_rate=0.857
Learning events: 90 total, 10 failed, success_rate=0.889
Tool calls: 24 total, 8 failed, success_rate=0.667
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: tool.allowed, tool.failed, tool.confirmation_required, tool.confirmation_confirmed
Top features: learning_assistant, auto_tutor
Top tools: search_history_knowledge, get_textbook_lesson, delete_demo_memory, start_timeline_game, suggest_review_plan, recommend_character, generate_quiz
LLM models: None
Failing tools: start_timeline_game, delete_demo_memory, generate_quiz
