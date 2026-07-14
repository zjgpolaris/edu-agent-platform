# EduAgent Eval Report

Generated: 2026-07-14T08:49:47.400481+00:00

Overall: FAIL
Suites: 25/26 passed
Cases: 142/143 passed
Duration: 1198.692s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| history_character_eval | agent | quality | PASSED | 9/9 | 314.5s |
| rag_retrieval_eval | rag | quality | PASSED | 5/5 | 43.1s |
| rag_groundedness_eval | rag | quality | PASSED | 4/4 | 4.0s |
| textbook_qa_eval | rag | quality | PASSED | 3/3 | 98.2s |
| game_generation_eval | agent | quality | PASSED | 4/4 | 230.4s |
| agent_ops_smoke | ops | smoke | PASSED | n/a | 15.4s |
| autotutor_session_recovery_smoke | agent | smoke | PASSED | n/a | 60.2s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 15.7s |
| material_rag_smoke | rag | smoke | PASSED | 4/4 | 46.6s |
| release_gate_smoke | ops | smoke | PASSED | n/a | 0.1s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 59.8s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 23.6s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| knowledge_graph_smoke | learning | smoke | PASSED | 16/16 | 0.0s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 5.4s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 3.8s |
| review_system_smoke | student | smoke | PASSED | 4/4 | 0.2s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 84.2s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| agent_safety_eval | safety | quality | PASSED | 5/5 | 14.0s |
| trace_smoke | observability | smoke | PASSED | 6/6 | 1.1s |
| trajectory_eval | tools | quality | PASSED | 5/5 | 14.9s |
| auto_tutor_trajectory_eval | agent | quality | PASSED | 11/11 | 27.7s |
| debate_multi_agent_smoke | agent | smoke | PASSED | 2/2 | 0.5s |
| mcp_client_smoke | tools | smoke | PASSED | n/a | 13.4s |
| agent_job_smoke | ops | smoke | FAILED | 0/1 | 121.9s |

## Metrics

- task_success_rate: 0.993
- retrieval_hit_rate: 1.0
- source_correctness: 1.0
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.993
- avg_latency_ms: 8382.46

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| agent | 6 | 0 | 0 |
| rag | 4 | 0 | 0 |
| ops | 2 | 1 | 0 |
| tools | 4 | 0 | 0 |
| memory | 3 | 0 | 0 |
| learning | 1 | 0 | 0 |
| teacher | 1 | 0 | 0 |
| student | 1 | 0 | 0 |
| safety | 2 | 0 | 0 |
| observability | 1 | 0 | 0 |

## Failed suites

- agent_job_smoke

## Failed cases

- agent_job_smoke: suite_process_failed (/Users/cengjiguang/Desktop/work/edu-agent-platform/backend/api/main.py:35: RuntimeWarning: JWT_SECRET environment variable is not set. Using an insecure default. Set JWT_SECRET in production.
  from security.auth import assert_student_access, auth_required, create_token, get_actor_from_request, require_auth, Actor
EDU_AGENT_AUTH_REQUIRED is not set — authentication is DISABLED
EDU_AGENT_AUTH_REQUIRED is not set — authentication is DISABLED
EDU_AGENT_AUTH_REQUIRED is not set — authentication is DISABLED
EDU_AGENT_AUTH_REQUIRED is not set — authentication is DISABLED
Traceback (most recent call last):
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/eval/agent_job_smoke.py", line 110, in <module>
    main()
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/eval/agent_job_smoke.py", line 100, in main
    assert status_payload["status"] in {"pending", "running", "succeeded"}, status_payload
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: {'id': 'job_b08e5c74adec4ff8ab82ee2306501beb', 'job_type': 'weekly_summary', 'actor_id': 'dev-teacher', 'status': 'cancelled', 'idempotency_key': 'weekly-student-api', 'trace_id': 'agent-job-dc2d7210efa69156', 'attempts': 1, 'max_attempts': 3, 'timeout_seconds': 120, 'cancel_requested': True, 'error': 'cancelled by request', 'created_at': '2026-07-14T07:02:02.601586+00:00', 'updated_at': '2026-07-14T07:02:43.542385+00:00', 'started_at': '2026-07-14T07:02:07.762813+00:00', 'finished_at': '2026-07-14T07:02:43.542385+00:00', 'payload': {'student_id': 'student-api'}, 'result': None})

## AgentOps

Status: partial_trace_coverage
Readiness: fail (trace_coverage_below_50_percent, audit_failures_present, learning_failures_present, tool_failures_present)
Trace coverage: 0.44 (88/200 events)
Audit events: 100 total, 17 failed, success_rate=0.83
Learning events: 100 total, 12 failed, success_rate=0.85
Tool calls: 23 total, 3 failed, success_rate=0.87
Latency: p50=Nonems, p95=Nonems, llm_p95=Nonems
LLM: calls=0, fallback_count=0, error_count=0
RAG diagnosis: None
RAG failure stage: None
Cost estimate: total_usd=0, avg_usd_per_llm_call=0.0
Top actions: history_character.rag_retrieve, tool.allowed, tool.confirmation_required, tool.failed, tool.role_denied, tool.confirmation_confirmed
Top features: learning_assistant, textbook_learning, homework_grading, history, history_timeline, quiz_practice
Top tools: search_history_knowledge, delete_demo_memory, start_timeline_game, suggest_review_plan, get_textbook_lesson, generate_quiz
LLM models: None
Failing tools: delete_demo_memory
