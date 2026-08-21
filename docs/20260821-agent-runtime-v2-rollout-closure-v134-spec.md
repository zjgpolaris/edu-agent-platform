# EduAgent Agent Runtime v2 产品闭环与安全灰度 v1.34 Spec

**创建时间：** 2026-08-21
**实现基线：** `main@67fb18c` 之后的当前工作区
**状态：** Implemented locally · deterministic verification passed
**生产状态：** NOT_RUN；未执行部署、真实 LLM、production RAG 或 canary

## 1. 决策

v1.34 不扩展动态规划、并行检索或 Agent 委派。本轮只完成学习助手 Runtime v2 的产品闭环：

```text
用户消息
  → 稳定 idempotency key
  → 原产品 API 创建或复用 canonical run
  → 单一 stream_learning_assistant_events() 业务执行源
  → Runtime v2 milestone/event/artifact
  → waiting_confirmation
      → owner-scoped token refresh
      → confirm/cancel 同一个 run + expected revision
  → terminal message/run/event 一致
  → cursor replay / AgentOps / readiness gate
```

保留 `backend/agents/learning_assistant_runtime.py` 作为 v2 adapter facade；不创建第二套学习助手执行链。地图、推荐和游戏不迁移为开放式 Agent。

## 2. 本轮范围

### 2.1 Runtime Client State

前端维护：

```ts
type AgentRunClientState = {
  runId: string;
  runRevision: number;
  eventCursor: number;
  idempotencyKey: string;
  stepId?: string;
};
```

- 新用户 turn 生成一次 idempotency key；网络重试复用原 key。
- `run_started`、产品事件和 replay envelope 都更新同一份 client state。
- SSE 中断后从 `/events?after=<cursor>` 补 milestone/terminal；不补 token delta。
- terminal replay 不重复追加 user/assistant message。

### 2.2 Confirmation/Cancel

v2 bucket 使用：

- `POST /api/agent-runs/{run_id}/confirmation-token`
- `POST /api/agent-runs/{run_id}/confirm`
- `POST /api/agent-runs/{run_id}/cancel`

所有 mutation 携带 `expected_revision`。确认额外携带绑定 run、step、revision 的 token 和 correlation key。

token 规则：

- raw token 不写 `agent_run_events`；
- raw token 不写 assistant message metadata/tool result；
- 页面恢复时通过 owner-authenticated API 重新签发；
- stale revision 返回 409，客户端刷新 run 后不得自动执行工具。

未进入 v2 bucket 的请求保留 legacy confirmation 一个兼容周期。

### 2.3 Message/Run 一致性

- waiting message metadata 引用 `run_id/run_revision/event_cursor`。
- confirm 成功后，原 assistant message 更新为 completed，并替换同名工具结果。
- cancel 后，原 assistant message 更新为 cancelled。
- 同一 idempotency key 的顺序或并发 replay 不追加第二条 user/assistant message；同 key 不同内容返回冲突。
- confirm terminal artifact 使用标准 `final` envelope，后续 replay 可返回最终结果。

### 2.4 Deployment Readiness

新增只读检查：

```text
GET /api/admin/agent-runtime/readiness
```

ready 必须同时满足：

- Alembic version 为 `008`；
- `autotutor_sessions` 存在；
- `agent_runs/agent_run_events/agent_run_artifacts/agent_checkpoints/agent_side_effects` 全部存在。

SQLite 的自动建表只服务本地开发，不能替代部署迁移证明。

### 2.5 Evidence Verifier 配置

确定性 Evidence Verifier 是 grounded completion 的强制安全边界，不再在 `.env.example` 中暴露未生效的 enable/percent/threshold 开关。真实 LLM verifier 如需加入，必须另起证据门控 Spec。

## 3. API 合同

所有 Run 查询和 mutation 响应至少返回：

```json
{
  "run_id": "run_x",
  "run_revision": 8,
  "event_cursor": 9,
  "status": "waiting_confirmation"
}
```

确认请求：

```json
{
  "expected_revision": 8,
  "correlation_key": "confirm:run_x:8",
  "confirmation_token": "confirm_..."
}
```

取消请求：

```json
{
  "expected_revision": 8
}
```

## 4. 验收矩阵

### 4.1 离线合同

- confirmation token 绑定当前 waiting revision；
- persisted run events/messages 不包含 raw token；
- confirm/cancel 只修改原 run；
- stale confirmation/cancel 返回 409；
- terminal artifact 支持 idempotent replay；
- repeated chat idempotency key 不增加消息数；
- replay cursor 单调递增；
- schema readiness 对缺表/旧 Alembic fail closed。

### 4.2 必跑测试

- `agent_runtime_learning_assistant_api_smoke`
- `agent_runtime_confirmation_smoke`
- `agent_runtime_idempotency_smoke`
- `agent_runtime_stream_parity_smoke`
- `agent_runtime_security_smoke`
- `agent_runtime_schema_readiness_smoke`
- Runtime v2 全部专项 smoke
- 前端 unit、build、学习助手核心 Playwright flow
- SQLite migration smoke 与真实 PostgreSQL migration smoke

### 4.3 生产门禁

本地通过不代表生产通过。进入 10% canary 前必须记录部署 commit/config，并满足：

| 指标 | 门槛 |
| --- | ---: |
| event coverage | >=95% |
| terminal consistency | 100% |
| high-risk without confirmation | 0 |
| duplicate side effects | 0 |
| invalid transitions | 0 |
| unexpected failure rate | <=2% |
| p95 相对 legacy 回退 | <=10% |
| 10% canary | 连续 48 小时无 P0 |

建议灰度顺序：staging 100% shadow → production allowlist/1% active → 至少 100 个 terminal runs → 10%/48h。

## 5. 非目标

- semantic router/planner 扩量；
- dynamic re-plan、read fan-out、agent-as-tool；
- AutoTutor LangGraph 重写；
- queued/batch 作文迁移；
- L0 能力全面 Agent 化；
- 真实 LLM、production RAG 或教学增益的离线替代证明。

## 6. 回滚

```dotenv
EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS=0
```

必要时再启用全局 kill switch。回滚只影响新请求；已有 run/event/artifact 保留用于查询、确认安全取消和审计，不删除 Runtime 数据。
