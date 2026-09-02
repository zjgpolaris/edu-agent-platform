# EduAgent AutoTutor LangGraph Independent Transition v1.49.1 Spec

**状态：** Proposed  
**日期：** 2026-09-02  
**优先级：** P0 独立 Transition 计算权、真实 Observation、独立 Comparator；P1 可聚合 Active 观测与生产 Canary 证据  
**前置版本：** v1.49 AutoTutor LangGraph Active Transition Canary  
**后续候选：** v1.50 AutoTutor Single Executor Consolidation

---

## 0. 决策摘要

v1.49 已完成并在以下提交上取得开发证据：

- code commit：`4b76ad011a5af86e0a9a026730c18e3bcc82654a`；
- Active evidence commit：`fe889ce79a042957e1f6574a99c9b4a7b908b6d1`；
- Shadow evidence commit：`fb9d3bc53ee21adc653dced5fd7d05606c0b91c7`；
- Fast release gate：66/66 suites、542/542 cases；
- Browser E2E：13/13；
- Shadow transition parity：29/29；
- Active synthetic full-outcome materialization：1/1；
- duplicate effect：0；
- unauthorized active：0。

这些结果证明了以下能力已经成立：

- 服务端可信 cohort 与 stable bucket 路由；
- session-level sticky `executor_mode`；
- active 默认关闭、BPS 默认 0；
- Graph 结果通道可以进入既有 CAS/事务边界；
- precommit Graph 异常可降级 Legacy；
- answer idempotency、restart/recovery 和 public API 无回归；
- PostgreSQL LangGraph checkpointer/`interrupt` 没有被隐式引入。

但结合当前代码，v1.49 尚未证明 Graph 已取得独立的 transition compute ownership：

1. `AutoTutorObservationBundle` 仍包含 `materialized` 完整 outcome；
2. `_act`、judge、reflect/re-plan、advance、exit ticket 和 `_finalize` 仍先在现有状态机中完成；
3. `_materialize_selected_outcome` 在完整 next state 已产生后才构造 observation；
4. Graph 节点根据 `materialized.next_state` 路由，最终 `_active_materialize` 反序列化预计算 outcome；
5. `CapturedAutoTutorObservationProvider`、`LegacyTransitionExecutor` 和 `GraphActiveTransitionExecutor` 尚未成为生产入口；
6. Active GO 报告只有一条合成 materialization case，不是独立 trajectory 或生产 canary 证据；
7. rollout observation 尚不能直接聚合 selected executor、transition kind、comparator、fallback 和分段 latency。

因此 v1.49.1 的决定是：

> 不扩大 Active BPS，不删除 Legacy，不进入 v1.50；先移除 `materialized outcome` 自证明结构，让 Observation Provider 只获取一次非确定性输入，让 Graph 从 `before + command + observations` 独立计算完整 outcome，并建立可验证的真实 canary evidence。

版本主题：**Graph 必须计算结果，而不是确认一个已经算好的结果。**

---

## 1. 项目实际基线

### 1.1 已可复用的 v1.49 安全边界

以下能力不在 v1.49.1 重写：

- `autotutor_sessions`：业务状态唯一真相；
- answer claim：在任何判分、模型调用和 effect 前抢占 revision/idempotency；
- `commit_autotutor_transition`：唯一业务事务提交边界；
- learning event、weakpoint evidence、review memory、Runtime finalize 的 typed intent；
- session CAS、stale、busy、replay、conflict；
- Runtime run/checkpoint/resume/reconcile；
- public state、evidence、handoff 和 demo trace allowlist；
- trusted actor、account status、traffic cohort、data scope 和 rollout eligibility；
- sticky executor config/version/bucket/fallback reason；
- kill switch 和 fail-closed Legacy；
- v1.48.1 的 canonical projection、Shadow reason codes 和 fail-closed ports。

### 1.2 当前实现的事实差距

| 维度 | 当前代码事实 | 风险 |
|---|---|---|
| Observation | bundle 含 `materialized: dict` | 含完整 derived outcome，不是真实 observation |
| Provider | provider 仅在独立 smoke 中使用 | 生产外部调用仍发生在现有 mutation 内 |
| Executor | Legacy/Graph executor 类未接生产入口 | sticky mode 没有真正选择两个独立计算器 |
| Graph route | 读取 `materialized.next_state.step_history` | Graph 分支由已知答案决定，形成自证明 |
| Graph outcome | `_active_materialize` 反序列化 outcome | Graph 没有独立生成 next state/effect/public result |
| Comparator | Graph outcome 与其来源 state 比较 | mismatch 检测无法发现共同来源错误 |
| Active evidence | 1 条 synthetic outcome | 不能证明 start/wrong/replan/exit/finalize trajectory |
| Rollout telemetry | transition/fallback 拼入 `status` | 无法稳定按维度聚合 latency/parity/fallback |
| Production canary | BPS 0，无 committed active 样本 | 不满足 v1.50 生产进入条件 |
| Spec 状态 | v1.49 标为 Development Complete，但 checklist 未回填 | 文档结论与证据粒度不一致 |

### 1.3 v1.49 GO 的正确解释

v1.49 GO 应解释为：

- **GO for active-canary infrastructure scaffold**；
- **GO for trusted routing/CAS/recovery integration**；
- **NO GO for independent Graph compute ownership**；
- **NO GO for production BPS > 0**；
- **NO GO for v1.50 Legacy removal**。

v1.49.1 完成后，才允许把 GO 的含义提升为“Graph active 独立计算已开发完成”。

---

## 2. 目标与非目标

### 2.1 P0 目标

- 生产路径实际使用 `AutoTutorObservationProvider`；
- provider 只返回非确定性输入，不返回 derived state/outcome；
- 一个 transition 的模型、检索、工具、clock、ID、seed observation 最多获取一次；
- Legacy 与 Graph 从同一 immutable bundle 独立计算；
- Graph 节点真正执行 plan/content/judge/reflect/re-plan/advance/finalize；
- Graph 产出完整 `AutoTutorState`、typed effects、events 和 public result；
- Graph active 路径不调用 Legacy transition mutation；
- Legacy comparator 不调用 Graph，不重复外部依赖；
- comparator 在 commit 前完成完整 outcome 比较；
- mismatch/failure 使用同一 bundle 回退 Legacy，并永久降级 session；
- commit 后不存在 executor fallback；
- existing CAS/idempotency/effect transaction 保持唯一提交边界；
- 建立能证明独立性的 source/runtime tripwire；
- 默认 active BPS 保持 0。

### 2.2 P1 目标

- rollout observation 可直接聚合 executor/transition/parity/fallback/latency；
- Active evidence 区分 development synthetic evidence 和 deployment observed evidence；
- AgentOps 展示 AutoTutor control/active 关键指标；
- 完成 production Phase 0 forced rehearsal；
- 在明确部署授权后，允许 verified runtime cohort 1% 手工 canary；
- 建立 v1.50 Go/No-Go 报告。

### 2.3 非目标

- 不删除 Legacy executor；
- 不把 Graph 设置为默认 executor；
- 不扩大到超过 1% production canary；
- 不自动晋级 5%、10% 或 100%；
- 不替换 `autotutor_sessions`；
- 不替换 `commit_autotutor_transition`；
- 不迁移 Runtime checkpoint/resume；
- 不安装 `langgraph-checkpoint-postgres` 或 psycopg3；
- 不使用 LangGraph `interrupt`；
- 不迁移其他 Agent；
- 不修改 verified mastery、错题、复习和教师证据算法；
- 不把真实外部 LLM/RAG 设为默认 CI 必需依赖；
- 不让 Demo、eval、operator、anonymous 或 unverified 承担生产 canary。

---

## 3. 不可破坏的系统不变量

### 3.1 单 Observation 集

一次 transition 只能存在一个 observation bundle：

```text
before + command + trusted context
              │
              ▼
      Observation Provider
      exactly one external-call set
              │
        immutable bundle
          ┌───┴───┐
          ▼       ▼
 selected executor comparator
          │       │
          └───┬───┘
              ▼
        precommit decision
```

- selected executor 和 comparator 不得各自调用 provider；
- Graph/Legacy 不得直接调用 LLM、retrieval、tool、time、uuid 或 random；
- fallback 不得再次调用 provider；
- retry 只能重用已经持久化或仍在 claim 作用域内的同一 bundle；
- provider 失败时释放 claim，不产生未验证题目或业务 effect。

### 3.2 单 Candidate 提交

- 一次 transition 只有一个 outcome 可以进入 commit；
- comparator outcome 永不提交；
- Graph failure/mismatch 只允许在 commit 前选择 Legacy outcome；
- commit 已开始或结果未知时，禁止执行另一 executor；
- unknown commit result 只允许通过 idempotency replay 查询；
- selected outcome 必须与 session 永久降级字段在同一 CAS 中提交。

### 3.3 单业务状态真相

- `autotutor_sessions.state_json + revision` 是业务恢复真相；
- Runtime checkpoint 只保存恢复引用和安全投影；
- Graph 不持久化第二份业务状态；
- 本版本没有 LangGraph checkpointer；
- Runtime checkpoint 与 session revision 不一致时，以 session 为准并 reconcile。

### 3.4 独立性边界

允许 Legacy 和 Graph 共享：

- Pydantic schema；
- `judge_answer`；
- `verified_mastery`；
- `replan_policy`；
- assessment/effect fingerprint builder；
- event/effect stable key builder；
- public projector；
- immutable observations。

禁止共享：

- 整段 transition orchestration；
- 已计算 next state；
- 已计算 public result；
- expected projection；
- Legacy mutation callback；
- Graph compiled result；
- comparator expected outcome。

---

## 4. Observation Provider v2 合同

### 4.1 Schema

建议将现有 observation schema 升级为：

```python
class AutoTutorObservationBundleV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["v1.49.1-observation"]
    transition_id: str
    transition_kind: TransitionKind
    plan: PlanObservation | None
    content: ContentObservation | None
    reflection: ReflectionObservation | None
    advance_content: ContentObservation | None
    exit_ticket: ExitTicketObservation | None
    clock: StableClockObservation
    identifiers: StableIdentifierObservation
    selection: StableSelectionObservation
    call_counts: ObservationCallCounts
    provenance: ObservationProvenance
```

必须删除：

```python
materialized
next_state
public_result
expected_state
expected_projection
effect_intents
runtime_events
verified_mastery
derived_status
```

禁止只通过 `exclude=True` 隐藏这些字段；它们不能存在于对象、private attr、闭包或 side channel 中。

### 4.2 Provider 接口

```python
class AutoTutorObservationProvider(Protocol):
    def prepare(
        self,
        *,
        before: AutoTutorState,
        command: AutoTutorTransitionCommand,
        context: AutoTutorExecutionContext,
    ) -> AutoTutorObservationBundleV2: ...
```

Provider 必须：

- 深拷贝或只读访问 `before`；
- 不修改 session state/private attrs；
- 不执行 `_emit`；
- 不构造 learning/weakpoint/review effect；
- 不写 trace、audit、Runtime 或业务表；
- 显式记录 model/retrieval/tool 调用次数；
- 显式注入 clock、UUID、assessment ID 和 selection seed；
- 返回完整教学内容、来源、assessment 和 reflection 原始结果；
- 保持 content gate fail-closed。

### 4.3 Transition observation 需求

| Transition | Provider 获取内容 |
|---|---|
| start | profile/weakpoints snapshot、计划输入、首步 retrieval/content、clock/IDs |
| correct lesson answer | 下一步 content 或 exit-ticket content、clock/IDs |
| retryable wrong | reflection model/fallback、reteach retrieval/content、clock/IDs |
| max attempts | advance content 或 exit-ticket content、clock/IDs |
| exit-ticket answer | clock/IDs；不得提前计算 mastery/effects |
| recovery resume | persisted state reference、clock；通常 external calls = 0 |

### 4.4 Call count 门禁

每个 transition 记录：

```text
model_calls
retrieval_calls
tool_calls
network_calls
clock_reads
id_allocations
selection_seed_reads
```

硬门禁：

- selected + comparator 总 external calls 等于 provider calls；
- executor external calls = 0；
- comparator external calls = 0；
- fallback additional external calls = 0。

---

## 5. 纯 Transition Kernel

### 5.1 建议模块

```text
backend/agents/autotutor_transition_kernel.py
```

建议拆分：

```python
apply_start(before, command, observations) -> TransitionDraft
apply_lesson_answer(before, command, observations) -> TransitionDraft
apply_exit_ticket_answer(before, command, observations) -> TransitionDraft
apply_recovery_resume(before, command, observations) -> TransitionDraft

build_event_intents(draft) -> list[AutoTutorRuntimeEventIntent]
build_effect_intents(draft) -> AutoTutorTransitionEffects
materialize_public_result(draft) -> dict[str, Any]
```

### 5.2 Kernel 约束

- 输入相同必须产生完全相同 outcome；
- 不访问数据库、网络、tool registry、LLM 或 trace store；
- 不读取 `time.time()`、`uuid4()` 或 random；
- 不修改输入 state/bundle；
- 所有 event/effect keys 稳定可重算；
- full state 通过 `AutoTutorState.model_validate`；
- typed effects 通过现有事务服务 schema；
- public result 只由 candidate state 和安全 diagnostics 投影；
- 不包含 executor 私有 bucket 或 raw observations。

### 5.3 当前函数迁移

| 当前函数 | v1.49.1 拆分 |
|---|---|
| `_act` | `prepare_content_observation` + `apply_content_observation` |
| `_reflect_and_replan` | `prepare_reflection_observation` + `apply_reflection/replan` |
| `_start_exit_ticket` | `prepare_exit_ticket_observation` + `apply_exit_ticket` |
| `_submit_exit_ticket_answer` | 纯 `apply_exit_ticket_answer` |
| `_advance` | 纯 route + observation application |
| `_finalize` | 纯 state/effect/event intent builder |
| `_emit` | event intent materializer；commit 后 trace mirror |
| `_record_content_event` | typed learning event intent builder |

迁移期间允许保留兼容 wrapper，但 wrapper 必须调用 provider/kernel，不得保留第二套业务规则。

---

## 6. 独立 Executor 与真实 LangGraph

### 6.1 Executor 接口

```python
class AutoTutorTransitionExecutor(Protocol):
    mode: ExecutorMode

    def execute(
        self,
        *,
        before: AutoTutorState,
        command: AutoTutorTransitionCommand,
        observations: AutoTutorObservationBundleV2,
    ) -> AutoTutorTransitionOutcome: ...
```

生产入口必须显式构造并调用：

```text
LegacyTransitionExecutor
GraphActiveTransitionExecutor
```

禁止 `auto_tutor.py` 先 mutation state，再调用 executor 包装结果。

### 6.2 Graph 真实节点

目标 Graph：

```text
load_context
  ├─ start
  │    plan → content_gate → teach → prepare_assessment → build_outcome
  ├─ lesson_answer
  │    judge
  │      ├─ correct → advance → next_content_or_exit → build_outcome
  │      ├─ retryable_wrong → reflect → re_plan → reteach → build_outcome
  │      └─ max_attempts → mark_struggling → advance → build_outcome
  ├─ exit_ticket_answer
  │    verify_exit_ticket → calculate_mastery → build_effect_intents → finalize
  └─ recovery_resume
       validate_state → route_current_phase → build_outcome
```

每个节点必须：

- 从 Graph state 的 `before/command/observations/draft` 读取；
- 返回新增 draft/state delta；
- 不读取 `materialized.next_state`；
- 不调用 Legacy wrapper；
- 不访问外部 port；
- 记录真实 visited node；
- 失败时返回安全 reason code。

### 6.3 Graph state

```python
class AutoTutorGraphTransitionState(TypedDict, total=False):
    schema_version: str
    before: dict[str, Any]
    command: dict[str, Any]
    observations: dict[str, Any]
    draft: dict[str, Any]
    outcome: AutoTutorTransitionOutcome
    visited_nodes: list[str]
    diagnostics: list[str]
```

禁止字段：

```text
legacy_after
expected_state
expected_projection
materialized_outcome
legacy_callback
```

---

## 7. 独立 Comparator

### 7.1 Comparator 流程

Graph active canary：

1. provider 获取一次 bundle；
2. Graph selected executor 独立计算 outcome；
3. Legacy dry-run 使用同一 before/command/bundle 独立计算 outcome；
4. comparator 比较完整 canonical outcome；
5. matched 才允许 Graph outcome 进入 commit；
6. mismatch 使用已算好的 Legacy outcome，并在同一 CAS 永久降级 session；
7. comparator outcome 永不产生 side effect。

Legacy control/shadow：

1. provider 获取一次 bundle；
2. Legacy selected executor 计算 outcome；
3. shadow 开启时 Graph dry-run；
4. 只提交 Legacy outcome。

### 7.2 比较维度

- `AutoTutorState.model_dump(mode="json")` 的稳定 canonical form；
- public result；
- runtime/domain event sequence；
- learning event effect keys 和 payload allowlist；
- weakpoint evidence key、parent evidence、assessment fingerprint；
- review memory key 和目标日期；
- verified mastery/evidence/summary；
- revision/status/phase/current step/replans；
- content-blocked contract；
- no answer leakage；
- Runtime finalize intent。

仅允许忽略：

- executor mode；
- executor-only diagnostics；
- measured latency；
- visited node 名称；
- trace implementation detail。

### 7.3 Reason codes

```text
state_mismatch
public_result_mismatch
event_sequence_mismatch
learning_effect_mismatch
weakpoint_effect_mismatch
review_effect_mismatch
mastery_mismatch
content_gate_mismatch
revision_mismatch
graph_execution_failed
legacy_comparator_failed
observation_invalid
observation_external_call_duplicate
```

reason code 可观测，但不得向学生公开内部状态或原始答案。

---

## 8. 生产 Orchestration 改造

### 8.1 Start

```text
start idempotency lookup
  → create immutable initial state
  → sticky executor decision
  → provider.prepare(start)
  → selected executor.execute
  → comparator.execute
  → precommit decision/fallback
  → persist session once
  → start/mirror Runtime run
  → write rollout observation
```

约束：

- initial state 在 executor 前不包含 lesson plan/content；
- plan/content 只能由 selected outcome 提供；
- Graph failure 前没有业务 session insert；
- fallback 使用同一 IDs/clock/content；
- idempotent replay 不重新调用 provider/executor。

### 8.2 Answer

```text
load session
  → claim revision/idempotency/request hash
  → read persisted sticky executor mode
  → provider.prepare(answer)
  → selected executor.execute
  → comparator.execute
  → precommit decision/fallback
  → commit_autotutor_transition
  → Runtime checkpoint mirror
  → rollout observation
```

约束：

- claim 前不调用 provider；
- stale/busy/replay/conflict 不调用 provider；
- provider/executor/comparator 异常释放 claim；
- commit unknown 不运行另一 executor；
- kill switch 在 provider 前永久降级 Graph session；
- resume handler 不自行选 executor。

### 8.3 Event 提交顺序

- executor 只产生 event intents；
- selected outcome 进入事务前不写 trace/learning/weakpoint/review；
- business effects 与 session CAS 同事务；
- trace/Runtime mirror 在 commit 成功后执行；
- mirror failure 不回滚已提交业务 transition，进入 reconcile。

---

## 9. Typed Outcome 与 Effect 完整性

### 9.1 Outcome schema

```python
class AutoTutorTransitionOutcomeV2(BaseModel):
    schema_version: Literal["v1.49.1-outcome"]
    executor_mode: ExecutorMode
    next_state: AutoTutorState
    learning_events: list[LearningEventIntent]
    weakpoint_evidence: list[WeakpointEvidenceIntent]
    review_memory: MemoryEntryUpsert | None
    runtime_events: list[AutoTutorRuntimeEventIntent]
    runtime_finalize: RuntimeFinalizeIntent | None
    public_result: AutoTutorPublicTransitionResult
    diagnostics: AutoTutorTransitionDiagnostics
```

禁止 `Any` 作为 production outcome 的 effect/state/public result 类型。

### 9.2 Stable effect key

Effect key 必须由以下稳定输入构造：

```text
session_id
claimed_revision
transition_kind
effect_kind
objective_id / assessment_fingerprint
parent evidence key（如适用）
```

同一 bundle 的 Legacy/Graph effect key 必须完全相同。

### 9.3 Public result

- 使用明确 Pydantic public schema；
- 不暴露 executor bucket、raw mismatch、raw observation；
- 不暴露 correct answer，除非既有 completed contract 明确允许；
- replay response 与首次 commit 完全一致；
- fallback 不能改变学生可见语义。

---

## 10. Rollout Observation v2

### 10.1 当前缺口

现有 `agent_rollout_observations` 只有：

- agent/config/runtime mode/commit/environment；
- status/latency/trace/data scope；
- cohort/eligibility。

当前 AutoTutor 将 `transition_kind` 拼入 `status`，无法可靠聚合：

- selected executor；
- comparator matched；
- fallback reason；
- provider/selected/comparator 分段 latency；
- external-call count；
- effect intent count。

### 10.2 Schema 建议

建议下一 Alembic migration 为 shared observation 表增加 nullable、安全枚举列：

```text
selected_executor TEXT
transition_kind TEXT
comparator_matched INTEGER
fallback_reason TEXT
provider_latency_ms INTEGER
executor_latency_ms INTEGER
comparator_latency_ms INTEGER
observation_external_calls INTEGER
effect_intent_count INTEGER
```

如果 shared table ownership 不允许扩展，则新增窄表：

```text
autotutor_rollout_observations
```

并以 `observation_id` 与 shared rollout observation 一一关联。实现前必须检查当前最新 migration revision，禁止凭文档硬编码冲突 revision。

### 10.3 隐私要求

禁止存储：

- student ID；
- session ID；
- raw answer；
- question/prompt/teaching text；
- raw Graph state；
- raw reflection；
- source content。

允许存储：

- 安全枚举；
- 聚合计数；
- 毫秒 latency；
- deployment/config/schema version；
- hashed/opaque trace reference（沿用现有合同）。

### 10.4 写入失败语义

- observation 写失败不改变已提交学生响应；
- 写失败必须进入 existing audit health；
- production canary 任一 observation failure 是 rollout blocker；
- observation failure 不允许通过静默 `except` 永久吞掉而无 health signal。

---

## 11. Active Evidence v2

### 11.1 Evidence scope

报告必须新增：

```text
evidence_scope = development | deployment
```

- development：deterministic trajectory、fault injection、forced Graph；
- deployment：来自指定 environment/commit/config/cohort 的数据库聚合。

禁止用一条 synthetic materialization case 宣称 production canary GO。

### 11.2 Development report

至少覆盖：

- start；
- correct answer；
- retryable wrong；
- reflect/re-plan/reteach；
- max attempts；
- next lesson；
- exit-ticket correct/wrong；
- content blocked；
- finalize effects；
- stale/busy/replay/conflict；
- precommit failure/mismatch fallback；
- restart/resume；
- kill switch。

至少 100 个 transition fixtures 或生成式 trajectory transitions，不能只有 1 条 synthetic outcome。

### 11.3 Deployment report

绑定：

- deployed code commit；
- config version；
- environment；
- observation/outcome/Graph schema；
- control baseline commit/config/window；
- trusted cohort contract；
- sample window；
- evidence query hash/version。

指标：

- sessions/transitions by executor/kind；
- exact comparator parity；
- success/failure/fallback；
- stale/busy/replay/conflict；
- duplicate effects；
- unauthorized active；
- observation failures；
- provider external calls；
- provider/Graph/Legacy/total p50/p95；
- restart/recovery；
- kill-switch drill；
- sensitive field scan。

---

## 12. 配置与 Canary 策略

### 12.1 v1.49.1 开发期间

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
```

即使当前 v1.49 evidence 为 GO，也不得在独立计算门禁前提高 BPS。

### 12.2 Phase 0：Forced Graph rehearsal

- production BPS 0；
- internal test context 才能强制 Graph；
- Graph independence tripwire 通过；
- development transitions ≥100；
- parity 100%；
- duplicate effects 0；
- full restart/kill-switch rehearsal；
- clean commit evidence GO。

### 12.3 Phase 1：Verified cohort 1%

只有明确部署授权后手工设置：

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=active_canary
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=100
```

约束：

- production only；
- verified + active account + runtime scope + eligible；
- comparator 100%；
- fallback enabled；
- observation health ready；
- 不自动晋级。

### 12.4 本版本最大范围

v1.49.1 最大生产范围为 1%。5%、10% 和 100% 均不属于本版本。

---

## 13. 核心测试计划

### 13.1 Observation provider

- before deep immutability；
- no DB/trace/Runtime writes；
- exact model/retrieval/tool counts；
- stable clock/ID/seed；
- start/correct/wrong/max-attempt/exit/recovery bundles；
- provider failure fail-closed；
- recursive forbidden-key scan；
- serialization 后仍不含 derived outcome。

### 13.2 Graph independence tripwire

测试必须同时执行：

1. monkeypatch `LegacyTransitionExecutor.execute` 为抛异常；
2. monkeypatch legacy mutation wrappers `_act/_reflect_and_replan/_start_exit_ticket/_finalize` 为抛异常；
3. forced Graph 完成：

```text
start
→ wrong
→ reflect
→ re-plan
→ reteach
→ correct/max-attempt advance
→ exit ticket
→ finalize
```

4. typed effects 和 public result 正确；
5. external calls 只来自 provider。

这是 v1.49.1 最重要的硬门禁。

### 13.3 Full parity

- full state exact canonical parity；
- public exact parity；
- runtime/domain event sequence；
- learning/weakpoint/review typed effects；
- effect keys/parent relationship；
- verified mastery；
- content blocked；
- answer feedback/reflection provenance；
- no answer leakage。

### 13.4 Transaction/fault injection

- start insert failure；
- answer claim release；
- failure before/after each effect；
- CAS stale；
- concurrent same revision；
- same/different idempotency payload；
- unknown commit result；
- Graph execution failure；
- comparator mismatch；
- Legacy comparator failure；
- no postcommit fallback；
- duplicate effects 0。

### 13.5 Routing/recovery

- old session defaults Legacy；
- sticky Graph across restart；
- BPS changes do not reroute existing session；
- kill switch permanently downgrades before provider；
- resume obeys persisted mode；
- stale Runtime checkpoint reconciles；
- Demo/eval/operator/unverified/anonymous excluded；
- public API cannot force executor。

### 13.6 Frontend/E2E

- Legacy 13 flows；
- internal forced Graph 13 flows；
- refresh/resume Graph session；
- wrong/replan/exit/evidence；
- content blocked；
- UI 不暴露 executor/mismatch/observation。

### 13.7 建议 suite

```text
autotutor_observation_provider_v2_smoke
autotutor_langgraph_independence_smoke
autotutor_langgraph_full_trajectory_parity_eval
autotutor_langgraph_typed_effect_parity_smoke
autotutor_langgraph_comparator_fallback_smoke
autotutor_langgraph_active_transaction_smoke
autotutor_langgraph_active_routing_smoke
autotutor_langgraph_active_recovery_smoke
autotutor_rollout_observation_v2_smoke
autotutor_active_evidence_v2_smoke
```

既有 false mastery、content blocked、idempotency、fault injection、trajectory、frontend 和 release gate 必须继续全绿。

---

## 14. 实现里程碑

### Milestone A：Characterization 与 Schema 禁令

- 固化 v1.49 public/state/effect characterization；
- 定义 observation v2/outcome v2；
- 加 recursive forbidden-key tripwire；
- 明确 v1.49 evidence scope；
- 默认 BPS 继续为 0。

### Milestone B：真实 Provider

- 拆 plan/content/reflection/exit-ticket observation；
- 注入 clock/ID/seed；
- 外部调用计数；
- Legacy 先改为消费 provider；
- 既有 trajectory/public/DB 行为保持不变。

### Milestone C：纯 Kernel 与 Typed Intents

- 拆现有 mutation；
- state delta/event/effect/public result 纯化；
- 移除 production outcome 中的 `Any`；
- stable effect key parity。

### Milestone D：Graph 独立计算

- Graph 节点调用纯 domain functions；
- 删除 `materialized`；
- 生产入口调用 `GraphActiveTransitionExecutor`；
- independence tripwire 全绿。

### Milestone E：独立 Comparator

- Legacy/Graph 同 bundle 双计算；
- full outcome comparator；
- precommit mismatch fallback；
- no postcommit fallback；
- comparator latency 和 reason codes。

### Milestone F：Observation/Evidence v2

- migration/schema；
- writer/health/AgentOps aggregation；
- development report ≥100 transitions；
- sensitive scan；
- clean commit GO。

### Milestone G：Production Phase 0/1

- immutable deployment verification；
- restart/kill-switch drill；
- 手工 verified 1% canary；
- ≥100 committed active transitions；
- v1.50 Go/No-Go。

---

## 15. 预计代码落点

| 文件 | 改动 |
|---|---|
| `backend/agents/autotutor_execution.py` | observation/outcome v2、真实 executor、删除 materialized |
| `backend/agents/autotutor_observations.py` | 新增真实 provider 与 call counter |
| `backend/agents/autotutor_transition_kernel.py` | 新增纯 transition/effect/event builders |
| `backend/agents/autotutor_graph.py` | Graph 节点真实计算，不读取预计算 state |
| `backend/agents/auto_tutor.py` | 收敛为 claim/provider/execute/compare/commit orchestration |
| `backend/services/autotutor_transition_service.py` | 仅在 typed schema 需要时收紧校验 |
| `backend/agent_runtime/rollout_observations.py` | v2 安全维度写入与聚合 |
| `backend/db/schema.py` | rollout observation nullable columns/窄表 |
| `backend/alembic/versions/*` | 下一可用 revision migration |
| `backend/agent_ops.py` | AutoTutor executor metrics |
| `backend/api/routers/learning.py` | 保持可信 context，不增加 public force flag |
| `backend/agent_runtime/resume_registry.py` | 保持 persisted mode |
| `eval/run_core_evals.py` | 注册 v1.49.1 suites |
| `scripts/release_gate.py` | 注册 P0 gates |
| `eval/reports/autotutor_active_latest.*` | 升级 evidence schema/scope |
| `.env.example`、`README.md` | 配置、状态和 rollout 说明 |

---

## 16. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Provider 抽取改变 Legacy 行为 | 先 characterization，再让 Legacy 单独消费 provider |
| 同 bundle 两执行器规则漂移 | 共享原子领域规则，不共享 orchestration/outcome |
| comparator 增加延迟 | 单独测量，1% canary，后续 v1.50 才停 comparator |
| clock/ID 导致 parity | 全部 provider 注入，禁止 executor 自取 |
| event trace 顺序变化 | event intents exact sequence parity |
| fallback 重复 effect | fallback 只选未提交 outcome，单 commit boundary |
| observation schema 写放大 | nullable 窄字段，不存 raw state/text |
| evidence 把 synthetic 当 production | 强制 `evidence_scope` 和 deployment sample requirement |
| Graph/Legacy 共同错误 | 独立 orchestration + domain invariant tests + public/effect gates |
| 迁移期间双代码复杂度 | milestone 完成即删除 compatibility path，不长期保留第三条路径 |

---

## 17. 回滚策略

### 17.1 即时回滚

```text
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=true
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
```

- 新 session 选择 Legacy；
- existing Graph session 在下一次 provider 前永久降级；
- 已提交 transition 不重放；
- fallback reason 进入安全 observation；
- 学习证据不回滚。

### 17.2 版本回滚

- observation/outcome v2 只存在于请求内存，不进入 session state；
- session state 新字段继续保持旧代码可忽略；
- DB migration 只增加 nullable 字段或窄表；
- 旧 writer 可继续工作；
- rollback 不删除 observation/evidence；
- 不需要 Graph checkpoint migration。

### 17.3 开发回滚点

每个 milestone 独立提交：

1. schema/tests；
2. provider + Legacy；
3. kernel；
4. Graph；
5. comparator；
6. telemetry/evidence。

任一阶段失败可退回上一稳定 milestone，不能通过重新引入 `materialized outcome` 绕过门禁。

---

## 18. Development Complete 定义

以下全部满足才可把 v1.49.1 标记为 Development Complete：

- [ ] Production observation schema 不含 `materialized` 或任何 derived outcome；
- [ ] Provider 实际进入 start/answer/resume production orchestration；
- [ ] Provider before mutation = 0；
- [ ] Provider business/Runtime writes = 0；
- [ ] 单 transition duplicate external observations = 0；
- [ ] Legacy executor 消费 observation v2；
- [ ] Graph executor 消费 observation v2；
- [ ] Graph 不调用 Legacy mutation/executor；
- [ ] Graph nodes 独立生成完整 next state；
- [ ] Outcome state/effect/public result 不使用 `Any`；
- [ ] independence tripwire 完整 trajectory 通过；
- [ ] full trajectory parity = 100%；
- [ ] event sequence parity = 100%；
- [ ] typed effect parity = 100%；
- [ ] precommit mismatch/failure fallback 使用同 bundle；
- [ ] postcommit fallback = 0；
- [ ] duplicate business effects = 0；
- [ ] stale/busy/replay/conflict provider calls = 0；
- [ ] sticky routing/restart/resume/kill switch 通过；
- [ ] unauthorized active = 0；
- [ ] default active BPS = 0；
- [ ] rollout observation v2 可聚合；
- [ ] development evidence transitions ≥100；
- [ ] evidence sensitive scan 通过；
- [ ] false mastery/content blocked/fault injection 全绿；
- [ ] Legacy 与 forced Graph E2E 各 13/13；
- [ ] frontend unit/lint/build 通过；
- [ ] fast release gate 通过；
- [ ] clean commit evidence GO；
- [ ] LangGraph PostgreSQL checkpointer/interrupt 未引入。

---

## 19. Deployment Verified 定义

以下全部满足才允许认为 production Phase 1 完成：

- [ ] v1.49.1 clean commit 已部署且 immutable verification 通过；
- [ ] production auth/trusted cohort ready；
- [ ] control baseline 样本充分；
- [ ] observation v2 health ready；
- [ ] verified cohort 1% 手工开启；
- [ ] active committed transitions ≥100；
- [ ] comparator exact parity = 100%；
- [ ] precommit fallback <1%；
- [ ] duplicate effect = 0；
- [ ] unauthorized active = 0；
- [ ] observation write failure = 0；
- [ ] active p95 ≤ control p95 ×1.20；
- [ ] active p95 绝对增加 ≤50ms；
- [ ] restart/recovery drill 通过；
- [ ] kill-switch drill 通过；
- [ ] sensitive field scan 通过；
- [ ] 未自动扩到 5%/10%/100%。

---

## 20. v1.50 进入条件

只有 v1.49.1 同时满足 Development Complete 和 Deployment Verified，才允许创建 v1.50 Spec。

v1.50 可以讨论：

- Graph 成为默认 transition executor；
- 停止在线 Legacy comparator；
- 删除 Legacy orchestration wrapper；
- active 从 1% 逐步扩大到 100%；
- 简化 shadow/active 双路由配置；
- 收敛兼容 schema 和旧 reason codes。

v1.50 仍不得自动引入 LangGraph checkpointer/`interrupt`。只有出现真实跨请求图内暂停需求，并能删除或降级现有一份状态真相时，才另立独立 ADR/Spec。

---

## 21. 最终验收问题

发布评审必须能用证据回答“是”：

1. 如果所有 Legacy transition mutation 都抛异常，forced Graph 是否仍能完成完整课程？
2. Observation 中是否完全不存在 next state、expected outcome 或 effect intents？
3. 同一次 transition 是否只有 provider 调用外部依赖？
4. Graph 与 Legacy 是否从同一 bundle 独立计算？
5. Comparator mismatch 是否发生在 commit 前并只提交一次？
6. Active evidence 是否来自 ≥100 条完整开发 transition，而不是单条 synthetic case？
7. Production evidence 是否绑定真实部署 commit/config/cohort/window？
8. Demo/eval/operator/unverified/anonymous active 是否始终为 0？
9. Rollback 是否只需 kill switch/mode/BPS，不需要数据修复？
10. 是否仍只有 `autotutor_sessions` 一个业务状态真相？

任一答案为“否”，v1.49.1 不得标记完成，也不得进入 v1.50。

---

## 22. Implementation Record（2026-09-02）

本轮已完成 Development 实现与本地证据：

- production start/answer/resume-answer 已接入一次性 Observation Provider；
- Legacy 与 Graph executor 均消费 `v1.49.1-observation`，不再接受 materialized outcome；
- selected/comparator 在 commit 前使用同一 bundle 独立计算，Graph mismatch/failure 使用已计算 Legacy outcome 永久降级；
- start insert + learning event intents、answer CAS + 全部业务 effects 分别保持单事务；
- trace/Runtime mirror 移到业务提交后，mirror failure 不触发第二次业务执行；
- rollout observation v2 migration 为 `014`，包含 executor、transition、comparator、fallback、分段 latency、external call 与 effect count；
- development trajectory 覆盖 start/correct/wrong/re-plan/max-attempt/next-content/exit-pass/exit-fail/content-blocked/recovery，共 `108/108` parity；
- Legacy mutation wrapper tripwire 通过，executor external calls / side effects 为 `0 / 0`；
- start/answer 事务 fault injection 为 `8/8`；
- core smoke 为 `513/514`，唯一未执行项是环境依赖的 `history_character_smoke`，无失败 suite。

仍属于发布阶段而非本地开发完成项：clean commit evidence、fast/production release gate、真实部署 1% canary、≥100 committed active production transitions、部署窗口 latency/health 与 kill-switch rehearsal。以上完成前，本 Spec 不得标记 Deployment Verified，也不得进入 v1.50。
