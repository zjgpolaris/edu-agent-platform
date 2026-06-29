# EduAgent Eval Report

Generated: 2026-06-25T09:33:16.317059+00:00

Overall: PASS
Suites: 12/12 passed
Cases: 73/74 passed
Duration: 69.965s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| history_character_smoke | agent | smoke | SKIPPED | 0/1 | 7.9s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 36.1s |
| material_rag_smoke | rag | smoke | PASSED | 3/3 | 0.6s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 7.0s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.5s |
| weakpoints_smoke | memory | smoke | PASSED | 5/5 | 0.2s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 5.8s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 5.5s |
| review_system_smoke | student | smoke | PASSED | 4/4 | 0.2s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 4.9s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| trace_smoke | observability | smoke | PASSED | 5/5 | 1.1s |

## Metrics

- task_success_rate: 0.9865
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9865
- avg_latency_ms: 945.47

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| agent | 1 | 0 | 1 |
| tools | 2 | 0 | 0 |
| rag | 1 | 0 | 0 |
| memory | 3 | 0 | 0 |
| teacher | 1 | 0 | 0 |
| student | 1 | 0 | 0 |
| safety | 1 | 0 | 0 |
| observability | 1 | 0 | 0 |

## Failed suites

None.

## Failed cases

None.

## AgentOps

Status: ok
Trace coverage: 0.64 (128/200 events)
Audit events: 100 total, 60 failed
Learning events: 100 total, 20 failed
Top actions: tool.failed, tool.allowed, tool.confirmation_required, tool.role_denied, tool.confirmation_confirmed
Top features: learning_assistant, homework_grading, history, history_timeline, textbook_learning
Top tools: search_history_knowledge, delete_demo_memory, suggest_review_plan, get_textbook_lesson, start_timeline_game
