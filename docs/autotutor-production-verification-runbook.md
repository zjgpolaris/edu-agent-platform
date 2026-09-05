# AutoTutor production verification 操作说明

所有阶段使用同一个完整 commit SHA、生产配置版本和已批准 cohort。代码变更并部署新 commit 后，应重新采集该 commit 的 control 基线。不要用旧版本证据替代。

1. 在 Render 使用 `legacy`、`active_bps=0`，等待部署完成并核对 commit。
2. 运行 `control_snapshot`，`generate_controlled_traffic=true`、`target_transitions=100`。检查 traffic receipt 的 `target_reached=true`，以及验证 artifact 中至少 100 条 control。记录 `autotutor-verification.json` 的 `result.snapshot.slice.since`。
3. 同 commit 切换 `active_canary`、`active_bps=100`（1%）。运行 `canary_snapshot`，生成至少 100 条受控转换，**将上一步的 `slice.since` 填入 `window_start`**。生成流量时 `window_end` 由本轮结束时间产生。
4. Canary 在发流量前查询这个起点至当前的窗口，核对同 commit、配置版本的 control 数量至少 100 且有 p95。最终快照沿用此起点，纳入 control 和 Graph；SQL 仍按 commit、配置版本、环境、可信 cohort 和 runtime 数据筛选，窗口最多七天。不要缩短窗口以排除其中失败的 Graph 样本。
5. 检查 candidate evidence 为 `CANDIDATE_GO`。恢复同 commit 的 `legacy`、`active_bps=0`，运行 `rollback_verify`，生成至少 20 条 control。回滚窗口仅使用本轮流量开始/结束时间，不沿用 Canary 的起点。
6. 确认 final evidence 已持久化且 decision 为 `GO`，再读 preflight 确认 `v150_entry_ready=true`。

预检 GET 最多尝试六次，总预算最多 180 秒，并受整轮流量时限约束；仅网络异常和 HTTP 502/503/504 会重试。认证错误和无效响应立即停止。日志与失败 traffic receipt 记录阶段、尝试次数、耗时和安全错误码，不含请求凭据或响应正文。此重试策略不代表服务端慢请求的原因已经解决，持续超时仍需检查 Render 同期请求、部署、健康检查和数据库等待。

流量步骤使用 `continue-on-error` 是为了保留诊断 artifacts。启用 `release_required` 时，流量失败仍会使发布验证失败，并且不会生成 candidate/final evidence。人工审批 rehearsal 的 `pass` 必须对应实际完成的演练。

若需只读重建快照，设置 `generate_controlled_traffic=false` 并提供完整、可追溯的 `window_start` / `window_end`；不要用这个模式掩盖失败采样。
