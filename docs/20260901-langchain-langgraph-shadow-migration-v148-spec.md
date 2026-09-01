# EduAgent LangChain 契约收口与 AutoTutor LangGraph Shadow 迁移 v1.48 Spec

**状态：** In Progress · Shadow 基线已实现 · Active Cutover NOT_RUN
**日期：** 2026-09-01
**优先级：** P0 调用来源可信、Shadow 无副作用、轨迹一致性；P1 Demo 可解释性与迁移文档
**前置版本：** v1.47 可重复 Agent Demo 与作品集导航收敛
**后续候选：** v1.49 AutoTutor LangGraph Active Cutover；LangSmith 观测试点另立版本

---

## 0. 决策摘要

EduAgent 已经使用 LangChain 作为模型集成层，并在 History Character、Essay Grader、Debate Supervisor 中局部使用 LangGraph；但核心 AutoTutor、Learning Assistant、checkpoint/resume、业务副作用和评测仍由项目自有实现承担。

本迭代不执行“全生态一次性迁移”，而是完成第一个可验证迁移切片：

1. 收口 LangChain 结构化调用结果，明确真实模型、备用模型和确定性降级的来源；
2. 将 AutoTutor 编排抽出为可被 Legacy 与 LangGraph 共同调用的纯领域节点；
3. 新增 AutoTutor LangGraph Shadow 图，只做同请求轨迹对照，不承担 active 响应；
4. Shadow 复用 active 执行已捕获的模型、检索和时间结果，不重复调用外部依赖；
5. Shadow 禁止写数据库、学习事件、错题、复习、审计和副作用账本；
6. 将安全的决策来源投影到现有 Demo Journey 与教师会话证据；
7. LangSmith、Agent Server、LangGraph 生产 checkpointer 和 active 切流继续保持非目标。

版本主题：**先证明 LangGraph 可以无风险承接现有编排，再决定是否切换核心执行权。**

---

## 1. 当前基线

### 1.1 已使用的生态能力

- `langchain-core`：消息、Document 和基础协议；
- `langchain-openai`：通过 OpenAI-compatible transport 接入百炼；
- `langchain-text-splitters`：RAG 文档切分；
- `langgraph`：三个非核心 Agent 的 `StateGraph`；
- `ManagedChatModel`：项目自有 profile、retry、fallback、能力门禁和 tracing facade；
- `LangGraphAdapter`：将 graph updates 映射为项目自有 Runtime events。

当前约束版本：

```text
langchain-core==1.6.1
langchain-openai==1.6.0
langchain-text-splitters==1.1.2
langgraph==1.2.11
langsmith==0.11.2
```

`langsmith` 当前只有依赖约束，没有业务代码直接调用。

### 1.2 AutoTutor 当前合同

AutoTutor 目前在单一模块中承担：

- 会话状态和 PostgreSQL/SQLite 持久化；
- plan / retrieve / content gate / teach；
- 等待学生作答；
- judge / reflect / re-plan / reteach；
- exit ticket / mastery verification；
- 学习事件、错题、复习和教师效果回流；
- CAS revision、answer idempotency 和 side-effect ledger；
- Runtime v2 checkpoint 镜像；
- public state、Demo trace 和会话证据。

这些合同已有大量 eval 和 13 条 E2E 覆盖，不能在一次框架迁移中全部重写。

### 1.3 当前模型来源不可判定

AutoTutor Reflect 使用 `invoke_structured(llm_quality, ..., fallback=...)`。调用者只拿到最终 Pydantic 对象，无法区分：

- quality profile 主模型成功；
- ManagedChatModel 内部备用 profile 成功；
- JSON repair 后成功；
- 所有模型失败后返回确定性 fallback。

因此当前 Demo Journey 能证明“系统发生了 reflect”，但不能证明 reflect 的真实执行来源。

### 1.4 自研 Runtime 与 LangGraph 重叠

项目自研 Runtime 已覆盖：

- event store；
- checkpoint；
- waiting input / waiting confirmation；
- resume registry；
- recovery；
- streaming；
- completion；
- side-effect ledger；
- rollout status 和 readiness。

LangGraph 可以承接其中的编排、interrupt、checkpoint 和 resume，但不能替代业务权限、CAS、事务、副作用幂等和证据语义。

---

## 2. 目标与非目标

### 2.1 P0 目标

- 新增向后兼容的 LangChain 结构化调用 provenance 合同；
- AutoTutor Reflect 记录真实执行来源，不把 deterministic fallback 标记成 LLM 成功；
- 建立 AutoTutor LangGraph Shadow 图和稳定 state schema；
- Shadow 不重复调用 LLM、RAG、工具或外部服务；
- Shadow 不执行任何持久化和业务副作用；
- active Legacy 响应、状态和耗时不依赖 Shadow 成功；
- 定义稳定的 Legacy/Graph parity projection；
- 提供 mismatch reason codes 和本地聚合评测；
- 扩展现有 Demo trace/evidence allowlist，安全展示决策来源；
- 默认配置下 LangGraph Shadow 完全关闭。

### 2.2 P1 目标

- 将 AutoTutor 纯编排节点从持久化和 API 层解耦；
- 为未来 PostgreSQL checkpointer 和 `interrupt` cutover 保留接口；
- README 如实区分 LangChain、LangGraph、自研领域事务与 fallback；
- Release gate 注册 Shadow parity 和 provenance smoke；
- 在不增加真实模型 CI 成本的前提下支持手动 real-LLM provenance 验证。

### 2.3 非目标

- 不把 LangGraph Shadow 切为 active；
- 不删除 Legacy AutoTutor；
- 不替换 `autotutor_sessions` 或现有 session URL 合同；
- 不启用生产 LangGraph checkpointer；
- 不删除自研 Runtime v2、side-effect ledger 或 rollout 代码；
- 不使用 LangChain `create_agent` 重写 AutoTutor；
- 不迁移 Learning Assistant；
- 不迁移其他 Agent；
- 不接入 LangSmith Cloud、LangSmith Dataset 或 LangSmith Deployment；
- 不移除 Langfuse；
- 不新增 staging、canary、immutable image 或自动放量；
- 不要求默认 CI 具备真实 LLM Key；
- 不改变学生掌握、错题、复习和教师聚合算法。

---

## 3. 目标架构

```text
FastAPI request
      │
      ▼
Legacy AutoTutor active executor ───────────────► active response
      │
      ├── capture nondeterministic observations
      │     ├── model result + provenance
      │     ├── retrieval result fingerprint
      │     ├── generated assessment fingerprint
      │     └── stable clock/identifier inputs
      │
      └── if shadow enabled
              │
              ▼
       AutoTutor LangGraph Shadow
       pure orchestration + injected observations
              │
              ▼
       canonical parity projection
              │
              ├── match
              └── mismatch(reason_codes)

Business writes remain Legacy-only:
session CAS / learning events / weakpoints / review / audit / side effects
```

### 3.1 所有权边界

| 能力 | 本迭代所有者 |
|---|---|
| 模型协议、消息和 structured output | LangChain + `ManagedChatModel` |
| AutoTutor Shadow 编排 | LangGraph `StateGraph` |
| Active AutoTutor 编排 | Legacy AutoTutor |
| 会话持久化与 revision CAS | EduAgent domain service |
| 学习事件、掌握、错题、复习 | EduAgent domain service |
| 工具权限、确认、审计 | EduAgent Tool Registry |
| 公共 Demo trace/evidence | EduAgent allowlist projector |
| 确定性发布门禁 | EduAgent eval runner |
| 云端 trace/eval | 本迭代不接入 |

---

## 4. LangChain 结构化调用 Provenance 合同

### 4.1 新接口

保留当前 `invoke_structured(...) -> T`，新增：

```python
StructuredInvocationResult[T](
    value: T,
    provenance: StructuredInvocationProvenance,
)

invoke_structured_with_provenance(...) -> StructuredInvocationResult[T]
```

旧调用方行为不得变化。

### 4.2 内部 provenance schema

```python
class StructuredInvocationProvenance(BaseModel):
    decision_source: Literal[
        "langchain_primary",
        "langchain_fallback_profile",
        "deterministic_fallback",
    ]
    provider: str | None
    transport: str | None
    configured_profile: str | None
    executed_profile: str | None
    configured_model: str | None
    executed_model: str | None
    model_attempt: int | None
    structured_repair_used: bool
    fallback_used: bool
```

语义：

- `langchain_primary`：配置 profile 的第一模型成功；
- `langchain_fallback_profile`：ManagedChatModel 的备用 profile 成功，仍属于真实模型调用；
- `deterministic_fallback`：模型调用、解析或 repair 最终失败，返回调用方提供的本地 fallback；
- `fallback_used=true` 只表示没有采用主路径结果，不等价于“使用了真实备用模型”；
- `structured_repair_used=true` 表示通过 repair 得到合法结构化结果。

### 4.3 ManagedChatModel 响应元数据

`ManagedChatModel.invoke()` 在成功返回的 `AIMessage.response_metadata` 中增加项目保留字段：

```json
{
  "edu_agent_provenance": {
    "provider": "bailian",
    "transport": "bailian_openai",
    "configured_profile": "quality",
    "executed_profile": "quality",
    "configured_model": "...",
    "executed_model": "...",
    "model_attempt": 1
  }
}
```

不得依赖共享 `last_call`、线程局部全局变量或可被并发请求覆盖的可变状态。

### 4.4 公共 provenance allowlist

公共 API 只允许：

```json
{
  "decision_source": "langchain_primary",
  "provider": "bailian",
  "profile": "quality",
  "model": "qwen...",
  "fallback_used": false,
  "structured_repair_used": false
}
```

不得包含：

- Prompt 或模型原文；
- 学生答案和正确答案；
- API Key；
- Provider request ID；
- Token usage 明细；
- endpoint/base URL；
- Trace ID 或 Run ID；
- 异常正文；
- fallback chain 的其他内部模型配置。

---

## 5. AutoTutor 纯编排边界

### 5.1 新模块建议

```text
backend/agents/autotutor_domain.py
backend/agents/autotutor_graph.py
backend/agents/autotutor_shadow.py
backend/agents/autotutor_provenance.py
```

职责：

- `autotutor_domain.py`：纯状态转换和下一动作判定；
- `autotutor_graph.py`：StateGraph schema、nodes、edges 和 compile；
- `autotutor_shadow.py`：捕获输入、无副作用执行、parity compare；
- `autotutor_provenance.py`：内部和公共来源投影。

允许根据实现需要调整文件名，但必须保持职责分离。

### 5.2 纯函数要求

以下逻辑应可在不访问数据库和网络的情况下执行：

- 根据当前状态决定下一 node；
- judge 后选择 pass / reflect；
- reflect 后选择 reteach / lower difficulty / change example；
- re-plan 修改难度、策略和后续顺序；
- 判断是否进入 exit ticket；
- 根据 exit ticket result 计算完成状态和 evidence intent；
- 生成 canonical next action。

不得把以下逻辑移动进纯 domain 层：

- 数据库连接；
- Tool Registry 调用；
- LLM 调用；
- 当前时间和 UUID 生成；
- learning event 写入；
- weakpoint/review 写入；
- audit event；
- Runtime event store 写入。

### 5.3 注入观察值

所有非确定性结果用显式对象传入：

```python
class AutoTutorObservedInputs(BaseModel):
    retrieval: dict | None = None
    teaching_content: dict | None = None
    assessment: dict | None = None
    reflection: dict | None = None
    reflection_provenance: dict | None = None
    stable_now: float | None = None
```

Shadow 只能读取 active 捕获的观察值，不得自行补调用。

---

## 6. AutoTutor LangGraph Shadow

### 6.1 Graph nodes

第一版图至少包含：

```text
load_context
plan
retrieve
content_gate
teach
prepare_assessment
wait_answer
judge
reflect
re_plan
reteach
prepare_exit_ticket
verify_exit_ticket
build_evidence_intent
finalize
```

节点可按现有实际边界合并，但公开 parity phase 必须稳定。

### 6.2 状态 schema

Graph state 必须是 JSON 可序列化结构，并至少包含：

- schema_version；
- session_id；
- student_id；
- phase/status；
- current_step_index；
- lesson plan 的公共编排字段；
- attempts/replans；
- reflection adjustment；
- content gate status；
- assessment fingerprints；
- exit ticket status；
- verified mastery；
- evidence intents；
- next action；
- injected observations；
- shadow diagnostics。

不得在 Graph state 放置：

- 数据库连接或 session；
- FastAPI Actor；
- 原始 JWT；
- LLM client；
- 原始 Prompt；
- 未脱敏工具输入；
- 不可序列化对象。

### 6.3 Shadow 执行模式

默认配置：

```text
EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED=false
EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_CONFIG_VERSION=v1.48-shadow
```

本迭代不增加流量百分比、灰度矩阵或生产 rollout 依赖。

当 Shadow 开启：

1. active Legacy 正常执行；
2. 捕获 before/after 状态和非确定性观察值；
3. 使用深拷贝构造 Graph 输入；
4. Graph 以 shadow effect sink 执行；
5. 对 Legacy 与 Graph 做 canonical projection；
6. 记录 match/mismatch；
7. 无论 Shadow 成功、失败或超时，都不改变 active response。

### 6.4 无副作用合同

Shadow effect sink 对任何写操作直接抛出：

```text
shadow_side_effect_forbidden
```

必须阻止：

- session save/update；
- learning event；
- weakpoint/mastery；
- review memory；
- teacher effectiveness；
- audit；
- Runtime run/event/checkpoint；
- side-effect ledger；
- 真实 Tool Registry；
- 真实 LLM；
- 远程 tracing flush。

测试必须以调用计数和数据库快照同时证明没有副作用。

### 6.5 失败隔离

- Shadow exception 只记录安全 reason code；
- 不向学生返回 Shadow stack trace；
- 不把 Shadow mismatch 标记成课程失败；
- 不延迟 active 路径超过可配置的本地测试预算；
- 生产默认关闭时不得初始化额外 graph/checkpointer/cloud client。

---

## 7. Parity 合同

### 7.1 Canonical projection

Legacy 和 Graph 统一投影为：

```json
{
  "status": "awaiting_answer",
  "phase": "lesson",
  "current_step_index": 0,
  "replans": 1,
  "steps": [
    {
      "knowledge_point": "洋务运动目的",
      "difficulty": "easy",
      "status": "active",
      "attempts": 1,
      "replanned": true,
      "assessment_fingerprint": "..."
    }
  ],
  "reflection_adjustment": "reteach",
  "exit_ticket": {
    "prepared": false,
    "passed": null
  },
  "verified_mastery": false,
  "evidence_intents": [],
  "next_action": "wait_answer"
}
```

明确忽略：

- session/run/trace ID；
- timestamp；
- latency；
- sequence number；
- provider request ID；
- token usage；
- UI 文案；
- 顺序无关 metadata。

### 7.2 Mismatch reason codes

至少支持：

```text
status_mismatch
phase_mismatch
step_index_mismatch
plan_shape_mismatch
difficulty_mismatch
attempt_count_mismatch
reflection_action_mismatch
assessment_fingerprint_mismatch
exit_ticket_mismatch
verified_mastery_mismatch
evidence_intent_mismatch
next_action_mismatch
shadow_execution_failed
shadow_side_effect_forbidden
shadow_input_incomplete
```

报告不得包含完整学生状态或答案。

### 7.3 Parity 门槛

本迭代 Development Complete 要求：

- 确定性 AutoTutor 核心 trajectory cases 100% match；
- false mastery cases 100% match；
- content blocked cases 100% match；
- session recovery 后的下一 transition 100% match；
- 并发/重复 answer 仍由 active CAS 处理，Shadow 不产生额外写入；
- 真实 LLM case 可手动运行，但不作为默认 CI blocking 条件。

---

## 8. Demo Journey 与教师 Evidence

### 8.1 Demo trace 扩展

现有 event 增加可选字段：

```json
{
  "decision_source": "policy | tool | langchain_primary | langchain_fallback_profile | deterministic_fallback | evidence_store",
  "model": {
    "provider": "bailian",
    "profile": "quality",
    "name": "qwen...",
    "fallback_used": false
  }
}
```

非模型步骤的 `model` 必须为 `null` 或缺省。

### 8.2 UI 文案

对应显示：

| source | 用户文案 |
|---|---|
| policy | 受限策略执行 |
| tool | 工具检索与核验 |
| langchain_primary | 真实模型决策 |
| langchain_fallback_profile | 备用模型完成 |
| deterministic_fallback | 确定性安全降级 |
| evidence_store | 学习证据写入 |

不得把 `deterministic_fallback` 显示为“真实模型决策”。

### 8.3 教师证据扩展

会话级 evidence 增加：

```json
{
  "decision_provenance": {
    "llm_decision_attempted": true,
    "llm_decision_succeeded": false,
    "deterministic_fallback_used": true,
    "provider": null,
    "profile": null,
    "model": null
  }
}
```

教师授权继续使用现有班级/作业关系，不新增宽松读取路径。

---

## 9. LangSmith 边界

本迭代明确不接入 LangSmith，原因：

- 需要先稳定内部 provenance 和 graph state schema；
- 当前 Langfuse 与本地 trace_store 已承担观测；
- 默认自动 trace 可能上传 Prompt、答案和学生上下文；
- 自研 eval 中大部分是确定性工程合同，不应迁移到云端 Dataset；
- 个人 Demo 不需要 Agent Server 或 LangSmith Deployment。

本迭代只保证未来可接入：

- Graph nodes 使用稳定名称；
- state 与公共 trace 分离；
- provenance 不依赖 Langfuse 特有对象；
- tracing 调用继续经过项目 facade，而非业务代码直接调用 SDK。

未来 LangSmith 试点必须另写 Spec，且默认只允许 Pilot 数据、关闭原始 Prompt/答案采集、设置短 retention，并与 Langfuse 二选一。

---

## 10. API 与兼容性

### 10.1 不新增业务 API

本迭代复用：

- `POST /api/autotutor/start`；
- `POST /api/autotutor/answer`；
- `GET /api/autotutor/session/{session_id}`；
- `GET /api/autotutor/session/{session_id}/demo-trace`；
- `GET /api/autotutor/session/{session_id}/evidence`。

只允许向 trace/evidence 添加向后兼容的可选字段。

### 10.2 状态兼容

- 不修改现有 session ID；
- 不要求数据库 migration；
- 不改变 public state 必填字段；
- 不使旧 completed session 无法恢复；
- 不要求前端理解 Graph 内部 node 名称；
- Shadow schema version 与 active session schema 独立。

---

## 11. 实现里程碑

### Milestone A：Provenance 基线

- 给 `ManagedChatModel` 返回值附加并发安全的实际 profile/model 元数据；
- 新增 `invoke_structured_with_provenance`；
- 覆盖 primary、fallback profile、repair 和 deterministic fallback；
- AutoTutor Reflect 写入内部 provenance；
- 旧调用方回归通过。

### Milestone B：纯领域节点

- 抽出下一动作、judge、re-plan、exit ticket 和 evidence intent 纯逻辑；
- Legacy path 改为复用纯逻辑；
- 对现有结果做 characterization tests；
- 不改变持久化和 API。

### Milestone C：LangGraph Shadow

- 定义 state schema 和 graph；
- 注入 active observations；
- 接入 no-op/deny effect sink；
- 运行 parity projection；
- mismatch 不影响 active。

### Milestone D：可解释 Demo

- 扩展 Demo trace allowlist；
- 扩展教师 evidence allowlist；
- UI 展示真实模型、备用模型和确定性降级；
- E2E 验证 deterministic CI 不被误标成真实模型。

### Milestone E：门禁与文档

- 注册 provenance 和 shadow suites；
- 更新 README 架构说明；
- 完整 unit/lint/build/E2E/release gate；
- 明确 Active Cutover 仍为 NOT_RUN。

---

## 12. 测试计划

### 12.1 LangChain provenance

- primary profile 成功；
- primary 超时、fallback profile 成功；
- primary 空响应、fallback profile 成功；
- 首次 JSON 失败、repair 成功；
- 全部模型失败、deterministic fallback；
- 并发调用不会串 profile/model 元数据；
- 旧 `invoke_structured` 返回值保持兼容；
- 日志和公共 payload 不含 secret/request ID。

### 12.2 Domain characterization

- 首次出题；
- 正确进入下一步；
- 错误触发 reflect/re-plan；
- 降难度；
- 换例子；
- 达到最大尝试；
- content blocked；
- exit ticket pass/fail；
- verified mastery 只来自独立 exit ticket。

### 12.3 Shadow parity

- 全部 `auto_tutor_trajectory_eval`；
- false mastery；
- content blocked；
- session recovery；
- stale answer；
- answer idempotent replay；
- Graph exception 不改变 active response；
- Shadow effect sink 拒绝写入；
- active 前后数据库行数和学习事件数量与 Shadow 关闭时一致。

### 12.4 API/授权

- Demo trace 只有 owner demo student/admin 可读；
- Evidence owner student、授权教师和 admin 可读；
- 其他学生/教师继续 403；
- provenance allowlist 不泄露答案、Prompt、token、request ID；
- 旧客户端忽略新增字段后正常工作。

### 12.5 前端

- 每类 decision source 文案映射；
- deterministic fallback 不显示“真实模型”；
- 无 provenance 的旧 session 显示“来源未记录”；
- Teacher evidence 显示模型参与和降级状态；
- Demo Journey 既有事件顺序不变。

### 12.6 发布前命令

```bash
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py \
  --suite llm_provider_contract_smoke \
  --suite autotutor_langchain_provenance_smoke \
  --suite autotutor_langgraph_shadow_parity_smoke \
  --suite auto_tutor_trajectory_eval \
  --suite autotutor_false_mastery_smoke \
  --suite autotutor_content_blocked_api_smoke \
  --suite autotutor_session_recovery_smoke \
  --no-report

npm run test:unit --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
npm run release:gate:fast
```

Suite 名称以实现时最终注册名为准，但测试语义不得减少。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Shadow 重复调用 LLM | 成本和结果漂移 | 只注入 active observation，测试调用计数为零 |
| Shadow 重复写业务数据 | 污染学习证据 | deny effect sink + 数据库快照测试 |
| 抽纯函数改变 Legacy 行为 | Demo 回归 | characterization tests 先行，Legacy 始终 active |
| Graph state 携带敏感字段 | Trace 泄露 | 内部 state 与 public projector 分离 |
| fallback 被标成真实模型 | 作品集可信度受损 | 三态 provenance，不使用单一 `fallback_used` 推断 |
| 并发请求串模型元数据 | 错误证据 | 元数据绑定 AIMessage，不使用共享 last-call 状态 |
| Shadow 延迟 active | 交互变慢 | 默认关闭、失败隔离、不得进入 active 返回依赖 |
| 双 Runtime 长期并存 | 复杂度进一步上升 | v1.49 cutover 必须决定继续或删除 Shadow，不无限双写 |
| 为迁移引入生产平台 | 运维重新膨胀 | LangSmith Deployment/Agent Server 明确非目标 |

---

## 14. 回滚策略

- 设置 `EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED=false` 即关闭 Graph；
- Shadow 无数据库 schema 和业务写入，关闭后无数据回滚；
- 公共 provenance 字段为可选字段，可独立停止投影；
- Legacy AutoTutor 始终保留且是唯一 active；
- 新 structured provenance 接口与旧 `invoke_structured` 并存；
- 如果纯领域抽取造成问题，可回退调用位置，不需要迁移 session 数据。

---

## 15. 完成定义

Development Complete 必须全部满足：

- [x] `invoke_structured_with_provenance` 可区分主模型、备用模型和确定性 fallback；
- [x] provenance 绑定单次响应且并发安全；
- [x] Legacy structured output 调用行为保持兼容；
- [x] AutoTutor 核心编排存在可测试的纯领域边界；
- [x] AutoTutor LangGraph Shadow 图可执行；
- [ ] Shadow 不调用真实 LLM、工具或网络；
- [ ] Shadow 不写 session、学习事件、错题、复习、审计或 Runtime 表；
- [x] Shadow 失败不改变 active response；
- [ ] 确定性核心 trajectory parity 100%；
- [ ] false mastery、content blocked 和 recovery parity 100%；
- [x] mismatch 只输出安全 reason codes；
- [x] Demo trace 正确区分真实模型和确定性降级；
- [x] Teacher evidence 显示会话级模型参与状态；
- [x] 公共 payload 无 Prompt、答案、token、request ID 或 secret；
- [x] 默认 Shadow 配置关闭；
- [x] 无数据库 migration；
- [x] frontend unit、lint、build 通过；
- [x] 完整 E2E 通过；
- [x] fast release gate 通过。

本版本不得标记 LangGraph Active Migration Complete。只有 Shadow parity 稳定后，才能单独提出 v1.49 Active Cutover Spec。

---

## 16. v1.49 进入条件

只有同时满足以下条件，才评估 active cutover：

- 本地和 CI 确定性 parity 连续稳定；
- Shadow 未发现副作用；
- Graph state schema 已版本化；
- session recovery 和 idempotent replay 通过；
- public trace/evidence 不依赖 Legacy 内部对象；
- 已定义 PostgreSQL checkpointer 迁移与清理策略；
- 已定义 in-flight Legacy session 的兼容策略；
- 已测量 Graph checkpoint 写放大和延迟；
- 明确哪些自研 Runtime 模块可以删除，而不是再增加一层永久 adapter。

v1.49 才允许讨论：

- Graph active；
- `interrupt` 接管答题暂停；
- PostgreSQL checkpointer；
- Legacy/Graph session 路由；
- 删除重复 checkpoint/resume 代码。

LangSmith 观测试点继续单独决策，不作为 LangGraph active 的前置条件。
