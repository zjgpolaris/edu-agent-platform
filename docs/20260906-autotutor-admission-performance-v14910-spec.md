# AutoTutor 准入性能与验证失败证据 v1.49.10

日期：2026-09-06。代码基线：`c969b8b2c56b5d21123253a09f73f1f1f5a2e955`。
状态：代码已实现；真实 PostgreSQL 集成测试、生产性能与最终发布证据待验证。

## 背景与边界

历史验证 run `33975671710` 在 100 control / 20 committed Graph 时安全停止。
Comparator 匹配率 100%，fallback、重复副作用和越权为 0；Graph p95 为 25,502 ms，
Legacy p95 为 17,516 ms，差额 7,986 ms。不能把这段差额全部归因于缓存。

本轮不删除 Legacy、不改教学语义、不改样本或延迟门禁、不自动部署或放量。
“代码修复完成”和“final evidence GO”是两个独立状态。

## 已实现任务

### P0-1 分段观测

`agents/autotutor_timing.py` 使用 ContextVar 隔离请求，输出
`autotutor_transition_timing` JSON 到 `uvicorn.error.autotutor_timing` INFO logger。
只记录受控维度和耗时；不记录函数参数、学生输入、返回内容或异常消息。
verification run 与 transition ID 使用 SHA256，可与证据中相应 ID 的 SHA256 对照。

计时边界：

- `start_session`：函数进入到返回/抛出；包括 observation writer，不包括 HTTP 中间件。
- `_submit_answer_locked`：进入锁内业务函数到返回/抛出；不包括外层锁等待/HTTP 排队。
- `session_read`、`session_claim`、`session_schema`、`business_commit`、`runtime_start`、
  `trace_mirror`、`observation_write` 分别记录实际执行阶段。
- `admission`：evaluate 函数完整耗时；其内包含 `admission_schema`、
  `admission_writer_health`、`admission_wait`，不能相加后再计一次。
- answer 的 `admission_route` 包含提前 bypass/downgrade 和可能的 `admission` 调用。
- `execution_with_provider` 的子阶段使用现有 provider/executor/comparator diagnostics。
- 缺失字段代表该阶段未测量/未执行，不等于耗时 0。

日志 `total_ms` 不替换原有发布门禁 `latency_ms`，后者仍在 observation 写入前取值。
成功返回、幂等重放和异常均记录边界结果；未到达执行/观测阶段的失败可能没有 transition ID。
日志自身失败不得改变业务返回或异常。诊断不将不同分布的 p95 相减，也不将嵌套阶段求和。

### P0-2 缓存与并发

- TTL 保持 10 秒，从刷新完成并发布快照时开始计算。
- key 保持 environment / deployed commit / runtime state fingerprint。
- 每 key 一个在途 Event；同 key 请求等待最多 2 秒，不串行阻塞不同 key 的刷新。
- 等待超时返回 `unknown/admission_refresh_timeout`，不使用过期快照放行 Graph。
- clear 同时撤销在途 Event 的发布权，旧刷新不能重新填入缓存。
- 异常和 clear 都唤醒等待者；异常不缓存为成功。
- 每次调用仍先检查 kill switch、资格与配置，再读取基础设施缓存。

注意：2 秒是等待其他请求刷新的上限，不是数据库查询本身的执行超时。
leader 仍受现有数据库连接/查询行为约束。突发冷缓存请求可能 fail-closed 降级，
必须在真实环境观测，不能将此行为描述为延迟问题全部解决。

### P0-3 Schema 查询优化

一次 readiness 调用复用 Inspector，使用 `get_multi_columns` 读取实际存在的四类表。
所有必需表、字段和 revision 校验保持不变，查询异常仍 unavailable。
不引入跨调用 schema 缓存，不延长 writer-health 新鲜度；writer-health 独立查询保持不变。

共享测试 `eval/schema_reflection_checks.py` 在真实连接上计数旧反射方式和批量方式的 SQL，
输出查询次数/耗时，并用事务 savepoint 注入缺表、缺列、错误 revision 后回滚。
PostgreSQL CI 必须断言查询次数减少；SQLite 不承诺减少 PRAGMA 次数。
耗时报告是当前测试连接的诊断结果，不是生产性能证明。

### P0-4 失败回执与 P1 操作状态

traffic runner 在配置检查前、账号选择、登录、每次 transition 请求前后、安全检查和退出时
原子替换 checkpoint JSON。所有可捕获异常保留失败回执，CLI 非零退出，API 调用方仍收到异常。
不增加有副作用请求的重试策略；保留原有同 payload/idempotency-key 有界重试。
各网络调用 timeout 不超过剩余总预算，安全检查失败不再开启下一会话。

回执字段解释：

- `successful_responses`：客户端成功解析的 transition 响应数。
- `transitions_sent`：兼容旧消费端的上述计数别名，不是服务端提交数。
- `transition_request_attempts`：请求尝试数，包括原有重试。
- `server_confirmed_committed=null`：必须从服务端精确窗口快照验证，不能从 HTTP 200 推断。
- `request_outcome_unknown=true`：最后尝试未收到可确认结果，可能已提交。
- `complete=false/status=running`：最近检查点，可能由于进程强制终止而不完整。
- `complete=true/status=failed`：失败已落盘，不表示业务成功或发布通过。
- `error_code`：白名单代码；不透传异常正文、URL 或请求信息。
- `started_at/finished_at/control_window_start/safety_window_end`：运行和检查窗口，不改现有证据窗口算法。

SIGKILL、主机丢失、磁盘不可写不能保证最终回执或 artifact 上传，只能尽可能保留最后一次原子检查点。
Workflow Summary 展示 phase/status/stage、commit/config、计数、错误码和下一动作。
artifact 仍 always 上传；traffic failure 仍禁止生成成功 candidate/final evidence。

## 验收与测试入口

```sh
.venv/bin/python eval/autotutor_admission_performance_smoke.py
.venv/bin/python eval/autotutor_transition_timing_smoke.py
.venv/bin/python eval/autotutor_verification_traffic_smoke.py
.venv/bin/python eval/agent_runtime_schema_readiness_smoke.py
.venv/bin/python eval/autotutor_production_workflow_contract_smoke.py
.venv/bin/python scripts/release_gate.py --fast
```

真实 PostgreSQL：由现有 `postgres-migration` CI job 的 `eval/postgres_schema_smoke.py` 执行。
不得对生产库运行带 schema 故障注入的测试；仅限已迁移的 CI/一次性测试库。

## 发布验收（未执行）

1. 所有离线回归、PostgreSQL 查询计数/故障测试及 CI 通过，冻结新 SHA。
2. 保持 Legacy/BPS=0，部署后核验实际 commit/config；检查日志可用性。
3. 新 SHA 收集至少 100 control，不混用旧 SHA 的历史样本。
4. 经人工审批启用最大 100 BPS Canary，按类型/缓存状态分析分段耗时。
5. 满足原有安全/延迟门禁和至少 100 committed Graph，取得 candidate GO。
6. 依现有证据合同完成并绑定真实故障演练，不盲目沿用历史手填 pass。
7. 人工恢复 Legacy/BPS=0，收集至少 20 rollback control，final GO 并回读校验。
8. 仅当 `v150_entry_ready=true` 才进入单执行器收敛。

任一步失败：停止新增流量，保持或恢复 Legacy/BPS=0，使用回执和分段日志定位。
若修复后仍不满足相对 20% / 绝对 50ms 的既有延迟限制，单独评审性能预算；本轮不调整阈值。
