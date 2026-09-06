# AutoTutor production verification 操作说明

所有阶段使用同一个完整 commit SHA、生产配置版本和已批准 cohort。代码变更并部署新 commit 后，应重新采集该 commit 的 control 基线。不要用旧版本证据替代。

## v1.49.10 失败诊断与性能修复

实现及验收边界见 [准入性能 spec](20260906-autotutor-admission-performance-v14910-spec.md)。
本地测试成功不等于 PostgreSQL CI 或生产 final GO。当前修复发布前保持 Legacy/BPS=0。

- 先读 Job Summary 的 traffic `stage/error_code/next_action`，再对照服务端精确窗口快照。
- `successful_responses`（兼容字段 `transitions_sent`）是客户端响应数量，不是服务端提交数量。
  重试可能返回幂等结果，服务端样本要求仍以 snapshot 为准。
- `request_outcome_unknown=true` 表示超时/断连可能发生在服务端提交之后，不得据此创建新请求重复执行。
- `complete=false` 是最后一个运行检查点；`complete=true/status=failed` 是完整失败记录，不是验证通过。
- 遇到 `verification_safety_stop:active_latency_regression`，停止新验证流量，人工恢复 Legacy/BPS=0。
  在 Render 日志搜索 `autotutor_transition_timing`，按 commit/config、transition_kind、cache_state 分组查看。
- `admission` 内包含 schema/health/wait 子阶段，`execution_with_provider` 内包含 provider/executor/comparator；
  不重复求和、不将不同分布的 p95 相减。日志 total 包含观测写入，发布门禁 latency 不包含，不能混用。
- `admission_refresh_timeout` 是同 key 等待刷新超过 2 秒后的 fail-closed 拒绝，不是可忽略告警。
  检查 leader 的 schema/health 耗时；不要延长 TTL、提高 BPS 或放宽门禁来绕过。

## 发布流程

受控演练工具见 [v1.49.11 安全边界和运行步骤](20260906-autotutor-scoped-rehearsals-v14911-spec.md)。
Canary 的 `build_candidate_evidence` 默认为 false，先采样再审查完整演练证据。
只有完整生产演练已验证时才显式开启 candidate 构建；scoped writer probe 不能代替完整 writer-failure attestation。
演练 runner 不产生 production GO，不能因为它绿色就填写三项 pass。

Canary 和 rollback 任务会先安装被验证 commit 的受约束 runtime 依赖并检查 evidence builder 能否导入，再开始流量采集。如果只需修复工作流编排，可以从环境已允许的独立分支手动运行修复后的 workflow，`expected_commit` 仍指定当前线上版本：工作流会检查该线上版本的成功 push CI、checkout 该完整 SHA，并验证其属于 main 历史。仅当修复没有改变受验证的应用代码时使用这种方式，且不得省略 production-verification 人工审批。若环境只允许 main，不得自行放宽分支规则；需要管理员明确授权特定分支，或按 main 发布流程处理。

1. 在 Render 使用 `legacy`、`active_bps=0`，等待部署完成并核对 commit。
2. 运行 `control_snapshot`，`generate_controlled_traffic=true`、`target_transitions=100`。检查 traffic receipt 的 `target_reached=true`，以及验证 artifact 中至少 100 条 control。记录 `autotutor-verification.json` 的 `result.snapshot.slice.since`。
3. 同 commit 切换 `active_canary`、`active_bps=100`（1%）。运行 `canary_snapshot`，生成至少 100 条受控转换，**将上一步的 `slice.since` 填入 `window_start`**。生成流量时 `window_end` 由本轮结束时间产生。
4. Canary 在发流量前查询这个起点至当前的窗口，核对同 commit、配置版本的 control 数量至少 100 且有 p95。最终快照沿用此起点，纳入 control 和 Graph；SQL 仍按 commit、配置版本、环境、可信 cohort 和 runtime 数据筛选，窗口最多七天。不要缩短窗口以排除其中失败的 Graph 样本。
5. 检查 candidate evidence 为 `CANDIDATE_GO`。恢复同 commit 的 `legacy`、`active_bps=0`，运行 `rollback_verify`，生成至少 20 条 control。回滚窗口仅使用本轮流量开始/结束时间，不沿用 Canary 的起点。
6. 确认 final evidence 已持久化且 decision 为 `GO`，再读 preflight 确认 `v150_entry_ready=true`。

预检 GET 最多尝试六次，总预算最多 180 秒，并受整轮流量时限约束；仅网络异常和 HTTP 502/503/504 会重试。认证错误和无效响应立即停止。日志与失败 traffic receipt 记录阶段、尝试次数、耗时和安全错误码，不含请求凭据或响应正文。此重试策略不代表服务端慢请求的原因已经解决，持续超时仍需检查 Render 同期请求、部署、健康检查和数据库等待。

流量步骤使用 `continue-on-error` 是为了保留诊断 artifacts。启用 `release_required` 时，流量失败仍会使发布验证失败，并且不会生成 candidate/final evidence。人工审批 rehearsal 的 `pass` 必须对应实际完成的演练。

若需只读重建快照，设置 `generate_controlled_traffic=false` 并提供完整、可追溯的 `window_start` / `window_end`；不要用这个模式掩盖失败采样。
