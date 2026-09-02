# EduAgent AutoTutor Production Canary Admission & Evidence Closure v1.49.3 Spec

**状态：** Proposed
**日期：** 2026-09-02
**优先级：** P0 Production Admission Fail-Closed；P1 Exact Evidence、AgentOps 与 1% Canary 演练
**前置版本：** v1.49.2 AutoTutor LangGraph Canary Readiness
**后续候选：** v1.50 AutoTutor Single Executor Consolidation（仅在本 Spec Production Verified 后允许创建）

---

## 0. 决策摘要

v1.49.2 已在本地完成 AutoTutor transition 计算链路的结构独立性与开发级 Canary readiness：

- Provider 已改为 source-only，不再调用 `_KERNEL_ACT` / `_KERNEL_MUTATE_ANSWER`；
- Graph 业务节点真实更新 transition draft，不再在 final node 调用完整 Legacy orchestration；
- Graph-only defect injection 能被 Comparator 检出，并在 commit 前回退 Legacy；
- 完整 trajectory parity 为 `108/108`；
- start/answer transaction fault injection 为 `8/8`；
- fast release gate 为 `69/69 suites`、`657/657 cases`；
- frontend lint、`30/30` unit tests 和 production build 通过；
- production Active 上限已硬限制为 `100 BPS = 1%`；
- migration 015 已定义 assigned/selected executor 与 transition provenance；
- AutoTutor transition aggregate、rollout status 和 AgentOps 后端聚合入口已建立；
- 默认 executor 仍为 Legacy，Active BPS 仍为 0；
- 未引入 PostgreSQL LangGraph checkpointer 或 `interrupt`。

当前本地提交链为：

```text
a38f353  feat: make AutoTutor transitions independently executable
1d49cde  docs: seal AutoTutor independent transition evidence
e20b364  feat: prepare AutoTutor graph canary rollout
```

但项目实际仍不满足 v1.50 进入条件：

1. `origin/main` 仍停在 `fb9d3bc`，上述 3 个提交尚未进入远端默认分支；
2. migration 015 尚未在生产数据库执行；
3. 当前 active evidence 绑定 dirty workspace，决策为 `NO_GO`；
4. 没有 production control baseline，也没有 verified cohort 的真实 Graph committed 样本；
5. `select_executor` 尚未把 schema readiness 与 observation health 纳入生产分流；
6. 已分配 Graph 的存量会话只对 kill switch 进行直接降级，未统一处理 schema、writer health 和配置漂移；
7. `bucket_not_selected` 等普通路由原因与真实 Graph fallback 共用 `executor_fallback_reason`，语义不够精确；
8. Canary aggregate 尚未形成 hash-sealed AutoTutor deployment evidence；
9. duplicate-effect、restart、writer failure、kill-switch rehearsal 尚未成为 production GO 的可验证输入；
10. AgentOps 前端仍主要展示通用 History Character control/shadow 结构，没有 AutoTutor transition Canary 专用面板。

因此 v1.49.3 的决定是：

> 不进入 Single Executor Consolidation，不扩大到 1% 以上；先把生产流量准入、存量会话降级、精确聚合、不可变 evidence、运维 UI 和演练闭环补齐，再完成一次受控的 verified 1% Canary。

版本主题：**生产系统不仅要能观测错误，还必须在观测链失效时拒绝把流量交给 Graph。**

---

## 1. 项目实际基线

### 1.1 已成立且必须保留的边界

- `autotutor_sessions` 是唯一业务状态真相；
- start idempotency 和 answer claim 在 Provider 前完成；
- stale、busy、replay、conflict 不调用 Provider；
- selected 与 comparator 共用同一个 immutable observation bundle；
- Provider external-call set 只能执行一次；
- Graph/Legacy/comparator/fallback 不得追加 retrieval、model、tool 或 network call；
- Comparator 比较 next state、public result、runtime events、learning effects、weakpoint effects、review memory 和 runtime finalize；
- Comparator mismatch 与 executor exception 只能在 commit 前回退；
- comparator outcome 永不提交；
- start/answer 的业务效果仍通过现有数据库事务一次提交；
- learning-event `effect_key` 唯一索引、weakpoint evidence key 和 Runtime side-effect ledger 继续承担幂等保护；
- session executor assignment、selected mode、config、bucket 与降级状态持久化；
- verified mastery、错题、复习、教师聚合和学生可见教学行为不变；
- public state、handoff、evidence 和 demo trace 继续使用 allowlist；
- Runtime resume 继续回到 `submit_answer`，不创建第二份 Graph checkpoint 状态；
- Legacy 始终可作为即时回滚路径；
- production BPS 默认 0，本版最高 1%。

### 1.2 v1.49.2 已完成能力

| 维度 | 当前状态 | 结论 |
|---|---|---|
| Provider 独立性 | source-only，源码 tripwire 禁止 `_KERNEL_*` | Development GO |
| Graph orchestration | 真实 node draft delta，禁止完整 Legacy entrypoint | Development GO |
| Comparator sensitivity | Graph-only mutation injection 可检出 | Development GO |
| 完整 parity | 108/108 | Development GO |
| 事务安全 | fault injection 8/8，无重复 effect | Development GO |
| Telemetry | migration 015 + assigned/selected/provenance | Code Complete |
| Canary aggregate | exact commit/config/environment/cohort/window 基础聚合 | Code Complete |
| Production cap | 100 BPS | Code Complete |
| Production deploy | 未 push、未 migrate、未 deploy | NO GO |
| Production samples | 0 committed Graph transition | NOT READY |
| Rehearsal evidence | 未形成 deployment evidence | NOT READY |

### 1.3 当前实现差距

| 差距 | 当前代码事实 | 生产风险 |
|---|---|---|
| Admission | `select_executor` 不读取 schema readiness | migration 缺失时仍可能分配 Graph |
| Observation health | 聚合会阻断 GO，但分流本身不阻断 | writer 失效期间可能继续产生不可审计 Active |
| Existing session | answer 前只检查 kill switch | schema/config/health 漂移不能及时永久降级 |
| Assignment reason | 普通 bucket 路由原因写入 fallback reason | fallback rate 与原因语义可能被污染 |
| Evidence | aggregate 是可变查询结果 | 无法证明评审看到的指标对应同一部署窗口 |
| Duplicate effect | 当前查询偏全局窗口 | 可能被无关 Agent/部署污染，或缺少 exact slice 解释 |
| Drills | 测试存在，但没有部署绑定的演练结果 | 无法证明真实部署可 restart/kill-switch/rollback |
| AgentOps UI | 通用 Runtime Rollout panel | 操作员不能直观看到 AutoTutor assigned/committed/fallback |
| Delivery | 本地领先 origin 3 commits | 不存在可部署的远端 immutable commit |

---

## 2. 目标与非目标

### 2.1 P0：Production Admission Fail-Closed

- 建立唯一 `AutoTutorCanaryAdmission` 判定入口；
- production 新会话只有 admission 全绿后才能进入 Graph bucket；
- 已分配 Graph 的存量会话在每次 Provider 前重新检查 admission；
- schema、writer health、commit、config、cohort、BPS 或 kill switch 任一异常均在 Provider 前降级 Legacy；
- admission 查询失败必须 fail-closed；
- admission 检查不得写学生数据、不得调用 LLM/RAG、不得改变 revision；
- admission 允许短 TTL 缓存，缓存过期或刷新失败不得沿用过期 GO；
- admission reason、assignment reason 与真实 fallback reason 明确分离；
- forced Graph 仅允许非 production eval/development scope。

### 2.2 P0：Exact Canary Aggregate 与不可变 Evidence

- 精确定义 observed、eligible、assigned、selected、committed、fallback；
- 只使用同一 commit/config/environment/cohort/window 的数据；
- 区分普通 Legacy control、Graph assigned、Graph committed、Graph fallback Legacy；
- comparator unknown 不能计入 parity 成功；
- observation write failure 必须按 exact deployment provenance 聚合；
- duplicate-effect 检查必须能解释其 transition/run/effect 关联方式；
- active/control latency 必须使用同一可信 cohort 和 deployment window；
- 生成 hash-sealed AutoTutor release evidence；
- evidence 必须包含 schema revision、部署 commit、配置版本、窗口、演练结果与聚合摘要；
- 缺少样本返回 `NOT_READY`，查询异常返回 `UNKNOWN/NO_GO`，不得返回 GO。

### 2.3 P1：AgentOps 与运维闭环

- 增加 AutoTutor transition Canary 专用 operator view；
- API 与前端展示同一 readiness contract；
- 展示 admission、schema、writer、cohort、BPS 和 kill-switch 状态；
- 展示 assigned/committed Graph、Comparator、fallback、latency、effect 和 blocker；
- 提供只读 evidence 查询；
- 明确 push → migrate → BPS 0 deploy → baseline → 1% → evidence → BPS 0 review 的顺序；
- 完成 restart、writer failure、Graph failure、Comparator mismatch 和 kill-switch rehearsal。

### 2.4 非目标

- 不把 Graph 设为默认 executor；
- 不删除 Legacy executor；
- 不停止在线 Comparator；
- 不允许 production 超过 1%；
- 不自动从 0 晋级到 1%；
- 不自动从 1% 晋级到 5%、10% 或 100%；
- 不修改教学内容、练习题、退出票或 mastery 算法；
- 不迁移其他 Agent；
- 不改变 AutoTutor CAS 或事务边界；
- 不引入 PostgreSQL LangGraph checkpointer；
- 不使用 LangGraph `interrupt`；
- 不以 demo/eval/operator/anonymous/unverified 样本作为生产证据；
- 不因为本地测试全绿而跳过真实 migration/deployment evidence。

---

## 3. 不可破坏的不变量

### 3.1 请求链路

```text
trusted request context
        │
        ▼
idempotency / claim
        │
        ▼
AutoTutor Canary Admission
schema / commit / config / health / cohort / BPS / kill switch
        │
   ┌────┴─────┐
   │          │
 denied      admitted
   │          │
 Legacy      sticky bucket assignment
   │          │
   └────┬─────┘
        ▼
source-only Provider（最多一次）
        │
        ▼
selected executor + optional comparator
        │
        ▼
one precommit decision
        │
        ▼
one atomic business commit
        │
        ▼
telemetry / trace / runtime mirror
```

### 3.2 Admission 必须在 Provider 前

如果 admission 在 Provider 后执行，会产生以下问题：

- schema/writer 已失效仍执行 Graph candidate；
- 被拒绝流量仍消耗 retrieval/model/tool；
- admission failure 无法证明 external-call set 为 0；
- existing Graph session 可能在健康状态失效后继续运行一个 transition。

因此 start 与 answer/recovery 的统一顺序必须是：

```text
claim → admission → provider → compute/compare → commit → observation
```

stale/replay/conflict 仍应在 admission 之前短路。

### 3.3 单提交边界

- admission 不提交业务状态；
- Provider 不提交业务状态；
- selected/comparator 不提交业务状态；
- fallback 不重放 Provider；
- 只有选中的一个 outcome 可以进入现有 transition service；
- observation write failure 不回滚学生已经成功提交的响应；
- observation write failure 必须进入 audit health 并阻断后续新 Graph admission。

---

## 4. Production Admission 合同

### 4.1 建议数据结构

```python
@dataclass(frozen=True)
class AutoTutorCanaryAdmissionSnapshot:
    status: Literal["admitted", "denied", "unknown"]
    checked_at: str
    expires_at: str
    environment: str
    deployed_commit: str
    config_version: str
    schema_revision: str | None
    observation_health: Literal["ok", "degraded", "unavailable"]
    active_bps: int
    reason_codes: tuple[str, ...]

    @property
    def admitted(self) -> bool: ...
```

该结构不得包含：

- student/session ID；
- raw answer；
- question/teaching/reflection；
- state JSON；
- profile、weakpoint 或 retrieval 内容。

### 4.2 Admission 检查项

production `active_canary` 必须同时满足：

1. `EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS` 在 `1..100`；
2. comparator enabled；
3. fallback enabled；
4. kill switch disabled；
5. config version 非空且与 telemetry slice 一致；
6. bucket salt 非空且在本次部署不可变；
7. deployed commit 为完整 40 位 SHA；
8. runtime schema readiness 为 ready；
9. Alembic revision 至少为 015；
10. `agent_rollout_observations` 包含 migration 015 所需列；
11. exact commit/config/environment 的 observation write health 不为 degraded/unavailable；
12. request data scope 为 runtime；
13. account status 为 active；
14. traffic cohort 为 verified；
15. rollout eligibility 为 true；
16. actor role 为允许的学生主体；
17. 非 internal-force production request。

任一失败都返回 denied。数据库、health 或配置读取抛出异常时返回 unknown，并按 denied 处理。

### 4.3 缓存语义

- 允许进程内 5–15 秒 TTL；
- cache key 至少包含 environment、commit、config version；
- denied/unknown 可短缓存，避免故障放大；
- admitted snapshot 过期后不得 stale-while-error；
- 新部署 commit 不得复用旧 commit snapshot；
- kill switch 必须绕过或主动清空缓存，立即生效；
- 测试可注入 clock，不使用真实 sleep。

### 4.4 路由原因与 fallback 原因分离

当前 `bucket_not_selected`、配置无效等普通 Legacy 路由原因不应写成业务 fallback。

建议 session state 增加：

```text
executor_assignment_reason
executor_admission_status
executor_admission_reasons
executor_admission_checked_at
```

语义：

- `executor_assignment_reason=bucket_not_selected`：正常 Legacy control；
- `executor_assignment_reason=graph_bucket_selected`：正常 Graph assigned；
- `executor_fallback_reason=graph_precommit_fallback:*`：Graph 已尝试但执行失败；
- `executor_fallback_reason=active_comparator_mismatch:*`：Graph 已尝试但 Comparator 不一致；
- `executor_fallback_reason=admission_revoked:*`：存量 Graph session 在下一 transition 前永久降级；
- `executor_fallback_reason=kill_switch_enabled`：已分配 Graph 的存量会话被 kill switch 降级。

普通 Legacy control 的 `executor_fallback_reason` 必须为空。

### 4.5 migration 016 决策

session state 新字段保存在现有 `state_json`，不需要修改 `autotutor_sessions` 表。

为支持跨部署精确审计，建议 migration 016 只增加 nullable telemetry 字段：

```text
assignment_reason TEXT
admission_status TEXT
admission_reason TEXT
admission_checked_at TEXT
```

约束：

- 不修改 migration 015；
- 不存 student/session/raw content；
- 旧 writer 可继续忽略新列；
- downgrade 只删除 nullable 列与对应索引；
- 若实现阶段证明现有字段能无歧义表达相同语义，可通过评审取消 migration 016，但不得继续复用 `fallback_reason` 表示普通 bucket 路由。

---

## 5. Existing Graph Session 降级

### 5.1 检查时点

已分配 Graph 的 session 在以下 transition 前重新检查 admission：

- lesson answer；
- exit-ticket answer；
- recovery resume。

start session 只执行一次 admission 与 bucket assignment。

### 5.2 永久降级规则

如果 session 原始 `executor_assigned_mode=graph_active`，且发生以下任一情况：

- kill switch enabled；
- schema not ready；
- observation health degraded/unavailable；
- deployed commit/config 与 session provenance 不匹配；
- production BPS/config fail-closed；
- admission query error；

则在 Provider 前：

```text
selected executor → legacy
assigned executor → graph_active（保留原分母）
fallback reason → admission_revoked:<reason>
```

该降级随 session state 持久化，后续请求不得自动回升 Graph。只有新 session 可以重新参与 bucket assignment。

### 5.3 不允许的行为

- 不重新执行已经 committed transition；
- 不清除学习证据；
- 不降低 revision；
- 不新建替代 session；
- 不在同一 session 上自动恢复 Graph；
- 不把 admission failure 伪装为 Comparator mismatch；
- 不在 admission denied 后调用 Graph executor。

---

## 6. Exact Canary Aggregate v2

### 6.1 Slice 身份

所有生产判断必须绑定：

```text
agent_type=auto_tutor
deployed_commit=<40-char SHA>
config_version=<immutable version>
environment=production
data_scope=runtime
traffic_cohort=verified
window_start=<UTC timestamp>
window_end=<UTC timestamp>
```

任一字段缺失时不得生成 GO evidence。

### 6.2 指标定义

```text
observed
  exact deployment window 中全部 AutoTutor observation

eligible
  runtime + verified + rollout_eligible=1

graph_assigned
  assigned_executor=graph_active

graph_selected
  graph_assigned 且 selected_executor=graph_active

graph_committed
  graph_selected 且 commit_status in {committed, completed}

graph_fallback
  graph_assigned 且 selected_executor=legacy

legacy_control
  assigned_executor=legacy 且 selected_executor=legacy
  且不存在真实 graph fallback reason

fallback_rate
  graph_fallback / graph_assigned

comparator_parity
  comparator_matched=true / graph_assigned
```

Comparator unknown、缺 observation、缺 provenance 都不得从分母中移除。

### 6.3 输出字段

聚合至少输出：

- observed/eligible/legacy control；
- Graph assigned/selected/committed/fallback；
- commit status 分布；
- assignment/admission/fallback reason 分布；
- transition kind coverage；
- Comparator matched/mismatched/unknown；
- fallback count/rate；
- Provider/executor/comparator/total p50/p95；
- control total p50/p95；
- relative/absolute latency regression；
- observation external-call count 的 min/p50/p95/max；
- effect intent count 的 min/p50/p95/max；
- provenance coverage；
- observation write failure by reason；
- duplicate effect count；
- unauthorized Active count；
- schema/admission health；
- exact slice provenance；
- blockers；
- `NOT_READY | GO | NO_GO | UNKNOWN`。

### 6.4 Duplicate effect 精确检查

优先使用现有关系，不新增学生标识到 rollout telemetry：

```text
observation.trace_id
  → agent_runs.trace_id / run_id
  → agent_side_effects.run_id
  → committed effect ledger

observation.trace_id + window
  → learning_events.metadata_json.trace_id
  → effect_key uniqueness
```

聚合只返回计数和 hash/状态，不返回 effect key、student ID 或 session ID。

如果数据库方言导致 JSON trace 关联不可移植，可在服务层读取 bounded rows 后做 PII-free correlation；不得退回全库无边界统计作为 production GO 依据。

必须区分：

- duplicate row actually committed；
- duplicate attempt prevented by unique key；
- idempotent replay without new effect；
- observation duplicated。

实际 committed duplicate 必须为 0；prevented/replayed 只作为解释性指标，不自动判失败。

### 6.5 GO/NO_GO 规则

Production GO 必须同时满足：

- exact slice provenance 完整；
- schema ready 且 revision ≥015（若采用 migration 016，则 revision ≥016）；
- committed Graph transitions ≥100；
- Graph assigned transitions ≥ committed Graph transitions；
- Comparator exact parity = 100%；
- fallback rate <1%；
- observation failure = 0；
- actual duplicate effect = 0；
- unauthorized Active = 0；
- provenance coverage = 100%；
- start、lesson answer、exit-ticket answer coverage 完整；
- active p95 ≤ control p95 ×1.20；
- active p95 - control p95 ≤50ms；
- restart rehearsal 通过；
- writer-failure rehearsal 通过；
- kill-switch rehearsal 通过；
- evidence hash 与 payload 匹配。

样本不足只返回 `NOT_READY`；指标失败返回 `NO_GO`；查询/schema/provenance 异常返回 `UNKNOWN` 且 decision 为 `NO_GO`。

---

## 7. AutoTutor Deployment Evidence

### 7.1 Evidence schema

建议复用 `agent_release_evidence` 表，新增 AutoTutor payload schema，不新建业务表：

```json
{
  "schema_version": 1,
  "agent_type": "auto_tutor",
  "runtime_mode": "active_canary",
  "deployed_commit": "<40-char SHA>",
  "config_version": "v1.49.3-canary",
  "environment": "production",
  "migration_revision": "015-or-016",
  "generated_at": "<UTC>",
  "window": {"start": "<UTC>", "end": "<UTC>"},
  "cohort": "verified",
  "aggregate": {},
  "admission": {},
  "drills": {},
  "decision": "GO|NO_GO|NOT_READY",
  "blockers": [],
  "evidence_sha256": "<hash>"
}
```

### 7.2 Evidence 约束

- development forced Graph evidence 不能持久化为 production GO；
- dirty workspace evidence 只能是 development `NO_GO`；
- evidence commit 必须等于真实 deployed commit；
- evidence config/environment/window 必须等于 aggregate slice；
- evidence 生成后不可原地修改；
- 相同 payload hash 幂等保存；
- hash 不匹配时拒绝读取为可信 evidence；
- evidence 只存聚合与 reason code，不存学生或教学内容；
- evidence 不自动修改 BPS。

### 7.3 建议脚本

新增：

```text
scripts/build_autotutor_canary_evidence.py
```

支持：

```text
--commit
--config-version
--environment
--window-start
--window-end
--minimum-graph-transitions
--persist
```

脚本必须：

- 默认只读；
- `--persist` 只保存 evidence，不改变 runtime config；
- 校验当前 deployed commit；
- 校验 migration revision；
- 复用服务层 aggregate，不复制 SQL；
- 输出无 PII JSON/Markdown；
- 查询失败退出非 0；
- blockers 非空时不得写 GO。

---

## 8. AgentOps、API 与前端

### 8.1 后端状态合同

`build_rollout_status(agent_type="auto_tutor")` 返回：

```text
phase
status
decision
deployment
schema
admission
control
autotutor_transition_canary
evidence
drills
blockers
next_action
```

建议 phase：

```text
deployment_blocked
deployed_bps_zero
collecting_control
control_ready
canary_not_enabled
collecting_canary
canary_blocked
canary_ready_for_review
production_verified
```

### 8.2 API

继续使用管理员接口：

```text
GET /api/admin/agent-runtime/rollout-status?agent_type=auto_tutor
```

要求：

- admin only；
- 返回 PII-free 聚合；
- production minimum samples 不得低于 100；
- unsupported agent 返回 400；
- query failure 返回明确 UNKNOWN contract，不返回部分 GO；
- 不提供修改 BPS、kill switch 或 cohort 的写接口。

### 8.3 AgentOps UI

增加 AutoTutor Canary panel：

- deployed commit/config/migration；
- current BPS 与 kill switch；
- admission status/reasons；
- control/Graph assigned/committed/fallback；
- Comparator parity；
- observation health；
- transition coverage；
- p95 regression；
- duplicate/unauthorized count；
- rehearsal status；
- evidence hash/freshness；
- blockers 与下一操作。

前端不得展示：

- student/session ID；
- raw answer；
- question/teaching/reflection；
- effect key；
- source content；
- state JSON。

---

## 9. 故障注入与演练

### 9.1 Development drills

必须自动化覆盖：

1. schema table missing → admission denied；
2. Alembic revision 014 → admission denied；
3. observation health degraded → admission denied；
4. observation health query exception → admission unknown/denied；
5. production commit 非完整 SHA → Legacy；
6. BPS 101 → Legacy；
7. comparator disabled → Legacy；
8. fallback disabled → Legacy；
9. kill switch enabled → existing Graph session 永久降级；
10. config drift → existing Graph session 永久降级；
11. Graph executor exception → precommit Legacy fallback；
12. Graph-only reducer mutation → Comparator mismatch fallback；
13. writer failure → 学生响应保持 committed，audit health degraded；
14. stale/replay/conflict → Provider 与 admission 不重复执行；
15. restart 后从持久化 state 恢复 assigned/selected/admission/fallback 语义；
16. aggregate query failure → UNKNOWN/NO_GO；
17. evidence hash tamper → 拒绝信任；
18. unrelated Agent duplicate effect → 不污染 AutoTutor exact slice。

### 9.2 Production rehearsal

生产演练只允许在 BPS 0 或受控 verified 1% 窗口执行：

- deploy/restart 后 schema/admission 恢复；
- 临时 kill switch 后新 session 走 Legacy；
- existing Graph session 下一 transition 前永久降级；
- 已提交 transition 不重放；
- observation/evidence 保留；
- 恢复 `mode=legacy, BPS=0` 不需要修复学生数据。

禁止通过制造真实学生错误数据演练。需要错误注入时使用受控 operator/test actor，并明确排除出生产 GO cohort，或只在预生产环境执行。

---

## 10. 配置合同

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy|shadow|active_canary
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0..100（production）
EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION=v1.49.3-canary
EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT=<immutable non-empty>
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=false
EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED=true
EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED=true
EDU_AGENT_DEPLOYED_COMMIT=<40-char SHA>
EDU_AGENT_ENVIRONMENT=production
```

推荐部署初始值：

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=false
```

只有 Deployment Ready 审核通过后，人工改为：

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=active_canary
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=100
```

达到采样目标后建议先恢复 BPS 0，再生成并评审 evidence。本 Spec 不授权继续扩大流量。

---

## 11. Deployment Runbook

### Phase 0：远端不可变提交

1. 确认 workspace clean；
2. push 本地 3 个前置提交与 v1.49.3 实现；
3. CI fast/full/frontend gates 通过；
4. 记录完整 commit SHA；
5. 禁止以未提交或 dirty artifact 部署。

### Phase 1：Migration 与 BPS 0 部署

1. production config 保持 Legacy/BPS 0；
2. 执行 migration 015；
3. 若采用 admission telemetry 字段，再执行 migration 016；
4. 验证 schema readiness；
5. 验证 observation writer；
6. 验证 admin rollout-status API；
7. 执行一次 restart rehearsal；
8. 生成 BPS 0 deployment preflight evidence。

### Phase 2：Control baseline

在同一 commit/config/environment/verified cohort 下收集：

- Legacy control transitions ≥100；
- start/lesson/exit transition coverage；
- total p50/p95；
- observation failure = 0；
- provenance coverage = 100%。

Control 不足时状态为 `NOT_READY`。

### Phase 3：Verified 1% Canary

需要单独人工授权：

1. mode 改为 active_canary；
2. BPS 设置为 100；
3. 只允许 verified runtime cohort；
4. 持续观察 admission、writer、fallback 和 latency；
5. 任一 hard blocker 立即 kill switch/BPS 0；
6. 达到 committed Graph ≥100 后恢复 BPS 0；
7. 执行 kill-switch rehearsal；
8. 生成 immutable evidence；
9. 评审 GO/NO_GO。

### Phase 4：Review

- GO 只表示 v1.49.3 Production Verified；
- 不自动重新开启 1%；
- 不自动扩大流量；
- 不自动删除 Legacy/Comparator；
- 只有评审通过才允许创建 v1.50 Spec。

---

## 12. 回滚

### 12.1 配置回滚

```text
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=true
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
```

预期：

- 新 session 使用 Legacy；
- existing Graph session 下一 transition 前永久降级；
- 已提交 transition 不重放；
- observation/audit/evidence 保留；
- 不需要学生数据修复。

### 12.2 代码回滚

- Legacy orchestration 必须持续可运行；
- migration 015/016 只增加 nullable telemetry 字段；
- 旧 writer 可忽略新字段；
- session state 对新增字段提供兼容默认值；
- 不通过删除生产 observation 进行回滚；
- 不通过修改 evidence payload 进行回滚；
- 不通过恢复 materialized/expected state 修复 parity。

---

## 13. 预计代码落点

| 文件 | 计划改动 |
|---|---|
| `backend/agents/autotutor_execution.py` | Admission contract、assignment/fallback reason 分离、production fail-closed |
| `backend/agents/auto_tutor.py` | start/answer/recovery 在 Provider 前执行 admission；存量 Graph 永久降级 |
| `backend/agent_runtime/readiness.py` | schema/admission 所需只读 readiness |
| `backend/agent_runtime/rollout_observations.py` | exact aggregate v2、分布、精确 effect/health 关联 |
| `backend/agent_runtime/rollout_status.py` | AutoTutor phase/status/evidence/drill readiness |
| `backend/agent_runtime/evidence_store.py` | AutoTutor immutable evidence 校验与读取 |
| `backend/agent_ops.py` | AutoTutor transition Canary 专用区块 |
| `backend/api/routers/agent_runtime.py` | AutoTutor rollout status 合同测试与错误语义 |
| `backend/db/schema.py` | 可选 admission telemetry nullable 字段 |
| `backend/alembic/versions/016_*` | 可选 admission provenance migration |
| `frontend/app/eval/page.tsx` | AutoTutor Canary operator panel |
| `scripts/build_autotutor_canary_evidence.py` | PII-free evidence builder |
| `scripts/release_gate.py` | Admission/evidence/drill/AgentOps gates |
| `eval/autotutor_*` | Admission、exact aggregate、evidence、restart/kill-switch tests |
| `.env.example` / `README.md` | v1.49.3 配置与 runbook |

---

## 14. 测试与 Release Gate

### 14.1 新增测试

建议新增：

```text
eval/autotutor_canary_admission_smoke.py
eval/autotutor_canary_admission_cache_smoke.py
eval/autotutor_existing_session_downgrade_smoke.py
eval/autotutor_canary_exact_aggregation_smoke.py
eval/autotutor_canary_evidence_smoke.py
eval/autotutor_canary_writer_failure_smoke.py
eval/autotutor_canary_restart_rehearsal_smoke.py
eval/autotutor_canary_kill_switch_rehearsal_smoke.py
eval/autotutor_canary_agent_ops_smoke.py
```

### 14.2 必须保留的测试

- observation provider source independence；
- Graph source independence；
- Comparator sensitivity；
- full outcome parity ≥108；
- active transaction single commit；
- finalize fault injection 8/8；
- transition idempotency；
- false mastery；
- adaptive difficulty；
- session recovery；
- migration upgrade/downgrade/rehearsal/lock；
- production BPS cap；
- AgentOps scope isolation；
- frontend lint/unit/build。

### 14.3 Development Complete Gate

```text
python compile
targeted AutoTutor suites
backend full smoke
fast release gate
frontend lint
frontend unit tests
frontend production build
git diff --check
sensitive field scan
```

默认 CI 不依赖真实 production 数据。Production Verified 必须由部署后 evidence 单独证明。

---

## 15. Milestones

### Milestone A：Admission Contract

- schema/health/config/cohort/BPS/kill-switch 统一判定；
- TTL cache；
- query error fail-closed；
- start 在 Provider 前 admission；
- admission source/PII scan。

### Milestone B：Assignment/Fallback 语义

- 普通 Legacy route reason 与 fallback 分离；
- session compatibility；
- telemetry assignment/admission reason；
- 可选 migration 016。

### Milestone C：Existing Session Safety

- answer/recovery Provider 前 recheck；
- admission revoked 永久降级；
- restart 恢复；
- 不回升 Graph；
- 不重复 effect。

### Milestone D：Exact Aggregate v2

- assigned/selected/committed/fallback；
- comparator unknown 入分母；
- exact health/effect correlation；
- latency/distribution/provenance；
- NOT_READY/UNKNOWN/NO_GO/GO。

### Milestone E：Evidence 与 AgentOps

- hash-sealed AutoTutor evidence；
- evidence builder；
- rollout status phase；
- API；
- AutoTutor operator panel。

### Milestone F：Development Complete

- admission/failure/restart/kill-switch drills；
- full gates；
- clean commit；
- push；
- deployment runbook review。

### Milestone G：Production Verified

- migration 015/016；
- BPS 0 deploy；
- control ≥100；
- verified 1% Graph committed ≥100；
- hard blockers = 0；
- rollback rehearsal；
- immutable evidence；
- v1.50 Go/No-Go。

---

## 16. 验收清单

### 16.1 Development Complete

- [ ] Admission 在 Provider 前执行；
- [ ] schema revision 不足时 production Graph assignment = 0；
- [ ] observation health degraded/unavailable 时 Graph assignment = 0；
- [ ] admission query exception fail-closed；
- [ ] kill switch 绕过缓存立即生效；
- [ ] bucket route reason 不再写成 fallback reason；
- [ ] existing Graph session admission revoked 后永久降级；
- [ ] restart 后 assignment/fallback 语义保持；
- [ ] stale/replay/conflict 不重复 admission/Provider；
- [ ] Graph failure/mismatch 仍为 precommit fallback；
- [ ] exact aggregate 区分 assigned/selected/committed/fallback；
- [ ] Comparator unknown 不从分母移除；
- [ ] duplicate effect 使用 exact AutoTutor slice；
- [ ] observation failure 按 commit/config/environment/window 聚合；
- [ ] evidence hash/tamper 校验通过；
- [ ] AgentOps/API/UI 使用同一状态合同；
- [ ] parity ≥108/108；
- [ ] fault injection 8/8；
- [ ] backend full smoke 通过；
- [ ] fast release gate 通过；
- [ ] frontend lint/unit/build 通过；
- [ ] diff/sensitive scan 通过；
- [ ] Active BPS 默认 0；
- [ ] 未引入 LangGraph checkpointer/interrupt。

### 16.2 Deployment Ready

- [ ] 本地前置提交与 v1.49.3 已 push；
- [ ] CI 绑定 clean commit；
- [ ] migration 015 ready；
- [ ] 若采用 migration 016，则 migration 016 ready；
- [ ] production BPS = 0；
- [ ] schema readiness = ready；
- [ ] observation health = ok；
- [ ] verified cohort ready；
- [ ] admin rollout-status 可用；
- [ ] restart rehearsal 通过；
- [ ] deployment preflight evidence 已封存。

### 16.3 Production Verified

- [ ] control transitions ≥100；
- [ ] committed Graph transitions ≥100；
- [ ] Comparator parity = 100%；
- [ ] fallback rate <1%；
- [ ] observation failures = 0；
- [ ] actual duplicate effects = 0；
- [ ] unauthorized Active = 0；
- [ ] provenance coverage = 100%；
- [ ] transition coverage 完整；
- [ ] p95 relative regression ≤20%；
- [ ] p95 absolute increase ≤50ms；
- [ ] writer failure rehearsal 通过；
- [ ] kill-switch rehearsal 通过；
- [ ] evidence commit/config/environment/window/cohort 一致；
- [ ] evidence hash 有效；
- [ ] 评审后 BPS 已恢复 0 或获得单独保持 1% 授权；
- [ ] production 未超过 1%。

---

## 17. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Admission 每请求查 DB 增加延迟 | 短 TTL cache，kill switch 直读，禁止 stale GO |
| Observation health 与流量形成循环依赖 | health 只要求 writer/schema 可用，不要求已有 Graph 样本 |
| 普通 Legacy 被误计 fallback | assignment reason 与 fallback reason 分离 |
| 全局 duplicate 查询误伤 | exact trace/run/window 关联 |
| 小样本 latency 波动 | committed Graph ≥100，并同时限制相对与绝对回归 |
| Comparator unknown 被静默排除 | unknown 保留在 Graph assigned 分母并直接阻断 GO |
| Evidence 与部署不一致 | commit/config/environment/window hash sealing |
| kill switch 被 Admission cache 延迟 | kill switch 绕过 cache，立即永久降级存量 Graph session |
| migration 016 增加部署复杂度 | 仅 nullable telemetry；实现评审可证明无需新列时取消 |
| UI 与 API 指标定义漂移 | 前端只渲染后端 readiness contract，不自行计算 GO |
| 本地测试被误当生产证据 | evidence_scope 与 environment 强校验，dirty evidence 永远 NO_GO |

---

## 18. v1.50 进入条件

只有 v1.49.3 同时满足 Development Complete、Deployment Ready 和 Production Verified，才允许创建 v1.50 Spec。

v1.50 才允许讨论：

- Graph 成为默认 transition executor；
- Comparator 从 100% 在线双算改为采样或离线；
- 删除 Legacy orchestration；
- 收敛旧 shadow schema/reason codes；
- 分阶段扩大流量；
- 降低双执行成本。

即使进入 v1.50，也不得自动引入 PostgreSQL LangGraph checkpointer 或 `interrupt`。只有出现真实跨请求图内暂停需求，且现有 session/CAS 无法满足时，才允许另立 ADR/Spec。

---

## 19. 最终验收问题

评审必须能用代码和不可变证据回答“是”：

1. production schema 或 writer health 失效时，是否在 Provider 前拒绝 Graph？
2. admission query 异常是否 fail-closed，而不是沿用过期 GO？
3. kill switch 是否绕过缓存立即生效？
4. 普通 bucket Legacy 是否与真实 Graph fallback 明确区分？
5. existing Graph session 是否会在 admission revoked 后永久降级且不重放 transition？
6. Graph assigned、Graph selected、Graph committed 和 fallback Legacy 是否有稳定分母？
7. Comparator unknown 是否仍保留在 Graph assigned 分母？
8. duplicate effect 是否按 exact AutoTutor deployment slice 检查？
9. observation failure 是否绑定相同 commit/config/environment/window？
10. AgentOps/API/UI 是否共享同一 GO/NO_GO 合同？
11. evidence 是否绑定真实 deployed commit、migration、cohort 与窗口并通过 hash 校验？
12. rollback 是否只需 kill switch/mode/BPS，不需要修复学生数据？
13. production 是否从未超过 1%？
14. 是否已有至少 100 个真实 committed Graph transitions？
15. 是否在 Production Verified 前继续拒绝进入 v1.50？

任一答案为“否”，v1.49.3 不得标记完成，不得扩大 Active BPS，也不得创建 v1.50。
