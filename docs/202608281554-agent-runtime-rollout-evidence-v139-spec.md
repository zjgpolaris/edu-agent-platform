# EduAgent Agent Runtime v2 灰度证据与发布门禁 v1.39 Spec

**创建时间：** 2026-08-28
**分析基线：** `main@71e3da9` + 本地 Runtime/LangGraph 纵向切片
**状态：** Milestone A/B Implementation Complete · release evidence pending · C/D NOT_RUN
**生产状态：** NOT_RUN；尚无本版本真实 LLM、production RAG、PostgreSQL migration 或 canary 证据

**2026-08-28 实施记录：** 已实现 per-agent rollout 聚合、证据与 baseline hash 校验、管理员只读 API、AgentOps `rollout_gates`、延迟/安全门禁 smoke、Runtime/Eval 依赖分层，以及 `dev-setup/dev/verify-runtime/verify-release` 入口。`make verify-runtime` 当前 6/6 suites 通过；完整离线 smoke 为 84/85 suites、405/406 cases，唯一 skip 是缺少外部真实 LLM/RAG 条件的 `history_character_smoke`；前端 22/22 tests 与 production build 通过。release workspace gate 已验证会拒绝脏工作区、意外根 lockfile、旧 Eval revision、缺少 deployed commit/config 和缺少真实 profile 证据。全新环境完整联网安装、PostgreSQL、真实 LLM/RAG、staging 100 runs 与 production canary 仍为 NOT_RUN。

## 0. 决策

v1.39 不继续扩展 dynamic re-plan、read fan-out、Agent 委派或 AutoTutor LangGraph 重写。本轮把 Runtime v2 从“本地合同通过”推进到“具备可复现环境、可计算灰度门禁和可审计发布证据”。

本轮核心路径：

```text
依赖与工作区收口
  → clean commit + 可复现 Python/Node 环境
  → 当前 commit 的 deterministic verification
  → per-agent Runtime rollout gate
  → staging 100% observable/shadow
  → 真实 LLM + production RAG + PostgreSQL readiness
  → production allowlist / 1%
  → 至少 100 个 terminal runs
  → gate pass
  → 10% / 48h
```

Runtime v2 继续遵循 [`202608280000-agent-runtime-langgraph-boundary-adr.md`](202608280000-agent-runtime-langgraph-boundary-adr.md)：Runtime 拥有业务治理合同，LangGraph 拥有图调度和图内部状态。

## 1. 当前事实与缺口

### 1.1 已具备

- `AgentContext/Plan/State/Event/Completion`、Run/Event/Artifact、CAS、side-effect ledger；
- owner/role/data scope、Tool/Capability allowlist、高风险确认；
- SSE cursor replay、terminal artifact、取消和受控恢复；
- Runtime v2 全部专项 smoke 本地通过；
- 历史人物 stream/non-stream 已共同消费 compiled LangGraph + `LangGraphAdapter`；
- `product_event/generation_delta/heartbeat` 被定义为瞬时事件，不写 Runtime event store；
- 本地 smoke 结果为 82/83 suites、405/406 cases；唯一 skip 为缺少外部 LLM/RAG 条件的 `history_character_smoke`。

### 1.2 尚不具备

- `.env.local` 未启用任何 Runtime v2 rollout、artifact、checkpoint 或 recovery 开关；
- 最新持久化 Eval 报告仍早于当前 commit，不能作为发布证据；
- `history_character_eval`、真实 LLM、production RAG、真实 PostgreSQL migration 未闭环；
- AgentOps 有原始指标，但没有按 Agent 自动输出 canary `pass/warn/fail`；
- 现有通用 readiness 的 trace coverage 通过线为 80%，低于 rollout 需要的 95%；
- active 相对 control 的 p95 基线没有带 commit/config 的持久证据；
- Python 只有宽范围 `requirements.txt`，Runtime/Eval 依赖未拆分锁定，完整安装存在 resolver 回溯；
- 本地启动可能产生根目录 `package-lock.json` 和非业务性的 lockfile 漂移，发布前缺少工作区卫生检查。

## 2. 目标与非目标

### 2.1 本轮目标

1. 新环境可使用固定命令完成依赖安装、启动和 Runtime smoke；
2. 发布证据绑定 commit、配置版本、模型、provider、数据集和运行环境；
3. AgentOps 按 `agent_type + config_version + runtime_mode` 计算 rollout gate；
4. 没有足够样本、基线或 schema readiness 时返回 `unknown`，禁止错误显示 `pass`；
5. 历史人物完成 staging observable/shadow 验证和 production 1% 前置准备；
6. 明确保留未运行证据，不以离线 deterministic 测试替代生产结论。

### 2.2 非目标

- 把历史人物立即拆成多节点可恢复图；
- AutoTutor 状态机重写；
- semantic router/planner 扩量；
- dynamic re-plan、read fan-out、agent-as-tool；
- 开放式 ReAct、动态创建 Agent、并行写；
- 用 SQLite smoke 代替 PostgreSQL migration 证明；
- 用 fallback 输出代替真实 LLM/RAG 质量证明。

## 3. 依赖与开发环境收口

### 3.1 Python 依赖分层

目标结构：

```text
backend/requirements-runtime.txt  # API、Runtime、LangGraph、RAG 运行依赖
eval/requirements-eval.txt        # ragas、数据集与离线评测依赖
constraints.txt 或 uv.lock        # CI 验证过的完整传递版本
backend/requirements.txt          # 兼容入口，引用 runtime + eval
```

要求：

- `langgraph` 保持已验证范围 `>=1.2.6,<1.3.0`；
- Runtime 安装不因 `ragas/instructor/langchain-openai` 的评测依赖发生长时间回溯；
- CI、开发启动和 release gate 使用同一 Python 主版本；
- 安装验证记录 Python、Node、npm、LangGraph 和 Pydantic 版本；
- 不提交临时虚拟环境、密钥或机器绝对路径。

### 3.2 统一命令

新增或收口：

```text
make dev-setup       # 安装/校验可复现依赖
make dev             # 启动前后端
make verify-runtime  # Runtime 专项 + 历史人物图 parity
make verify-release  # clean revision + full gate + evidence manifest
```

`verify-release` 必须拒绝：

- tracked 文件存在未提交修改；
- 非 allowlist 的未跟踪 lockfile；
- Eval report revision 与 HEAD 不一致；
- Runtime config version 缺失；
- release seal 依赖的 profile 未实际运行。

## 4. Rollout 配置合同

### 4.1 staging 历史人物配置

```dotenv
EDU_AGENT_RUNTIME_V2_ENABLED=true
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=true
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=10000
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=10000
EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS=0
EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS=0
EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED=true
EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED=false
EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED=false
EDU_AGENT_RUNTIME_V2_RECOVERY_ENABLED=false
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.39-history-shadow
```

历史人物当前是 `observable`，不因存在 LangGraph 就开启 resumable/checkpoint。只有出现真实跨请求暂停恢复需求后，才另行设计图 checkpoint 与 Runtime checkpoint 引用。

### 4.2 production 灰度配置

第一阶段：

```dotenv
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=false
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=100
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=100
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.39-history-canary-1pct
```

`100` 表示 1%。所有比例使用稳定 subject hash；同一 actor/student/session 不应在请求间随机切换 bucket。

## 5. Per-Agent Rollout Gate

### 5.1 数据来源

只使用服务端可信数据：

- `agent_runs`：agent/config/runtime mode、状态、created/finished、revision；
- `agent_run_events`：milestone、terminal、错误和公开 completion；
- `agent_side_effects`：副作用状态与重复阻止；
- `agent_checkpoints`：仅 resumable run 的业务 checkpoint；
- `audit_events`：invalid transition、越权、确认和幂等审计；
- release/eval evidence manifest：部署 commit、环境、control baseline、真实 profile 结果。

不得从客户端上报的 `success`、耗时或 completion 推导发布结论。

### 5.2 聚合维度

至少支持：

```text
agent_type
config_version
runtime_mode = control | shadow | active
data_scope = runtime
window_hours
deployed_commit
```

Eval/demo 数据不得进入 production rollout gate。

### 5.3 输出合同

在现有 AgentOps summary 增加 `runtime_v2.rollout_gates`，并提供管理员只读端点：

```text
GET /api/admin/agent-runtime/rollout-readiness
    ?agent_type=history_character
    &window_hours=24
    &minimum_terminal_runs=100
```

示例响应：

```json
{
  "status": "pass",
  "agent_type": "history_character",
  "config_version": "v1.39-history-canary-1pct",
  "runtime_mode": "active",
  "deployed_commit": "abc1234",
  "window_hours": 24,
  "run_count": 126,
  "terminal_runs": 120,
  "event_coverage": 0.992,
  "terminal_consistency": 1.0,
  "unexpected_failure_rate": 0.008,
  "duplicate_side_effects": 0,
  "invalid_transitions": 0,
  "high_risk_without_confirmation": 0,
  "run_latency": {
    "sample_count": 120,
    "p50_ms": 2200,
    "p95_ms": 4200
  },
  "control_baseline": {
    "commit": "base123",
    "config_version": "legacy-control",
    "p95_ms": 4000,
    "sample_count": 150
  },
  "p95_regression": 0.05,
  "reasons": []
}
```

响应不得包含学生输入、模型正文、Artifact 内容或 raw confirmation token。

## 6. 指标定义

| 指标 | 定义 |
| --- | --- |
| run count | 窗口内符合 agent/config/mode/scope 的 Run 数 |
| terminal runs | `completed/partial/failed/cancelled` Run 数 |
| event coverage | 至少有一个持久 milestone 的 Run / run count |
| terminal consistency | terminal 且同时存在 completion、finished_at、terminal event 的 Run / terminal runs |
| unexpected failure rate | 非 expected-control、非 user cancel 的系统失败 Run / terminal runs |
| duplicate side effects | 窗口内 duplicate side-effect 审计与事件数 |
| invalid transitions | `agent_runtime.invalid_transition` 审计数 |
| high-risk without confirmation | high-risk side effect 缺少有效 confirmation 证据的执行数 |
| run latency | `finished_at - created_at`，只统计合法 terminal timestamp |
| p95 regression | `(active_p95 - control_p95) / control_p95` |

`partial` 不是系统失败，但必须按 completion reason 单独展示；`guardrail_blocked`、`confirmation_required`、`role_denied` 和用户主动取消属于预期控制结果。

## 7. Gate 判定

### 7.1 Pass 条件

必须同时满足：

| 条件 | 门槛 |
| --- | ---: |
| schema readiness | ready，且 Alembic head 与代码一致 |
| deployed commit/config | 已记录且与当前实例一致 |
| terminal runs | >=100 |
| event coverage | >=95% |
| terminal consistency | 100% |
| unexpected failure rate | <=2% |
| duplicate side effects | 0 |
| invalid transitions | 0 |
| high-risk without confirmation | 0 |
| p95 regression | <=10% |
| real LLM profile | pass |
| production RAG profile | pass |

### 7.2 Unknown 条件

以下情况必须返回 `unknown`，不能返回 `pass`：

- terminal 样本不足；
- 没有绑定 commit/config 的 control baseline；
- p95 样本不足或 timestamp 无效；
- schema readiness 未证明；
- real LLM / production RAG profile 未运行；
- Eval report 与部署 commit 不一致。

### 7.3 Fail 与 Warn

- 任意安全不变量非零：`fail`；
- terminal consistency <100%：`fail`；
- unexpected failure >2%：`fail`；
- event coverage <80%：`fail`；
- event coverage 80%~95% 或 p95 回退 5%~10%：`warn`；
- 只有 `pass` 可以扩大 rollout，`warn/unknown/fail` 均保持或回滚比例。

## 8. Control Baseline 合同

当前 control bucket 不创建 `agent_run`，因此不能伪造 active/control 同库对比。本轮使用独立、持久、绑定版本的 baseline evidence：

```json
{
  "agent_type": "history_character",
  "commit": "base123",
  "config_version": "legacy-control",
  "environment": "production",
  "window_start": "...",
  "window_end": "...",
  "sample_count": 150,
  "p50_ms": 2100,
  "p95_ms": 4000,
  "source": "server_trace_aggregate"
}
```

要求：

- baseline 由服务端 trace 聚合生成，不接受手填数值；
- baseline 不包含用户正文；
- baseline 与 release evidence 一起保存并校验 hash；
- baseline 缺失或跨模型/provider 大幅变化时 gate 为 `unknown`；
- 本轮不为 control 流量创建虚假 Runtime Run，也不双跑 LLM。

## 9. 历史人物 staging 验证矩阵

至少覆盖：

| 场景 | 期望 |
| --- | --- |
| non-stream verified | completed，terminal artifact 可读取 |
| stream verified | sources/delta/final/fact_card；随后 runtime terminal |
| 同 idempotency key 重放 | 不重新执行图，不增加事件或 memory 写 |
| verifier exception | partial/failed verification，禁止 verified/completed |
| 无 RAG 来源 | fail-closed 或显式 partial，不伪造来源 |
| LLM fallback | 标记 degraded，原因进入 completion/AgentOps |
| SSE 中断 | token 不补发；可按 cursor 补 milestone/terminal |
| 非 owner 查询 | 403 |
| event 数据检查 | 不包含原始 token、完整学生正文、confirmation token |
| memory 写边界 | 已验证回答最多写一次 |

staging 至少产生 100 个 terminal runs，且 stream/non-stream、verified/partial、fallback/verifier failure 均有样本。

## 10. 实施阶段

### Milestone A：工作区与依赖收口

实现：

- 清理非业务 lockfile 漂移；
- 拆分 Runtime/Eval requirements 并生成锁定约束；
- 增加统一 setup/dev/verify 命令；
- release gate 增加 clean revision 和 evidence revision 检查。

退出条件：

- 全新临时环境可安装并运行 Runtime 专项；
- 不使用机器私有 Python 路径；
- 安装不出现无限 resolver 回溯；
- `git status` 只包含明确批准的业务改动。

### Milestone B：Rollout Gate 聚合

实现：

- per-agent/config/runtime mode 指标；
- run duration p50/p95；
- safety invariant 计数；
- baseline evidence 读取和 hash 校验；
- `pass/warn/unknown/fail` 判定与管理员只读 API；
- AgentOps UI 展示 gate、样本、原因和版本。

退出条件：

- 无样本、缺 baseline、旧 schema 均为 `unknown`；
- 安全不变量非零均为 `fail`；
- eval/demo 事件不能改变 production gate；
- 聚合 SQL 在 SQLite/PostgreSQL smoke 通过。

### Milestone C：staging shadow

实现：

- history 100% observable/shadow；
- 记录部署 commit/config/model/provider；
- 执行真实 LLM、RAG、stream/non-stream 和错误注入；
- 生成 control baseline 和 current rollout evidence。

退出条件：

- >=100 terminal runs；
- gate 为 `pass`；
- `history_character_eval` 不再 skip；
- production-like PostgreSQL schema readiness 为 ready。

### Milestone D：production 1% → 10%

步骤：

1. allowlist 或 1% active；
2. 达到 100 terminal runs 后读取 gate；
3. gate pass 才升 10%；
4. 10% 连续 48 小时无 P0；
5. 再决定 50%/100%，不得自动扩量。

## 11. 测试矩阵

### 11.1 新增测试

- `agent_runtime_rollout_gate_smoke.py`
  - no samples → unknown；
  - insufficient terminal → unknown；
  - coverage 94% → warn；
  - terminal inconsistency → fail；
  - duplicate/invalid/high-risk → fail；
  - valid 100 runs + baseline → pass；
  - eval/demo isolation；
  - commit/config mismatch → unknown/fail closed。
- `agent_runtime_latency_baseline_smoke.py`
  - timestamp duration；
  - p50/p95；
  - invalid timestamp 排除；
  - baseline hash；
  - p95 regression 边界。
- `history_character_rollout_smoke.py`
  - stream/non-stream parity；
  - product event 不落库；
  - graph 单次执行；
  - memory exactly-once；
  - verifier fail-closed。

### 11.2 必跑回归

- Runtime v2 全部专项 smoke；
- `history_character_runtime_smoke`；
- `agent_runtime_product_routes_smoke`；
- `history_character_eval`；
- SQLite 与 PostgreSQL migration/readiness；
- frontend unit/lint/build；
- production RAG health；
- real LLM profile；
- clean revision full release gate。

## 12. 可观测与数据安全

- Runtime event 只保存 milestone、结构化结果引用和安全 completion；
- token delta、`product_event`、heartbeat 不落库；
- 学生输入和完整模型输出只保存于 owner-protected Artifact；
- baseline 和 rollout evidence 只保存聚合延迟、计数、版本与 hash；
- public/internal payload 继续分层；
- 管理员 readiness API 不返回 PII、prompt、正文或密钥；
- 所有生产结论必须限定 window、scope、agent、config 和 deployed commit。

## 13. 回滚

历史人物单 Agent 回滚：

```dotenv
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=0
```

全局回滚：

```dotenv
EDU_AGENT_RUNTIME_V2_KILL_SWITCH=true
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=0
```

规则：

- 回滚只影响新请求；
- 已有 Run/Event/Artifact 保留用于查询和审计；
- 不删除证据，不回滚 owner、verifier fail-closed 或幂等安全修复；
- gate 为 `fail` 时立即回滚；`unknown/warn` 时停止扩量并调查；
- 回滚后记录触发原因、commit、config、窗口和恢复条件。

## 14. 后续多节点图决策门

只有 v1.39 staging/production 证据通过后，才评估把历史人物单节点图拆为：

```text
retrieve → generate → verify
                      ├─ failed → partial finalize
                      └─ passed → fact_card → memory_commit → finalize
```

拆图必须证明至少一项明确收益：节点级重试、暂停恢复、故障隔离或可观测性显著提升。仅为了“看起来更像 LangGraph”不构成重写理由。

## 15. 完成定义

v1.39 只有在以下条件全部满足时可标记 Production Rollout Ready：

1. clean revision 与可复现依赖环境通过；
2. rollout gate 的无样本、缺基线、安全失败均 fail-closed；
3. staging >=100 terminal runs 且 gate pass；
4. real LLM、production RAG、PostgreSQL readiness 均有当前 commit 证据；
5. production 1% 达标后，10% 连续 48 小时无 P0；
6. duplicate side effect、invalid transition、high-risk without confirmation 均为 0；
7. p95 相对 control 回退不超过 10%；
8. 未运行证据不被标记为通过。

在第 1–8 项未全部完成前，状态保持 **Proposed / Development Complete / Canary Running** 中对应阶段，不得标记为 Production Complete。
