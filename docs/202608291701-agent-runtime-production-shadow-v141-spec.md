# EduAgent Runtime v2 生产迁移、证据编排与 Shadow 验收 v1.41 Spec

**创建时间：** 2026-08-29 17:01 CST
**代码基线：** `main@7ca2785`
**目标环境：** Render production + PostgreSQL/pgvector
**状态：** Implementation complete · dependency/PostgreSQL validation pending CI · Operational NOT_RUN

## 0. 决策摘要

v1.41 不继续增加 Agent、LangGraph、多 Agent 或动态规划能力。本轮处理 v1.40 已实现但尚未在生产闭环的部分：安全完成 PostgreSQL `003 → 011` 迁移，补齐 Run provenance，自动编排可信评测证据，并完成 `history_character` 的 control 与 shadow 验收。

```text
生产迁移预检
  → PostgreSQL 003 升级 011
  → control 真实观测 >=100
  → offline + real LLM + production RAG
  → hash-bound evidence 入库
  → history_character 100% shadow
  → shadow terminal runs >=100
  → rollout gate PASS
```

本轮仍遵循 [`202608280000-agent-runtime-langgraph-boundary-adr.md`](202608280000-agent-runtime-langgraph-boundary-adr.md)：Runtime 负责治理、持久化和发布合同，LangGraph 负责图内调度。

## 1. 当前生产事实

2026-08-29 对公开生产后端执行只读检查：

```text
GET https://edu-agent-backend-1e5x.onrender.com/api/health
GET https://edu-agent-backend-1e5x.onrender.com/api/ready?require_runtime=true
```

结果：

| 项目 | 当前状态 |
| --- | --- |
| deployed commit | `7ca278508db8cb61aae8014b18a991c6197e95e7` |
| API liveness | PASS |
| database | PostgreSQL，PASS |
| pgvector | PASS |
| history collection | 2850 documents |
| LLM 配置 | PASS |
| embedding 配置 | PASS |
| Alembic revision | `003` |
| 代码要求 revision | `011` |
| Runtime config version | 缺失 |
| Runtime v2 | disabled |
| rollout evidence | 缺失 |
| latest eval | 缺失 |
| strict Runtime readiness | FAIL |

生产数据库尚缺少 `004-011` 的 Agent Job、Assistant Session、Runtime Run/Event/Artifact、side-effect ledger、独立复习证据和 rollout evidence schema。继续开发上层 Agent 能力会扩大“代码合同领先于生产数据库”的风险。

## 2. 目标与非目标

### 2.1 本轮目标

1. 提供可重复、互斥、失败即停止启动的生产迁移入口；
2. 在 production-shaped PostgreSQL 上证明 `003 → 011` 不破坏既有数据；
3. 每个 rollout Run 绑定真实 commit、environment、config 和 mode；
4. 自动生成并持久化同一 deployed commit 的三类发布证据；
5. 收集不少于 100 个真实 control observations；
6. 完成 `history_character` 100% observable shadow，不改变学生最终回答；
7. 收集不少于 100 个 shadow terminal runs，并使 rollout gate 达到 PASS；
8. 样本、凭证或外部条件不足时准确返回 `NOT_RUN/unknown`。

### 2.2 非目标

- 多 Agent 委派、仲裁或 agent-as-tool；
- dynamic re-plan、read fan-out 或开放式 ReAct；
- AutoTutor LangGraph 重写；
- checkpoint/resumable 扩展到历史人物；
- production active 1% 或更高比例扩量；
- 使用 demo/eval/合成流量冒充真实 production runtime 样本；
- 证明真实学生学习效果或 24 小时保持效果。

## 3. P0：生产迁移闭环

### 3.1 迁移入口

新增受控入口，例如：

```text
backend/start_backend.py
  → acquire PostgreSQL advisory lock
  → inspect current revision
  → alembic upgrade head
  → verify revision + required tables/columns
  → release lock
  → exec uvicorn
```

要求：

- 数据库迁移发生在 API 接受请求之前；
- 使用固定 advisory lock key，避免多实例并发迁移；
- 配置 `lock_timeout` 和 `statement_timeout`；
- 生产迁移使用独立 `DIRECT_URL`/session connection；transaction pooler 不承担 advisory lock；
- 输出结构化迁移结果：from/to revision、duration、status、failure stage；
- 迁移失败时进程非零退出，不启动 API；
- 已在 `011` 时快速 no-op；
- 不在 FastAPI lifespan 内隐式执行 Alembic；
- 不在生产执行自动 downgrade。

当前服务使用 Render free plan。Render 官方 `preDeployCommand` 适用于付费 Web Service，因此本轮使用 Docker 启动前的受控迁移入口；升级付费计划后再迁移到 pre-deploy command：<https://render.com/docs/deploys>。

### 3.2 生产形态迁移验证

新增 PostgreSQL migration rehearsal：

1. 创建 PostgreSQL + pgvector；
2. 迁移到 `003`；
3. 写入 production-shaped 账号、学习事件、审计、复习会话、AutoTutor 会话和 RAG 文档；
4. 记录关键表 row count 和内容 hash；
5. 迁移到 `011`；
6. 验证旧数据保持、新字段默认值正确、新索引存在；
7. 再执行一次 `upgrade head`，验证 no-op；
8. 执行关键读写 smoke。

需要特别覆盖：

- `audit_events.data_scope`、`learning_events.data_scope` 默认值；
- `autotutor_sessions` 新增 revision/idempotency/hash 字段；
- `learning_events.effect_key` 唯一索引对 NULL 和既有数据兼容；
- `review_sessions` 既有唯一约束与新增 revision/replay 字段；
- `agent_runs`、events、artifacts、checkpoints、side effects；
- `agent_rollout_observations` 和 `agent_release_evidence`；
- `rag_documents` 数量与 pgvector extension 不受影响。

### 3.3 回滚边界

所有 `004-011` 变更以新增表、列和索引为主。生产回滚策略：

- 回滚应用镜像；
- 设置 `EDU_AGENT_RUNTIME_V2_KILL_SWITCH=true`；
- 设置 `EDU_AGENT_RUNTIME_V2_ENABLED=false`；
- 保留 `011` schema 和已写证据；
- 禁止自动执行 `alembic downgrade`；
- 如发生数据级异常，使用迁移前数据库快照恢复，而不是依赖破坏性 downgrade。

## 4. P0：Run Provenance 完整性

### 4.1 当前缺口

v1.40 evidence 已绑定 deployed commit/environment，但 rollout gate 的 Run 指标主要按 `agent_type + config_version + runtime_mode` 聚合。若同一个 config version 被多个 commit 复用，可能混入旧 Run。

### 4.2 合同

每个 Runtime Run 的可信服务端上下文必须包含：

```json
{
  "agent_type": "history_character",
  "config_version": "v1.41-history-shadow",
  "runtime_mode": "shadow",
  "deployed_commit": "<sha>",
  "environment": "production",
  "data_scope": "runtime"
}
```

要求：

- 在创建 Run 时由服务端写入 commit/environment；
- 不接受客户端提供或覆盖 provenance；
- rollout gate 同时按 agent/config/mode/commit/environment/scope 过滤；
- 增加 `run_provenance_coverage`；
- provenance coverage 小于 100% 时不得 PASS；
- 旧 Run 缺少 provenance 时排除并报告数量；
- Runtime 启用时 config version 为空或仍为过时默认值应 fail-closed；
- Runtime 配置统一从 `backend/deployment.py` 读取，避免不同模块默认值不一致。

### 4.3 观测失败

业务请求不应因为非关键 rollout observation 写入失败而失败，但也不能静默隐藏：

- observation 继续 fail-safe；
- 记录限频、无学生内容的审计或内部计数；
- AgentOps 展示 observation write failures；
- schema 缺失和 DB 失败可区分；
- readiness 在持续观测失败时返回 warning/fail，而非 PASS。

## 5. P0：发布证据工作流编排

### 5.1 新工作流

新增 `.github/workflows/runtime-rollout-evidence.yml`，只允许手动触发，并使用受保护的 `production` environment。

输入：

```text
deployed_commit
agent_type
target_config_version
runtime_mode = shadow | active
baseline_config_version
baseline_commit
environment
minimum_samples
ready_url
```

### 5.2 执行顺序

同一次 workflow 必须：

1. checkout 指定 commit；
2. 验证工作区 clean；
3. 查询线上 `/api/ready`，确认 deployed commit 一致；
4. 运行完整 offline core 并保存报告；
5. 运行 real LLM profile 并保存报告；
6. 运行 production RAG profile 并保存报告；
7. 使用只读聚合查询构建 control baseline；
8. 生成 hash-bound rollout evidence；
9. 使用生产 `DATABASE_URL` 持久化 evidence；
10. 重新查询 strict readiness；
11. 查询 per-agent rollout gate；
12. 上传聚合报告、状态文件和 evidence manifest。

### 5.3 Fail-closed 条件

以下任一情况必须失败且不得入库：

- workflow commit 与 deployed commit 不一致；
- Git revision dirty；
- 任一报告超过 7 天或 generated_at 在未来；
- offline、real LLM、production RAG 任一 `NOT_RUN/fail/stale`；
- real LLM 没有 run-scoped calls；
- production RAG 未真实访问目标生产环境；
- baseline 环境、commit、config 不匹配；
- baseline 样本不足；
- evidence hash 或 baseline hash 不一致。

### 5.4 Artifact 安全

上传内容仅允许：

- 聚合指标；
- commit/config/environment/provider/model；
- eval run ID；
- status/reason；
- evidence/baseline hash；
- 样本数量和延迟分位数。

禁止上传：

- 学生输入和模型完整回答；
- 原始 trace/artifact；
- prompt、confirmation token；
- 数据库连接串和 API key；
- 私有盲测原始数据。

## 6. P1：历史人物 Control 与 Shadow

### 6.1 Phase A：Control

生产配置：

```dotenv
EDU_AGENT_ENVIRONMENT=production
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.41-history-control
EDU_AGENT_RUNTIME_ROLLOUT_AGENT_TYPE=history_character
EDU_AGENT_RUNTIME_V2_ENABLED=false
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=0
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=0
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=true
EDU_AGENT_RUNTIME_V2_KILL_SWITCH=false
```

目标：

- 原有产品链路不变；
- 只记录无内容的 control terminal observation；
- 累计至少 100 个真实 production terminal observations；
- demo/eval 数据使用对应 data scope，不进入 baseline；
- baseline 绑定 control commit/config/environment。

### 6.2 Phase B：100% Observable Shadow

在 control baseline 合格并生成当前 commit 的三类 profile 后切换：

```dotenv
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.41-history-shadow
EDU_AGENT_RUNTIME_V2_ENABLED=true
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=true
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=10000
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=10000
EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED=true
EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED=false
EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED=false
EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED=false
EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED=false
```

Shadow 定义：

- 使用原有历史人物业务执行结果；
- Runtime 记录 Run/Event/Artifact 和 completion；
- 不进行第二次 LLM 调用；
- 不改变用户可见答案、来源和 SSE 合同；
- 不启用 checkpoint/resume；
- 不引入额外工具写副作用。

## 7. Rollout Gate

### 7.1 必须 PASS 的指标

| 指标 | 门槛 |
| --- | ---: |
| Alembic revision | `011` |
| deployed commit/config | 存在且一致 |
| control terminal observations | >=100 |
| shadow terminal runs | >=100 |
| run provenance coverage | 100% |
| event coverage | >=95% |
| terminal consistency | 100% |
| unexpected failure rate | <=2% |
| `duplicate_side_effect_executed` | 0 |
| invalid transitions | 0 |
| high-risk without confirmation | 0 |
| latency sample count | >=100 |
| p95 regression | <=10% |
| offline profile | PASS |
| real LLM profile | PASS |
| production RAG profile | PASS |

### 7.2 状态语义

- `pass`：所有 blocking 条件满足；
- `warn`：未超过失败线，但达到预警线，例如 p95 regression 5%-10%；
- `fail`：安全、状态一致性、失败率或延迟超过硬门槛；
- `unknown`：样本、schema、provenance、baseline 或外部证据不足；
- `NOT_RUN`：外部 profile 未实际执行。

不得通过降低 `minimum_terminal_runs`、混入 eval/demo 数据或重用旧 evidence 将 `unknown/NOT_RUN` 改成 PASS。

## 8. API 与 AgentOps

### 8.1 Strict readiness

```text
GET /api/ready?require_runtime=true
```

必须展示：

- deployed commit/config/environment；
- Alembic current/required revision；
- rollout agent type/mode；
- evidence hash、生成时间和三个 profile 状态；
- evidence 与实例 provenance 是否匹配；
- 不返回密钥、学生内容或内部 Artifact。

### 8.2 Per-agent gate

```text
GET /api/admin/agent-runtime/rollout-readiness
    ?agent_type=history_character
    &window_hours=24
    &minimum_terminal_runs=100
```

新增或确认输出：

```text
deployed_commit
environment
run_provenance_coverage
excluded_missing_provenance_runs
observation_write_failures
duplicate_attempts_prevented
idempotent_replays
duplicate_side_effects
control_baseline
p95_regression
profiles
reasons
```

## 9. 实现任务映射

| 区域 | 任务 |
| --- | --- |
| `backend/Dockerfile` | 使用受控 backend startup entrypoint |
| `render.yaml` | 补齐 production/runtime 安全默认配置和迁移说明 |
| `backend/start_backend.py` / `scripts/` | migration runner、preflight 与发布校验脚本 |
| `backend/deployment.py` | 统一 commit/config/environment 读取和校验 |
| `backend/agent_runtime/context.py` | 移除过时默认 config，Runtime enabled 时 fail-closed |
| `backend/agent_runtime/event_store.py` | Run 写入可信 provenance |
| `backend/agent_runtime/rollout_gate.py` | 按 commit/environment 过滤并计算 provenance coverage |
| `backend/agent_runtime/rollout_observations.py` | 观测失败分类与聚合 |
| `backend/agent_ops.py` | 暴露 provenance/observation health |
| `backend/api/routers/debug.py` | strict readiness 公开安全摘要 |
| `.github/workflows/` | 单次、受审批的 Runtime evidence workflow |
| `eval/` | PostgreSQL 003→011、provenance、workflow contract smoke |
| `README.md` | control/shadow 操作命令和状态语义 |

## 10. 测试计划

### 10.1 Deterministic

- Runtime config fail-closed；
- Run provenance 不可由客户端伪造；
- gate 排除 missing/mismatched provenance；
- observation 写失败不破坏用户请求，但产生健康计数；
- stale/dirty/mismatched profile 禁止生成 evidence；
- evidence 重复持久化幂等；
- prevented/replay 不算重复副作用；
- strict readiness 在 schema/config/evidence 任一缺失时失败。

### 10.2 PostgreSQL

- fresh `head` migration；
- production-shaped `003 → 011`；
- 重复 `upgrade head`；
- advisory lock 并发；
- migration failure 不启动 API；
- Runtime 并发 Run/Event/side-effect 写入；
- 旧数据 row count/hash 保持。

### 10.3 外部/生产

- real LLM：必须观测真实 run-scoped call；
- production RAG：真实 API、embedding、pgvector 和 history collection；
- control：100 个真实 terminal observations；
- shadow：100 个真实 terminal runs；
- 生产窗口内无 P0/P1 安全或一致性事故。

## 11. 发布阶段与停止条件

### 阶段 0：Migration only

- Runtime 保持 disabled；
- 执行 `003 → 011`；
- shallow readiness、核心学生/教师路径和 RAG smoke 通过。

停止条件：迁移失败、旧数据不一致、核心路径回归失败。

### 阶段 1：Control collection

- 配置 `v1.41-history-control`；
- 累计 100 个真实 terminal observations；
- 生成可信 baseline。

停止条件：观测写入持续失败、数据库延迟异常、无法区分 runtime 与 eval/demo。

### 阶段 2：Shadow

- 配置 `v1.41-history-shadow`；
- 100% history_character observable shadow；
- 累计 100 个 terminal runs；
- rollout gate 必须 PASS。

停止条件：任何 duplicate executed、invalid transition、high-risk violation、terminal inconsistency、失败率或 p95 超线。

### 阶段 3：稳定观察

- gate PASS 后继续观察至少 48 小时；
- 本轮仍不切 active；
- 输出 v1.41 production evidence report。

## 12. 完成定义

### 12.1 Development Complete

必须同时满足：

1. startup migration、advisory lock 和 post-migration verification 完成；
2. production-shaped PostgreSQL `003 → 011` 测试通过；
3. Run provenance coverage 合同完成；
4. evidence workflow 和 fail-closed 测试完成；
5. Runtime/evidence/PostgreSQL/full release gate 通过；
6. 文档明确外部证据状态，不把 deterministic PASS 写成生产 PASS。

### 12.2 Operational Complete

必须同时满足：

1. 生产数据库 revision 为 `011`；
2. strict readiness 中 deployment/schema/evidence 全部 PASS；
3. control baseline >=100；
4. shadow terminal runs >=100；
5. per-agent rollout gate 为 PASS；
6. 48 小时稳定观察无 P0；
7. 证据报告绑定生产 commit/config/environment；
8. GitHub artifact 不包含学生内容或密钥。

如果真实流量不足，状态保持 `Operational NOT_RUN/unknown`，不得缩小样本门槛宣称完成。

### 12.3 2026-08-29 实现记录

仓库实现已覆盖 startup migration/advisory lock/postcheck、`003 → 011` production-shaped rehearsal、服务端 Run provenance、observation health、strict readiness、AgentOps、evidence workflow 与 fail-closed smoke，并已接入 release gate/CI。

当前本机仅完成 Python 语法、YAML、workflow contract 和 diff 检查。因本机 Python 依赖未安装、无 Docker/PostgreSQL 且磁盘空间不足，依赖型 Runtime smoke、真实 PostgreSQL rehearsal 与完整 release gate 状态为 **NOT_RUN（待 CI）**，不能据此标记 Development Complete。生产迁移、control/shadow 样本和 48 小时观察均未执行，Operational 状态保持 **NOT_RUN/unknown**。

## 13. 后续版本

v1.41 Operational Complete 后建议：

1. **v1.42 真实教学效果证据**：教师盲审、初中生可理解性、真实 24h retention；
2. **v1.43 history_character active canary**：allowlist → 1% → 10%，每阶段独立 evidence；
3. 再根据真实 failure/latency 数据决定是否扩展 Runtime 到 AutoTutor，而不是预先重写。
