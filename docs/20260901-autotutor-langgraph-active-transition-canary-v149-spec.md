# EduAgent AutoTutor LangGraph Active Transition Canary v1.49 Spec

**状态：** Implemented（Development Complete；Production Canary Pending）
**日期：** 2026-09-01
**优先级：** P0 完整 active transition、单写入源、可信粘性灰度、可回滚；P1 Active 证据与重复代码收敛
**前置版本：** v1.48.1 AutoTutor LangGraph Shadow 可信性闭环
**后续候选：** v1.50 AutoTutor 单执行源收敛；只有出现跨请求图内暂停的真实需求时，才另立 LangGraph Checkpointer/Interrupt Spec

---

## 0. 决策摘要

v1.48.1 已在 clean code commit `229ecacf1fc9b6ef9e3f9563f71da2492b7fe1fd` 上取得正式 `GO`：

- 13/13 Legacy trajectory cases；
- 29/29 独立 transition parity；
- 外部调用 0；
- Shadow 业务/Runtime 写入 0；
- Graph p95 约 1.6ms；
- 无证据 blocker。

但这个 `GO` 只证明 Graph 能根据 `before + command + captured observations` 重算 canonical transition，不代表当前 Graph 可以立即成为 active：

1. observation 仍在 Legacy 完成整次 mutation 后从 `legacy_after` 中提取；
2. Graph candidate 只完整覆盖 parity projection，没有承载教学正文、来源、完整题目、反馈、Runtime steps 和 summary；
3. Graph effect intents 只有 `kind`，还不能直接交给原子事务提交服务；
4. AutoTutor API 没有把服务端可信 `traffic_cohort/rollout_eligible` 传入执行器选择；
5. 现有 Runtime rollout validator 只支持 `control/shadow`，没有 active canary 配置合同；
6. AutoTutor 没有写入可用于 active/control 比较的 rollout observations；
7. `langgraph-checkpoint-postgres` 和 psycopg3 当前未安装，现有环境只有 `psycopg2-binary`。

因此 v1.49 不做“一次性 LangGraph 全面接管”，而做一个可回滚的 Active Transition Canary：

- 把非确定性调用从 Legacy mutation 中抽为单次 observation provider；
- Legacy executor 与 Graph executor 消费同一 observation bundle；
- Graph 产出完整 `AutoTutorState + typed effects + domain events`；
- `autotutor_sessions` CAS 和 `commit_autotutor_transition` 继续作为唯一持久化/业务写入边界；
- 新会话按服务端可信 cohort 和稳定 bucket 选择 executor，并在整个 session 内粘性保持；
- Graph active 默认关闭、BPS 默认 0，仅允许 verified cohort 手工 canary；
- active canary 同时运行无副作用 Legacy comparator，但只有 Graph candidate 能提交；
- 本版本不接 PostgreSQL LangGraph checkpointer，不使用 `interrupt`。

版本主题：**先切换“状态转移计算权”，不同时迁移业务事务、恢复真相和生产基础设施。**

---

## 1. 项目实际基线

### 1.1 已可复用的安全边界

- `autotutor_sessions` 已持久化完整状态、revision、start/answer idempotency 和 inflight claim；
- answer transition 在任何 judge/reflect/副作用前先执行数据库 claim；
- `commit_autotutor_transition` 在一个数据库事务中提交：
  - learning events；
  - weakpoint evidence；
  - review memory；
  - Runtime side-effect ledger；
  - session CAS 与 replay response；
- stale、busy、replay、conflict 已有确定性合同；
- Runtime v2 已提供可信 cohort、稳定 bucket、kill switch、run/event/checkpoint、resume 和 rollout evidence；
- AutoTutor Runtime resume handler 最终仍调用 `submit_answer`，因此可以自动服从 session 内持久化的 executor mode；
- v1.48.1 Graph 已有版本化 transition envelope、fail-closed ports 和安全 mismatch codes。

### 1.2 当前不能直接 active 的缺口

| 维度 | 当前实现 | Active 风险 |
|---|---|---|
| Observation 来源 | 从已执行完成的 Legacy after 提取 | Graph active 仍依赖 Legacy 先运行 |
| Candidate 完整度 | 面向 canonical projection 的最小状态 | public state、恢复和持久化信息缺失 |
| Effect intents | `kind` 级占位 | 无法进入原子业务事务 |
| Domain events | Legacy `_emit/_record_content_event` 在 mutation 中执行 | Graph active 轨迹和学习事件无法等价 |
| Executor 路由 | 无 session-level executor mode | 可能在同一会话中途换执行器 |
| 可信灰度上下文 | API 未下传 actor cohort/eligibility | 可能信任客户端或误放 Demo 流量 |
| Active 配置校验 | validator 只允许 control/shadow | active 可能绕过 fail-closed 配置 |
| Active 观测 | AutoTutor 未写 rollout observation | 无法比较 control/active 成功率和延迟 |
| Graph 持久化 | 无 PostgreSQL saver 依赖 | 不应把 checkpointer 作为本版隐式前提 |

### 1.3 为什么本版不接 LangGraph PostgreSQL checkpointer

当前 AutoTutor 的暂停点恰好是 HTTP 请求边界：每次 start/answer transition 完成后先原子提交 `autotutor_sessions`，随后等待下一次学生请求。Graph 本身不需要跨请求保持未完成节点栈。

此时再引入 Graph checkpointer 会形成：

```text
autotutor_sessions.state_json
        +
agent_checkpoints.state_json
        +
LangGraph checkpoint tables
```

三份恢复状态和两个 revision 真相，而现有项目还未安装 `langgraph-checkpoint-postgres`/psycopg3。为了框架形式引入第三份状态，不符合已接受的 Runtime/LangGraph ADR。

v1.49 的明确决定：

- `autotutor_sessions` 是业务状态唯一真相；
- Runtime checkpoint 继续只保存公开恢复边界和 side-effect ledger 引用；
- Graph 每次只执行一个有界 transition；
- 不使用 `interrupt`；
- 只有未来确实需要“单次 Graph run 跨请求暂停且恢复节点栈”时，才单独评估 PostgreSQL saver，并必须同时给出旧 checkpoint 清理和单真相迁移方案。

---

## 2. 目标与非目标

### 2.1 P0 目标

- 抽出无 session mutation 的 `AutoTutorObservationProvider`；
- 同一 transition 的模型、检索、内容生成和时间/ID observation 最多获取一次；
- 定义完整、版本化的 `AutoTutorTransitionOutcome`；
- Graph executor 产出可直接验证为 `AutoTutorState` 的完整 next state；
- Graph executor 产出 typed learning/weakpoint/review/Runtime effect intents；
- Graph executor 产出完整 domain/runtime event intents；
- Legacy 与 Graph active 都通过同一个 `commit_autotutor_transition` 提交；
- active transition 不先执行 Legacy mutation；
- 每个 session 在 start 时选择并持久化 executor mode，answer/resume 不重新分桶；
- production active 只允许服务端认证的 verified cohort；
- Demo、eval、operator、anonymous 和 unverified cohort 默认不进入 production active；
- Active 默认关闭、BPS 默认 0、配置错误 fail-closed 到 Legacy；
- active Graph failure 在 commit 前安全回退 Legacy，且只复用同一 observation bundle；
- active commit 后禁止回退或重复执行；
- 记录 control/active rollout observations 和 executor fallback reason；
- 现有 API、授权、revision、idempotency、恢复和 evidence 合同保持兼容。

### 2.2 P1 目标

- active canary 对每次 Graph outcome 运行无副作用 Legacy comparator；
- AgentOps/admin evidence 可查看聚合 executor mode、parity、fallback 和 latency；
- 标记 Graph active 可替代的 Legacy mutation 代码，不在证据不足时删除；
- 建立 v1.50 是否移除双 executor 的 Go/No-Go 门禁；
- README 明确 active 的含义是“transition compute owner”，不是 Graph 拥有业务数据库。

### 2.3 非目标

- 不删除 `autotutor_sessions`；
- 不替换 `commit_autotutor_transition`、CAS 或 side-effect ledger；
- 不启用 LangGraph PostgreSQL checkpointer；
- 不安装 `langgraph-checkpoint-postgres` 或 psycopg3；
- 不使用 LangGraph `interrupt` 接管学生答题暂停；
- 不删除 Runtime checkpoint/resume/recovery；
- 不删除 Legacy executor；
- 不自动生产放量；
- 不让 Demo 账号承担生产 canary；
- 不接入 LangSmith Cloud、Agent Server 或 LangGraph Deployment；
- 不迁移 Learning Assistant 或其他 Agent；
- 不更改 verified mastery、错题、复习和教师聚合算法；
- 不把真实 LLM availability 设为默认 CI 前置条件。

---

## 3. 目标架构

```text
Authenticated API request
        │
        ├── trusted actor/cohort/eligibility
        ▼
AutoTutor sticky executor router
        │
        ├── existing session: read persisted executor_mode
        └── new session: config + cohort + stable bucket
        │
        ▼
claim transition / start idempotency boundary
        │
        ▼
AutoTutorObservationProvider
model / retrieval / content / stable clock+ids
        │  one immutable bundle, one external-call set
        ├───────────────────────────────┐
        ▼                               ▼
selected active executor         dry-run comparator
Legacy or LangGraph              other executor, no effects
        │                               │
        ▼                               ▼
AutoTutorTransitionOutcome       canonical comparison
complete state + typed intents          │
        │                               └── safe reason codes
        ▼
commit_autotutor_transition
single DB transaction / CAS / effects
        │
        ├── public response
        ├── Runtime checkpoint mirror
        └── rollout observation
```

### 3.1 单执行源定义

“单执行源”指一次业务 transition 只有一个 candidate 可以进入 commit：

- `legacy` session：Legacy outcome 可提交，Graph 只能 dry-run；
- `graph_active` session：Graph outcome 可提交，Legacy 只能 dry-run；
- comparator 不调用外部依赖、不写状态、不产生 effect；
- 不能在同一次 transition 中先提交 Legacy 再覆盖为 Graph；
- 不能在 Graph commit 失败后重新运行 Legacy transition；
- commit 前 Graph execution failure 或 comparator mismatch 可以用同一 observation bundle 回退 Legacy；本次 Legacy outcome 必须在同一 CAS 中把 session 永久降级为 `executor_mode=legacy`，并记录 `graph_precommit_fallback` 或安全 mismatch reason。

### 3.2 所有权边界

| 能力 | v1.49 所有者 |
|---|---|
| 模型、检索和内容 observation 获取 | EduAgent Observation Provider + LangChain model facade |
| Transition 条件分支和节点调度 | Selected executor；Graph active 时为 LangGraph |
| 领域判分、重规划、mastery、effect intent 纯规则 | EduAgent domain functions |
| Session claim/revision/CAS | EduAgent `autotutor_sessions` |
| 学习、错题、复习、memory 写入 | EduAgent transaction service |
| Runtime Run/Event/Artifact 和治理 | Runtime v2 |
| HTTP 答题暂停/恢复 | API + persisted session + Runtime resume handler |
| Graph checkpoint/interrupt | 本版本不存在 |
| Public trace/evidence allowlist | EduAgent projector |

---

## 4. Observation Provider 合同

### 4.1 目标

把当前散落在 `_generate_plan`、`_act`、`_reflect_and_replan` 和 `_start_exit_ticket` 中的“获取非确定性结果”与“修改 session”分离。

建议模块：

```text
backend/agents/autotutor_observations.py
```

建议接口：

```python
class AutoTutorObservationBundle(BaseModel):
    schema_version: Literal["v1.49-observation"]
    transition_kind: TransitionKind
    plan: PlanObservation | None
    content: ContentObservation | None
    reflection: ReflectionObservation | None
    exit_ticket: ExitTicketObservation | None
    clock: StableClockObservation
    identifiers: StableIdentifierObservation
    provenance: ObservationProvenance

class AutoTutorObservationProvider(Protocol):
    def prepare(
        self,
        *,
        before: AutoTutorState,
        command: AutoTutorTransitionCommand,
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundle: ...
```

### 4.2 Provider 约束

- 不修改 `before`；
- 不访问 `legacy_after`；
- 不调用 session persist/commit；
- 不写 learning events、weakpoints、review、memory、audit 或 Runtime 表；
- 不执行 `_emit`；
- 每个 model/retrieval/tool 调用有显式计数和 provenance；
- 同一 bundle 可以安全提供给 Legacy 和 Graph；
- observation 包含完整教学/题目/来源对象，但不得包含 derived next status、verified mastery、evidence intents 或 expected projection；
- 所有 clock/ID/selection seed 必须显式注入，两个 executor 不得各自调用 `time/uuid/random`；
- Provider 失败时维持当前内容安全门禁，不生成未经验证题目。

### 4.3 迁移顺序

1. 先让 Legacy executor 消费 provider，验证 public state 和数据库行为不变；
2. v1.48.1 Graph Shadow 改为直接消费 provider bundle，不再从 after 捕获；
3. Shadow parity 再次 100% 后，才启用 Graph active 测试路径；
4. 删除 `capture_transition_observations(before, legacy_after)` 的生产调用；测试兼容 helper 可以暂留一版。

---

## 5. 完整 Transition Outcome

### 5.1 内部 schema

```python
class AutoTutorTransitionOutcome(BaseModel):
    schema_version: Literal["v1.49-outcome"]
    executor_mode: Literal["legacy", "graph_active"]
    next_state: AutoTutorState
    learning_events: list[LearningEventIntent]
    weakpoint_evidence: list[WeakpointEvidenceIntent]
    review_memory: MemoryEntryUpsert | None
    runtime_events: list[AutoTutorRuntimeEventIntent]
    runtime_finalize: RuntimeFinalizeIntent | None
    public_result: dict[str, Any]
    diagnostics: AutoTutorTransitionDiagnostics
```

### 5.2 完整性要求

Graph active outcome 必须完整覆盖：

- lesson plan 全字段；
- objective、teaching、sources、content validation/version/label；
- practice/exit-ticket assessment 全字段；
- answer feedback；
- reflection diagnosis/explanation/provenance；
- runtime steps 的顺序、status 和安全 metadata；
- summary、evidence 和 verified mastery；
- revision 预期值；
- typed effect keys、owner、assessment fingerprint 和 parent evidence；
- public response 所需的所有字段。

禁止在 Graph outcome 产生后再调用 Legacy mutation 补齐字段。

### 5.3 Event intent

将 `_emit` 和 `_record_content_event` 从直接修改/写入改为构造 intent：

- executor 只产生 event intents；
- outcome materializer 将 intents 放入 next state/runtime steps；
- transaction service 只提交 typed learning/weakpoint/review effects；
- Runtime controller 在 CAS commit 成功后镜像 run/checkpoint；
- event key 必须由 transition/session/revision/step 稳定生成；
- Legacy 和 Graph 对同一 bundle 产生完全相同的 canonical event sequence。

---

## 6. Executor 接口与 Graph Active

### 6.1 Executor protocol

```python
class AutoTutorTransitionExecutor(Protocol):
    mode: Literal["legacy", "graph_active"]

    def execute(
        self,
        *,
        before: AutoTutorState,
        command: AutoTutorTransitionCommand,
        observations: AutoTutorObservationBundle,
    ) -> AutoTutorTransitionOutcome: ...
```

建议模块：

```text
backend/agents/autotutor_executor.py
```

### 6.2 Graph nodes

Graph active 至少包含真实节点：

```text
load_context
  ├─ start: plan → content_gate → teach → prepare_assessment → wait_answer
  ├─ lesson_answer: judge
  │      ├─ correct → advance
  │      ├─ retryable_wrong → reflect → re_plan → reteach → wait_answer
  │      └─ max_attempts → mark_struggling → advance
  ├─ exit_ticket_answer: verify_exit_ticket → build_effect_intents → finalize
  └─ recovery_resume: validate_state → route_current_phase
```

Graph state 必须使用版本化 Pydantic/TypedDict schema，不能依赖 Legacy private attrs 或整段 transition 函数。

### 6.3 Legacy comparator

Graph active canary 期间：

- 使用相同 `before/command/observations` 运行 Legacy dry-run；
- 只比较 canonical outcome、event sequence 和 effect intent keys；
- 任一业务 mismatch 必须在 commit 前阻断 Graph outcome，使用同一 observations fail-closed 回退 Legacy，并在 fallback outcome 中持久化 session 降级；
- Graph outcome 一旦进入 commit，就不得再根据晚到的 comparator/观测结果改用 Legacy；
- comparator 不能重复 LLM/RAG/tool 调用；
- comparator latency 单独记录，不混入用户主路径 Graph latency。

---

## 7. 粘性 Executor 路由

### 7.1 Session 状态字段

`AutoTutorState` 新增：

```python
executor_contract_version: Literal[3] = 3
executor_mode: Literal["legacy", "graph_active"] = "legacy"
executor_config_version: str | None = None
executor_bucket: int | None = None
executor_fallback_reason: str | None = None
```

这些字段保存在既有 `state_json`，本迭代不要求数据库 column migration。

### 7.2 路由原则

- 只在创建新 session 时分桶；
- answer、get、resume 和 recovery 读取持久化 `executor_mode`；
- 旧 session 缺少字段时默认 `legacy`；
- 已开始的 Legacy session 不升级为 Graph；
- 已开始的 Graph session 不因 BPS 调整自动降级；
- kill switch 可以在 commit 前把 Graph session 降级到 Legacy，但必须记录安全 reason；
- completed session 永不重新路由；
- bucket 由 server-owned subject + versioned salt 稳定计算；
- 不信任 request body、query 或 header 提供 executor mode。

### 7.3 可信上下文

AutoTutor API 必须将服务端 Actor 的以下信息传入内部 execution context：

- actor ID/role；
- account status；
- traffic cohort；
- data scope；
- `rollout_eligibility(actor, data_scope)` 结果和 reason；
- deployed commit、environment 和 executor config version。

production active 仅允许：

```text
account_status=active
traffic_cohort=verified
data_scope=runtime
rollout_eligible=true
```

Demo、eval、operator、anonymous 和 unverified 一律不进入 production active。测试只能通过明确的 internal test context 强制 Graph，不能增加公共 API 开关。

---

## 8. 配置合同

### 8.1 新配置

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION=v1.49-active
EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT=v1.49
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=false
EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED=true
EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED=true
```

`EXECUTOR_MODE` 允许：

- `legacy`：只运行 Legacy active；
- `shadow`：Legacy active + Graph dry-run；
- `active_canary`：eligible session 按 BPS 选择 Graph active，其他 session Legacy active。

### 8.2 旧配置兼容

- 新配置缺失时保持 v1.48.1 行为；
- `EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED=true` 在新 mode 缺失时映射为 `shadow`；
- 新 mode 一旦设置，以新配置为唯一真相；
- 不复用 `EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS` 作为 executor BPS：该变量继续只控制 Runtime v2 run 接入，避免治理平面和业务执行器选择互相隐式影响。

### 8.3 Active validator

现有 `validate_runtime_rollout_config` 只支持 control/shadow。本迭代新增 AutoTutor executor validator，或扩展为明确的 `active_canary` phase，并检查：

- active mode 显式启用；
- BPS 在 1..1000，v1.49 不允许一次超过 10%；
- kill switch 未开启；
- comparator 开启；
- fallback 开启；
- config version、bucket salt、deployed commit、environment 完整；
- production auth configuration 正确；
- verified cohort 可用；
- control baseline 和 Shadow GO evidence commit/version 匹配；
- Runtime observation schema ready；
- Demo/eval scope 排除；
- 不要求 checkpoint/resumable/dynamic replan/read fan-out 为 active executor 前提。

配置不满足时，新 session fail-closed 到 Legacy，并输出安全 reason code；不得导致服务启动失败或学生无法进入 Legacy AutoTutor。

---

## 9. Commit、恢复与失败语义

### 9.1 Start

1. 检查 start idempotency；
2. 创建初始 state 和 sticky executor decision；
3. provider 获取一次 observations；
4. selected executor 生成完整 outcome；
5. comparator 验证；
6. 原子持久化 session；
7. commit 成功后创建/镜像 Runtime run；
8. 记录 rollout observation。

若 Graph 在第 4/5 步失败，可用同一 observations 执行 Legacy 并保存 `executor_mode=legacy`、`executor_fallback_reason`。不得再次调用 provider。

### 9.2 Answer

1. 从 DB 读取持久化 state/executor mode；
2. claim revision + idempotency key + request hash；
3. provider 获取一次 observations；
4. selected executor 生成 outcome；
5. comparator 验证；
6. `commit_autotutor_transition` 原子提交 effects + session CAS；
7. commit 成功后镜像 Runtime checkpoint；
8. 记录 rollout observation。

约束：

- provider/executor 异常必须释放 inflight claim；
- Graph execution failure 或 comparator mismatch 的 Legacy fallback 必须在该次 outcome 中把 session 永久降级为 Legacy，避免下一次请求重复故障；
- commit 返回 stale/replay/conflict 后不得运行另一 executor；
- commit 发生未知结果时不得自动重试业务 effect，只能通过 idempotency replay 查询；
- Graph active 和 Legacy 使用相同 request hash、effect keys 和 response replay；
- Runtime resume handler 不自行选择 executor。

### 9.3 Recovery

- 旧 session：默认 Legacy；
- Graph active session：从 `autotutor_sessions.state_json` 恢复完整 state；
- Runtime checkpoint 只校验 session/run/revision 引用；
- session revision 与 Runtime checkpoint 不一致时，以 session CAS 为业务真相，Runtime 进入 reconcile，而不是覆盖 session；
- recovery worker 不重放已提交 effect；
- 部署回滚到 Legacy-only 版本前必须验证新 state schema 可被旧代码忽略/恢复；不兼容时 kill switch 必须 fail-closed 503，而不是损坏数据。

---

## 10. Rollout Observations 与 Active 证据

### 10.1 每次 transition 记录

使用现有 `agent_rollout_observations`，增加/复用安全聚合字段：

- agent type = `auto_tutor`；
- runtime mode = `control` 或 `active`；
- deployed commit/environment/config version；
- trusted cohort/eligibility；
- status；
- selected executor；
- transition kind；
- latency；
- comparator matched；
- fallback reason code；
- no raw answer/session/student ID in aggregate payload。

如果现有表无法容纳 executor/transition 维度，优先使用安全枚举 metadata 扩展或新窄表，不把完整 Graph state 放入 observation。

### 10.2 Active evidence report

新增：

```text
eval/reports/autotutor_active_latest.json
eval/reports/autotutor_active_latest.md
```

报告绑定：

- active code commit；
- executor config version；
- observation/outcome/Graph schema；
- dataset hash；
- control baseline commit/config；
- deployment environment；
- cohort trust contract。

报告至少包含：

- sessions/transitions by executor；
- exact comparator parity；
- success/failure/fallback rate；
- stale/busy/replay/conflict rate；
- duplicate effect count；
- verified mastery/evidence intent parity；
- control/active p50/p95；
- provider external-call count；
- Graph/Legacy compute latency；
- recovery/restart result；
- kill-switch drill result；
- sensitive field scan；
- Go/No-Go blockers。

---

## 11. Canary 阶段

### Phase 0：Development / forced test

- production BPS = 0；
- 测试 context 显式 Graph active；
- Legacy/Graph full outcome parity 100%；
- 完整 unit/smoke/E2E/restart/fault injection；
- 默认用户路径仍是 Legacy。

### Phase 1：Verified cohort 1%

- `active_canary` + 100 BPS；
- 仅 verified runtime cohort；
- comparator 100% 开启；
- 人工变更配置，不自动晋级；
- 任一 hard blocker 立即 kill switch。

### Phase 2：Verified cohort 5%

进入条件：

- Phase 1 至少 100 个 committed transitions；
- exact comparator parity 100%；
- Graph precommit fallback < 1%；
- duplicate effect = 0；
- unauthorized/demo/eval active = 0；
- active p95 不高于 control p95 20%，且绝对增加不超过 50ms；
- restart/recovery/kill-switch drill 通过。

### Phase 3：Verified cohort 10%

v1.49 最大范围为 1000 BPS。即使全部指标通过，也不在本版本自动进入 100%。扩大到单执行源属于 v1.50 决策。

---

## 12. 硬门禁

### 12.1 Development Complete

| Gate | 阈值 |
|---|---:|
| Provider 修改 before state | 0 cases |
| 单 transition 重复 model/RAG/tool observation | 0 |
| Graph full outcome parity | 100% |
| Public state parity | 100% |
| Runtime/domain event sequence parity | 100% |
| Typed effect intent parity | 100% |
| false mastery/content blocked/recovery parity | 100% |
| stale/busy/replay/conflict parity | 100% |
| Graph active duplicate business effects | 0 |
| Graph active unauthorized cohort | 0 |
| Graph failure影响已提交 active response | 0 cases |
| Legacy active 回归 | 0 |
| Default active BPS | 0 |

### 12.2 Deployment Verified

- deployed commit 与 active evidence 一致；
- production auth/trusted cohort ready；
- control baseline 样本充分；
- observation writes 无失败；
- Phase 1 样本和 parity 达标；
- restart/recovery 实机演练通过；
- kill switch 在一次配置发布窗口内生效；
- 无敏感 answer/prompt/student ID 出现在 rollout evidence；
- 未执行自动 Phase 2/3 放量。

---

## 13. 测试计划

### 13.1 Observation provider

- start plan/content observation；
- correct/wrong/max-attempt answer；
- reflect primary/fallback provenance；
- next lesson/exit-ticket/content-blocked observation；
- provider before-state immutability；
- stable clock/ID/seed；
- external-call counts；
- provider failure 不产生未验证题目。

### 13.2 Full outcome parity

- 完整 `AutoTutorState.model_dump` canonicalization；
- public state exact parity；
- runtime step/event sequence；
- learning event intents；
- weakpoint evidence keys/parent relationship；
- review memory；
- summary/evidence/mastery；
- decision provenance；
- no answer leakage。

### 13.3 Active transaction

- Graph start commit；
- Graph lesson answer commit；
- Graph exit-ticket finalize commit；
- stale/busy/replay/conflict；
- concurrent same revision；
- fault before/after each business effect；
- unknown commit result + idempotent lookup；
- Graph execution failure precommit fallback；
- mismatch precommit fallback；
- no postcommit fallback；
- effect rows and response 与 Legacy 一致。

### 13.4 Sticky routing与授权

- old session defaults Legacy；
- verified actor bucket hit/miss；
- demo/unverified/operator/anonymous/eval excluded；
- answer/resume 不重新分桶；
- BPS 变化不中途换 executor；
- kill switch existing/new session；
- public request 不能指定 executor；
- unsafe config fail-closed Legacy。

### 13.5 Recovery

- process restart after start；
- restart after lesson answer；
- restart before/after exit-ticket commit；
- Runtime resume API 对 Graph session；
- stale Runtime checkpoint reconcile；
- old deployment compatibility rehearsal；
- no duplicate learning/weakpoint/review effects。

### 13.6 Frontend/E2E

- 现有 13 条 browser flow 对 Legacy 和 forced Graph 各运行一次；
- refresh/resume 同一 Graph session；
- wrong → reflect → re-plan → exit ticket → evidence；
- content blocked；
- teacher evidence；
- UI 不暴露 bucket、内部 mismatch 或原始 observation。

### 13.7 建议发布前命令

```bash
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py \
  --suite autotutor_observation_provider_smoke \
  --suite autotutor_langgraph_full_outcome_parity_eval \
  --suite autotutor_langgraph_active_transaction_smoke \
  --suite autotutor_langgraph_active_routing_smoke \
  --suite autotutor_langgraph_active_recovery_smoke \
  --suite autotutor_transition_idempotency_smoke \
  --suite autotutor_finalize_fault_injection_smoke \
  --suite auto_tutor_trajectory_eval \
  --suite autotutor_false_mastery_smoke \
  --suite autotutor_content_blocked_api_smoke \
  --suite autotutor_session_recovery_smoke

npm run test:unit --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
E2E_PYTHON=.venv/bin/python npm run test:e2e --prefix frontend
npm run release:gate:fast
```

suite 名称以实现时最终注册为准，但测试语义不得减少。

---

## 14. 实现里程碑

### Milestone A：Provider 与 Legacy characterization

- 定义 command/observation/outcome schema；
- 抽 provider；
- Legacy 改为消费 provider；
- public state/database/event/effect characterization 先保持全绿。

### Milestone B：Graph full outcome

- 扩展 Graph state 和真实节点；
- 产生完整 next state、events 和 typed effects；
- 移除生产路径的 after-capture；
- full outcome parity 100%。

### Milestone C：Active transaction

- executor protocol；
- claim → provider → selected executor → comparator → commit；
- precommit fallback；
- fault injection 和 no-double-effect。

### Milestone D：Sticky trusted rollout

- state executor fields；
- API 下传 trusted actor context；
- stable bucket、old session、kill switch；
- active validator 和 observations。

### Milestone E：Evidence 与演练

- active report；
- forced Graph E2E；
- restart/recovery；
- kill-switch drill；
- v1.50 Go/No-Go。

### 14.1 预计代码落点

| 文件/模块 | 变化 |
|---|---|
| `backend/agents/autotutor_observations.py` | 新增 provider 和完整 observation schema |
| `backend/agents/autotutor_executor.py` | 新增 executor protocol、Legacy/Graph outcome |
| `backend/agents/autotutor_domain.py` | 扩展完整纯 transition/events/effects |
| `backend/agents/autotutor_graph.py` | 产出完整 active outcome |
| `backend/agents/autotutor_shadow.py` | 改用 provider bundle，保留 comparator |
| `backend/agents/auto_tutor.py` | 重排 claim/provider/executor/commit，持久化 sticky mode |
| `backend/api/routers/learning.py` | 下传服务端可信 rollout context |
| `backend/agents/autotutor_rollout.py` | 新增 executor settings/router/validator |
| `backend/agent_runtime/rollout_observations.py` | AutoTutor active 聚合维度 |
| `backend/agent_runtime/rollout_status.py` | admin-only active status |
| `eval/run_core_evals.py` | 注册 active suites |
| `scripts/release_gate.py` | 注册 active deterministic gates |

---

## 15. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Provider 抽取改变 Legacy 行为 | 先于 Graph active 产生回归 | Legacy characterization 先行，active BPS 保持 0 |
| Observation 偷带 derived after | 形成新的同源自证 | schema allowlist，禁止 status/mastery/effects/expected projection |
| Graph outcome 字段不完整 | public state 或恢复丢失 | full state/public/effect exact parity 门禁 |
| 两 executor 重复外部调用 | 成本和结果漂移 | provider 单次调用计数，bundle 双消费 |
| Graph/Legacy 都写 effect | 重复学习证据 | 只有 selected outcome 进入唯一 commit service |
| 中途重新分桶 | 同一会话行为漂移 | executor mode 持久化，answer/resume 只读 |
| 客户端伪造 active | 未授权流量进入 canary | 只使用服务端 Actor/cohort/eligibility |
| Demo 被 canary 破坏 | 作品集主线不稳定 | production Demo cohort 永久排除 |
| Graph mismatch 后错误提交 | 学习状态损坏 | commit 前 comparator fail-closed Legacy |
| commit 未知后双执行 | 重复副作用 | 禁止 postcommit fallback，只做 idempotent lookup |
| Runtime/session revision 双真相 | recovery 覆盖业务状态 | session CAS 为业务真相，Runtime 只 reconcile |
| 为 active 强行加 checkpointer | 三份状态和运维膨胀 | v1.49 明确非目标，无依赖/migration |
| 低流量样本不足 | 错误晋级 | 不自动晋级，样本不足保持当前 phase |

---

## 16. 回滚策略

### 16.1 即时回滚

- 设置 `EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=true`；
- 新 session 全部选择 Legacy；
- 未进入 commit 的 Graph transition 使用同一 observation bundle 回退 Legacy；
- 已提交 transition 不重放；
- active rollout observation 记录 kill-switch/fallback reason。

### 16.2 版本回滚

- `executor_mode` 存在于 state JSON，不新增必需 DB column；
- 旧 session 默认 Legacy；
- 新 Graph state 必须保持旧代码可忽略新字段的兼容性；
- 回滚演练必须使用真实 Graph active session state；
- 若旧代码不能安全读取新 state，部署回滚前先关闭入口并 fail-closed，不做自动降级转换。

### 16.3 数据处理

- 不删除 Graph session；
- 不回滚已经原子提交的合法学习证据；
- duplicate/unknown effect 通过 idempotency key 和 side-effect ledger 审计；
- active evidence 和 audit 保留用于事故复盘。

---

## 17. 完成定义

Development Complete 必须全部满足：

- [ ] Provider 不修改 before 且不写业务/Runtime 数据；
- [ ] 同一 transition observation 外部调用只发生一次；
- [ ] Legacy 已改为消费 provider，既有行为无回归；
- [ ] 生产 Shadow 不再从 Legacy after 捕获 observation；
- [ ] Graph 产出完整可验证 AutoTutorState；
- [ ] Graph 产出 typed domain/runtime effect intents；
- [ ] full state/public state/event/effect parity 100%；
- [ ] Graph active 不执行 Legacy mutation；
- [ ] 只有 selected outcome 可以进入 commit；
- [ ] precommit failure/mismatch fallback 使用同一 observations；
- [ ] postcommit fallback 为 0；
- [ ] duplicate effects 为 0；
- [ ] sticky executor mode 持久化并覆盖 answer/resume/recovery；
- [ ] old session 默认 Legacy；
- [ ] trusted cohort 和 data scope 路由正确；
- [ ] Demo/unverified/operator/eval production active 为 0；
- [ ] active config validator fail-closed；
- [ ] default active BPS = 0；
- [ ] control/active rollout observations 可聚合；
- [ ] restart/recovery/kill-switch drill 通过；
- [ ] false mastery/content blocked/idempotency/fault injection 全绿；
- [ ] Legacy 和 forced Graph 各自完整 E2E 通过；
- [ ] frontend unit/lint/build 通过；
- [ ] fast release gate 通过；
- [ ] active evidence 绑定 clean commit/schema/dataset/config；
- [ ] PostgreSQL LangGraph checkpointer/interrupt 未被隐式引入。

Deployment Verified 还需：

- [ ] 目标 commit 已部署；
- [ ] production auth/trusted cohort ready；
- [ ] control baseline 样本充分；
- [ ] Phase 1 verified cohort canary 人工开启；
- [ ] 至少 100 个 active committed transitions；
- [ ] comparator parity 100%；
- [ ] duplicate effect/unauthorized cohort/observation failure 均为 0；
- [ ] active latency 门槛通过；
- [ ] production restart 和 kill-switch drill 通过；
- [ ] 未自动扩大到 Phase 2/3。

---

## 18. v1.50 进入条件

只有 v1.49 Development Complete 且 production Phase 1/2 证据满足门禁，v1.50 才允许讨论：

- Graph 成为 AutoTutor 默认 transition executor；
- 停止在线 Legacy comparator；
- 删除 Legacy mutation executor；
- active 从 10% 扩大到 100%；
- 简化 Shadow/Active 双路由配置。

LangGraph checkpointer/interrupt 不随 v1.50 自动进入。只有出现以下真实需求才单独立项：

- 一个 Graph run 必须跨 HTTP 请求保持未完成节点栈；
- 仅靠 `autotutor_sessions` 无法可靠恢复；
- 能删除或降级一份现有 checkpoint 真相；
- 已安装并验证 PostgreSQL saver 依赖；
- 已定义 checkpoint migration、TTL、清理、加密和写放大 SLO。
