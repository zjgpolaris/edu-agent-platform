# EduAgent AutoTutor LangGraph Shadow 可信性闭环 v1.48.1 Spec

**状态：** Development Complete · Cutover Evidence Sealed
**日期：** 2026-09-01
**优先级：** P0 独立状态转移、无副作用实证、可复核 parity 证据；P1 延迟基线与迁移决策材料
**前置版本：** v1.48 LangChain 契约收口与 AutoTutor LangGraph Shadow 基线
**后续候选：** v1.49 AutoTutor LangGraph Active Cutover（仅在本 Spec 门禁全部满足后立项）

---

## 0. 决策摘要

v1.48 已完成 structured output provenance、AutoTutor 纯领域函数、LangGraph Shadow 骨架和安全的 Demo/Evidence 投影，但当前实现还不能证明 LangGraph 与 Legacy 编排等价：

- Graph 根据 Legacy 已产生的 `runtime_steps` 回放节点名称；
- Graph 的 canonical projection 直接来自 Legacy 同一终态；
- comparator 实际比较“Legacy 终态投影”和“同一 Legacy 终态的再次投影”；
- `DenyShadowEffects` 已存在，但没有作为 Graph 执行依赖被真实节点消费；
- Shadow 结果只写普通日志，调用者丢弃返回值，没有可复核的 run 级证据；
- 当前 smoke 为绿色，只证明骨架可执行、输入未被原地修改、异常被隔离，不证明独立状态转移 parity。

因此下一迭代不进入 Active Cutover，不接 LangSmith，不扩展新 Agent，而是完成一个更窄但必要的可信性闭环：

1. 将对比单位从“终态快照”升级为“状态转移”；
2. Graph 只接收 Legacy 转移前状态、命令和已捕获的非确定性观察值；
3. Graph 独立计算候选终态，禁止读取 Legacy 转移后终态；
4. comparator 在图外比较 Legacy after 与 Graph candidate；
5. 用真实依赖 tripwire 证明 Shadow 不调用模型、检索、工具、网络或业务写入；
6. 生成绑定 commit、schema、case 和延迟的可复核 parity 报告；
7. 只有报告满足硬门禁，才允许另立 v1.49 Active Cutover Spec。

版本主题：**把“看起来一致的 Shadow”升级为“可以支持切流决策的独立迁移证据”。**

---

## 1. 项目实际基线

### 1.1 已完成且保留

- `invoke_structured_with_provenance` 可区分主模型、备用模型和 deterministic fallback；
- provenance 绑定单次响应，不依赖共享 `last_call` 状态；
- AutoTutor 已抽出 `judge_answer`、`replan_policy` 和 canonical projection；
- `StateGraph` 骨架可执行，默认配置关闭；
- Shadow 异常不会改变 active response；
- Demo Journey 和教师 Evidence 使用独立 allowlist 展示决策来源；
- 无数据库 migration，Legacy 仍是唯一 active 执行源；
- 当前相关确定性回归 6/6 suites、13/13 cases 通过。

### 1.2 当前可信性缺口

| 维度 | 当前实现 | 结论 |
|---|---|---|
| Graph 输入 | 完整 Legacy 终态 | 无法证明独立计算 |
| 节点语义 | 从 `runtime_steps` 推导并消费节点名 | 更接近 trace replay，不是 transition executor |
| Graph 输出 | 对输入 Legacy 终态调用 canonical projection | parity 具有同源自证问题 |
| Effect sink | 类存在，测试直接调用 | 没有证明真实 Graph 节点受其约束 |
| 外部调用 | 代码路径看似没有调用 | 缺少集成级调用计数与 fail-fast tripwire |
| 数据写入 | 输入 deep copy，未观察到写入 | 缺少 session/event/weakpoint/review/runtime 前后快照 |
| 对比覆盖 | 4 个手工终态快照 | 未覆盖 start、stale、replay、recovery 等转移合同 |
| 运行证据 | 普通日志 | 不绑定 commit、case、schema，也不可聚合复核 |
| 延迟 | 未报告 | 无法判断同步 Shadow 对请求的影响 |

### 1.3 为什么此时不做 v1.49

Active Cutover 会改变学生答题暂停、CAS revision、幂等 replay、业务副作用和恢复边界。当前 Shadow 还没有独立执行这些状态转移，直接切流无法回答以下问题：

- Graph 是否在不读取 Legacy 结果时得到同一状态；
- Graph exception 是否在真实 transition 路径上完全隔离；
- stale answer 与 idempotent replay 是否保持现有响应合同；
- exit ticket 是否仍是 verified mastery 的唯一来源；
- Graph 是否引入模型、工具或数据库的第二次调用；
- 同步 Shadow 的 p95 延迟是否可接受。

这些问题属于切流前置证据，不应留到 active 之后验证。

---

## 2. 目标与非目标

### 2.1 P0 目标

- 定义版本化的 `AutoTutorTransitionEnvelope`；
- Graph 输入中不包含 Legacy after state；
- Graph 独立执行核心确定性 transition；
- 非确定性结果通过 observation 注入，Shadow 不重复调用外部依赖；
- comparator 只在 Graph 完成后接触 Legacy after state；
- Graph 的 effect、model、retrieval、tool、network 依赖默认 fail-closed；
- 覆盖 start、lesson answer、reflect/re-plan、content blocked、exit ticket、recovery、stale 和 replay；
- 生成 commit-bound、schema-bound 的 JSON/Markdown parity 报告；
- 确定性核心、安全、恢复和幂等 parity 达到 100%；
- Shadow 失败、超时和 mismatch 均不改变 active response 或 commit。

### 2.2 P1 目标

- 记录 Graph 单次执行耗时和 active 请求附加开销；
- 建立 mismatch reason code 的 case 级聚合；
- 将 v1.48 未完成项改为有证据链接的完成状态；
- 形成 v1.49 是否立项的 Go/No-Go 决策页；
- 明确哪些逻辑可由 LangGraph 接管，哪些领域事务继续归 EduAgent 所有。

### 2.3 非目标

- 不将 LangGraph 切为 active；
- 不启用 LangGraph checkpointer 或 `interrupt`；
- 不改变 `autotutor_sessions` schema、URL 或公共 API；
- 不删除 Legacy AutoTutor；
- 不把 Shadow 结果写入学习事件、错题、复习或教师聚合；
- 不接入 LangSmith Cloud、Agent Server 或 LangGraph Deployment；
- 不迁移 Learning Assistant、History Character、Essay Grader 或其他 Agent；
- 不要求默认 CI 使用真实 LLM Key；
- 不以增加更多手工终态 fixture 代替独立 transition 执行。

---

## 3. Transition Envelope 合同

### 3.1 对比单位

Shadow 的最小对比单位由终态快照改为一次业务状态转移：

```text
before_state + command + captured_observations
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
    Legacy transition    LangGraph transition
          │                   │
          ▼                   ▼
     legacy_after         graph_candidate
          └─────────┬─────────┘
                    ▼
          canonical comparator
```

### 3.2 内部 schema

建议新增：

```python
class AutoTutorTransitionEnvelope(TypedDict):
    schema_version: Literal["v1.48.1-transition"]
    transition_id: str
    transition_kind: Literal[
        "start",
        "lesson_answer",
        "exit_ticket_answer",
        "recovery_resume",
    ]
    before: dict[str, Any]
    command: dict[str, Any]
    observations: dict[str, Any]

class AutoTutorGraphCandidate(TypedDict):
    schema_version: Literal["v1.48.1-transition"]
    after: dict[str, Any]
    effect_intents: list[dict[str, Any]]
    visited_nodes: list[str]
    diagnostics: list[str]
```

约束：

- `before` 只包含转移开始前的领域状态；
- `command` 只包含本次命令所需字段；
- `observations` 只包含 active 已取得且 Graph 计算必需的不可重复结果；
- Graph invoke 参数禁止出现 `legacy_after`、`expected_projection` 或同义字段；
- `effect_intents` 只是纯数据，不执行写入；
- `transition_id` 使用安全内部标识，公共报告不得包含 session/student/trace 原始 ID。

### 3.3 Observation allowlist

允许注入：

- 已生成教学计划的安全结构化结果；
- 已验证的教材片段 fingerprint 与 content gate decision；
- 已生成 assessment 的结构化内容和 fingerprint；
- Reflect 结构化结果与内部 provenance；
- 稳定 clock/identifier 输入；
- active 已得到的 tool outcome 的必要结构化部分。

禁止注入：

- Legacy after state 或 canonical expected output；
- API Key、Authorization header、provider request ID；
- 原始 Prompt、chain-of-thought 或未脱敏模型响应；
- 与本次 transition 无关的学生资料；
- 可由纯领域函数从 before/command 推导出的结果。

---

## 4. 独立 Graph 状态转移

### 4.1 Graph 节点必须产生新状态

v1.48 的 `_consume(node)` 只记录访问节点。本迭代中每个纳入 parity 的节点必须至少完成一项真实领域计算：

| Node | 输入 | 输出 |
|---|---|---|
| `plan` | before + plan observation | lesson plan candidate |
| `content_gate` | content observation | status/phase gate decision |
| `prepare_assessment` | assessment observation | question state + fingerprint |
| `judge` | answer command + verified assessment | judgement + attempts |
| `reflect` | captured reflection observation | reflection record candidate |
| `re_plan` | before + reflection | difficulty/strategy/plan mutation |
| `advance` | current step result | next index/status/phase |
| `prepare_exit_ticket` | exit ticket observation | exit ticket candidate |
| `verify_exit_ticket` | answer + verified exit ticket | pass/fail，不直接写 mastery |
| `build_evidence_intent` | verified result | learning/weakpoint/review intents |
| `finalize` | candidate + intents | completed candidate state |

### 4.2 共享领域函数边界

Legacy 和 Graph 可以共享以下纯函数：

- answer judgement；
- re-plan policy；
- content/assessment fingerprint；
- verified mastery 判定；
- evidence intent 生成；
- canonical projection。

不允许 Graph 调用 Legacy 的整段 `_act`、`submit_answer`、`_finalize` 或持久化入口，否则仍然不是独立编排实现。

### 4.3 comparator 隔离

执行顺序必须为：

1. 在 Legacy transition 前构造 envelope；
2. Legacy 正常计算并提交 active 结果；
3. Graph 仅使用 envelope 计算 candidate；
4. comparator 在 Graph 外取得 `legacy_after`；
5. 对两侧执行同版本 canonical projection；
6. 输出 reason codes 和安全指标。

Graph 模块不得 import comparator 的 expected state，也不得访问 session store 重新读取 Legacy 结果。

---

## 5. 无副作用与无外部调用实证

### 5.1 Fail-closed ports

Graph context 显式携带以下端口，Shadow 默认全部使用 deny 实现：

- `effect_sink`；
- `model_port`；
- `retrieval_port`；
- `tool_port`；
- `network_port`；
- `session_store`；
- `runtime_store`。

任何未由 observation 满足的外部需求必须产生安全 reason code 并终止 Shadow，不得回退到真实依赖。

建议 reason codes：

- `shadow_external_call_attempted`；
- `shadow_side_effect_attempted`；
- `shadow_input_incomplete`；
- `shadow_execution_failed`；
- `shadow_timeout`；
- `status_mismatch`；
- `phase_mismatch`；
- `plan_shape_mismatch`；
- `reflection_action_mismatch`；
- `exit_ticket_mismatch`；
- `verified_mastery_mismatch`；
- `evidence_intent_mismatch`；
- `next_action_mismatch`。

### 5.2 集成级断言

测试不能只直接调用 `DenyShadowEffects().save(...)`。必须从真实 Graph transition 入口触发并断言：

- model invoke count = 0；
- retriever call count = 0；
- tool call count = 0；
- outbound network count = 0；
- session insert/update count = 0；
- learning event count delta = 0；
- weakpoint evidence count delta = 0；
- review schedule count delta = 0；
- audit/runtime/checkpoint count delta = 0；
- active transition 的 commit payload 与 Shadow 关闭时一致。

### 5.3 执行隔离

- 默认关闭；
- 单次 Shadow 设置本地超时预算；
- exception、timeout、mismatch 只产生诊断结果；
- 不允许 Shadow 成为 active commit 的前置条件；
- 不允许 Shadow 修改 active state 对象；
- 若同步执行，必须记录附加延迟；若改为 commit 后异步执行，必须使用不可变 envelope，不能重新读取可变 session。

---

## 6. Parity 数据集与证据报告

### 6.1 必须覆盖的 transition matrix

| 类别 | 最少场景 |
|---|---|
| Start | 正常 start、focus tags、content blocked |
| Lesson answer | 首次正确、首次错误、连续错误、达到单步上限 |
| Reflect/re-plan | reteach、lower difficulty、change example、advance |
| Progression | 下一知识点、进入 exit ticket |
| Exit ticket | pass、fail、重复提交 |
| Mastery | 练习正确但 exit ticket 未通过、独立 exit ticket 通过 |
| Idempotency | 同 key replay、同 key 不同 payload conflict |
| Concurrency | stale revision、busy claim |
| Recovery | 持久化恢复后继续 lesson、恢复后完成 exit ticket |
| Failure isolation | Graph exception、deny port、timeout、输入不完整 |

不得仅用已完成终态覆盖上述场景；每个 case 必须保存 before、command、observation fixture，并由两条执行路径分别产生 after。

### 6.2 报告产物

新增独立报告，避免混淆现有通用 `eval/reports/latest.*`：

```text
eval/reports/autotutor_shadow_latest.json
eval/reports/autotutor_shadow_latest.md
```

报告至少包含：

- `eval_run_id`；
- `git_commit` 和 dirty 标记；
- Graph config version；
- transition schema version；
- dataset version/hash；
- 总 case 数与分类覆盖；
- exact parity rate；
- reason code 聚合；
- external call attempt count；
- side-effect attempt/count delta；
- exception/timeout count；
- Graph p50/p95；
- active added latency p50/p95；
- sensitive field scan 结果；
- Go/No-Go 结论和 blocker 列表。

报告不得包含原始答案、Prompt、session/student/trace ID、provider request ID 或 secret。

### 6.3 Commit-bound 原则

- dirty workspace 报告只能用于本地调试，不能作为 cutover 证据；
- 报告 commit 必须与待决策 commit 一致；
- schema、dataset 或 Graph config 任一变化后旧报告自动失效；
- 默认 CI 只运行确定性数据，不伪装为真实 LLM 证据；
- real-LLM provenance 验证可以是补充项，但不是 transition parity 的替代品。

---

## 7. 硬门禁

进入 v1.49 讨论前必须同时满足：

| Gate | 阈值 |
|---|---:|
| 核心 deterministic transition parity | 100% |
| false mastery / content blocked / recovery parity | 100% |
| stale / replay / conflict 合同 parity | 100% |
| Shadow 外部调用 | 0 |
| Shadow 业务/Runtime 数据写入 | 0 |
| active response/commit 受 Shadow 影响 | 0 cases |
| 未分类 mismatch reason | 0 |
| 敏感字段泄露 | 0 |
| Graph exception/timeout 导致 active 失败 | 0 |
| committed evidence report | 必须存在且 commit 一致 |

延迟先作为决策门禁而非产品 SLO：

- 确定性评测记录 Graph p95；
- Demo shadow 记录 active added latency p95；
- 若 added latency p95 超过 20ms，v1.49 必须先决定异步执行或取消在线 Shadow；
- 不得通过删除困难 case 来满足延迟或 parity 阈值。

---

## 8. API、UI 与数据边界

### 8.1 公共 API

本迭代不新增学生/教师业务 API，不改变现有 session URL、public state、Demo trace 或 Evidence schema。

### 8.2 管理证据

Parity 报告首先作为仓库内 eval artifact，不进入学生或教师页面。若后续需要 AgentOps 展示，必须另行设计 admin-only projector，不能直接暴露 envelope 或内部 Graph state。

### 8.3 业务数据

- 不新增数据库 migration；
- 不在 `autotutor_sessions` 保存 Graph candidate；
- 不将 mismatch 写成学习事件；
- 不让教师聚合读取 Shadow 结果；
- Demo/Evidence 中现有 decision provenance 合同保持不变。

---

## 9. 实现建议

### Milestone A：Transition characterization

- 为 Legacy start/answer/finalize 建立 before-command-observation-after fixture；
- 固化 revision、idempotency、mastery 和 evidence intent 合同；
- 为 fixture 增加 schema 与 dataset hash。

### Milestone B：纯领域 transition 扩展

- 将 advance、exit ticket verification、mastery 和 evidence intent 抽成纯函数；
- Legacy 先复用纯函数并跑现有回归；
- 不改变持久化、CAS 和副作用提交顺序。

### Milestone C：独立 LangGraph transition

- Graph 只消费 envelope；
- 真实节点产生 candidate state 和 effect intents；
- 删除以 Legacy 终态 `_trace_nodes` 作为 parity 主逻辑；
- deny ports 接入 Graph context。

### Milestone D：集成 parity 与隔离

- comparator 在 Graph 外比较 after；
- 覆盖 active Shadow 开/关响应一致性；
- 增加外部调用计数和数据库快照；
- 增加 exception/timeout/failure isolation。

### Milestone E：证据与 Go/No-Go

- 生成 JSON/Markdown 报告；
- release gate 校验报告 schema 和 commit；
- 回填 v1.48 未完成项；
- 输出 v1.49 Go/No-Go，不在本版本执行切流。

### 9.1 预计代码落点

| 文件/模块 | 变化 |
|---|---|
| `backend/agents/autotutor_domain.py` | 扩展纯 transition 与 effect intent |
| `backend/agents/autotutor_graph.py` | 从 trace replay 改为独立 transition graph |
| `backend/agents/autotutor_shadow.py` | envelope、deny ports、timeout、result metrics |
| `backend/agents/auto_tutor.py` | 在现有 transition 边界捕获 immutable envelope |
| `eval/autotutor_langgraph_shadow_parity_smoke.py` | 保留快速合同测试，去除同源自证 |
| `eval/autotutor_langgraph_transition_parity_eval.py` | 新增完整 transition matrix |
| `eval/autotutor_langgraph_shadow_isolation_smoke.py` | 新增外部调用/写入 tripwire |
| `eval/report_generator.py` 或独立 reporter | 生成专用 parity 报告 |
| `eval/run_core_evals.py` | 注册 suite 与指标 |
| `scripts/release_gate.py` | 注册硬门禁与 commit-bound 报告校验 |

---

## 10. 测试与验收

### 10.1 后端

- Legacy characterization 全通过；
- Graph 不读取 Legacy after；
- 每类 transition exact parity；
- false mastery、content blocked、recovery parity；
- stale、busy、replay、conflict parity；
- deny ports 从 Graph 入口触发；
- active Shadow 开/关 response 和 committed state 一致；
- public projector 不新增敏感字段。

### 10.2 前端

本迭代没有 UI 变更。仍运行现有 unit/lint/build，确保 provenance、Demo Journey 和 Teacher Evidence 无回归；完整 E2E 可作为发布前总门禁，不要求新增仅为 Shadow 服务的 UI case。

### 10.3 建议命令

```bash
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py \
  --suite autotutor_langchain_provenance_smoke \
  --suite autotutor_langgraph_shadow_parity_smoke \
  --suite autotutor_langgraph_transition_parity_eval \
  --suite autotutor_langgraph_shadow_isolation_smoke \
  --suite auto_tutor_trajectory_eval \
  --suite autotutor_false_mastery_smoke \
  --suite autotutor_content_blocked_api_smoke \
  --suite autotutor_session_recovery_smoke

npm run test:unit --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
npm run release:gate:fast
```

suite 名称以实现时注册结果为准，但测试语义和硬门禁不得减少。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 为了 parity 直接复用 Legacy 整段函数 | 形成伪独立实现 | 只共享纯领域函数，禁止调用 Legacy transition 入口 |
| observation 偷带 expected 结果 | 再次形成同源自证 | schema allowlist + 测试禁止 after/expected 字段 |
| 抽纯函数改变 Legacy 行为 | 产品回归 | characterization 先行，Legacy 先复用再接 Graph |
| deny sink 只停留在单元测试 | 无法证明真实隔离 | 从 Graph transition 入口执行调用计数与数据快照 |
| Shadow 同步执行增加延迟 | 学生答题变慢 | 默认关闭、超时、记录 added latency、超过阈值先决策异步化 |
| 报告与代码不一致 | 错误放行 | commit/schema/dataset/config 四重绑定 |
| mismatch 日志泄露学生数据 | 安全风险 | 只输出 reason code、case alias 和聚合指标 |
| 双实现长期存在 | 维护成本上升 | 本迭代结束必须给出 v1.49 Go/No-Go，不无限扩展 Shadow |

---

## 12. 回滚策略

- `EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED=false` 继续作为即时 kill switch；
- Legacy 始终是唯一 active 和唯一业务写入路径；
- Transition envelope 和报告均为内部诊断合同，无数据迁移；
- Graph exception/timeout 不参与 active commit；
- 若纯函数抽取造成回归，可逐函数回退调用位置，不回滚 session 数据；
- 专用 parity 报告可独立停止生成，不影响学生和教师功能。

---

## 13. 完成定义

Development Complete 必须全部满足：

- [x] Graph 输入不包含 Legacy after/expected projection；
- [x] Graph 核心节点独立产生 candidate state；
- [x] Legacy 与 Graph 只共享纯领域函数，不共享整段 transition executor；
- [x] deny effect/model/retrieval/tool/network/store ports 接入真实 Graph context；
- [x] Shadow 外部调用计数为 0；
- [x] Shadow session/learning/weakpoint/review/audit/runtime 写入 delta 为 0；
- [x] active Shadow 开/关 response、revision 和 commit payload 一致；
- [x] deterministic transition matrix parity 100%；
- [x] false mastery、content blocked、recovery parity 100%；
- [x] stale、busy、replay、conflict 合同 parity 100%；
- [x] exception、timeout、mismatch 不影响 active；
- [x] mismatch 仅输出安全 reason codes；
- [x] 专用 JSON/Markdown 报告生成并通过敏感字段扫描；
- [x] 报告绑定 clean commit、schema、dataset 和 Graph config；
- [x] Graph p50/p95 与 active added latency p50/p95 已记录；
- [x] 现有 provenance、Demo Journey、Teacher Evidence 无回归；
- [x] frontend unit、lint、build 和完整 E2E 通过；
- [x] fast release gate 通过；
- [x] v1.48 未完成项使用本版本报告回填，不再以骨架 smoke 代替。

本版本完成后只输出 v1.49 `Go` 或 `No-Go`。`Go` 代表可以开始编写 Active Cutover Spec，不代表已经允许生产切流。

### 13.1 本地完成证据

- 独立真实 transition：29/29 parity，覆盖 start、lesson answer 与 exit-ticket answer；
- Legacy trajectory：13/13 cases；
- Spec 相关后端门禁：8/8 suites、42/42 cases；
- fast release gate：61/61 suites、541/541 cases；
- frontend unit：12 files、30/30 tests；
- frontend lint、Next.js production build：通过；
- Playwright：13/13 browser flows；
- Shadow 外部调用：0；业务/Runtime 写入：0；
- 最近一次 Graph p50/p95：以 `eval/reports/autotutor_shadow_latest.*` 为准，均低于 20ms 决策阈值。

已在 clean code commit `229ecacf1fc9b6ef9e3f9563f71da2492b7fe1fd` 上重新生成证据：29/29 transition parity、外部调用 0、副作用 0、无 blocker，结论为 `GO`。该结论只允许开始编写 v1.49 Active Cutover Spec，不代表已经允许生产切流。

---

## 14. v1.49 立项边界

只有本 Spec 所有 P0 门禁满足，v1.49 才允许讨论：

- Graph active/Legacy active 的 cohort 路由；
- LangGraph PostgreSQL checkpointer；
- `interrupt` 接管学生答题暂停；
- in-flight Legacy session 兼容；
- checkpoint 写放大、恢复演练和 kill switch；
- Runtime checkpoint 引用 Graph checkpoint 的边界；
- 删除重复 graph scheduling/checkpoint/resume 代码。

即使 v1.48.1 通过，以下事项仍不自动进入 v1.49：

- LangSmith Cloud；
- 新 Agent；
- 多租户 Demo workspace；
- 自动生产放量；
- 用真实 LLM 评测替代确定性 transition parity。
