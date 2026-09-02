# EduAgent AutoTutor LangGraph Canary Readiness v1.49.2 Spec

**状态：** Proposed
**日期：** 2026-09-02
**优先级：** P0 Provider/Graph 结构独立性与 Comparator 有效性；P1 Production Canary 聚合、门禁与发布闭环
**前置版本：** v1.49.1 AutoTutor LangGraph Independent Transition
**后续候选：** v1.50 AutoTutor Single Executor Consolidation（仅在本 Spec Deployment Verified 后允许创建）

---

## 0. 决策摘要

v1.49.1 已在本地提交上完成开发实现：

- code commit：`a38f35365a6f879436b59ae4650c782c3b9e3e0e`；
- development evidence commit：`1d49cde`；
- observation/outcome schema：`v1.49.1-observation` / `v1.49.1-outcome`；
- development trajectory parity：`108/108`；
- Legacy mutation wrapper tripwire：通过；
- executor external calls / side effects：`0 / 0`；
- start/answer transaction fault injection：`8/8`；
- core smoke：无失败 suite，只有环境依赖 suite 被跳过；
- default Active BPS：`0`；
- PostgreSQL LangGraph checkpointer/`interrupt`：未引入。

这些结果证明 materialized outcome 已移除，生产 start/answer 已进入 provider → selected executor → comparator → single commit 链路，开发级完整 outcome parity 已成立。

但结合当前代码，v1.49.1 仍不足以直接开启可信 production canary：

1. Provider 仍通过 `_KERNEL_ACT` / `_KERNEL_MUTATE_ANSWER` 在私有 candidate 上运行兼容 mutation，尚非严格 source-only observation acquisition；
2. Legacy 与 Graph 最终都调用同一个完整 `execute_autotutor_transition`，Graph 多数节点只记录 visited node，Comparator 对共享内核错误不敏感；
3. migration 014 的 transition telemetry 已写入，但 AgentOps、rollout readiness 和 deployment evidence 尚未按新维度聚合；
4. fallback 后只保留 selected executor，缺少稳定的 assigned executor 分母，无法准确计算 Graph attempt/fallback rate；
5. production 配置仍允许最高 10% BPS，与 v1.49.1 的 1% 上限不一致；
6. release gate 未完整覆盖新增 provider/kernel/migration/fault-injection 文件；
7. 当前两个提交尚未进入 `origin/main`，没有对应部署、生产 schema、verified cohort 或 committed Active 样本。

因此 v1.49.2 的决定是：

> 不扩大流量，不进入 v1.50；先消除 Provider 对 mutation 的依赖，让 Graph 节点真实持有 orchestration，证明 Comparator 能发现故意注入的差异，再完成可聚合、可阻断、可回滚的 1% Canary 运维闭环。

版本主题：**不仅要得到相同结果，还要证明两条计算路径足够独立，且生产证据能够阻止错误放量。**

---

## 1. 项目实际基线

### 1.1 已成立且必须保留的边界

- `autotutor_sessions` 仍是唯一业务状态真相；
- start idempotency 和 answer claim 在 provider 前完成；
- stale/busy/replay/conflict 不调用 provider；
- `commit_autotutor_start` 原子提交 start session 与 learning-event intents；
- `commit_autotutor_transition` 原子提交 answer CAS、learning、weakpoint、review 与 Runtime side-effect ledger；
- trace/Runtime mirror 在业务提交后执行；
- selected/comparator 共用一个 immutable observation bundle；
- comparator outcome 永不提交；
- Graph failure/mismatch 只允许 precommit fallback；
- session executor mode、config、bucket 和 fallback reason 持久化；
- trusted actor/cohort/data scope/eligibility 由服务端构造；
- public state、handoff、evidence 和 demo trace 继续执行 allowlist；
- verified mastery、错题、复习与教师证据算法保持不变；
- Runtime resume 仍通过 `submit_answer` 回到同一业务状态真相；
- Active 默认关闭，Legacy 始终可作为即时回滚路径。

### 1.2 当前结构差距

| 维度 | 当前代码事实 | 风险 |
|---|---|---|
| Provider start | 调用 `_KERNEL_ACT(candidate, ...)` | Provider 同时执行内容 mutation 和 observation acquisition |
| Provider answer | 调用 `_KERNEL_MUTATE_ANSWER(candidate, ...)` | Provider 提前运行 judge/advance/finalize 分支 |
| Legacy executor | 调用完整 `execute_autotutor_transition` | 合理，但与 Graph 共用完整 orchestration |
| Graph nodes | 多数节点只追加 `visited_nodes` | 节点名存在，draft/state delta 不存在 |
| Graph outcome | `build_outcome` 再调用完整 kernel | Graph 不是独立 orchestration owner |
| Comparator | 两端共用同一个完整 kernel | 共同错误可能稳定得到 100% parity |
| Telemetry | migration 014 新字段只写不聚合 | 无法形成 production Go/No-Go |
| Executor denominator | fallback 后 `selected_executor=legacy` | 无法区分 Legacy control 与 Graph attempt fallback |
| Observation health | writer failure进入 audit | 尚未纳入 AutoTutor canary blocker |
| BPS | validator 上限 1000 BPS | 可能违反本版本 1% 上限 |
| Release gate | 未编译新 provider/kernel/migration 014 | 关键文件可绕过 fast gate |
| Deployment | local HEAD 领先 origin 两个提交 | 不存在可验证 production deployment |

### 1.3 v1.49.1 GO 的正确解释

当前 GO 只表示：

- GO for development transition contract；
- GO for materialized removal；
- GO for single-bundle/single-commit scaffold；
- GO for deterministic development parity；
- NO GO for structurally independent production comparator；
- NO GO for production Active BPS > 0；
- NO GO for Graph default；
- NO GO for Legacy removal；
- NO GO for v1.50。

---

## 2. 目标与非目标

### 2.1 P0 目标：结构独立性

- Provider 只采集 profile/weakpoint/model/retrieval/tool/clock/ID/seed observation；
- Provider 不创建 candidate next state；
- Provider 不调用 `_KERNEL_*`、Legacy mutation、Graph executor、effect builder、`_emit` 或 finalize；
- Provider 不计算 mastery、status、phase、revision、summary 或 public result；
- transition 规则拆成可组合的纯 reducer；
- Legacy executor 以顺序 orchestration 调用 reducer；
- Graph 每个业务节点实际读取/更新 draft；
- Graph 不调用 Legacy executor、Legacy wrapper 或完整 Legacy orchestration entrypoint；
- Graph/Legacy 允许共享叶子级领域函数，不允许共享完整 transition orchestration；
- Comparator 比较完整 state/public/events/effects/finalize intent；
- 故意注入 Graph reducer 差异时 Comparator 必须检出；
- mismatch/failure 使用同一 observation bundle 回退已计算 Legacy outcome；
- fallback 只提交一次并永久降级 session；
- default Active BPS 保持 0。

### 2.2 P1 目标：Canary 运维闭环

- 明确记录 assigned executor 与 selected executor；
- 按 commit/config/environment/cohort/window 聚合 transition observation；
- 输出 committed Active、parity、fallback、latency、effect、observation health 和 unauthorized 指标；
- production 1% 上限在配置校验层硬编码 fail-closed；
- AgentOps 和 rollout readiness 能直接产生 AutoTutor Go/No-Go；
- deployment evidence 区分 development 与 production；
- release gate 覆盖全部新增关键文件和 fault injection；
- 形成 push → migrate → deploy → baseline → 1% canary → kill-switch rehearsal 的人工操作顺序。

### 2.3 非目标

- 不把 Graph 设为默认 executor；
- 不删除 Legacy executor 或在线 comparator；
- 不允许 production Active 超过 1%；
- 不自动晋级 5%、10% 或 100%；
- 不修改学生可见教学产品功能；
- 不调整 verified mastery、错题、复习和教师聚合算法；
- 不替换 `autotutor_sessions` 或现有 CAS；
- 不引入第二份业务状态真相；
- 不安装 LangGraph PostgreSQL checkpointer；
- 不使用 LangGraph `interrupt`；
- 不迁移其他 Agent；
- 不要求默认 CI 访问真实 LLM/RAG；
- 不以 Demo、eval、operator、anonymous 或 unverified 流量冒充 production canary。

---

## 3. 不可破坏的不变量

### 3.1 Observation 与计算分离

```text
before + command + trusted context
              │
              ▼
       source-only provider
 profile / weakpoint / model / retrieval
 clock / ids / selection seeds
              │
       immutable observations
          ┌───┴───┐
          ▼       ▼
 Legacy orchestration   Graph orchestration
 reducers in sequence   reducers by real nodes
          │       │
          └───┬───┘
              ▼
      full outcome comparator
              │
       one precommit decision
              │
              ▼
       one transaction commit
```

硬约束：

- provider external-call set = 1；
- selected executor external calls = 0；
- comparator external calls = 0；
- fallback additional external calls = 0；
- provider before mutation = 0；
- provider business/Runtime writes = 0；
- executor persistence writes = 0；
- committed outcome count = 1。

### 3.2 允许共享与禁止共享

允许共享：

- Pydantic domain models；
- `judge_answer`、`verified_mastery` 等叶子级纯函数；
- assessment/content validation primitives；
- effect key builder；
- public DTO projector；
- canonical normalization utilities。

禁止共享：

- 完整 transition orchestration 函数；
- Legacy executor callback；
- Legacy after/expected state；
- materialized outcome；
- mutation candidate；
- precomputed route result；
- comparator expected projection。

### 3.3 单状态真相

- `autotutor_sessions.state_json` 是唯一业务恢复状态；
- Runtime checkpoint 只镜像公开恢复边界；
- Graph draft 仅存在于单次请求内存；
- observation/outcome 不持久化进 session state；
- 不新增 LangGraph checkpoint table；
- commit 未知时禁止重跑 executor；
- 已提交 transition 不因 telemetry/trace mirror 失败而回滚。

---

## 4. Provider v3 合同

### 4.1 Source-only DTO

建议新增显式 observation DTO：

```python
class AutoTutorObservationBundleV3(BaseModel):
    schema_version: Literal["v1.49.2-observation"]
    transition_id: str
    transition_kind: TransitionKind
    clock: ClockObservation
    identifiers: IdentifierObservation
    profile: ProfileObservation | None
    weakpoints: list[WeakpointObservation]
    plan_inputs: PlanInputObservation | None
    content: ContentObservation | None
    reflection: ReflectionObservation | None
    next_content: ContentObservation | None
    exit_ticket_content: ContentObservation | None
    selection: SelectionObservation
    call_counts: ObservationCallCounts
    provenance: ObservationProvenance
```

禁止字段：

```text
candidate
next_state
legacy_after
expected_state
expected_projection
materialized
public_result
effect_intents
runtime_events
verified_mastery
derived_status
derived_phase
derived_revision
```

### 4.2 Provider 拆分

```text
prepare_start_observations
  ├─ read_profile
  ├─ read_weakpoints
  ├─ allocate_clock_ids
  └─ acquire_content_observation

prepare_lesson_answer_observations
  ├─ acquire_reflection_observation（仅 retryable wrong）
  ├─ acquire_next_content_observation（需要 advance/reteach 时）
  └─ acquire_exit_ticket_content（需要 exit ticket 时）

prepare_exit_answer_observations
  └─ allocate_clock_ids

prepare_recovery_observations
  └─ persisted reference + clock
```

Provider 可根据 `before + command` 判断“需要哪类外部 observation”，但不得将判断结果写入业务状态，也不得提前计算最终 mastery/effects/public result。

### 4.3 Call count

必须记录：

```text
model_calls
retrieval_calls
tool_calls
network_calls
clock_reads
id_allocations
selection_seed_reads
```

测试必须证明：同一 transition 被 Graph、Legacy、fallback、comparator 消费多次时，call count 不增加。

---

## 5. 纯 Reducer 与双 Orchestration

### 5.1 Reducer API

建议将完整 kernel 拆成无 I/O reducer：

```text
initialize_draft(before, command, observations)
apply_plan
apply_content_gate
apply_teaching_content
apply_practice_assessment
apply_judgement
apply_reflection
apply_replan
apply_advance
apply_next_content
apply_exit_ticket
apply_exit_judgement
apply_mastery
build_effect_intents
finalize_draft
build_public_result
```

每个 reducer：

- 输入、输出为 typed draft/delta；
- 不调用 provider；
- 不读 clock/uuid/random；
- 不写数据库、trace、Runtime 或 audit；
- 不依赖 executor mode；
- 不知道 comparator 是否存在；
- 可被独立单测和 mutation test。

### 5.2 Legacy orchestration

Legacy executor 允许用普通 Python 顺序/分支组合 reducer：

```text
initialize → route → reducers → effects → public result → outcome
```

禁止继续调用旧 `_act/_reflect_and_replan/_advance/_finalize` 完成 selected transition。兼容 wrapper 可以保留给旧测试或回滚，但不能成为 v1.49.2 production Legacy executor 的业务实现。

### 5.3 Graph orchestration

Graph state：

```python
class AutoTutorGraphState(TypedDict, total=False):
    before: AutoTutorState
    command: AutoTutorTransitionCommand
    observations: AutoTutorObservationBundleV3
    draft: AutoTutorTransitionDraft
    outcome: AutoTutorTransitionOutcome
    visited_nodes: list[str]
    diagnostics: list[str]
```

每个 Graph node 必须调用对应 reducer 并返回真实 draft delta。禁止仅调用 `_active_visit` 后在 `build_outcome` 一次性执行完整 transition。

目标路径：

```text
start:
  initialize → plan → content_gate → teach → assessment → effects → outcome

lesson correct:
  initialize → judge → advance → next_content_or_exit → effects → outcome

lesson retryable wrong:
  initialize → judge → reflect → re_plan → reteach → effects → outcome

lesson max attempts:
  initialize → judge → mark_struggling → advance → next_content_or_exit → effects → outcome

exit answer:
  initialize → verify_exit → calculate_mastery → effects → finalize → outcome

recovery:
  initialize → validate_state → route_phase → outcome
```

### 5.4 独立性 source gate

Graph production module 禁止引用：

```text
LegacyTransitionExecutor
execute_autotutor_transition（完整 Legacy orchestration）
_KERNEL_*
_act
_reflect_and_replan
_advance
_start_exit_ticket
_finalize
```

Provider production module 禁止引用上述 mutation 符号和 Graph executor。

---

## 6. Comparator 有效性证明

### 6.1 正常 parity

继续覆盖至少 100 个完整 transition，包含：

- start verified；
- start content blocked；
- correct answer；
- retryable wrong；
- reflection/re-plan/reteach；
- max attempts；
- next lesson；
- exit correct；
- exit wrong；
- recovery；
- sticky restart；
- kill-switch fallback；
- idempotent replay/conflict/stale/busy。

比较维度：

- full stable state；
- status/phase/revision/current step/replans；
- teaching/content validation/assessment identity；
- runtime/domain event sequence；
- learning/weakpoint/review intent payload；
- verified mastery/evidence/summary；
- Runtime finalize intent；
- public result；
- sensitive-field allowlist。

### 6.2 Comparator sensitivity test

必须新增故意缺陷注入：

| 注入点 | 预期 reason |
|---|---|
| Graph judge 反转结果 | `state_mismatch` / `public_result_mismatch` |
| Graph advance 少一步 | `step_index_mismatch` |
| Graph effect 少一个 | `learning_effect_mismatch` |
| Graph mastery 错误 | `mastery_mismatch` |
| Graph public response 泄露答案 | `public_result_mismatch` / sensitive gate |
| Graph runtime event 缺失 | `runtime_event_mismatch` |

每个注入用例必须证明：

- comparator 在 commit 前失败；
- Legacy outcome 使用原 bundle；
- provider calls 不增加；
- session 永久降级 Legacy；
- business effects 只提交一次；
- response 不泄露内部 mismatch 细节。

### 6.3 反共同错误门禁

仅有 100% parity 不足以判定 GO。必须同时满足：

- Graph/Legacy source independence gate；
- comparator sensitivity mutation tests；
- reducer invariant tests；
- effect and public DTO tests。

---

## 7. Telemetry v3 与 migration 015

### 7.1 为什么需要 assigned executor

当前 fallback 后 `selected_executor=legacy`，会丢失“该 transition 原本尝试 Graph”的分母。生产 fallback rate 应定义为：

```text
graph_fallback_count / graph_assigned_transition_count
```

因此建议 migration 015 为 `agent_rollout_observations` 增加 nullable 字段：

```text
assigned_executor TEXT
observation_schema_version TEXT
outcome_schema_version TEXT
transition_id TEXT
commit_status TEXT
```

已有字段继续保留：

```text
selected_executor
transition_kind
comparator_matched
fallback_reason
provider_latency_ms
executor_latency_ms
comparator_latency_ms
observation_external_calls
effect_intent_count
```

禁止存储 student/session/raw answer/question/teaching/reflection/source/state。

### 7.2 AutoTutor transition aggregate

新增专用只读聚合：

```python
aggregate_autotutor_transition_canary(
    deployed_commit,
    config_version,
    environment,
    traffic_cohort="verified",
    window_start,
    window_end,
) -> AutoTutorCanaryAggregate
```

输出至少包含：

- observed/eligible/assigned/committed transitions；
- control vs Graph assigned count；
- transition kind coverage；
- comparator matched/mismatched/unknown；
- fallback count/rate/by reason；
- provider/executor/comparator/total p50/p95；
- observation external-call distribution；
- effect intent count distribution；
- observation write failure count；
- duplicate effect count；
- unauthorized Active count；
- commit/config/environment/cohort/window provenance。

### 7.3 写入失败语义

- observation 写失败不改变学生响应；
- failure 必须写现有 audit health；
- production canary 窗口内 failure > 0 直接 NO-GO；
- schema missing、writer error 和 provenance invalid 分开聚合；
- 不允许用缺失 observation 的业务成功样本补算 100% parity。

---

## 8. 配置与生产流量上限

### 8.1 配置合同

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy|shadow|active_canary
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0..100（production v1.49.2）
EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION=v1.49.2-canary
EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT=<non-empty immutable value>
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=false
EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED=true
EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED=true
```

### 8.2 Fail-closed 规则

production 下任一条件成立均退回 Legacy：

- BPS > 100；
- BPS < 1 且 mode=active_canary；
- comparator disabled；
- fallback disabled；
- kill switch enabled；
- commit 非完整 SHA；
- config/salt 缺失；
- schema head 未就绪；
- observation health degraded；
- actor/cohort/scope 不可信。

非 production 的 forced Graph eval 可以使用 100%，但必须标记 `evidence_scope=development`，不能进入 production aggregate。

---

## 9. AgentOps 与 Go/No-Go

AgentOps 新增 `autotutor_transition_canary` 区块：

```text
status
commit/config/environment/window
assigned_graph / committed_graph
comparator_parity
fallback_rate
observation_health
duplicate_effects
unauthorized_active
transition_coverage
provider/executor/comparator/total p95
blockers
```

生产 GO 必须同时满足：

- committed Graph transitions ≥100；
- comparator exact parity = 100%；
- fallback rate <1%；
- observation failures = 0；
- duplicate effects = 0；
- unauthorized Active = 0；
- transition kind coverage 完整；
- active p95 ≤ control p95 ×1.20；
- active p95 absolute increase ≤50ms；
- provenance coverage = 100%；
- restart/kill-switch rehearsal 通过。

缺少样本返回 `NOT_READY`，不得返回 GO；查询失败返回 `UNKNOWN/NO_GO`，不得 fail-open。

---

## 10. Release Gate 收敛

`scripts/release_gate.py` 必须纳入：

- `backend/agents/autotutor_observations.py`；
- `backend/agents/autotutor_transition_kernel.py`；
- 新 reducer/orchestration 模块；
- migration 014/015；
- observation source-independence smoke；
- Graph source-independence smoke；
- comparator sensitivity smoke；
- full outcome parity ≥100；
- start/answer fault injection 8/8；
- rollout aggregation/readiness smoke；
- production BPS cap smoke；
- migration upgrade/rehearsal/lock smoke。

Development Complete 前必须运行：

```text
backend full smoke
fast release gate
frontend lint
frontend unit tests
frontend production build
git diff --check
sensitive field scan
```

本轮没有前端产品改动，但仍需 frontend gate 证明共享 API/build 无回归。

---

## 11. Deployment 流程

### Phase 0：代码与不可变部署

1. push clean commits；
2. CI/release gate 全绿；
3. migration 014/015 通过生产锁与 revision 校验；
4. 部署 commit 与 evidence commit 绑定；
5. immutable deployment verification 通过；
6. production 配置保持 Legacy/BPS 0。

### Phase 1：Control baseline

- verified runtime cohort；
- exact commit/config/environment；
- observation health ready；
- control samples ≥100；
- transition coverage 和 latency baseline 可用；
- unauthorized/failure/duplicate 为 0。

### Phase 2：Forced rehearsal

- 非生产或受控内部环境 forced Graph；
- restart drill；
- precommit Graph exception fallback；
- injected comparator mismatch fallback；
- kill switch drill；
- observation writer failure drill；
- commit unknown 不重跑 executor。

### Phase 3：Production verified 1%

人工设置：

```text
mode=active_canary
active_bps=100
comparator=true
fallback=true
kill_switch=false
```

只允许 verified runtime cohort。达到 100 committed Graph transitions 后生成 deployment evidence，立即恢复 BPS 0，完成评审后再决定是否保持 1%。本版本不得继续扩大。

---

## 12. 回滚策略

### 12.1 即时回滚

```text
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=true
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
```

- 新 session 使用 Legacy；
- existing Graph session 下一次 provider 前永久降级；
- 已提交 transition 不重放；
- observation/evidence 保留；
- 不需要学生数据修复。

### 12.2 代码回滚

- migration 014/015 仅增加 nullable 列；
- 旧 writer 可忽略新增列；
- observation/outcome 只存在请求内存；
- session state 不依赖 Graph draft；
- Legacy orchestration 必须始终可运行；
- 禁止通过重新引入 materialized/expected state 修复 parity。

---

## 13. 预计代码落点

| 文件 | 改动 |
|---|---|
| `backend/agents/autotutor_observations.py` | source-only provider v3，删除 mutation aliases |
| `backend/agents/autotutor_transition_kernel.py` | 拆分 typed reducers，不再同时承担完整双端 orchestration |
| `backend/agents/autotutor_execution.py` | assigned/selected executor、v3 contracts、production 1% cap |
| `backend/agents/autotutor_graph.py` | Graph nodes 实际更新 draft，删除 final monolithic compute |
| `backend/agents/auto_tutor.py` | 保留 claim/provider/select/compare/commit orchestration |
| `backend/agent_runtime/rollout_observations.py` | v3 writer 与 AutoTutor aggregate |
| `backend/agent_runtime/rollout_status.py` | AutoTutor canary readiness |
| `backend/agent_ops.py` | transition-level canary 指标 |
| `backend/db/schema.py` | assigned executor/provenance nullable columns |
| `backend/alembic/versions/015_*` | telemetry v3 migration |
| `scripts/release_gate.py` | 新文件、migration、sensitivity/fault/aggregate gates |
| `eval/autotutor_*` | source tripwire、mutation sensitivity、≥100 trajectory、drills |
| `eval/reports/autotutor_*` | development/deployment evidence 分离 |
| `.env.example` / `README.md` | v1.49.2 配置、1% 上限、runbook |

---

## 14. Milestones

### Milestone A：Provider 去 mutation

- source DTO；
- content/reflection/exit observation acquisition；
- provider source gate；
- call counter；
- before/write/runtime mutation = 0。

### Milestone B：Reducer 拆分

- typed transition draft；
- start/lesson/exit/recovery reducers；
- event/effect/public reducers；
- invariant unit tests。

### Milestone C：双 Orchestration

- Legacy 顺序 orchestration；
- Graph real-node orchestration；
- 删除 Graph monolithic kernel call；
- source/runtime tripwire。

### Milestone D：Comparator sensitivity

- ≥100 normal parity；
- mutation injection matrix；
- single-bundle fallback；
- duplicate effect/fault tests。

### Milestone E：Canary telemetry/ops

- migration 015；
- assigned vs selected executor；
- aggregate/readiness/AgentOps；
- observation health blocker；
- deployment evidence builder。

### Milestone F：Release 与 deployment rehearsal

- release gates；
- frontend gates；
- production 1% config cap；
- restart/kill-switch/writer-failure drills；
- clean development evidence GO。

### Milestone G：Production 1%（需要单独部署授权）

- push/deploy/migrate；
- control baseline；
- verified 1% manual enable；
- ≥100 committed Graph transitions；
- deployment evidence；
- v1.50 Go/No-Go。

---

## 15. Development Complete 定义

- [ ] Provider 不调用任何 transition mutation/Legacy/Graph executor；
- [ ] Provider before mutation、business write、Runtime write 均为 0；
- [ ] Observation 不含任何 derived outcome；
- [ ] 单 transition provider external-call set = 1；
- [ ] Legacy 使用 reducer 顺序 orchestration；
- [ ] Graph 每个业务节点产生真实 draft delta；
- [ ] Graph 不调用完整 Legacy orchestration；
- [ ] Graph/Legacy executor external calls = 0；
- [ ] normal full trajectory parity ≥100 且 100%；
- [ ] event/effect/public result parity = 100%；
- [ ] comparator sensitivity mutation matrix 全绿；
- [ ] mismatch/failure precommit fallback 只提交一次；
- [ ] fallback additional provider calls = 0；
- [ ] stale/busy/replay/conflict provider calls = 0；
- [ ] start/answer transaction fault injection 全绿；
- [ ] assigned/selected executor 可准确聚合；
- [ ] AutoTutor rollout aggregate/readiness/AgentOps 全绿；
- [ ] production BPS >100 fail-closed；
- [ ] default Active BPS = 0；
- [ ] release gate 纳入全部关键文件与 migration；
- [ ] backend smoke、fast release gate、frontend lint/unit/build 全绿；
- [ ] sensitive field scan 通过；
- [ ] clean commit development evidence GO；
- [ ] 未引入 LangGraph checkpointer/interrupt。

---

## 16. Deployment Verified 定义

- [ ] clean commits 已 push 并部署；
- [ ] deployed commit/config/environment 与 evidence 完全匹配；
- [ ] migration 014/015 ready；
- [ ] production auth/trusted cohort ready；
- [ ] control baseline ≥100；
- [ ] observation health ready；
- [ ] verified cohort 1% 手工开启；
- [ ] committed Graph transitions ≥100；
- [ ] comparator exact parity = 100%；
- [ ] fallback rate <1%；
- [ ] observation failure = 0；
- [ ] duplicate effects = 0；
- [ ] unauthorized Active = 0；
- [ ] active p95 ≤ control p95 ×1.20；
- [ ] active p95 absolute increase ≤50ms；
- [ ] restart rehearsal 通过；
- [ ] comparator mismatch rehearsal 通过；
- [ ] kill-switch rehearsal 通过；
- [ ] sensitive scan 通过；
- [ ] production BPS 未超过 1%；
- [ ] deployment evidence 已封存。

---

## 17. v1.50 进入条件

只有 v1.49.2 同时满足 Development Complete 和 Deployment Verified，才允许创建 v1.50 Spec。

v1.50 才允许讨论：

- Graph 成为默认 transition executor；
- 停止在线 Legacy comparator；
- 删除 Legacy orchestration；
- 逐级扩大流量；
- 收敛旧 shadow schema/reason codes；
- 减少双执行器成本。

v1.50 仍不得自动引入 PostgreSQL LangGraph checkpointer/`interrupt`。该能力必须由真实跨请求图内暂停需求触发，并另立 ADR/Spec。

---

## 18. 最终验收问题

评审必须能用代码和证据回答“是”：

1. Provider 是否只获取 source observations，而不运行 transition mutation？
2. Graph 节点是否真实生成 draft delta，而不是最终调用完整 Legacy kernel？
3. Legacy 与 Graph 是否只共享叶子领域函数，不共享 orchestration？
4. 故意破坏 Graph reducer 时，Comparator 是否一定发现差异？
5. Comparator mismatch 是否发生在 commit 前，并只提交一次 Legacy outcome？
6. fallback 是否完全复用原 observation bundle？
7. AgentOps 是否能准确区分 Graph assigned、Graph committed 与 fallback Legacy？
8. production 配置是否从代码层禁止超过 1%？
9. Production evidence 是否绑定真实 commit/config/cohort/window，而不是 development forced Graph？
10. Rollback 是否只需 mode/BPS/kill switch，不需要修复学生数据？
11. 是否仍只有 `autotutor_sessions` 一个业务状态真相？
12. 是否在满足真实 production ≥100 committed Graph transitions 前拒绝进入 v1.50？

任一答案为“否”，v1.49.2 不得标记完成，不得扩大 Active BPS，也不得创建 v1.50。
