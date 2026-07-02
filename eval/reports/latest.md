# EduAgent Eval Report

Generated: 2026-07-02T07:29:11.675639+00:00

Overall: FAIL
Suites: 15/17 passed
Cases: 92/97 passed
Duration: 1376.256s

| Suite | Category | Kind | Status | Cases | Duration |
| --- | --- | --- | --- | ---: | ---: |
| history_character_eval | agent | quality | FAILED | 0/1 | 173.5s |
| rag_retrieval_eval | rag | quality | SKIPPED | 0/1 | 6.2s |
| textbook_qa_eval | rag | quality | FAILED | 0/3 | 57.3s |
| game_generation_eval | agent | quality | PASSED | 4/4 | 195.2s |
| learning_assistant_smoke | tools | smoke | PASSED | 10/10 | 152.3s |
| material_rag_smoke | rag | smoke | PASSED | 3/3 | 0.6s |
| student_profile_smoke | memory | smoke | PASSED | 6/6 | 6.1s |
| homework_grading_smoke | agent | smoke | PASSED | 3/3 | 0.5s |
| weakpoints_smoke | memory | smoke | PASSED | 8/8 | 0.2s |
| learning_closure_smoke | memory | smoke | PASSED | 4/4 | 5.1s |
| teacher_features_smoke | teacher | smoke | PASSED | 6/6 | 4.8s |
| review_system_smoke | student | smoke | PASSED | 4/4 | 0.3s |
| tool_registry_smoke | tools | smoke | PASSED | 13/13 | 4.2s |
| guardrails_smoke | safety | smoke | PASSED | 14/14 | 0.0s |
| trace_smoke | observability | smoke | PASSED | 5/5 | 1.2s |
| trajectory_eval | tools | quality | PASSED | 5/5 | 158.7s |
| auto_tutor_trajectory_eval | agent | quality | PASSED | 7/7 | 610.2s |

## Metrics

- task_success_rate: 0.9485
- retrieval_hit_rate: 0.4286
- source_correctness: 0.4286
- tool_schema_validity: 1.0
- guardrail_pass_rate: 1.0
- format_validity: 0.9485
- avg_latency_ms: 14188.21

## Category summary

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| agent | 3 | 1 | 0 |
| rag | 1 | 1 | 1 |
| tools | 3 | 0 | 0 |
| memory | 3 | 0 | 0 |
| teacher | 1 | 0 | 0 |
| student | 1 | 0 | 0 |
| safety | 1 | 0 | 0 |
| observability | 1 | 0 | 0 |

## Failed suites

- history_character_eval
- textbook_qa_eval

## Failed cases

- history_character_eval: suite_process_failed (llm_invoke_empty provider=anthropic model=kimi-k2.5
llm_invoke_empty provider=anthropic model=GLM-5.1
llm_invoke_empty provider=anthropic model=kimi-k2.5
llm_invoke_empty provider=anthropic model=GLM-5.1
Traceback (most recent call last):
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/eval/history_character_eval.py", line 151, in <module>
    asyncio.run(main())
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/asyncio/runners.py", line 195, in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/asyncio/base_events.py", line 691, in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/eval/history_character_eval.py", line 94, in main
    results = [await run_case(case) for case in cases]
               ^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/eval/history_character_eval.py", line 58, in run_case
    result = await graph.ainvoke(state)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langgraph/pregel/main.py", line 4105, in ainvoke
    async for chunk in self.astream(
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langgraph/pregel/main.py", line 3455, in astream
    async for _ in runner.atick(
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langgraph/pregel/_runner.py", line 396, in atick
    await arun_with_retry(
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langgraph/pregel/_retry.py", line 744, in arun_with_retry
    return await task.proc.ainvoke(task.input, config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langgraph/_internal/_runnable.py", line 733, in ainvoke
    input = await asyncio.create_task(
            ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langgraph/_internal/_runnable.py", line 501, in ainvoke
    ret = await self.afunc(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langchain_core/runnables/config.py", line 707, in run_in_executor
    return await asyncio.get_running_loop().run_in_executor(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/concurrent/futures/thread.py", line 59, in run
    result = self.fn(*self.args, **self.kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/.local/python3.12/lib/python3.12/site-packages/langchain_core/runnables/config.py", line 698, in wrapper
    return func(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/backend/agents/history_character.py", line 292, in generate_response
    resp = llm.invoke(build_generation_messages(state))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cengjiguang/Desktop/work/edu-agent-platform/backend/llm_config.py", line 99, in invoke
    raise RuntimeError(str(last_error) if last_error else "LLM request failed")
RuntimeError: anthropic/GLM-5.1 returned empty content
During task with name 'generate' and id '15b0bc15-3df4-7f29-51ee-b262350c20a3')
- textbook_qa_eval: 默认教材解释
- textbook_qa_eval: 默认教材重要性
- textbook_qa_eval: 默认教材考点

## AgentOps

Status: ok
Trace coverage: 0.52 (104/200 events)
Audit events: 100 total, 19 failed
Learning events: 100 total, 9 failed
Top actions: tool.allowed, tool.confirmation_required, tool.failed, tool.role_denied, tool.confirmation_confirmed, history_character.rag_multi_query
Top features: learning_assistant, auto_tutor, homework_grading, history, history_timeline, textbook_learning
Top tools: search_history_knowledge, delete_demo_memory, get_textbook_lesson, start_timeline_game, suggest_review_plan, recommend_character, generate_quiz
