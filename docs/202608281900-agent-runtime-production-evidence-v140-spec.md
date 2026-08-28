# EduAgent Runtime v2 生产证据供应链 v1.40 Spec

**日期：** 2026-08-28
**基线：** `main@91b8ce1`
**状态：** 代码实现完成；外部环境验收 NOT_RUN

## 1. 迭代结论

v1.40 不扩展多 Agent、动态规划或 AutoTutor 图重写。本轮关闭 v1.39 的发布证据缺口：生产门禁只接受与部署 commit、Runtime config、运行模式和环境一致的服务端证据，并明确区分“幂等保护成功”与“重复副作用实际发生”。

```text
服务端 terminal observation
  → 同环境 control baseline（>=100）
  → clean commit 的 offline + real LLM + production RAG 报告
  → hash-bound rollout evidence
  → PostgreSQL 持久化
  → /api/ready?require_runtime=true
  → per-agent rollout gate
```

## 2. 已实现范围

### 2.1 可信观测与持久证据

- Alembic head 升至 `011`，新增 `agent_rollout_observations` 与 `agent_release_evidence`；
- 历史人物 control/shadow/active 路径记录 terminal latency、状态、trace ID、commit/config/environment，不保存学生输入或模型正文；
- control baseline 只聚合同环境、同 commit/config、`data_scope=runtime` 的服务端观测；幂等 replay 不进入延迟基线；
- evidence 入库前校验 manifest/baseline hash、三类 profile、commit、环境、时间新鲜度和来源。

### 2.2 Fail-closed 发布门禁

- 三类报告必须来自相同 clean deployed commit，生成时间不得超过 7 天；
- `offline`、`real_llm`、`production_rag` 任一 NOT_RUN/fail/stale 均不能生成证据；
- `/api/ready?require_runtime=true` 要求部署 provenance、Alembic 011 和当前切片的持久 evidence；
- Runtime 关闭返回 `disabled`，不会被解释成通过；
- 文件证据缺失时可从数据库加载同 agent/config/mode/commit 的最新 hash-bound evidence。

### 2.3 指标语义修正

| 指标 | 判定 |
| --- | --- |
| `duplicate_side_effect_executed` | blocking failure |
| `duplicate_side_effect_prevented` | informational，证明保护生效 |
| `tool.idempotent_replay` | informational，不重复执行工具 |
| invalid transition | blocking failure |
| high risk without confirmation | blocking failure |
| event coverage <95% | 非 pass；<80% 为 failure |
| p95 regression >10% | blocking failure |

### 2.4 PostgreSQL 与 CI

- Docker Compose 使用 PostgreSQL 16 + pgvector，先迁移再启动 API；
- CI 增加 pgvector service、Alembic head migration 与 schema smoke；
- evidence workflow 始终上传 pass/fail/not_run 状态文件，手动 release-required 运行遇到 NOT_RUN 会失败；
- production readiness 先生成 production RAG 报告，再以 strict Runtime readiness 验收。

## 3. 验收标准

代码/CI 验收：

1. Python 文件可编译，YAML/Compose 可解析，`git diff --check` 通过；
2. rollout/evidence/migration/readiness smoke 纳入 release gate；
3. PostgreSQL job 可迁移至 `011`，新增表和索引存在；
4. stale、dirty、commit mismatch、profile NOT_RUN、baseline 不足均 fail-closed；
5. prevented/replay 计数不再误判为重复副作用。

外部环境验收（不得由本地 deterministic smoke 替代）：

1. staging control 至少 100 个 terminal observations；
2. 当前 clean commit 的 offline、真实 LLM、production RAG 三份报告；
3. staging shadow 至少 100 个 terminal runs，gate 为 pass；
4. production 1% canary 至少 100 个 terminal runs，随后 10% 持续 48 小时；
5. 任何 gate fail/unknown 均停止扩量，使用既有 Runtime kill switch 回退。

## 4. 当前证据状态

- 代码与静态合同：已实现；
- 本机 PostgreSQL/pgvector：NOT_RUN（本机无 Docker）；
- 完整 Python smoke：NOT_RUN（本机磁盘不足，未安装完整依赖）；
- 真实 LLM、production RAG、staging/production traffic：NOT_RUN（需要 CI/部署密钥与真实流量）；
- 因此本文件不宣称生产 canary 已通过，只声明迭代代码已经具备采集和 fail-closed 判定能力。
