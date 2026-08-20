# EduAgent 统一 Agent Runtime v2 架构升级 v1.33 Spec

**创建时间：** 2026-08-20

**状态：** Proposed · Live-code revised（已按 `dbf5ff1` 实际执行链修订，尚未开始实现）

**目标版本：** v1.33.0（统一合同与执行语义）+ v1.33.1（持久化运行与恢复）+ v1.33.2（专用子图迁移与受限增强）

**优先级：** P0 架构治理；动态规划增强为 P1，必须通过真实证据门槛后启用

**适用范围：** `随问 · 学习助手`、AutoTutor、历史人物对话、作文批改、历史辩论；地图、人物推荐、时间线/卡牌/多人游戏仅纳入能力合同，不强制创建独立 Agent Run

**前置基线：** `main@dbf5ff1`（与 `origin/main` 同步，生成前工作区干净）

**关联文档：**

- `docs/202608141024-agent-intelligence-evidence-rollout-v130-spec.md`
- `docs/202608141550-history-qa-retrieval-v131-spec.md`
- `docs/202608131651-agent-intelligence-upgrade-v129-spec.md`
- `docs/202606291030-autotutor-autonomous-loop-dev.md`
- `docs/20260709-ai-agent-engineering-direction-confirmation.md`
- `docs/20260813-learning-assistant-conversation-first-ux-spec.md`

---

## 0. 决策摘要

当前 EduAgent 已经拥有多条可工作的 AI 链路，但它们并不是建立在同一套 Agent Runtime 上：

- 学习助手使用自研 `Router → Planner → Runtime → Tool → Verifier`；
- AutoTutor 使用自研教学状态机，状态同时保存在进程内 TTL cache 和运行时创建的 `autotutor_sessions` 表；
- 历史人物、作文批改、历史辩论部分使用 LangGraph；
- 历史人物和辩论的流式接口又各自维护了一套手写执行链；
- 地图、人物推荐、时间线/卡牌生成与多人游戏属于 LLM Chain 或确定性领域引擎。

现阶段主要问题不是“缺少一个更强的模型”，而是运行合同碎片化：

1. 相同能力的流式与非流式入口可能执行不同节点；
2. 不同 Agent 对 `completed / partial / failed / verified` 的定义不一致；
3. Trace 主要存于单进程内存，不能承担跨进程恢复和发布证据；
4. AutoTutor 的 `RLock` 只能防止同一进程内重复提交，不能保证多实例原子更新；
5. 部分链路绕过统一 Tool Registry、Evidence Verifier 或标准化 generation operation；
6. LangGraph 图、自研状态机和手写循环没有统一 checkpoint、预算、幂等与暂停恢复协议；
7. 新增 Agent 时容易重复实现 SSE、Trace、重试、会话、错误处理和安全策略。
8. `autotutor_sessions` 尚未进入 Alembic/`db/schema.py`，数据库结构存在运行时 DDL 与迁移双轨；
9. 历史与作文入口对 `student_id/session_id` 的 owner 约束弱于学习助手，不能直接复用为通用 Run API 的安全基线；
10. `langgraph>=0.2.0` 只有下界、没有经过验证的版本上界，不能在未锁定版本的情况下依赖 checkpointer/interrupt 细节。

本轮选择的目标不是“所有代码迁移到 LangGraph”，而是建立一套框架无关的统一运行合同：

```text
统一 Agent Context / State / Plan / StepResult / CompletionDecision
  + 统一 Policy / Tool / Evidence / Memory / Trace / Checkpoint
  + SequentialPlanAdapter（复用学习助手现有执行器）
  + LangGraphAdapter（承载真正有状态、分支和暂停恢复的子图）
  + FunctionAdapter（承载地图、推荐、游戏生成等简单能力）
```

复杂任务使用状态图；简单能力继续保持 Tool/Chain。框架是实现细节，产品 API、持久化状态、事件协议和完成语义必须由 EduAgent 自己的 Pydantic 合同定义。

目标形态：

```text
API / SSE
  → Agent Gateway（鉴权、owner check、guardrail、trace）
  → Router / Policy / Rollout
  → Unified Agent Runtime（按 durability mode 分级）
       → Plan
       → Execute
       → Observe
       → Evidence Verify
       → 一次受限 Repair / Re-plan
       → Waiting Input / Waiting Confirmation（必要时）
       → Finalize
  → Postgres Run / Event Store（仅 resumable run 写 checkpoint）
  → AgentOps / Eval / Release Gate
```

本 Spec 不授权开放式 ReAct、模型自由生成工具、无限循环、任意 Agent 委派或无约束并行。v1.33.0/1 的首要价值是让已有 Agent 具备统一完成语义和可持久观测，并让确实需要暂停恢复的 Agent 可恢复；不会为了“全量 durable”把短时只读请求全部 checkpoint。更强自主能力只能在真实 blind、real LLM 和生产 canary 达标后灰度。

---

## 1. 当前项目实际基线

### 1.1 当前代码与发布状态

截至 2026-08-20：

| 项目 | 当前状态 | 本 Spec 结论 |
| --- | --- | --- |
| Git 基线 | `dbf5ff1`，`main == origin/main` | 作为迁移对比基线 |
| 学习助手 Router/Planner/Runtime | 同步与流式入口均消费 `stream_learning_assistant_events()`，Planner 受 feature flag 控制 | 保留单一执行生成器，只抽取合同/事件/等待状态 |
| Tool Registry | Pydantic schema、角色、风险、确认、审计、Trace | 继续作为唯一工具执行入口 |
| Grounded Completion | source ID、claim/citation、conflict、完成门控 | 升级为所有需要事实支撑能力的公共节点 |
| AutoTutor | 教学计划、讲解、出题、反思、重规划、退出票、学习证据；`autotutor_sessions` 由模块运行时建表 | 先纳入 migration 并完成数据库 CAS，再迁移状态图 |
| LangGraph | `backend/requirements.txt` 为 `langgraph>=0.2.0`；历史人物、作文、辩论非流式接口已使用 | 保留为 Runtime adapter，并在实施前锁定已验证版本范围 |
| Agent Jobs | 数据库队列、幂等、重试、取消、超时、stale recovery | 复用为长任务调度，不替代交互 run state |
| Assistant Sessions | 仅学习助手具备 DB session/message/owner；历史人物与作文仍使用 Redis/内存 `session_store`（TTL 1 小时） | 不误当作全平台会话层；需要恢复的敏感输入使用专用 artifact |
| Trace Store | 单进程内存 + TTL | 保留兼容读取，新增持久化事件源 |
| AgentOps | data_scope、路由/计划/核验/反馈/工具指标 | 扩展到 run/step/checkpoint/recovery 指标 |
| v1.30 真实证据 | blind、real LLM、生产 canary 尚未闭环 | 阻止动态能力全量开放 |
| v1.31 生产 RAG | 真实 pgvector/embedding/reranker 盖章待完成 | 阻止生产检索增强全量开放 |

### 1.2 当前 Agent 架构盘点

| 能力 | 当前实现 | 状态管理 | 规划/循环 | 工具/证据 | 当前定位 |
| --- | --- | --- | --- | --- | --- |
| 学习助手 | 自研 Router + Planner + Runtime | assistant session + 请求内 outputs | 最多 3 步、确定性组合、一次只读 repair | Tool Registry + Answer Verifier | 核心受控 Agent |
| AutoTutor | 自研有限教学状态机（当前未使用 LangGraph） | 内存 TTL + 运行时 DDL `autotutor_sessions` | plan/act/observe/judge/reflect/re-plan/exit ticket | Registry 取材，教学证据独立落库 | 核心教学 Agent |
| 历史人物 | LangGraph 线性图 + 手写 SSE 链 | session_store + 请求内 state | retrieve/generate/verify | RAG + LLM verifier | RAG 工作流 Agent |
| 作文批改 | LangGraph Critic 图 | 请求内 TypedDict + session message | grade/critique | 结构化评分，无真正 revise | 审核工作流 |
| 历史辩论 | LangGraph 固定 Supervisor-Worker + 手写 SSE | 请求内 rounds | 固定 3 轮 + judge；流式另有 fact checker/coach | 部分 RAG，仅流式链路使用 | 固定多角色工作流 |
| 历史地图 | 手写 RAG/LLM chain | 无长期 run state | narrate + map action | 直接 RAG/LLM | 简单 Chain |
| 人物推荐 | RAG + 规则评分 + LLM + fallback | 无 run state | 单次选择 | 直接检索与结构化输出 | Capability/Tool |
| 时间线/卡牌生成 | 可信候选 + LLM 选择 + validator + fallback | 游戏 round 存储 | 单次生成 | 候选绑定和确定性校验 | 生成器 |
| 多人游戏 | 确定性游戏状态机 + AI 话术/策略 | round store | 固定回合 | LLM 只生成卡片/解释/话术 | 领域引擎 |

### 1.3 已确认的架构问题

#### A. 历史人物双执行链不等价

- 非流式接口调用 `build_character_graph()`：`retrieve → generate → verify`；
- 流式接口调用 `stream_character_response()`：额外执行 fact card、memory update 和不同的 trace；
- 相同输入因 `stream=true/false` 可能产生不同副作用、最终状态和可观测事件；
- API 构造 `CharacterState` 时没有传入 `student_id`，因此流式链末尾的 character interaction/memory update 对已登录学生也可能实际 no-op；
- 当前 `verify_response()` 在 verifier 异常时仍可返回 `verified=True`，属于 fail-open。

#### B. 作文批改没有真正 Critic-Reviser

- `critique()` 会立即设置 `final_comments`；
- `should_finalize()` 检测到 `final_comments` 后结束；
- 图中没有 `revise` 节点，critic 只能标记人工复核，不能修正评分；
- 教师复核结果只写 session/audit，没有进入统一 run state 和后续质量学习。

#### C. 辩论同步/流式能力分叉

- 非流式 LangGraph 只有 pro/con/judge；
- 流式循环增加 RAG fact checker、judge、learning coach；
- 两种接口的来源、角色数量和输出字段不一致；
- worker 直接调用模型，没有统一 completion/evidence 合同。

#### D. AutoTutor 多实例一致性不足

- session `RLock` 只在一个 Python 进程内有效；
- `revision` 检查发生在进程内 state 上，数据库更新没有 `WHERE revision=:expected_revision`；
- 两个实例可能同时加载旧 revision 并各自写入；
- 当前持久化是整段 `state_json` 覆盖，缺少 append-only run event 和 checkpoint lineage。

#### E. Trace 不能作为 durable event source

- `trace_store.py` 使用进程内字典并默认 1 小时 TTL；
- 服务重启后 trace 丢失；
- SSE 断线后无法按持久化 cursor 补发；
- AgentOps 能聚合 audit/learning event，但不能完整重放一次 run 的状态转换。

#### F. 工具、模型和完成语义没有全平台统一

- 学习助手严格通过 Tool Registry，其他 Agent 仍存在直接 RAG/LLM 调用；
- Answer Verifier 只覆盖部分学习助手 intent；
- 历史人物、辩论、地图等事实输出没有统一 `EvidenceClaim`；
- 不同模块对模型 fallback、degraded 和 verified 的定义不同。

#### G. 会话所有权与人工复核链路不完整

- 学习助手已经对 session/student 调用 `assert_student_access()`，历史人物、历史游戏和作文入口没有同等级的显式 owner 校验；
- 历史人物直接按客户端传入的 `session_id` 从 `session_store` 读取消息，session 本身没有 owner 字段；
- 作文批改把 `student_id` 直接当 `session_id`，同一学生的多篇作文会覆盖同一个缓存键；
- `/api/chinese/essay/review-result` 当前只要求登录，没有调用 `require_teacher_actor()`，且复核只追加 system message，不能恢复原 graph/run；
- 这些问题必须作为 v1.33 P0 前置修复，不能等待通用 Runtime 完成后再处理。

#### H. 作文评分状态合同与实现不一致

- `EssayState` 声明 `draft_score/final_score`，但 `grade()` 只写 `draft_comments`；
- API 最终只返回 comments，没有稳定的结构化总分合同；
- critic 不通过时仍把 draft 写入 `final_comments`；
- 批量作文复用同一 graph，因此必须在迁移前先固定评分 schema、总分和人工复核语义。

#### I. 持久化与前端事件不能一刀切

- 学习助手前端、历史人物、历史辩论各自解析 SSE，虽然已有 `frontend/lib/sse.ts`，尚未统一消费；
- token delta 可能包含学生内容，不适合写入 append-only 数据库；
- 地图、推荐、游戏直接调用时是短请求或领域状态机，为其创建 checkpoint 只会增加延迟；
- 因此必须按 durability mode 分级，而不是要求每个能力、每个节点都持久化。

### 1.4 证据边界

仓库现有 `eval/reports/latest.md` 是 2026-08-14 的离线 core 报告，记录 `35/35 suites`、`462/462 cases` 通过，但对应旧 revision `060c166dbc89 (dirty)`，真实 LLM 调用为 0，AgentOps trace coverage 为 `0.575 (115/200)`，release seal 为 `not_applicable`。因此它可作为“确定性合同已有覆盖”的参考，不能作为当前 `dbf5ff1`、真实模型、生产检索或本架构迁移的发布证明。Milestone 0 必须在当前基线重新生成 legacy baseline；迁移后的报告必须记录 commit/config/evidence profile。

当前离线评测证明现有工程主路径稳定，但不能证明以下能力已经适合全量生产：

- 中文自然表达的真实语义路由；
- 模型生成的动态计划；
- 多 Agent 委派；
- 生产 RAG 索引质量和延迟；
- 多实例故障恢复；
- 长任务 checkpoint 恢复；
- 真实学生场景下的教学增益。

因此本轮允许做“架构治理和等价迁移”，不允许用架构重构名义绕过 v1.30/v1.31 的真实证据门槛。

---

## 2. 目标与非目标

### 2.1 产品目标

1. 相同 Agent 的流式与非流式接口执行同一 run，只是消费事件的方式不同。
2. SSE 断线后能够补发已持久化的里程碑/终态；`resumable` 任务可从 checkpoint 恢复，普通短任务在进程中断时明确失败并允许安全重试。
3. 用户能明确区分运行中、等待补充、等待确认、部分完成、证据不足和失败。
4. 需要史料/教材支撑的能力，只有来源和关键声明通过核验才能标记 completed。
5. AutoTutor 在多实例部署下不会重复判题、重复写学习事件或覆盖新 revision。
6. 现有 API、会话、工具卡和主要前端交互保持兼容。
7. 简单功能不因“Agent 化”增加不必要的模型调用和延迟。

### 2.2 工程目标

- 建立统一 `AgentContext / AgentRunState / AgentPlan / AgentStep / StepResult / CompletionDecision / RuntimeEvent`。
- 建立 Postgres 持久化 run、append-only milestone event 和按需 checkpoint，不持久化 token delta。
- 建立框架无关 `RuntimeAdapter`，支持 sequential、LangGraph 和 function 三种执行器。
- 所有工具和有副作用 capability 继续走服务端 allowlist、权限、确认、审计和幂等。
- 建立统一预算：步骤数、工具调用、LLM 调用、wall time、cost estimate。
- 建立统一 waiting/resume/cancel/recovery 协议。
- 建立统一 Evidence Verification 和 fail-closed completion。
- 让 AgentOps 能按 agent、run、step、operation、revision、config version 聚合。
- 通过稳定 bucket、shadow、kill switch 逐 Agent 迁移。

### 2.3 非目标

- 不把所有 Python 函数改成 LangGraph node。
- 不把地图、推荐、游戏生成器升级为开放式 Agent。
- 不允许模型生成任意工具名、Python、SQL、shell 或外部 URL。
- 不引入无约束 ReAct、无限循环或无限上下文。
- 不在 v1.33.0 开放任意 Agent-as-tool。
- 不在 v1.33.0 开放并行写操作。
- 不新增 Kafka、Celery 或独立微服务作为首期必需依赖。
- 不重写 v1.31 RAG、Tool Registry、会话或现有学习事件模型。
- 不用 LLM-as-judge 替代确定性权限、schema、来源 ID、幂等和状态转换检查。
- 不把完整学生 prompt、作文或私有 blind 数据写入 trace/event metadata。
- 不承诺短时 LLM 调用中断后从 token 位置继续生成。
- 不在首期把 `assistant_sessions` 扩展成所有产品共用的会话表。

---

## 3. 架构原则

1. **合同先于框架。** API、状态、事件和完成语义由 EduAgent Pydantic model 定义，LangGraph 只是 adapter。
2. **单一执行源。** 同一 run 只有一套 node execution；SSE、同步响应和后台查询读取同一 event/result。
3. **完成是业务结论。** 函数返回不等于 completed；必须同时满足执行、策略和证据标准。
4. **状态服务端可信。** 用户和模型不能直接声明 step completed、verified、approved 或 revision。
5. **业务副作用默认一次。** write/session_create 必须具有 idempotency key，并在 checkpoint 后可判断是否已经执行；LLM 外部调用记录 attempt，但不虚假承诺 provider 级 exactly-once。
6. **失败默认封闭。** verifier、policy、owner check 和 schema 失败不能升级为 verified/completed。
7. **先静态图，后受限动态。** 首期迁移现有行为；真实证据达标后最多允许一次动态 re-plan。
8. **复杂流程图化，简单能力工具化。** 只有需要分支、等待和恢复的流程进入状态图。
9. **里程碑事件可重放。** UI 的 run/step/terminal 状态可由 append-only event 重建；token delta 仅实时传输，重连后从最近完成产物继续展示。
10. **灰度按 Agent 独立。** 学习助手、AutoTutor、历史人物、作文、辩论分别分桶和回滚。
11. **产品状态与内部状态分层。** 学生端不展示模型 confidence、bucket、内部 prompt 或完整错误栈。
12. **不以重构冒充智能提升。** 架构升级指标和教学/路由/RAG质量指标分开报告。

---

## 4. 目标总体架构

### 4.1 分层结构

```text
┌─────────────────────────────────────────────────────────────┐
│ Product API Layer                                           │
│ learning / auto_tutor / character / essay / debate / games │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ Agent Gateway                                               │
│ auth · owner · guardrail · request normalization · trace   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ Router / Policy / Rollout                                   │
│ deterministic baseline · semantic shadow · risk · budget   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ Unified Agent Runtime · durability mode aware                │
│ plan → execute → observe → verify → repair/re-plan → final │
│ waiting_input · waiting_confirmation · cancel · recover    │
└──────────────┬──────────────────┬───────────────────────────┘
               │                  │
┌──────────────▼────────────┐ ┌───▼───────────────────────────┐
│ Runtime Adapters          │ │ Capability / Tool Registry   │
│ sequential / langgraph /  │ │ tools / subgraphs / function │
│ function                  │ │ schema · role · risk · idem  │
└──────────────┬────────────┘ └───┬───────────────────────────┘
               │                  │
┌──────────────▼──────────────────▼───────────────────────────┐
│ Shared Intelligence Services                               │
│ RAG · Evidence · Memory/Profile · LLM Gateway · Guardrail │
└──────────────┬──────────────────┬───────────────────────────┘
               │                  │
┌──────────────▼───────────┐ ┌────▼──────────────────────────┐
│ Run / Event / Artifact / │ │ Trace / AgentOps / Eval      │
│ Checkpoint · Postgres     │ │ metrics · release seal       │
└──────────────────────────┘ └───────────────────────────────┘
```

### 4.2 Agent 类型分层

#### L0：Function Capability

适用：人物推荐、地图动作、时间线/卡牌生成、AI 话术。

- 单次输入输出；
- 不维护独立目标；
- 不创建开放计划；
- 通过 FunctionAdapter 注册；
- 直接产品调用默认只写 trace/audit，不创建独立 `agent_run`；被学习助手组合调用或产生业务写操作时才关联 parent run；
- 保留现有 validator 和 deterministic fallback。

#### L1：Static Workflow Subgraph

适用：历史人物、作文批改、辩论。

- 固定节点和有限分支；
- 统一 event/completion；只有进入人工复核、确认或其他等待状态时才要求 checkpoint；
- 可等待人工复核；
- 使用 LangGraphAdapter；
- 不允许模型改变图结构。

#### L2：Bounded Agent

适用：学习助手。

- 结构化路由；
- 服务端生成受限计划；
- 最多 3 步作为初始默认；
- 一次只读 repair；
- Evidence Verifier 决定完成；
- 使用 SequentialPlanAdapter；v1.33 不迁移为 LangGraph，后续只有出现真实分支/暂停需求时才重新评估。

#### L3：Adaptive Teaching Agent

适用：AutoTutor。

- 持久化教学计划；
- 学生作答驱动 observe/judge；
- 有界 reflect/re-plan；
- 退出票和学习证据；
- 目标使用 LangGraphAdapter，教学业务逻辑作为固定 Teaching Subgraph；
- 必须支持多实例 CAS、恢复和重复请求幂等。

### 4.3 单一 Orchestrator 与 Specialist

学习助手作为产品级 Orchestrator，只能调用注册的 typed capability：

```text
grounded_history_answer
textbook_answer
quiz_generation
review_plan
character_recommendation
timeline_game_start
auto_tutor_handoff（只创建/跳转，不修改教学 state）
```

历史人物、作文、辩论可以作为独立产品入口和内部 specialist subgraph，但首期不得由模型自由决定是否委派；只能由 Router/Plan 的服务端 allowlist 选择。

### 4.4 Durability Mode

Runtime 不对所有能力采用同一持久化强度：

| Mode | 适用对象 | 持久化 | 中断语义 |
| --- | --- | --- | --- |
| `trace_only` | 地图、推荐、游戏 AI 辅助的直接调用 | 现有 trace/audit/learning event | 请求失败，由产品 API 按现有策略重试 |
| `observable` | 学习助手普通回答、历史人物、辩论、无需人工复核的作文 | `agent_runs` + milestone/terminal events；不写 token delta | 进程中断标记 `failed/retryable`，不从半个 LLM 输出续写 |
| `resumable` | 学习助手高风险确认、AutoTutor、作文人工复核、waiting_input | run + event + checkpoint + artifact reference | 按 revision/CAS 从最近业务边界恢复 |
| `queued` | 现有周报，以及后续明确迁入 job API 的批量/长任务 | `agent_jobs` + 关联 run | 继续复用 claim/retry/stale recovery |

规则：

- mode 由服务端 capability/route 决定，客户端和模型不能提升；
- `trace_only` 可以生成只用于本次请求关联的 ephemeral `run_id`，但不写 `agent_runs`，也不能通过 Run API 查询/恢复；
- `observable` 可以在进入 waiting 状态前升级为 `resumable`，升级必须先持久化输入引用和 checkpoint；
- L0 direct capability 不纳入 run coverage 分母；
- 生产报告必须按 mode 分别统计 event coverage、checkpoint success 和 recovery success，不能要求 `trace_only` 具备 checkpoint。

---

## 5. 核心运行合同

### 5.1 AgentContext

```python
class AgentContext(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    agent_type: str
    actor_id: str | None
    actor_role: Literal["anonymous", "student", "teacher", "admin"]
    student_id: str | None
    session_id: str | None
    source_feature: str | None
    source_session_id: str | None
    trace_id: str
    data_scope: Literal["runtime", "eval", "demo"]
    durability_mode: Literal["trace_only", "observable", "resumable", "queued"]
    config_version: str
    rollout_bucket: int | None
    locale: str = "zh-CN"
```

约束：

- Context 由 API/Gateway 创建，模型不能修改；
- `student_id` 与 `actor_id` 必须经过现有 owner/role 策略；
- subgraph 继承 parent Context，只能收窄权限；
- trace/event 中只记录必要 ID，不记录完整用户输入。

### 5.2 AgentBudget

```python
class AgentBudget(BaseModel):
    max_steps: int = Field(default=3, ge=1, le=12)
    max_tool_calls: int = Field(default=3, ge=0, le=12)
    max_llm_calls: int = Field(default=3, ge=0, le=12)
    max_replans: int = Field(default=0, ge=0, le=1)
    max_wall_time_ms: int = Field(default=15_000, ge=1000, le=300_000)
    max_parallel_reads: int = Field(default=1, ge=1, le=3)
    estimated_cost_limit_usd: float | None = None
```

初始默认：

| Agent | max_steps | max_tool_calls | max_llm_calls | max_replans |
| --- | ---: | ---: | ---: | ---: |
| 学习助手 | 3 | 3 | 3 | 0（repair 不算动态 plan） |
| AutoTutor 单次 answer transition | 4 个 node | 2 | 3 | 沿用全课最多 3 次教学重规划 |
| 历史人物 | 5 | 1 | 2 | 0 |
| 作文批改 | 4 | 0 | 3 | 1 次 revise |
| 辩论 | 固定 3 轮 | 1 次检索 | 9 | 0 |

### 5.3 AgentStep

```python
class AgentStep(BaseModel):
    step_id: str
    kind: Literal["tool", "generation", "subgraph", "verification", "control"]
    operation: str
    input: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    side_effect: Literal["none", "read", "write", "session_create", "external_call"]
    risk_level: Literal["low", "medium", "high"]
    idempotency_key: str | None = None
    timeout_seconds: int = 15
```

要求：

- operation 必须能在 Capability/Tool Registry 解析；
- 模型不得创建未注册 operation；
- write/session_create 必须有 idempotency key；
- `external_call`（包括 LLM provider）记录 request/attempt/provider ID；发生“请求可能已送达但结果未知”时不得自动重放，除非 provider 支持可靠幂等；
- high-risk 必须进入 waiting_confirmation；
- dependencies 只能引用先前步骤，首期禁止循环依赖。

### 5.4 AgentPlan

```python
class AgentPlan(BaseModel):
    schema_version: Literal[1] = 1
    plan_id: str
    revision: int = 0
    objective: str
    strategy: Literal["direct", "sequential", "subgraph"]
    steps: list[AgentStep]
    required_output: dict[str, Any] = Field(default_factory=dict)
    generated_by: Literal["deterministic", "template", "llm_proposal"]
    planner_version: str
```

要求：

- `steps` 必须非空且不超过 `budget.max_steps`；
- step ID 在 plan 内唯一，依赖关系必须构成 DAG；
- `llm_proposal` 只表示计划来源，仍须通过服务端 operation allowlist、风险、预算和依赖校验；
- re-plan 必须保留 `plan_id`、递增 `revision`，且不能修改已经提交的步骤；
- API 只返回步骤摘要，不向学生暴露内部 planner prompt 和安全策略。

### 5.5 StepResult

```python
class StepResult(BaseModel):
    step_id: str
    operation: str
    status: Literal[
        "completed", "partial", "waiting_input", "waiting_confirmation",
        "failed", "cancelled", "degraded"
    ]
    output: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    evidence_claims: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    retryable: bool = False
    side_effect_committed: bool = False
    attempt: int = 1
    latency_ms: float | None = None
```

### 5.6 AgentRunState

```python
class AgentRunState(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    revision: int = 0
    durability_mode: Literal["observable", "resumable", "queued"]
    status: Literal[
        "received", "routed", "planned", "running", "verifying",
        "waiting_input", "waiting_confirmation", "completed", "partial",
        "failed", "cancelled"
    ]
    objective: str
    current_step_id: str | None = None
    plan: AgentPlan | None = None
    step_results: dict[str, StepResult] = Field(default_factory=dict)
    completion: "CompletionDecision | None" = None
    budget: AgentBudget
    used_budget: dict[str, int | float] = Field(default_factory=dict)
    context_refs: dict[str, Any] = Field(default_factory=dict)
    input_artifact_refs: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
```

状态只能通过 Runtime 的 transition function 改变，节点不得直接写数据库状态。

### 5.7 CompletionDecision

```python
class CompletionDecision(BaseModel):
    status: Literal[
        "completed", "partial", "waiting_input", "waiting_confirmation",
        "failed", "cancelled"
    ]
    completion_allowed: bool
    completed_steps: int
    total_steps: int
    verification_status: Literal["verified", "partial", "failed", "not_required"]
    reason_codes: list[str]
    deliverable_refs: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
```

Runtime 必须在 finalize 前生成该对象；API 不得根据“response 非空”自行推断 completed。

---

## 6. 生命周期与状态转换

### 6.1 标准生命周期

```text
received
  → routed
  → planned
  → running
      ├─ waiting_input ─────────┐
      ├─ waiting_confirmation ──┤→ running
      ├─ cancelled              │
      └─ verifying              │
            ├─ completed        │
            ├─ partial          │
            └─ failed           │
```

### 6.2 合法转换

| From | Allowed To |
| --- | --- |
| received | routed, failed, cancelled |
| routed | planned, waiting_input, failed, cancelled |
| planned | running, waiting_confirmation, failed, cancelled |
| running | running, verifying, waiting_input, waiting_confirmation, partial, failed, cancelled |
| waiting_input | running, cancelled, failed（超时） |
| waiting_confirmation | running, cancelled, failed（token 过期） |
| verifying | completed, partial, failed |
| completed/partial/failed/cancelled | 无 |

非法转换必须记录 `runtime.invalid_transition` 并拒绝更新。

### 6.3 Pause / Resume

```python
class ResumeSignal(BaseModel):
    expected_revision: int
    kind: Literal["input", "confirmation", "retry"]
    correlation_key: str
    input_patch: dict[str, Any] = Field(default_factory=dict)
    confirmation_token: str | None = None
```

- waiting 状态必须先写 checkpoint，再向客户端发事件；
- resume 请求必须提供 `run_id + expected_revision + correlation key`；
- confirmation v2 token 绑定 run/step/revision/payload/actor/issued_at；现有只绑定 tool/payload/actor/issued_at 的 v1 token 兼容读取一个发布周期，但不能用于 v2 resume；
- 重复 resume 返回同一结果，不重复执行已提交副作用；
- 超时由 recovery worker 统一转 failed/cancelled，不依赖在线请求触发。

### 6.4 Repair 与 Re-plan

首期区分：

- `repair`：不改变目标和计划结构，只调整查询或重试只读 operation；
- `re-plan`：允许替换尚未执行的步骤，必须生成新 `plan_revision`。

规则：

- v1.33.0 只复用现有一次只读 repair；
- v1.33.1 可以对确定性 failure policy 执行一次 re-plan；
- v1.33.2 才允许结构化 LLM 提议 re-plan；
- 已完成的写步骤不能被移除或重复执行；
- 新计划仍必须经过 allowlist、dependency、risk 和 budget 校验。

---

## 7. Runtime Adapter 设计

### 7.1 接口

```python
class RuntimeAdapter(Protocol):
    def stream(self, context: AgentContext, state: AgentRunState) -> AsyncIterator[RuntimeEvent]: ...
    def resume(self, context: AgentContext, state: AgentRunState, signal: ResumeSignal) -> AsyncIterator[RuntimeEvent]: ...
    async def cancel(self, context: AgentContext, state: AgentRunState) -> RuntimeEvent: ...
```

### 7.2 SequentialPlanAdapter

来源：现有 `learning_assistant_runtime.py`。

职责：

- 执行服务端验证后的最多 N 步计划；
- 保留 success criteria、dependency、confirmation、repair 和 partial；
- `observable` 模式每步写 milestone event；只有进入 waiting 或执行业务写操作时写 checkpoint；
- 所有结果转换为统一 StepResult/RuntimeEvent；
- 不直接依赖学习助手 intent。
- 当前同步 generator 通过现有 `run_in_threadpool(next)` 模式桥接到 AsyncIterator，首期不重写成全异步执行器。

### 7.3 LangGraphAdapter

适用：历史人物、作文、辩论、AutoTutor。

职责：

- 将 EduAgent run/context/checkpoint 注入 compiled graph；
- 将 node start/end/error 映射为 RuntimeEvent；
- graph state 中不保存权限对象和 secret；
- interrupt 映射为 waiting_input/waiting_confirmation；
- graph 结束后仍由公共 CompletionEvaluator 决定最终状态；
- `resumable` graph 使用 `EduAgentCheckpointSaver` 写入 `agent_checkpoints` 并同步 CAS revision，不再维护另一套独立 checkpoint 真相；
- `observable` graph 不启用 LangGraph checkpointer；
- 实施前将 `langgraph>=0.2.0` 收敛为经过 CI 验证的兼容范围，升级需单独跑 graph/checkpoint/interrupt contract。

### 7.4 FunctionAdapter

适用：地图、推荐、时间线/卡牌生成和游戏 AI 辅助。

- 包装现有函数，不新增自主循环；
- 输入/输出必须有 Pydantic schema；
- 继承 context、budget、timeout、trace；
- 如果有业务副作用，必须转为 Tool Registry command；FunctionAdapter 本身仅允许 none/read/external inference；
- validator/fallback 结果明确标记 generation mode。

---

## 8. Capability 与 Tool 治理

### 8.1 保留 Tool Registry

现有 `ToolSpec` 继续承担：

- input/output schema；
- role；
- risk；
- side effect；
- confirmation；
- timeout；
- audit；
- trace。

不修改现有工具名称和主要请求合同。

### 8.2 新增 CapabilityBinding

```python
class CapabilityBinding(BaseModel):
    name: str
    version: str
    kind: Literal["tool", "function", "subgraph", "generation"]
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    executor: str
    allowed_callers: list[str]
    tool_name: str | None = None
    durability_mode: Literal["trace_only", "observable", "resumable", "queued"]
    requires_evidence: bool = False
    default_timeout_seconds: int = 15

    model_config = {"arbitrary_types_allowed": True}
```

Capability Binding 不是第二套安全注册表，也不是让模型任意选择的插件市场：

- `kind=tool` 必须引用现有 `ToolSpec.name`，role/risk/side_effect/confirmation/timeout 只从 Tool Registry 读取，禁止重复声明；
- function/subgraph/generation 默认只能是 none/read/external inference；需要业务写操作时必须调用已注册 Tool；
- Planner 只能从调用者对应的服务端 allowlist 中引用；
- Registry 启动时校验 operation 唯一、tool reference 存在、Pydantic model 可生成 schema。

### 8.3 首期 Capability 清单

| Capability | Kind | 调用者 | 证据要求 |
| --- | --- | --- | --- |
| history.search | tool | learning_assistant, auto_tutor, history_character, debate | 返回标准 sources |
| textbook.lesson | tool | learning_assistant, quiz | 标准 lesson items |
| quiz.generate | tool/function | learning_assistant, auto_tutor | source_item_ids |
| profile.review_plan | tool | learning_assistant | 不要求事实 citation |
| character.recommend | function | learning_assistant, history UI | 检索覆盖元数据 |
| history_character.answer | subgraph | history UI，后续可供 assistant 明确调用 | 必须 grounded |
| essay.grade | subgraph | chinese API | rubric + human review policy |
| debate.run | subgraph | debate API | fact-check sources |
| timeline.generate | function | game tool | candidate-bound validator |
| card.generate | function | game tool | candidate-bound validator |

### 8.4 禁止绕过

- Agent subgraph 不得直接执行业务写数据库或外部副作用；必须调用 Tool Registry；迁移期 service command 需先增加 Tool wrapper 才能被 subgraph 调用；
- 允许 generation node 调用统一 LLM Gateway，但必须记录 provider/model/run/latency/fallback；
- 允许内部纯函数不注册 capability；
- RAG 读取必须返回标准 source contract，不能只把文本拼入 prompt 后丢失 source ID。

---

## 9. 持久化、Checkpoint 与并发

### 9.1 复用与新增边界

| 现有表/服务 | 继续职责 | 不承担 |
| --- | --- | --- |
| assistant_sessions/messages | 学习助手用户可见会话、消息与 owner | 其他产品会话、node checkpoint |
| session_store | 历史人物/作文迁移期短期消息兼容（Redis 或进程内 TTL） | owner 可信存储、人工复核恢复、durable run |
| autotutor_sessions | 当前教学会话兼容；v1.33 首先纳入 Alembic 与 `db/schema.py` | 跨 Agent 通用 run |
| agent_jobs | 异步队列、重试、取消、stale recovery | 交互式 run 的所有 step state |
| audit_events | 安全和副作用审计 | 完整执行重放 |
| learning_events | 学习效果与产品事件 | 运行时 checkpoint |
| trace_store | 兼容实时 trace/UI | 唯一持久化事件源 |

### 9.2 新增 `agent_runs`

建议 migration：`backend/alembic/versions/007_agent_runtime_v2.py`。该 migration 接管当前由 `auto_tutor._ensure_session_table()` 创建的 `autotutor_sessions`：表不存在时创建，已存在时使用方言兼容的 idempotent column/index migration 补充 revision/idempotency 字段，不能只执行 `CREATE TABLE IF NOT EXISTS`；同时在 `backend/db/schema.py` 声明。发布两个周期后才能删除运行时 DDL fallback。

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| run_id | TEXT PK | `run_<uuid>` |
| agent_type | TEXT | learning_assistant/auto_tutor/... |
| actor_id | TEXT nullable | owner/auth |
| student_id | TEXT nullable | 学习对象 |
| session_id | TEXT nullable | 产品会话 |
| parent_run_id | TEXT nullable | subgraph 关系 |
| durability_mode | TEXT | observable/resumable/queued |
| status | TEXT | 标准 run status |
| revision | INTEGER | optimistic concurrency |
| current_step_id | TEXT nullable | 当前节点 |
| objective | TEXT | 脱敏、限长目标摘要 |
| context_refs_json | TEXT | 只保存引用和可信槽位 |
| input_artifact_refs_json | TEXT | 敏感输入/可恢复产物引用，不存原文 |
| plan_json | TEXT nullable | 当前受控计划 |
| state_json | TEXT | 最新运行快照/摘要；敏感输入只保存 artifact ref |
| completion_json | TEXT nullable | 最终完成决策 |
| budget_json | TEXT | 配额 |
| used_budget_json | TEXT | 已使用配额 |
| config_version | TEXT | rollout/config |
| trace_id | TEXT | 关联 trace |
| idempotency_scope | TEXT | 非空 owner/session scope，避免 nullable actor 破坏唯一性 |
| idempotency_key | TEXT nullable | 请求级幂等 |
| last_event_sequence | INTEGER | 事件 cursor |
| expires_at | TEXT nullable | 等待/保留策略 |
| created_at/updated_at/finished_at | TEXT | 时间 |

索引：

- `(idempotency_scope, idempotency_key)` unique when key not null；scope 由服务端从 actor/session 生成，不能由客户端直接指定；
- `(session_id, created_at)`；
- `(status, updated_at)`；
- `(agent_type, created_at)`；
- `(parent_run_id)`。

### 9.3 新增 `agent_run_events`

append-only：

| 字段 | 说明 |
| --- | --- |
| event_id | `evt_<uuid>` |
| run_id | run FK/reference |
| sequence | run 内严格递增 |
| event_type | 标准 RuntimeEvent 类型 |
| step_id | nullable |
| operation | nullable |
| status | event status |
| public_payload_json | 可返回前端的脱敏事件 |
| internal_metadata_json | 仅服务端/管理员读取 |
| data_scope | runtime/eval/demo |
| created_at | 时间 |

约束：`UNIQUE(run_id, sequence)`。

### 9.4 新增 `agent_run_artifacts`

用于解决当前作文正文、历史人物输入和人工复核没有 durable 安全存储的问题；不得把这些内容塞进 event metadata。

| 字段 | 说明 |
| --- | --- |
| artifact_id | `art_<uuid>` |
| run_id | run FK/reference |
| owner_actor_id | actor owner，nullable |
| student_id | 学生资源 owner，nullable |
| artifact_type | input/structured_output/final_output/review_payload |
| sensitivity | normal/student_content/restricted |
| content_json | 受控内容；API 不直接透传 |
| content_sha256 | 去重和审计，不作为鉴权 |
| expires_at | 按产品/敏感度设置保留时间 |
| created_at/updated_at | 时间 |

约束：

- owner/teacher/admin 权限由服务端校验，不能凭 artifact ID 读取；
- 作文正文只允许写 artifact，不写 objective、event、trace 或 audit metadata；
- v1.33 不自行发明应用层加密算法，依赖部署数据库/备份加密，并执行字段级最小访问和 retention；如生产环境不能满足该前置条件，作文 human-review resume 不得开启；
- history/learning 的普通短请求无需保存完整输入，只有升级为 `resumable` 时才创建 artifact。

索引：`(run_id)`、`(owner_actor_id, created_at)`、`(student_id, created_at)`、`(expires_at)`。

### 9.5 新增 `agent_checkpoints`

| 字段 | 说明 |
| --- | --- |
| checkpoint_id | `chk_<uuid>` |
| run_id | run |
| revision | 对应 run revision |
| node_name | 最近完成节点 |
| state_json | schema-versioned state |
| side_effect_ledger_json | 已提交副作用/幂等键 |
| created_at | 时间 |

写入规则与保留策略：

- `trace_only/observable`：不写 checkpoint；
- `resumable`：进入 waiting 前、业务写操作提交后和 AutoTutor 题目展示后写 checkpoint；不要求每个纯计算 node 都写；
- active/waiting resumable run：保留业务边界 checkpoint；
- terminal run：默认保留最后 5 个 checkpoint 30 天；
- audit/legal retention 仍由现有审计策略决定；
- eval/demo 可缩短保留期。

### 9.6 原子更新

核心写入必须采用 CAS：

```sql
UPDATE agent_runs
SET state_json=:state,
    revision=revision+1,
    status=:status,
    last_event_sequence=last_event_sequence+1,
    updated_at=:now
WHERE run_id=:run_id AND revision=:expected_revision;
```

`rowcount != 1` 时返回 `stale_revision`，重新加载状态，不重放已提交副作用。状态 CAS、sequence 分配、milestone event 插入以及必要 checkpoint/ledger 更新必须处于同一数据库事务；如果无法在当前方言中可靠 `RETURNING`，则在事务内先锁定/读取当前 sequence，再执行条件更新，不能在进程内自增。

### 9.7 副作用账本

每个 write/session_create step 记录：

```json
{
  "step_id": "step_2",
  "operation": "start_timeline_game",
  "idempotency_key": "run_x:step_2:attempt_1",
  "status": "committed",
  "resource_ref": "round_x",
  "committed_at": "..."
}
```

恢复时先查询账本/下游幂等结果，再决定是否执行；禁止只依赖“节点是否开始过”。

LLM/RAG 等 external inference 只记录 attempt、provider/model/request ID 和结果是否确定；响应未知的调用不得按业务副作用账本标记 committed，也不得自动 exactly-once 重放。

### 9.8 Agent Jobs 的复用

- 对话内预计 15 秒内完成的 run 继续同步/SSE 执行；
- 周报继续复用现有 `agent_jobs`；当前批量作文仍是请求内并发，只有新增 job API、状态查询与前端轮询后才迁入 `queued`，本 Spec 不把它描述为现状；
- 长检索构建等后续任务可进入 `agent_jobs`，但必须先注册明确 job handler；
- `agent_jobs` 的 handler 可以创建一个 `agent_run` 并等待其 terminal；
- job retry 不能创建第二个相同 idempotency run；
- 首期不把所有学习助手请求排队，避免增加延迟和运维复杂度。

---

## 10. RuntimeEvent 与 API/SSE

### 10.1 统一事件 envelope

```json
{
  "schema_version": 2,
  "run_id": "run_x",
  "trace_id": "trace_x",
  "sequence": 12,
  "event": "step_completed",
  "timestamp": "2026-08-20T00:00:00Z",
  "data": {}
}
```

### 10.2 标准事件

| 事件 | 用途 |
| --- | --- |
| run_started | run 已持久化 |
| route_decided | 活跃路由结果，内部字段按角色脱敏 |
| plan_created | 公共步骤摘要 |
| step_started | 节点开始 |
| tool_started | 工具开始 |
| tool_result | 工具最终结果摘要 |
| generation_delta | 文本增量，只做实时 SSE，不持久化 |
| repair_attempted | 固定 repair |
| plan_revised | plan revision 变化 |
| verification_result | verified/partial/failed |
| waiting_input | 需要补充信息 |
| waiting_confirmation | 需要高风险确认 |
| step_completed | 步骤完成 |
| step_failed | 步骤失败 |
| run_completed | completed/partial + completion decision |
| run_failed | terminal failure |
| run_cancelled | 已取消 |
| heartbeat | SSE 保活，不写数据库 |

### 10.3 事件持久化策略

- `observable/resumable/queued` 的 route、plan、step milestone、verification、waiting、terminal 必须持久化；
- generation delta、heartbeat 不持久化；重连后返回最近 `step_completed` 产物摘要或 terminal artifact，不尝试补齐丢失 token；
- `trace_only` 继续使用现有 trace/audit，不写 `agent_run_events`；
- public payload 不包含 prompt、secret、完整学生档案和内部 stack；
- internal metadata 只允许 admin/eval API 读取；
- SSE 从持久化 cursor 补发后，再订阅内存实时事件。

### 10.4 API 兼容

现有产品 API 路径保持不变。响应和 SSE 增量增加：

- `run_id`；
- `run_revision`；
- `completion_status`；
- `verification_summary`；
- `event_cursor`。

新增内部/运维 API：

| 方法 | 路径 | 权限 | 用途 |
| --- | --- | --- | --- |
| GET | `/api/agent-runs/{run_id}` | owner/admin | 当前状态和公共结果 |
| GET | `/api/agent-runs/{run_id}/events?after=N` | owner/admin | 断线补发 |
| POST | `/api/agent-runs/{run_id}/resume` | owner | 补槽位/继续 |
| POST | `/api/agent-runs/{run_id}/confirm` | owner | 高风险确认 |
| POST | `/api/agent-runs/{run_id}/cancel` | owner/admin | 请求取消，不物理删除审计；与现有 job cancel 语义一致 |
| POST | `/api/admin/agent-runs/recover` | admin | 手动恢复 stale runs |

禁止开放“任意 agent_type + 任意 operation”的通用学生端创建 API；产品路由必须先决定允许的 Agent。

### 10.5 流式/非流式一致性

- 产品 endpoint 创建 run 后调用同一 Runtime；
- `stream=false` 等待 terminal 并读取 completion/result；
- `stream=true` 按 sequence 推送同一 run events；
- 两者不得分别调用 graph 与手写 loop；
- 同一 idempotency key 的流式/非流式重试必须指向同一 run。
- 学习助手当前已经由同步和流式 API 共用 `stream_learning_assistant_events()`；迁移只抽取 adapter 和持久化，不重新实现第二条执行链。
- 前端统一复用 `frontend/lib/sse.ts`；学习助手、历史人物、历史辩论不得继续各自新增 SSE parser。
- L0 `trace_only` direct endpoint 不要求创建 run，也不适用本小节的 run parity；其输入输出合同由 FunctionAdapter/产品 API 回归保证。

---

## 11. Evidence 与完成门控

### 11.1 统一 EvidenceClaim

```python
class EvidenceClaim(BaseModel):
    claim_id: str
    text: str
    critical: bool
    source_ids: list[str]
    citations: list[dict[str, str]]
    producer_step_id: str
```

### 11.2 Evidence-required 能力

首期：

- history_search；
- textbook_qa；
- 基于史料/教材的 quiz；
- 历史人物事实回答；
- 辩论 fact checker 与裁判中的事实判断；
- 地图历史事件解说（至少来源充分性状态，不要求逐句 citation UI）；
- AutoTutor 使用史料生成的关键史实讲解和题目。

作文风格反馈、复习建议和普通闲聊不要求历史 citation，但仍需自己的 rubric/policy validation。

### 11.3 完成规则

`completed` 必须同时满足：

1. 所有 required step 达到 success criteria；
2. 没有未确认的高风险操作；
3. budget 未超限；
4. required evidence intent 的 source ID 有效；
5. supported claim coverage 和 citation precision 达标；
6. 无未解决 source conflict；
7. verifier/policy 没有异常；
8. completion evaluator 明确 `completion_allowed=true`。

`partial`：已有可验证交付结果，但至少一个非关键目标未完成、证据仅部分充分或来源冲突已显式呈现。

`failed`：没有安全可交付结果、关键 step 失败、无必要来源或 verifier/policy fail-closed。

### 11.4 Fail-closed

- 历史人物 verifier 异常必须 `verified=false`；
- structured verifier 超时回到确定性 verifier，不得自动通过；
- 引用未知 source ID 必须失败；
- source conflict 不得 completed；
- LLM judge 的“APPROVED”不能替代确定性 schema/rubric 检查。

---

## 12. 上下文、记忆与学习状态

### 12.1 三层状态分离

| 层 | 内容 | 生命周期 |
| --- | --- | --- |
| Run State | 当前目标、计划、步骤、等待、预算 | 单次 run |
| Conversation State | 最近消息、可信教材/来源上下文、未解决槽位 | 学习助手使用 assistant session；其他产品继续使用自身 session，不能跨产品假定同表 |
| Learning Memory | 薄弱点、兴趣、偏好、错题、复习目标 | 跨会话 |

不得把三层全部塞入 graph state 或 prompt。

需要跨重启 resume 的敏感输入（例如作文）通过 `agent_run_artifacts` 引用；`session_store` 只作为迁移期短缓存，不能作为 owner 可信或人工复核的唯一数据源。

### 12.2 Context Resolver

统一 resolver 输出引用和有限摘要：

```python
class ResolvedContext(BaseModel):
    conversation_message_ids: list[str]
    trusted_topic: str | None
    textbook_ref: dict[str, str] | None
    weakpoint_refs: list[str]
    preference_refs: list[str]
    unresolved_goal: dict[str, Any] | None
    token_budget: int
```

### 12.3 Memory Policy

- 只有 verified/completed 或明确用户反馈支持的结果可以形成高置信 memory；
- partial/failed run 不自动写“已掌握”；
- 用户纠正必须能降低/禁用冲突 memory；
- subgraph 只能提出 `MemoryProposal`，由服务端 policy 决定写入；
- AutoTutor 继续使用 weakpoint/exit-ticket 证据，但通过统一 event 引用 run_id；
- 本 Spec 只统一接口，不在首期实现完整 BKT/IRT 掌握概率模型。

---

## 13. 各 Agent 迁移设计

### 13.1 学习助手

保留：

- deterministic/semantic Router；
- rollout/kill switch；
- Pydantic Plan；
- operation allowlist；
- Tool Registry；
- Answer Verifier；
- conversation-first API 和现有 UI。

迁移：

```text
learning_assistant.py
  → Agent Gateway 创建 run
  → Router/Planner 生成统一 AgentPlan
  → SequentialPlanAdapter 执行
  → 公共 CompletionEvaluator
  → assistant message 持久化引用 run_id
```

兼容：

- 保留现有 `stream_learning_assistant_events()` 作为同步/流式共同执行源，`learning_assistant_runtime.py` 先成为 v2 adapter facade；
- 现有 SSE event 保留一个兼容发布周期；
- 未启用 v2 的 bucket 继续走 legacy runtime；
- v1.33.0 不扩展组合类型，仍只允许 explain→quiz。
- 现有 `TaskPlan/PlanStep` 通过 mapper 进入公共合同，不在首期同时删除旧 model；parity 通过后再收敛。
- 当前 confirmation 请求仍按 tool name/token 重新进入 chat；v2 只对启用 run 的 bucket 改为 resume，旧 token 保留兼容读取但不能跨 run 使用。

### 13.2 AutoTutor

保留：

- LessonStep、Teaching、Question、Reflection、ExitTicket 业务合同；
- 最大步骤/尝试/重规划护栏；
- owner check 和 assistant handoff 中立性；
- weakpoint、learning event、effectiveness 指标。

阶段 1：先修持久化和并发，不更换状态机：

- migration 007 接管 `autotutor_sessions`，`db/schema.py` 增加声明，保留 `_ensure_session_table()` 作为两周期兼容 fallback；
- 为 `autotutor_sessions` 增加显式 `revision`、`last_idempotency_key`（或等价请求记录）并使用 `WHERE session_id=:id AND revision=:expected` CAS；
- 两实例并发测试通过前，不开始 LangGraph 迁移；
- `RLock` 继续降低同进程竞争，但不再被视为正确性边界。

阶段 2：在行为 parity 后接入 LangGraphAdapter：

- 每次 start/answer 创建或 resume 同一个 durable run；
- 使用数据库 CAS 更新 revision；
- answer 请求使用 `run_id + expected_revision + idempotency_key`；
- plan/teach/question/judge/reflect/re-plan/exit-ticket/finalize 形成 milestone event；题目展示、answer 判定提交、waiting 和 finalize 等业务边界形成 checkpoint；
- 进程重启后从 checkpoint 恢复当前题，不重新生成已展示题目；
- 副作用（学习事件、weakpoint、memory）写入 side-effect ledger；
- 迁移期继续同步写 `autotutor_sessions`，直到双读对比通过。

### 13.3 历史人物

目标统一子图：

```text
receive
  → retrieve
  → sufficiency_gate
      ├─ none → limited_no_evidence_response
      └─ partial/sufficient → generate
  → deterministic_evidence_check
      ├─ pass → optional_llm_review
      └─ fail → partial/failed
  → fact_card
  → memory_proposal
  → finalize
```

要求：

- Runtime 改造前先独立修复 `verify_response()` exception 返回 `verified=True` 的 P0 问题，并补 verifier exception smoke；
- `/api/history/*` 只要携带 `student_id` 就调用 `assert_student_access()`，按 round/session/report 读取资源时也校验其 owner；迁移期 character session cache key 至少绑定 actor/student，v2 以 run owner 为准；
- `CharacterState` 必须显式携带已校验的 `student_id`，并增加有学生/无学生两种 memory side-effect 测试，避免当前字段丢失导致静默 no-op；
- 流式/非流式执行同一图；
- generation delta 由 LangGraphAdapter 转 event；
- verifier 异常 fail-closed；
- fact card 只能来自最终已核验回答和 sources；
- memory update 只有在 final 可交付后执行一次；
- 为兼容当前 UI 可以继续发 legacy `final/fact_card`，但 v2 `run_completed` 必须等 fact card 和 memory proposal 处理完成后再发；
- 复用 v1.31 标准 HistorySource 和 Answer Verifier。

### 13.4 作文批改

目标图：

```text
receive
  → rubric_validate
  → grade_structured
  → deterministic_score_check
  → critic
      ├─ approved → finalize
      ├─ fixable and revision_count<1 → revise → critic
      └─ disagreement/high_risk → waiting_human_review
```

要求：

- `/api/chinese/essay/grade` 先执行 `assert_student_access(actor, student_id)`；`session_id` 必须使用独立 UUID/run_id，禁止继续直接等于 `student_id`；
- `/api/chinese/essay/review-result` 必须调用 `require_teacher_actor()`，并按 run owner/student 授权复核；
- 先固定 `EssayGradePayload → draft_score/draft_comments → final_score/final_comments` 映射和总分字段，禁止保留永远为空的 score state；
- 增加真正 `revise` 节点；
- `final_score` 与 `final_comments` 只在 finalize 写入；
- 分项总分、范围和 JSON schema 用规则验证；
- teacher review 恢复同一个 run，而不是只追加 system message；
- score override 记录 actor、reason 和 audit；
- 作文正文只写 owner-protected `agent_run_artifacts`，不写 trace/internal event/objective；生产数据库加密/retention 未满足时，不启用 human-review resume。

### 13.5 历史辩论

目标图：

```text
topic_guard
  → retrieve_shared_evidence
  → pro/con fixed rounds × 3
  → fact_check
  → judge
  → learning_coach
  → finalize
```

要求：

- 非流式与流式使用同一图；
- 所有 worker 使用同一来源池，但角色 prompt 相互隔离；
- fact checker 输出结构化 claims/citations；
- judge 不得把未通过事实核验的论点作为获胜依据；
- 固定角色和固定轮数，首期不动态创建 Agent；
- 单个 worker 失败时按 policy 决定 partial 或 fail，不重跑完整辩论。

### 13.6 历史地图

保持 FunctionAdapter：

- `retrieve → narrate → validate map actions`；
- map action 使用 Pydantic allowlist，禁止任意前端命令；
- narration 增加 source refs 和 sufficiency；
- 不引入 Planner，直接调用保持 `trace_only`，不创建独立长期 run；由学习助手组合调用时只作为 parent run 的 step。

### 13.7 人物推荐

保持 FunctionAdapter：

- 复用 RAG + rule score + structured model + fallback；
- 输出 catalog membership、coverage、source refs；
- 不增加循环和长期 state；
- 注册为只读/外部 inference capability；直接调用保持 `trace_only`。

### 13.8 时间线、卡牌与多人游戏

保持领域引擎：

- LLM 只能从可信候选池选择；
- validator 和 static fallback 保持；
- round state 继续由游戏服务管理；
- Runtime 只在学习助手组合调用“创建一局”时负责 parent step 的幂等和审计；游戏直接入口继续使用现有 round store；
- 游戏每回合不升级为通用 Agent run；
- AI commentary/coach 不得改变确定性游戏结果。

---

## 14. 安全、隐私与权限

### 14.1 权限继承

- AgentContext 的 actor/role/student 由 API 鉴权产生；
- child subgraph 不能提升 role；
- owner check 在 run 创建、查询、resume、confirm、cancel 都执行；
- admin 查询 internal events 需要独立权限和审计；
- teacher human review 只能访问授权学生/班级资源。
- 在 Agent Gateway 上线前，先补齐现有 `/api/history/*` 和 `/api/chinese/essay/*` 的 `assert_student_access/require_teacher_actor`，因为当前路由安全水平并不一致；
- `session_id/run_id/artifact_id` 都只是资源标识，不能作为访问凭据。

### 14.2 Prompt Injection

- 用户输入继续经过 guardrail；
- RAG、作文、对话历史和工具输出视为 untrusted context；
- Tool/Capability 名称、风险、side effect 不从 prompt 读取；
- 模型输出只能作为 typed proposal，由服务端 sanitizer/policy 决定；
- high-risk route 不进入 semantic active 或动态 re-plan。

### 14.3 数据最小化

- run objective 仅保存限长摘要；
- 原始作文保存到 owner-protected `agent_run_artifacts`，不复制到 objective/event/trace/audit metadata；
- trace/event 不记录完整学生 prompt、完整画像或 memory content；
- rollout subject 使用 hash；
- private blind 路径和样本不进入 run/event；
- event retention 按 data_scope 区分。

### 14.4 幂等与重放安全

- write/session_create 必须有 idempotency；
- external inference 记录 attempt 和不确定结果，不能宣称 exactly-once；
- confirmation v2 token 绑定 run revision 和 step，v1 token 只做 legacy 兼容；
- stale resume 不执行；
- event replay 只更新 UI，不触发 node；
- checkpoint 恢复先核对 side-effect ledger。

---

## 15. 可观测、指标与 SLO

### 15.1 Run 指标

- run_count by agent/status/config；
- completion/partial/failure/cancel/waiting rate；
- plan completion rate；
- step success/failure/degraded rate；
- repair/re-plan count and success；
- checkpoint write/recovery success；
- stale revision count；
- duplicate side-effect prevented count；
- stream reconnect/replay count；
- budget exceeded count；
- latency p50/p95 by agent/operation；
- LLM calls/model/fallback/error/cost estimate；
- evidence validity/coverage/precision/conflict；
- human review wait/resolution time。

### 15.2 生产 readiness 门槛

| 指标 | 10% canary | 50% | 100% |
| --- | ---: | ---: | ---: |
| runtime trace/event coverage | >=95% | >=97% | >=99% |
| terminal run state consistency | 100% | 100% | 100% |
| duplicate side effects | 0 | 0 | 0 |
| invalid transition | 0 | 0 | 0 |
| checkpoint write success（resumable only） | >=99.5% | >=99.8% | >=99.9% |
| stale recovery success（resumable only） | >=95% | >=97% | >=99% |
| 同一 run 的 stream/non-stream terminal contract parity | 100% | 100% | 100% |
| required evidence no-source completed | 0 | 0 | 0 |
| high-risk execution without confirmation | 0 | 0 | 0 |
| unexpected failure rate | <=2% | <=1% | <=0.5% |

### 15.3 性能目标

| 场景 | 目标 |
| --- | --- |
| 首个 SSE run_started | p95 <=300ms（不含鉴权依赖故障） |
| 简单规则 chat | 不因持久化增加超过 100ms p95 |
| 学习助手正常回答 | p95 <=4.5s |
| checkpoint 单次写入 | p95 <=100ms |
| SSE 断线事件补发 | 100 events p95 <=500ms |
| stale run 恢复发现 | <=60s |
| owner/idempotency/CAS | 100% server-side |

上述延迟是 v1.33 目标值而非已证明基线。Milestone A 必须先记录 legacy p50/p95；灰度期间除满足绝对目标外，学习助手/历史人物/辩论相对 legacy 的 p95 回退不得超过 10%。不同请求的真实 LLM 文本不做逐字 parity，只校验同一 run 的步骤、来源、完成状态和最终 artifact 一致。

### 15.4 AgentOps 展示

新增：

- Runtime v1/v2 流量比例；
- 按 `durability_mode` 的 run/trace-only 分母；
- run status 漏斗；
- waiting/recovery；
- per-agent checkpoint health；
- stream parity；
- side-effect duplicate prevention；
- dynamic re-plan active rate；
- legacy/v2 disagreement；
- release config version。

无生产样本继续显示 `unknown / --`，不得显示误导性 0%。

---

## 16. Feature Flags 与灰度

建议新增：

```dotenv
EDU_AGENT_RUNTIME_V2_ENABLED=false
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=true
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=0
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.33-control
EDU_AGENT_RUNTIME_V2_KILL_SWITCH=false
EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS=true
EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED=false
EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED=false
EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED=false
EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED=false
EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED=false

EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS=0
EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS=0
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=0
EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS=0
EDU_AGENT_RUNTIME_V2_DEBATE_BPS=0
```

规则：

- global kill switch 优先于 per-agent；
- high-risk 和人工复核请求首期只走经过验证的路径；
- shadow 可以双写事件/比较结果，但不能重复执行工具、LLM 或副作用；
- shadow 对 graph 只比较 plan/state mapping，不运行第二份模型链；
- bucket 继续使用稳定 SHA-256；
- artifact/checkpoint/resumable 三个开关必须同时满足且通过数据库加密/retention readiness，才能启用作文人工复核恢复；
- 每次 rollout 必须记录 config version 和 commit。

### 16.1 灰度顺序

0. 不等待 Runtime 灰度，先发布历史人物 verifier fail-closed、历史/作文 owner 校验、作文 teacher review 权限和独立 session ID；
1. `observable/resumable` 的 run/event dual-write，0% v2 execution；`trace_only` 不写 run；
2. 历史人物统一图 10%，作为第一个 LangGraphAdapter 纵向切片；
3. 作文批改 10%；
4. 辩论 10%；
5. 学习助手 10%，继续使用 SequentialPlanAdapter；
6. AutoTutor 先灰度 DB CAS（仍运行旧状态机），确认两实例正确后再灰度 LangGraphAdapter/durable transition；
7. 各自达到样本/时间门槛后扩到 50%/100%；
8. L0 FunctionAdapter 只做合同映射，不作为 Runtime v2 流量迁移项；
9. 全部稳定后才评估一次动态 re-plan 和只读 fan-out。

---

## 17. 实施阶段

### Milestone 0：P0 正确性与安全前置（2–3 天，可独立发布）

实现：

- 历史人物 verifier exception 改为 fail-closed，并增加确定性 fallback 状态；
- `/api/history/*` 携带 `student_id` 或读取 round/session/report 时执行 student/resource owner 校验；
- 作文 grade 执行 student owner check，生成独立 session/run ID；
- 作文 review-result 强制 teacher/admin，并禁止仅凭 session ID 复核；
- 固定作文结构化评分/总分 schema；
- 记录现有各 Agent p50/p95、SSE 事件、LLM 调用和 DB 写入基线。

退出条件：

- verifier exception 的 `verified=true` 数量为 0；
- 非 owner 历史/作文访问与非教师复核全部 403；
- 同一学生两篇作文不覆盖同一 session key；
- P0 修复进入 fast gate，不依赖 Runtime v2 flag。

### Milestone A：最小 Runtime 合同与持久化（3–4 天）

实现：

- `AgentContext/State/Plan/Result/Completion/Event` 与 durability mode；
- state transition validator；
- migration 007：接管 `autotutor_sessions`，新增 `agent_runs/agent_run_events/agent_run_artifacts/agent_checkpoints`；
- run CAS、event sequence、artifact owner/retention、checkpoint store；
- 旧 trace 兼容 adapter；
- Runtime v2 feature flags。

退出条件：

- 合法/非法状态转换测试全绿；
- 多并发 CAS 只有一个成功；
- event sequence 无重复/倒序；
- artifact 非 owner 不可读取且正文不进入 event/trace；
- migration 在 SQLite/Postgres smoke 通过；
- `autotutor_sessions` 由 migration/schema 声明，运行时 DDL 仅为兼容 fallback。

### Milestone B：Adapter 与公共完成门控（3–4 天）

实现：

- SequentialPlanAdapter、LangGraphAdapter、FunctionAdapter；
- Capability Binding（不复制 ToolSpec 安全字段）；
- CompletionEvaluator、Evidence Verifier adapter；
- budget/policy/side-effect ledger；
- 标准 SSE envelope、milestone replay 和 `frontend/lib/sse.ts` 公共消费；
- 锁定并验证 LangGraph 兼容版本范围。

退出条件：

- 三种 adapter 输出同一 RuntimeEvent schema；
- tool/policy/evidence 失败不能 completed；
- token delta 未落库，SSE 重连可恢复最近 milestone/terminal artifact；
- legacy/v2 deterministic step parity 通过；
- Tool Binding 与 ToolSpec 风险字段不存在双真相。

### Milestone C：历史人物纵向切片（3–4 天）

实现：

- 把 retrieve/generate/verify/fact-card/memory proposal 合并为一张固定图；
- 同步与 SSE 都消费同一 LangGraphAdapter run；
- 复用 HistorySource/Answer Verifier；
- owner-bound session/run；
- 更新历史人物前端为公共 SSE parser，同时保留 legacy event adapter。

退出条件：

- 同一 run 的 stream/non-stream terminal contract parity 100%；
- verifier 故障不再 verified/completed；
- fact card 只来自已核验结果；
- memory side effect 最多一次；
- 10% canary 达到第 15 节门槛。

### Milestone D：作文与辩论专用子图（5–7 天）

作文实现：

- score/comments 明确映射、确定性 rubric 校验、一次 revise；
- human-review interrupt/resume 和 artifact；
- 批量作文暂保留原执行模式，除非另行提供 queued job API。

辩论实现：

- 合并非流式 pro/con/judge 与流式 fact-check/coach；
- 固定 3 轮、共享来源池、结构化 fact claim；
- 公共 SSE parser 和 per-agent rollout。

退出条件：

- 作文 critic 可触发一次真实 revise，teacher review 恢复同一 run；
- 作文正文不进入 trace/event，score state 不再为空壳；
- 辩论所有接口具备相同 rounds/fact-check/judge/coach 语义；
- unsupported fact 不参与获胜依据。

### Milestone E：学习助手接入（3–4 天）

实现：

- 现有 TaskPlan/PlanStep → AgentPlan mapper；
- 保留 `stream_learning_assistant_events()`，由 SequentialPlanAdapter 包装；
- run_id 写入 assistant message metadata；
- v2 confirmation/resume/cancel 与 v1 token 兼容读取；
- 旧/new SSE compatibility；
- v1.30 rollout/evidence 指标复用。

退出条件：

- 现有 intent/trajectory/groundedness/multiturn 不回退；
- 组合 explain→quiz parity；
- repair、partial、waiting_confirmation 一致；
- 未新增第二条学习助手执行链；
- 10% canary 达到第 15 节门槛。

### Milestone F：AutoTutor 分阶段 Durable Migration（5–8 天）

阶段 1：

- 在现有状态机上实现 `autotutor_sessions` 数据库 CAS、start/answer idempotency 和两实例测试；
- 保留 RLock，但只作为进程内优化；
- 题目展示、answer 提交、exit ticket/finalize 写业务边界 checkpoint。

阶段 2（阶段 1 通过后）：

- AutoTutor state mapper 与固定 Teaching Subgraph；
- LangGraphAdapter、process restart recovery、side-effect ledger；
- migration dual-read/compare；
- owner/handoff security regression。

退出条件：

- 两实例提交同一 revision 只判题一次；
- 重启后当前题、attempt、replan、exit ticket 不变化；
- learning event/weakpoint 无重复；
- AutoTutor trajectory/teaching/effectiveness 全绿；
- 10% canary 连续 48 小时无 P0。

### Milestone G：受限增强（证据门控，3–4 天）

前置条件：

- v1.30 中文 blind、真实 LLM、生产 canary 达标；
- v1.31 production RAG gate 达标；
- Runtime v2 100% 或目标 Agent 至少 50% 且稳定；
- trace/event coverage >=97%；
- 无重复副作用或高风险越权。

可启用：

- 一次结构化 dynamic re-plan；
- 最多 3 路只读检索 fan-out；
- 明确 allowlist 的 specialist subgraph 调用；
- 长任务 run 与 agent_jobs 集成。

仍不启用：

- 动态创建 Agent；
- 并行写；
- 模型生成代码/SQL；
- 无预算开放循环。

---

## 18. 文件改动规划

### 18.1 新增

```text
backend/agent_runtime/
  __init__.py
  models.py
  context.py
  transitions.py
  engine.py
  policy.py
  budget.py
  capability_registry.py
  completion.py
  event_store.py
  artifact_store.py
  checkpoint_store.py
  side_effects.py
  sse.py
  recovery.py
  adapters/
    __init__.py
    sequential.py
    langgraph.py
    function.py
  subgraphs/
    history_character.py
    essay_grader.py
    debate.py
    auto_tutor.py

backend/alembic/versions/007_agent_runtime_v2.py
backend/api/routers/agent_runtime.py

eval/agent_runtime_contract_smoke.py
eval/agent_runtime_checkpoint_smoke.py
eval/agent_runtime_concurrency_smoke.py
eval/agent_runtime_recovery_smoke.py
eval/agent_runtime_stream_parity_smoke.py
eval/agent_runtime_idempotency_smoke.py
eval/agent_runtime_security_smoke.py
eval/history_character_runtime_smoke.py
eval/essay_grader_runtime_smoke.py
eval/debate_runtime_smoke.py
eval/autotutor_runtime_v2_smoke.py
```

### 18.2 修改

```text
backend/agents/learning_assistant.py
backend/agents/learning_assistant_runtime.py
backend/agents/answer_verifier.py
backend/agents/auto_tutor.py
backend/agents/history_character.py
backend/agents/essay_grader.py
backend/agents/debate_supervisor.py
backend/tools/base.py
backend/tools/registry.py
backend/agent_ops.py
backend/trace_store.py
backend/db/schema.py
backend/requirements.txt
backend/api/main.py
backend/api/routers/learning.py
backend/api/routers/history.py
backend/api/routers/chinese.py
backend/api/routers/eval_ops.py
backend/services/learning_assistant_session_service.py
backend/services/agent_job_service.py
backend/session_store.py
eval/run_core_evals.py
scripts/release_gate.py
frontend/app/learning-assistant/page.tsx
frontend/app/(student)/student/auto-tutor/page.tsx
frontend/app/history-character/page.tsx
frontend/app/history-debate/page.tsx
frontend/app/eval/page.tsx
frontend/lib/sse.ts
SCHEMA.md
README.md
.env.example
```

### 18.3 首期不修改

- v1.31 RAG 检索算法和索引格式；
- 学生长期 memory 内容模型；
- 游戏判分和正确顺序算法；
- 现有 Tool 名称；confirmation v1 token 只保留一个发布周期的 legacy 解码，v2 resume 使用绑定 run/step/revision 的新 token；
- 导航信息架构；
- 现有公开 endpoint 路径。

以下 L0 文件首期也不修改；只有发现输入/输出 schema 缺口或被 parent run 调用时才增加薄封装：

- `backend/agents/history_map_agent.py`；
- `backend/agents/character_recommender.py`；
- `backend/agents/timeline_question_generator.py`；
- `backend/agents/card_game.py`；
- `backend/agents/history_games_pkg/timeline_flow.py`。

---

## 19. 测试与评测矩阵

### 19.1 合同单测

- Pydantic schema；
- 状态转换；
- dependency DAG；
- budget；
- invalid operation；
- risk/side effect；
- CompletionDecision；
- Event envelope 和脱敏。

### 19.2 持久化与故障注入

- checkpoint 写入后进程异常；
- node 完成、event 未发时异常；
- side effect 成功、checkpoint 未完成时异常；
- DB 短暂失败；
- SSE 断线重连；
- 重连只补 milestone/terminal，不补 token delta；
- stale waiting run；
- agent_job retry；
- migration upgrade/downgrade smoke。

### 19.3 并发与幂等

- 同一 run/revision 两个并发 resume；
- 同一 answer idempotency key 重复提交；
- 两 worker claim 同一 transition；
- confirmation 重放；
- cancel 与 complete 竞争；
- duplicate side-effect ledger；
- event sequence 并发写。

### 19.4 安全

- 非 owner 查询/resume/cancel；
- 历史人物携带其他学生 ID/会话 ID，历史游戏读取其他学生 round/report；
- 作文冒用其他 student_id、学生调用 teacher review；
- artifact ID 越权读取与 retention；
- student 提升 teacher/admin role；
- subgraph 提升权限；
- prompt 注入生成高风险 operation；
- 未确认写操作；
- trace/event PII/secret 泄漏；
- blind 数据路径泄漏；
- unknown source ID 和 verifier exception。

### 19.5 Agent 专项

#### 学习助手

- intent 300 cases；
- trajectory；
- multi-intent explain→quiz；
- clarification resume；
- read repair；
- partial/waiting/failed；
- grounded completion；
- multiturn/session feedback。

#### AutoTutor

- plan target weakpoints；
- wrong→reflect/re-plan；
- difficulty downgrade；
- exit ticket；
- restart recovery；
- multi-worker revision；
- side-effect exactly-once；
- handoff neutrality。

#### 历史人物

- stream/non-stream parity；
- retrieval none/partial/sufficient；
- verifier fail-closed；
- fact card from verified answer；
- memory write once；
- verified student_id 正确进入 CharacterState，匿名请求不写学生 memory。

#### 作文

- schema/rubric total；
- draft/final score 与 comments 映射；
- 同一学生多篇作文独立 session/run；
- critic approved；
- one revise；
- max revision；
- human review wait/resume；
- teacher override audit；
- essay content not leaked to trace。

#### 辩论

- fixed round count；
- shared sources；
- fact-check claims；
- judge excludes unsupported fact；
- worker partial failure；
- stream/non-stream parity。

### 19.6 发布门禁

fast gate 新增：

- runtime contracts；
- checkpoint/CAS；
- idempotency；
- stream parity；
- verifier fail-closed；
- legacy compatibility。

full gate 新增：

- restart recovery；
- 专用 subgraph；
- migration；
- frontend SSE replay；
- LangGraph pinned-version contract；
- all specialist regressions。

production gate 新增：

- deployed run/event DB readiness；
- runtime v2 active percent；
- persistent trace coverage；
- recovery/duplicate/invalid transition；
- real LLM and production RAG evidence；
- release config/commit match。

---

## 20. 验收清单

### 20.1 公共 Runtime

- [ ] 三种 adapter 使用同一 AgentContext/State/Event/Completion schema。
- [ ] 非法状态转换被拒绝并审计。
- [ ] observable run 有 milestone event；resumable run 在 waiting/业务写边界有 checkpoint；trace_only 不被错误纳入 checkpoint 分母。
- [ ] terminal run 不可再次 resume。
- [ ] run revision 使用数据库 CAS。
- [ ] SSE 可按 cursor 补发。
- [ ] token delta 未写数据库，重连可读取最近完成 artifact/terminal。
- [ ] stream/non-stream 读取同一 run。
- [ ] kill switch 可立即回 legacy。

### 20.2 工具与副作用

- [ ] 所有新增 operation 在 Capability/Tool Registry 注册。
- [ ] 模型不能调用未知 operation。
- [ ] high-risk 未确认执行数为 0。
- [ ] write/session_create 有 idempotency key。
- [ ] external inference 不被错误宣称 exactly-once，未知结果不会自动重放。
- [ ] 重启恢复不重复副作用。
- [ ] side-effect ledger 与审计可关联。

### 20.3 Evidence 与完成

- [ ] required evidence 无来源 completed rate=0。
- [ ] unknown source ID 被拒绝。
- [ ] verifier 异常 fail-closed。
- [ ] source conflict 降为 partial/failed。
- [ ] completion 只由 CompletionEvaluator 生成。
- [ ] UI 不把 waiting/partial 显示为已完成。

### 20.4 Agent 迁移

- [ ] 历史人物只有一套执行图。
- [ ] 历史人物 verifier 故障不再 `verified=true`。
- [ ] 作文存在真正 revise 节点。
- [ ] 作文 grade/review owner 与 teacher 权限生效，session_id 不再等于 student_id。
- [ ] 作文 draft/final score 不再是空壳状态，正文只存受控 artifact。
- [ ] 教师复核恢复同一作文 run。
- [ ] 辩论流式/非流式角色和 fact-check 一致。
- [ ] 学习助手现有 trajectory/groundedness 不回退。
- [ ] AutoTutor 两实例并发不重复判题。
- [ ] AutoTutor 数据库表由 Alembic/schema 管理，RLock 不再是唯一并发边界。
- [ ] AutoTutor 重启后当前题和 revision 不变化。
- [ ] 地图/推荐/游戏没有被无意义升级为开放式 Agent。
- [ ] 学习助手仍只有 `stream_learning_assistant_events()` 一条业务执行源。

### 20.5 可观测与生产

- [ ] runtime event coverage 达到灰度门槛。
- [ ] AgentOps 可按 agent/config/revision 查询。
- [ ] 无样本显示 unknown。
- [ ] duplicate side effect=0。
- [ ] invalid transition=0。
- [ ] checkpoint/recovery 指标可见。
- [ ] real LLM、blind、production RAG 与架构回归分层报告。
- [ ] release report commit/config 与部署一致。

### 20.6 回归

- [ ] fast gate 全绿，无新增阻断 skip。
- [ ] full core 全绿。
- [ ] frontend unit/build/E2E 全绿。
- [ ] SQLite 本地和 Postgres migration smoke 全绿。
- [ ] legacy/v2 parity 数据集达标。
- [ ] 10% canary 连续 48 小时无 P0。

---

## 21. 回滚方案

### 21.1 全局回滚

```dotenv
EDU_AGENT_RUNTIME_V2_KILL_SWITCH=true
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=0
```

效果：

- 新请求回到 legacy runtime；
- 已运行 v2 run 可继续只读查询或安全取消；
- 不删除 run/event/checkpoint 数据；
- 不回滚 Milestone 0 的 owner/teacher/verifier 安全修复，也不回滚现有 Tool/Evidence 安全合同。

### 21.2 单 Agent 回滚

将对应 `..._<AGENT>_BPS=0`：

- 学习助手回现有 sequential runtime；
- AutoTutor 回已经完成数据库 CAS/幂等修复的旧状态机，不允许回到仅靠 RLock 的版本；
- 历史人物/作文/辩论回 legacy endpoint；
- event dual-write 可继续用于排查，但不得执行第二份逻辑。

### 21.3 Checkpoint 回滚

- 关闭 `EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED` 后，新的 resumable 请求回 legacy/CAS 路径；observable/trace_only 可继续；
- active resumable run 不允许在无 checkpoint 下继续写操作；
- 可安全完成只读 finalization 或转 partial/cancelled；
- recovery worker 暂停后保留状态，待恢复服务。

### 21.4 数据库回滚

- 新表为 additive，不修改现有业务表主键；
- 应用回滚时旧版本忽略新表；
- 不在紧急回滚中删除 run/event/checkpoint；
- downgrade 仅在确认无 v2 active/waiting run 后执行；
- `autotutor_sessions` 至少保留两个发布周期。

### 21.5 动态能力回滚

```dotenv
EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED=false
EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED=false
```

立即回到静态图/确定性计划，不影响 durable runtime。

---

## 22. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 大规模重构引入行为回归 | 主路径不稳定 | adapter + parity + per-agent 分桶，不大爆炸替换 |
| 双写导致重复副作用 | 学习事件/会话重复 | shadow 不执行第二链；side-effect ledger + idempotency |
| checkpoint 增加 DB 压力 | 延迟上升 | 仅 resumable 业务边界写；token delta 不落库；索引和 retention |
| LangGraph 与自研 state 双真相 | 恢复错误 | EduAgent run revision 为唯一产品真相；adapter 对齐 |
| trace/event 含 PII | 合规风险 | public/internal 分层、引用而非原文、专项泄漏测试 |
| artifact 成为敏感数据池 | 作文/学生内容泄漏 | owner ACL、数据库/备份加密前置、最小访问、短 retention、越权测试 |
| 自动恢复重放写操作 | 重复操作 | ledger + 下游幂等 + CAS |
| dynamic re-plan 失控 | 成本/越权 | 默认关闭、最多一次、服务端校验、budget |
| 多 Agent 增加幻觉 | 错误互相放大 | fixed specialist、共享来源、公共 verifier |
| 简单能力 Agent 化 | 延迟和复杂度上升 | L0 FunctionAdapter，不添加循环 |
| 新旧 SSE 不兼容 | 前端错误 | envelope v2 + legacy event 兼容一个周期 |
| LangGraph 浮动版本破坏 checkpoint/interrupt | 恢复或流式行为变化 | 锁定验证范围；依赖升级单独跑 adapter contract |
| waiting run 堆积 | 存储/运维负担 | expires_at、recovery、取消、retention 指标 |
| release gate 只证明离线 | 假成熟 | blind/real LLM/prod canary 分层，不互相替代 |

---

## 23. 依赖与版本边界

### 23.1 可以立即实施

- 历史人物 verifier fail-closed；
- 历史/作文 owner 与 teacher-review 权限修复；
- 作文独立 session ID 和结构化评分合同；
- 公共合同；
- run/event/artifact/checkpoint 表；
- CAS/idempotency；
- adapter；
- stream parity；
- 作文真正 revise；
- 辩论单图；
- AgentOps runtime 指标。

这些属于架构正确性，不要求先开放语义路由或动态规划。

### 23.2 必须等待 v1.30/v1.31 证据

- 语义 Router 全量；
- 模型生成 dynamic re-plan；
- specialist subgraph 由模型选择；
- 并行只读 fan-out；
- agent-as-tool；
- production RAG 扩大流量。

前置证据：

- 中文 blind >=200 且 accuracy/macro-F1/high-risk 达标；
- 当前 run 有真实 LLM provider/model/calls；
- production RAG Recall/MRR/nDCG/latency 达标；
- 生产 trace/event coverage 和 canary 样本达标；
- release seal 对应 clean commit 和 config version。

### 23.3 不进入 v1.33

- 通用网页浏览 Agent；
- 学生上传任意文件后自动执行工具；
- 自动写 SQL/代码；
- 跨组织 Agent 市场；
- 无人工监督的教师批量写操作；
- 自主修改 prompt/工具/策略的 self-modifying Agent。

---

## 24. 最终成功定义

v1.33 架构升级完成后，EduAgent 应达到以下状态：

1. 所有有状态 Agent 共享统一 context、state、event 和 completion 语义；只有 resumable run 使用 checkpoint，L0 direct capability 保持 trace_only。
2. LangGraph 与自研 sequential plan 通过 adapter 接入；简单函数只在被编排调用时使用 FunctionAdapter，不向 API 泄漏框架差异。
3. 相同 run 的流式与非流式结果一致，不再维护两套业务执行链。
4. resumable run 在服务重启和 worker 切换后可恢复且不重复业务副作用；observable run 中断会明确失败并安全重试；SSE 重连可补里程碑和最终产物。
5. AutoTutor 在多实例下使用数据库 CAS 和幂等，保持教学状态正确。
6. 历史人物、辩论和历史回答统一 grounded completion，verifier 不再 fail-open。
7. 作文批改具备真正的 critic/revise/human-review 状态闭环。
8. 地图、推荐和游戏保持简单、确定性优先，不因架构统一变成不必要的自主 Agent。
9. 历史与作文入口具备与学习助手一致的 owner/role 安全边界，作文敏感内容只存在受控 artifact。
10. AgentOps 能回答“哪个 Agent、哪个 config、哪个 durability mode、哪个 step、为什么 partial/failed、是否恢复、是否重复副作用”。
11. 动态 re-plan、只读 fan-out 和 specialist 委派默认关闭，只能在真实证据和生产 canary 达标后逐步启用。

达到以上标准后，项目才从“多套可工作的垂直 Agent/工作流并存”升级为“统一、可持久化、可验证、可灰度的教育 Agent 平台”。
