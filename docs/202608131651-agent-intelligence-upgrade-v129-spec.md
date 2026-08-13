# EduAgent 智能体升级 v1.29 迭代 Spec

**创建时间：** 2026-08-13 16:51
**状态：** Implemented / 待最终发布盖章
**目标版本：** v1.29.0（语义路由基线）+ v1.29.1（受限组合任务）
**优先级：** P0
**适用范围：** `随问 · 学习助手`、Agent Eval、AgentOps；复用现有 Tool Registry、会话、RAG、SSE、权限与确认治理
**关联文档：**

- `docs/20260813-learning-assistant-free-question-spec.md`
- `docs/20260813-learning-assistant-conversation-first-ux-spec.md`
- `docs/202606291030-autotutor-autonomous-loop-dev.md`
- `docs/20260709-ai-agent-engineering-direction-confirmation.md`

---

## 0. 实施结果（2026-08-13）

v1.29.0 / v1.29.1 已按本 Spec 完成代码、评测、前端和门禁落地，默认仍使用安全 feature flag 灰度：

- 结构化混合路由、槽位、澄清、30 分钟待补状态和规则 fallback 已实现；
- 最多 3 步确定性计划、operation allowlist、依赖校验、fail-fast、一次只读 repair、证据验证和 completion status 已实现；
- SSE、会话 metadata、计划进度 UI、partial / clarification 状态和 Eval / AgentOps 看板已同步；
- 离线路由集 `300/300`，accuracy / macro-F1 / slot / clarification / multi-intent / high-risk recall 均为 `1.0`；
- 工具 selection / input / output utilization、组合计划 completion、repair / rollback 均为 `1.0`；
- fast release gate `16/16 suites、367/367 cases`，完整 CORE `31/31 suites、453/453 cases`；
- 前端 unit `11/11`、production build PASS、Playwright 关键 E2E `7/7`（含真实三步“解释后出题”界面链路）；
- 最新离线报告明确标记 `LLM execution: not_observed`，不把 deterministic fallback 等同于真实模型质量；真实模型发布盖章仍需用 `--require-real-llm` 在有凭证环境运行。

---

## 1. 决策摘要

当前 EduAgent 已具备较完整的垂直 Agent 工程能力：AutoTutor 有规划、教学、判定、反思、重规划和退出票闭环；学习助手具备多轮会话、RAG、工具调用、权限确认、Trace 和反馈；Tool Registry、MCP、Eval、AgentOps 均已有实现。

本轮不继续增加新页面或新业务入口，而是解决当前限制 Agent 智能上限的三个问题：

1. **开放式理解依赖关键词。** `learning_assistant.detect_learning_intent()` 仍是顺序匹配规则，同义改写、隐式表达和组合请求容易误判。
2. **一次请求只能选择一个 intent 和一个工具。** 当前 `build_tool_call()` 返回单个 `(tool_name, payload)`，不能稳定完成“先解释，再出题”这类组合目标。
3. **质量报告与发布门禁不能完整代表当前智能水平。** 最新完整报告早于本轮学习助手改动；快速 gate 未包含意图准确率，且离线 fallback 通过不能等同于真实模型质量通过。

v1.29 采用渐进式方案：

```text
用户请求
  → 安全与高风险规则预检
  → 混合语义路由（明确规则直达 / 歧义请求结构化分类）
  → 槽位完整性与澄清判断
  → 确定性计划构建（最多 3 步，只能使用允许的能力）
  → 复用 Tool Registry 顺序执行
  → 证据检查与答案合成
  → Trace / Eval / Feedback
```

核心原则：

- 不让 LLM 绕过 Tool Registry、角色权限、确认和审计。
- 不让 LLM 自由生成任意工具名；工具必须来自服务端允许列表。
- 低置信度或缺关键参数时优先澄清，不错误执行。
- v1.29.0 先保证单任务路由正确；v1.29.1 再开启最多 3 步的组合任务。
- AutoTutor 保持独立教学状态机；随问不得修改其 `revision`、`attempts`、当前题目或掌握度。

---

## 2. 当前基线与问题证据

### 2.1 本轮实测基线

| 能力 | 当前结果 | 判断 |
| --- | ---: | --- |
| 学习助手意图准确率 | `14/18 = 77.8%` | 低于现有评测的 `80%` 门槛 |
| 学习助手工具轨迹 | `5/5` | 已覆盖工具选择、参数和结果利用，但均为明确表达 |
| 学习助手多轮会话 | PASS | 会话、代词追问、反馈、隔离等契约稳定 |
| AutoTutor 轨迹 | `11/11` | 规划、答错反思、重规划、难度下降、退出票闭环稳定 |
| AutoTutor 离线教学质量 | `5/5` | 证明 fallback 可用，不等同于真实 LLM 教学质量 |
| 快速发布 gate | `46/46` | 主路径稳定，但未覆盖意图准确率 |

当前 4 个意图误判样本：

| 输入 | 期望 | 当前结果 | 根因 |
| --- | --- | --- | --- |
| 出几道关于鸦片战争的选择题 | `quiz_generation` | `history_search` | “选择题”未进入出题关键词，后续“战争”先命中历史检索 |
| 我最近错了很多题，帮我安排复习 | `review_plan` | `chat` | 只识别固定短语，不理解“安排复习” |
| 五四运动是怎么发生的 | `history_search` | `chat` | 没有命中有限历史关键词 |
| 这节课讲了什么？ | `textbook_qa` 或澄清 | `chat` | 没有显式 `book_id + lesson_id` 时无法理解指代 |

### 2.2 现有架构优势

本轮必须复用而不是重建：

- `backend/tools/registry.py`：schema 校验、角色策略、风险等级、确认 token、审计、超时和 Trace。
- `backend/services/learning_assistant_session_service.py`：持久化会话、最近 12 条消息、会话所有权和上下文。
- `backend/agents/learning_assistant.py`：SSE runtime step、RAG、模板/fallback、画像建议和 learning event。
- `backend/agents/auto_tutor.py`：独立的教学规划、反思、重规划、退出票和学习证据闭环。
- `backend/tracing.py`、`backend/trace_store.py`、`backend/agent_ops.py`：运行轨迹和聚合指标。
- `eval/run_core_evals.py`、`scripts/release_gate.py`：统一评测和发布闸门。

### 2.3 当前智能边界

当前学习助手主链路本质为：

```text
关键词分类 → 单个工具映射 → 执行一次 → 按 intent 模板合成
```

它适合稳定演示和明确命令，但不适合：

- 同义表达和口语表达；
- 多轮中的“它、刚才、这一课”与话题切换并存；
- “解释 + 比较 + 出题”组合目标；
- 关键参数不完整时的主动澄清；
- 工具失败后的受控修复；
- 以任务完成标准而不是“函数执行完成”判断成功。

---

## 3. 迭代目标

### 3.1 产品目标

1. 学生可以使用自然、口语化表达，不需要记住固定关键词。
2. 系统能识别“先做 A，再做 B”的学习请求，并展示可理解的执行进度。
3. 缺少教材、主题或题型等关键条件时，助手会提出一个最小必要问题。
4. 工具调用、安全、AutoTutor 状态中立性和对话优先体验保持不变。
5. 评测和发布门禁能真实暴露意图、工具、组合任务和真实模型质量状态。

### 3.2 工程目标

- 将路由结果改为 Pydantic 结构化契约。
- 将“意图识别”“计划构建”“执行”“答案合成”拆分为可单测组件。
- 所有执行步骤继续走 `run_tool()` 或受控的 generation operation。
- 每个路由、计划和执行步骤都写入 trace，并能被 AgentOps 聚合。
- 新能力可通过 feature flag 灰度，关闭后回到 v1.28 单任务路径。

### 3.3 非目标

- 不重写 AutoTutor，不把 AutoTutor 改成开放聊天 Agent。
- 不引入通用多 Agent runtime、并行 fan-out 或动态子 Agent 委派。
- 不允许模型自由创建工具、Python 代码、SQL 或外部请求。
- 不在本轮增加网页搜索、文件上传、图片问答或其他学科。
- 不在本轮默认把所有对话写入长期 memory。
- 不在 v1.29 新增数据库表或 Alembic migration。
- 不用 LLM-as-judge 替代所有确定性断言；规则能判断的继续使用规则。

---

## 4. 用户故事

### 4.1 同义表达

作为学生，我可以说：

- “我最近错得有点多，帮我排一下接下来怎么复习。”
- “五四运动到底是怎么起来的？”
- “针对鸦片战争给我来三道选择题。”

系统应识别真实目标，而不是要求我改成预设关键词。

### 4.2 缺少上下文时澄清

作为从普通入口进入的学生，我问“这节课讲了什么”，系统没有可靠课程上下文时，应询问：

> 你指的是哪一本教材、哪一课？也可以直接告诉我课名。

系统不能静默猜测具体课文，也不能只返回能力介绍。

### 4.3 组合任务

作为学生，我可以说：

> 先用简单的话解释洋务运动，再给我出 3 道选择题。

系统应：

1. 检索洋务运动史料；
2. 基于同一批可信来源生成解释；
3. 基于同一主题生成 3 道选择题；
4. 回答中保留来源和练习入口；
5. 任一步失败时说明失败位置，不伪装成完整成功。

### 4.4 多轮指代和话题切换

已讨论“鸦片战争”后，学生问“它有什么影响”，应继承主题；随后问“那辛亥革命呢”，应识别为新主题，不能永久绑定旧上下文。

### 4.5 高风险工具

如果组合任务包含高风险操作，系统执行到该步骤时必须暂停并展示现有确认 UI。取消后不得继续执行该高风险步骤；已完成的只读步骤可以保留在回答依据中。

---

## 5. 目标架构

### 5.1 总体流程

```text
Receive Query
  ↓
Guardrail / Injection Check
  ↓
Load Trusted Context
  ↓
Hybrid Semantic Router
  ├─ blocked              → 安全拒绝
  ├─ needs_clarification  → 澄清问题
  └─ routed tasks         → Plan Builder
                              ↓
                         Policy Validation
                              ↓
                         Sequential Executor
                              ↓
                         Evidence Verifier
                              ↓
                         Answer Synthesis
                              ↓
                         Feedback / Memory / Trace
```

### 5.2 模块边界

建议新增：

```text
backend/agents/learning_assistant_router.py
backend/agents/learning_assistant_planner.py
backend/agents/learning_assistant_runtime.py
```

职责：

| 模块 | 职责 | 不负责 |
| --- | --- | --- |
| `learning_assistant_router.py` | 安全规则后的语义分类、槽位提取、置信度和澄清 | 不执行工具 |
| `learning_assistant_planner.py` | 把受支持的任务转成最多 3 步确定性计划 | 不调用任意模型工具 |
| `learning_assistant_runtime.py` | 逐步执行、暂停确认、收集证据、失败收敛 | 不绕过 Tool Registry |
| `learning_assistant.py` | SSE 编排、答案合成、建议、画像和 learning event | 不继续承载大段路由规则 |

为降低首轮改动风险，v1.29.0 可以先只新增 router，将 planner/runtime 留在原文件；v1.29.1 再完成文件拆分。最终必须避免 `learning_assistant.py` 继续成为所有职责的单文件入口。

---

## 6. 语义路由设计

### 6.1 路由契约

```python
class IntentName(str, Enum):
    textbook_qa = "textbook_qa"
    quiz_generation = "quiz_generation"
    character_recommendation = "character_recommendation"
    timeline_game = "timeline_game"
    history_search = "history_search"
    review_plan = "review_plan"
    memory_delete_demo = "memory_delete_demo"
    chat = "chat"


class RoutedTask(BaseModel):
    task_id: str
    intent: IntentName
    topic: str | None = None
    count: int | None = Field(default=None, ge=1, le=10)
    question_type: Literal["choice", "short_answer", "mixed"] | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    schema_version: Literal[2] = 2
    mode: Literal["rule", "semantic", "fallback", "clarification"]
    tasks: list[RoutedTask] = Field(max_length=3)
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = None
    reason_code: str
```

约束：

- `tasks` 最多 3 个；v1.29.0 即使识别多个任务也只执行第一个，并通过 trace 记录 `multi_intent_deferred`。
- `memory_delete_demo` 不允许与其他任务组合。
- `timeline_game` 创建操作必须是计划最后一步。
- `book_id`、`lesson_id` 必须来自后端可信会话或经服务端教材目录校验。
- `confidence` 仅用于策略判断，不能当成真实概率展示给学生。

### 6.2 混合路由策略

#### 第一层：确定性安全与显式命令

继续用规则处理：

- prompt injection / 越权请求；
- 高风险工具演示命令；
- 已确认工具的恢复执行；
- 服务端可信教材上下文和 AutoTutor handoff 约束。

这些规则不能交给模型覆盖。

#### 第二层：明确低歧义请求直达

只保留可证明低歧义的直达规则，例如：

- “开始时间线游戏”；
- “推荐三个历史人物”；
- “删除演示记忆”且命中 demo 范围。

规则不再使用“为什么、影响、战争”这种高召回低精度词直接决定最终 intent，而只生成候选意图。

#### 第三层：结构化语义路由

以下情况调用 `llm_fast` 的结构化输出：

- 没有高置信规则结果；
- 两个候选意图分数接近；
- 包含“先、再、然后、并且、顺便”等组合任务信号；
- 包含“它、这个、刚才、这节课”等指代，且上下文不足以确定；
- 需要抽取数量、题型、主题或比较对象。

路由 prompt 只传入：

- 当前问题；
- 最近 6 条对话的截断摘要；
- 服务端可信课程上下文；
- 允许的 intent 及简短定义；
- 可用工具名称和用途摘要，不传高风险内部参数。

模型输出必须通过 Pydantic；解析失败、超时或空响应时进入确定性 fallback。

### 6.3 澄清策略

满足任一条件时 `needs_clarification=true`：

- `textbook_qa` 使用“这节课/这一课”但没有可信教材上下文或可从历史唯一解析的课名；
- 比较任务缺少第二个对象；
- 请求出题但无法确定主题，且会话内也没有当前主题；
- 路由置信度 `< 0.65`；
- 前两名候选 intent 差值 `< 0.12` 且会导致不同工具或副作用；
- 用户要求执行不在允许能力中的操作。

澄清要求：

- 每次只问一个最小必要问题；
- 不调用业务工具；
- 允许直接回答“我指的是洋务运动”，下一轮继承待补槽位；
- 澄清状态保存在 assistant message 的 `metadata_json.routing` 中，不新增表；
- 澄清不计为工具失败，也不计入 fallback。

### 6.4 Fallback

当语义路由模型不可用时：

1. 使用扩展后的确定性候选打分；
2. 只有分数和间隔达到阈值才执行；
3. 否则返回澄清；
4. 禁止为了维持“成功率”把所有未知请求归为 `chat`。

---

## 7. 受限任务规划与执行

### 7.1 启用范围

- v1.29.0：只执行单任务；完成语义路由、槽位和澄清。
- v1.29.1：通过 `EDU_AGENT_ASSISTANT_PLANNER_ENABLED=true` 启用最多 3 步组合任务。
- 未开启 flag 时，API 和前端保持 v1.28 行为，不返回多步计划。

### 7.2 计划契约

```python
class PlanStep(BaseModel):
    step_id: str
    title: str
    kind: Literal["tool", "generation"]
    operation: str
    input: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    status: Literal["pending", "running", "waiting_confirmation", "completed", "failed"] = "pending"


class TaskPlan(BaseModel):
    schema_version: Literal[1] = 1
    objective: str
    steps: list[PlanStep] = Field(min_length=1, max_length=3)
    max_tool_calls: int = Field(default=3, ge=1, le=3)
```

### 7.3 计划生成原则

第一版使用**确定性计划模板**，不让模型自由规划工具：

| 任务 | 计划模板 |
| --- | --- |
| 历史解释 | `search_history_knowledge → answer_from_sources` |
| 教材问答 | `get_textbook_lesson → answer_from_lesson` |
| 基于主题出题 | `search_history_knowledge → quiz_from_sources` |
| 基于教材出题 | `generate_quiz` |
| 解释后出题 | `search_history_knowledge → answer_from_sources → quiz_from_sources` |
| 复习计划后出题 | `suggest_review_plan → quiz_from_selected_topic`，缺主题时澄清或从明确薄弱点选择 |
| 人物推荐 | `recommend_character` |
| 时间线游戏 | `start_timeline_game` |

`answer_from_sources`、`answer_from_lesson`、`quiz_from_sources` 属于受控 generation operation，不进入 Tool Registry，但必须：

- 有固定 operation allowlist；
- 输入只能来自已验证的工具结果和可信上下文；
- 使用结构化输出；
- 写 generation trace、模型、fallback、耗时和成本；
- 失败时不能伪造已生成题目。

后续版本可把稳定的 generation operation 提升为正式工具，但 v1.29 不为追求“工具数量”强行改变业务边界。

### 7.4 执行器

执行器按拓扑顺序串行执行：

1. 校验 `steps <= 3`、`max_tool_calls <= 3`；
2. 校验 operation 在 allowlist；
3. 工具步骤调用现有 `run_tool()`；
4. generation 步骤只读取声明的依赖输出；
5. 每步完成后执行 success criteria；
6. 任一步失败默认停止后续依赖步骤；
7. 独立步骤仅在不会造成误导时允许继续；v1.29 默认 fail-fast；
8. 总执行时间上限 45 秒，单工具继续使用现有超时；
9. 不做无限循环、不做自动重试风暴。

### 7.5 工具失败修复

v1.29 仅允许一次受控修复：

- schema/参数错误：根据 Pydantic 错误补齐可从可信上下文获得的字段；无法补齐则澄清；
- 检索为空：使用一次 query rewrite 后重试；
- 外部超时：不自动重复有副作用工具；只读工具最多重试一次；
- 权限拒绝：立即停止，不转换为其他工具绕过；
- confirmation required：进入等待确认，不算失败重试。

每次 repair 必须产生 `repair_attempt` trace，记录原因和变更字段，不记录敏感原值。

### 7.6 高风险确认

复用当前 `confirmed_tool_name / confirmation_token / confirmation_decision` 契约。

组合任务遇到 confirmation：

- 当前计划状态为 `waiting_confirmation`；
- SSE 返回现有 `tool_result` 和新增 `plan_step` 状态；
- 用户确认后只恢复该待执行工具，不能重新执行之前已完成的步骤；
- 用户取消后计划标记 `cancelled_by_user`，不执行后续依赖步骤；
- v1.29 不支持一个计划中包含两个高风险工具。

如果现有无状态请求无法安全恢复组合计划，则 v1.29.1 首版限制高风险工具只能单任务执行；不得通过重新跑完整请求模拟恢复。

---

## 8. 答案合成与证据验证

### 8.1 合成输入

答案合成只能读取：

- 当前用户问题；
- 服务端可信课程上下文；
- 最近会话摘要；
- 已完成步骤的压缩结果；
- 使用过的 typed memory 摘要；
- 允许公开的来源字段。

工具原始大对象不能无上限进入 prompt。每个步骤结果最多保留：

- 4 条来源；
- 每条来源正文 500 字；
- 教材最多 5 个知识点；
- 学生画像只保留完成任务所需字段。

### 8.2 完成状态

最终响应新增：

```json
{
  "completion_status": "completed",
  "completed_steps": 3,
  "total_steps": 3,
  "partial_reason": null
}
```

取值：

- `completed`：所有必要步骤通过；
- `partial`：部分独立结果可用，但至少一个目标未完成；
- `needs_clarification`：未执行任务，等待补充；
- `waiting_confirmation`：等待高风险确认；
- `failed`：没有可安全交付的结果。

禁止出现“工具失败但回答文案声称已完成”的情况。

### 8.3 最小证据检查

| 任务 | 必须满足 |
| --- | --- |
| 历史事实回答 | 至少 1 条可公开来源，或明确标记为普通解释且不声称教材依据 |
| 教材问答 | lesson 存在且回答使用 lesson 内容 |
| 出题 | 题目数符合请求或明确说明实际数量；每题有题干和答案 |
| 复习计划 | 至少 1 条基于画像/薄弱点的动作；无画像时明确冷启动 |
| 工具操作 | ToolResult `ok=true`；等待确认不能算完成 |

---

## 9. API 与 SSE 契约

### 9.1 请求兼容

`POST /api/learning/assistant/chat` 请求字段保持不变。v1.29 不要求前端新增必填参数。

服务端内部继续忽略不可信客户端课程正文，只使用：

- 已校验的 `session_id` 所属关系；
- session 中持久化的教材上下文；
- AutoTutor 后端加载的可信 handoff；
- 经教材 loader 校验的 `book_id / lesson_id`。

### 9.2 新增 SSE 事件

保留现有 `runtime_step`、`intent`、`tool_start`、`tool_result`、`suggestions`、`final`。新增：

#### `route`

```json
{
  "schema_version": 2,
  "mode": "semantic",
  "tasks": [
    {"task_id": "task_1", "intent": "history_search", "topic": "洋务运动"},
    {"task_id": "task_2", "intent": "quiz_generation", "topic": "洋务运动", "count": 3, "question_type": "choice", "depends_on": ["task_1"]}
  ],
  "confidence": 0.91,
  "needs_clarification": false,
  "reason_code": "multi_intent_explain_then_quiz"
}
```

#### `plan`

```json
{
  "objective": "解释洋务运动并生成 3 道选择题",
  "steps": [
    {"step_id": "step_1", "title": "查找史料", "status": "pending"},
    {"step_id": "step_2", "title": "生成简明解释", "status": "pending"},
    {"step_id": "step_3", "title": "生成 3 道选择题", "status": "pending"}
  ]
}
```

#### `plan_step`

```json
{
  "step_id": "step_1",
  "sequence": 1,
  "status": "completed",
  "result_summary": "检索到 4 条相关史料",
  "latency_ms": 126.4
}
```

#### `clarification`

```json
{
  "question": "你指的是哪一本教材、哪一课？也可以直接告诉我课名。",
  "missing_slots": ["book_id", "lesson_id"],
  "reason_code": "missing_textbook_context"
}
```

### 9.3 `intent` 兼容策略

- v1.29 继续发送 `intent`，其 `intent` 字段等于第一主任务，兼容现有前端和持久化字段。
- 完整多任务信息放入新增 `route` 事件和最终 `routing` 字段。
- `assistant_messages.intent` 暂存主 intent；完整路由、计划和完成状态写入已有 `metadata_json`。
- 不在本轮把数据库 `intent` 列改为 JSON。

### 9.4 final 扩展

```json
{
  "response": "...",
  "intent": "history_search",
  "routing": {"schema_version": 2, "mode": "semantic", "task_count": 2},
  "plan_summary": {"completed_steps": 3, "total_steps": 3},
  "completion_status": "completed",
  "tool_results": [],
  "sources": [],
  "generation_mode": "llm"
}
```

所有新增字段均为可选，保证旧前端可继续消费。

---

## 10. 前端交互

### 10.1 默认学生界面

保持“对话优先”设计，不重新引入常驻 Agent 控制台。

新增行为：

- `clarification`：以普通助手消息展示，可直接在输入框回答；
- 组合任务执行中：在当前回答下展示一行轻量进度，如“正在查找史料 · 1/3”；
- 完成后：默认只展示答案、练习和来源；完整计划放在“查看回答依据”折叠区；
- `partial`：明确展示“已完成解释，练习题生成失败”，提供“只重试未完成步骤”；首版若后端不支持安全恢复，则按钮改为预填自然语言重试；
- `waiting_confirmation`：复用现有 ToolConfirmationDialog。

### 10.2 开发调试模式

Trace / RAG / Tools / Memory 面板增加：

- routing mode；
- 主 intent 与子任务；
- confidence（仅调试展示）；
- clarification reason；
- 计划步骤和依赖；
- repair attempt；
- completion status。

### 10.3 可访问性

- 计划进度使用 `aria-live="polite"`，避免每个 token 重复播报；
- 失败和等待确认不能只用颜色表达；
- 澄清问题必须是可复制的文本；
- 移动端不新增占据首屏的固定面板。

---

## 11. 上下文与记忆策略

### 11.1 本轮上下文预算

会话仍持久化最近 12 条消息；路由和生成使用不同视图：

- 路由：最近 6 条、每条最多 200 字；
- 答案合成：最近 8 条、每条最多 400 字；
- 工具 query：当前主题 + 最近一个相关用户问题 + 当前问题，总长最多 500 字；
- 可信课程上下文优先于历史推断；
- 当前问题明确提出新主题时，不继承旧主题作为硬约束。

### 11.2 待补槽位

澄清产生的待补槽位写入上一条 assistant message 的 `metadata_json`：

```json
{
  "routing": {
    "completion_status": "needs_clarification",
    "pending_task": {"intent": "textbook_qa"},
    "missing_slots": ["lesson_id"]
  }
}
```

下一轮仅在：

- 该消息是最近一条 assistant 消息；
- 用户回答时间未超过 30 分钟；
- 用户没有明确开启新主题；

时尝试补齐。无法安全判断时重新路由。

### 11.3 长期记忆

本轮保持现有 typed memory 读取与建议个性化，不新增自动写入规则。路由不得因为兴趣记忆把当前明确问题改成其他主题。

---

## 12. Trace、AgentOps 与指标

### 12.1 新增 trace step

| step_name | event_type | 关键 metadata |
| --- | --- | --- |
| Semantic Routing | `routing` | mode、tasks、confidence_bucket、reason_code |
| Clarification | `clarification` | missing_slots、reason_code |
| Plan Build | `plan` | step_count、tool_step_count、generation_step_count |
| Plan Step | `plan_step` | step_id、operation、status、latency_ms |
| Repair Attempt | `repair` | failure_code、repair_type、attempt=1 |
| Evidence Verify | `verification` | criteria_count、passed_count、completion_status |

不得在 trace 中写入：

- confirmation token 原文；
- API key、认证 header；
- 完整学生画像；
- 未压缩的工具原始结果；
- 模型内部推理文本。

### 12.2 AgentOps 指标

新增聚合：

| 指标 | 定义 |
| --- | --- |
| `routing_accuracy` | 在线反馈或抽样标注中路由正确比例 |
| `clarification_rate` | `needs_clarification / total_requests` |
| `clarification_resolution_rate` | 澄清后成功完成任务的比例 |
| `multi_intent_rate` | 多任务请求比例 |
| `plan_completion_rate` | 所有必要步骤完成比例 |
| `partial_completion_rate` | `partial / planned_requests` |
| `repair_rate` | 触发 repair 的计划比例 |
| `repair_success_rate` | repair 后完成比例 |
| `assistant_real_llm_rate` | generation_mode=llm 的回答比例 |
| `assistant_fallback_rate` | generation_mode=fallback 的回答比例 |
| `answer_resolution_rate` | 用户选择“解决了”的比例 |

指标必须区分离线 eval、demo seed 和真实运行数据，避免 seed 失败事件污染生产 readiness。

---

## 13. Eval 设计

### 13.1 数据集扩充

新增：

```text
eval/datasets/learning_assistant_intent_cases.json
eval/datasets/learning_assistant_composition_cases.json
eval/datasets/learning_assistant_clarification_cases.json
```

意图数据集从当前 18 条扩充到至少 300 条，分布建议：

| 类别 | 最少 case |
| --- | ---: |
| 每个现有 intent 的明确表达 | 8 × 15 = 120 |
| 同义改写和口语表达 | 50 |
| hard negative / 非历史学习请求 | 30 |
| 多轮指代 | 30 |
| 缺关键槽位 | 25 |
| 组合任务 | 30 |
| 话题切换 | 15 |

要求：

- 手写核心 case，不全部由同一个 LLM 批量生成；
- 生成 paraphrase 需要人工抽查和去重；
- 固定 train/dev/test 划分；规则调整只能看 train/dev，最终阈值看 test；
- 每个失败线上样本脱敏后进入 regression set；
- 数据集记录 `source=handwritten|production_regression|generated_reviewed`。

### 13.2 组件评测

改造 `eval/intent_accuracy_eval.py` 输出：

- accuracy；
- macro-F1；
- per-intent precision / recall / F1；
- slot accuracy；
- clarification precision / recall；
- multi-intent exact match；
- routing mode 分布；
- confusion matrix。

验收阈值：

| 指标 | v1.29.0 | v1.29.1 |
| --- | ---: | ---: |
| 单意图 accuracy | `>= 90%` | `>= 92%` |
| macro-F1 | `>= 0.88` | `>= 0.90` |
| slot accuracy | `>= 88%` | `>= 90%` |
| clarification precision | `>= 85%` | `>= 90%` |
| high-risk intent recall | `100%` | `100%` |
| multi-intent exact match | 仅观测 | `>= 85%` |

### 13.3 轨迹评测

扩展 `eval/trajectory_eval.py`：

- 保留现有 5 个单工具 case；
- 新增至少 10 个语义改写 case；
- 新增至少 8 个组合计划 case；
- 新增工具失败、空检索、确认等待和参数缺失；
- 断言工具选择、参数、顺序、依赖、结果利用和 completion status；
- 断言 high-risk 工具不会被组合计划绕过。

目标：

- 单任务 tool selection accuracy `>= 95%`；
- tool input accuracy `>= 95%`；
- tool output utilization `>= 95%`；
- 组合计划 completion `>= 85%`；
- 权限与确认绕过 `0`。

### 13.4 多轮与状态中立性

扩展 `learning_assistant_multiturn_smoke.py` 和 `autotutor_question_handoff_smoke.py`：

- 指代继承；
- 显式新主题覆盖旧主题；
- 澄清后补槽位；
- 澄清超时后重新路由；
- 组合任务持久化；
- regenerate 不重复写 user message；
- 使用随问前后 AutoTutor `revision / attempts / question / mastery` 不变。

### 13.5 离线与真实模型分层

#### PR / 本地快速层

- 禁用外部模型或使用 deterministic stub；
- 验证路由规则、schema、计划、工具、安全和 fallback；
- 必须稳定、低成本、可重复。

#### Nightly / 手动真实模型层

- 使用固定 provider 和模型 snapshot；
- 实际 `llm.calls > 0`；
- 输出 model、latency、cost、fallback 和 error；
- 评测语义理解、回答 groundedness、题目质量和教学适配；
- 配额错误标记为 infra failure，不能算质量 PASS；
- 未配置凭证时整套状态为 `NOT_RUN`，不能显示绿色 PASS。

---

## 14. 发布门禁

### 14.1 fast gate

将以下离线 suite 加入 `scripts/release_gate.py::FAST_SUITES`：

- `intent_accuracy_eval`
- `trajectory_eval`
- `learning_assistant_multiturn_smoke`
- `autotutor_question_handoff_smoke`

AutoTutor 轨迹和教学质量已在 `QUICK_SUITES`，但 fast release gate 当前使用独立列表；本轮需要明确是否纳入。建议：

- `auto_tutor_trajectory_eval` 纳入 fast；
- `autotutor_teaching_quality_eval` 纳入 fast；
- fast 后端总时长目标 `< 120 秒`；超过目标时优化测试隔离，不直接移除智能质量 gate。

### 14.2 完整 gate

完整 CORE 必须包括：

- intent；
- single/multi-step trajectory；
- multiturn；
- AutoTutor handoff；
- RAG retrieval/groundedness；
- tool registry/permission；
- agent safety；
- AutoTutor trajectory/teaching quality；
- AgentOps/trace。

### 14.3 报告新鲜度

- `eval/reports/latest.md` 必须包含代码 commit SHA、suite profile 和是否真实调用 LLM；
- 当报告 commit SHA 不是当前 HEAD 时，Eval 页面展示 `STALE`；
- 报告生成时间超过 7 天时展示 warning；
- 任一必需 suite 未运行时不能显示 Overall PASS；
- `skipped`、`not_run`、`infra_failed`、`quality_failed` 必须分开。

---

## 15. 安全与隐私

1. 路由前执行现有 prompt injection 检查。
2. RAG、教材和 MCP 工具结果一律作为 untrusted context 包装。
3. 模型输出的 tool/operation 名称必须经过服务端 allowlist。
4. 模型输出参数必须经过现有 Pydantic schema。
5. 学生不能通过 prompt 修改 `actor_role`、`student_id` 或其他会话所有权字段。
6. AutoTutor handoff 上下文继续由服务端按 session 加载，不信任 query 中的讲解和答案。
7. 澄清状态不保存答案、correct_answer 或未公开题目字段。
8. 高风险操作继续使用一次性确认 token、过期时间和 audit；路由 confidence 不能绕过确认。
9. 真实线上失败样本进入 eval 前必须去除姓名、账号、token 和自由文本中的敏感信息。
10. generation operation 不能执行外部请求、代码或数据库写入。

---

## 16. Feature Flag 与灰度

新增环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED` | `false` | 启用结构化语义路由 |
| `EDU_AGENT_ASSISTANT_PLANNER_ENABLED` | `false` | 启用最多 3 步组合计划 |
| `EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE` | `true` | 只记录新旧路由差异，不改变用户结果 |
| `EDU_AGENT_ASSISTANT_ROUTER_CONFIDENCE_THRESHOLD` | `0.65` | 低于该值进入澄清 |

灰度阶段：

### 阶段 0：离线

- 新 router 只跑数据集；
- 不进入 API；
- 达到 v1.29.0 指标后进入 shadow。

### 阶段 1：Shadow

- 用户结果继续使用旧路由；
- 新路由并行计算但不执行工具；
- Trace 记录 `legacy_intent / semantic_intent / agreement`；
- 观察至少 200 个脱敏请求或 7 天，以先满足者为准。

### 阶段 2：单任务灰度

- 10% demo/内部学生启用语义路由；
- `planner=false`；
- 关注误执行、高风险召回、澄清率、fallback 和延迟。

### 阶段 3：单任务全量

- 语义路由 100%；
- 旧规则保留为 fallback；
- 达标后开启 planner 内部灰度。

### 阶段 4：组合任务灰度

- 先对 explain + quiz 两步/三步模板开放；
- 不包含高风险组合；
- 完成率达到 `>=85%` 后逐步全量。

回滚：关闭两个 flag 即恢复 v1.28 单任务路径；数据库没有新 schema，因此无需数据回滚。

---

## 17. 预计代码改动

### 17.1 后端

| 文件 | 改动 |
| --- | --- |
| `backend/agents/learning_assistant.py` | 接入新 router/plan/runtime；保留 SSE、合成和兼容事件 |
| `backend/agents/learning_assistant_router.py` | 新增结构化语义路由、规则候选、澄清和 fallback |
| `backend/agents/learning_assistant_planner.py` | 新增确定性模板计划和计划校验 |
| `backend/agents/learning_assistant_runtime.py` | 新增串行执行、step 状态、repair 和 verification |
| `backend/api/routers/learning.py` | 透传新增 SSE；持久化 routing/plan/completion metadata |
| `backend/agent_ops.py` | 新增路由、澄清、计划、repair 和真实模型指标 |
| `backend/llm_config.py` | 不改变 provider；确保 router generation 有统一 trace/cost |

### 17.2 前端

| 文件 | 改动 |
| --- | --- |
| `frontend/app/learning-assistant/page.tsx` | 消费 route/plan/plan_step/clarification；展示轻量进度和 partial 状态 |
| `frontend/components/*` | 如需要，抽出 PlanProgress / ClarificationCard；保持默认折叠 |
| `frontend/components/learningAssistantComposer.test.ts` | 增加澄清、计划进度和旧事件兼容测试 |

### 17.3 Eval / Ops

| 文件 | 改动 |
| --- | --- |
| `eval/intent_accuracy_eval.py` | 数据集化，新增 macro-F1、slot、clarification、multi-intent 指标 |
| `eval/trajectory_eval.py` | 多步计划、失败、确认和结果利用 |
| `eval/learning_assistant_multiturn_smoke.py` | 澄清、话题切换、计划持久化 |
| `eval/autotutor_question_handoff_smoke.py` | 新路由下的 AutoTutor 状态中立性 |
| `eval/run_core_evals.py` | 注册/分类新 suite 和指标 |
| `scripts/release_gate.py` | fast gate 纳入智能质量 suite |
| `eval/report_generator.py` | commit SHA、profile、LLM 状态、stale 信息 |
| `frontend/app/eval/page.tsx` | 展示 stale、not_run、routing/plan 指标 |

### 17.4 文档

实施完成时同步：

- `README.md`：测试命令和智能路由说明；
- `SCHEMA.md`：新增文件、SSE 事件、测试和版本记录；
- `.env.example`：新增 feature flags；
- 本 Spec：把状态更新为 Implemented，并记录实际偏差。

---

## 18. 实施拆分

### Milestone A：v1.29.0 语义路由基线（预计 4–5 天）

1. 先建立 300 条路由数据集和指标脚本。
2. 定义 `RoutingDecision / RoutedTask` schema。
3. 抽取现有规则为 candidate scorer 和安全直达规则。
4. 实现结构化语义路由、澄清和 deterministic fallback。
5. 接入现有单工具执行，不开启多步。
6. 增加 route/clarification trace 和 SSE 兼容字段。
7. fast gate 加入 intent、trajectory、multiturn、handoff。
8. shadow mode 对比新旧路由。

Milestone A 退出条件：

- 单意图 accuracy `>=90%`；
- macro-F1 `>=0.88`；
- high-risk recall `100%`；
- 现有 trajectory `5/5` 无回归；
- 多轮、handoff、fast gate 全绿；
- 关闭 flag 时行为与 v1.28 一致。

### Milestone B：v1.29.1 受限组合任务（预计 4–5 天）

1. 定义 TaskPlan 和 deterministic template builder。
2. 实现最多 3 步串行 runtime。
3. 抽取受控 generation operations。
4. 增加 plan/plan_step/verification 事件。
5. 实现 fail-fast、一次 repair、partial/completion status。
6. 前端展示轻量计划进度和澄清卡。
7. 增加组合任务和失败轨迹 eval。
8. planner shadow/灰度。

Milestone B 退出条件：

- multi-intent exact match `>=85%`；
- 组合计划 completion `>=85%`；
- tool input/output utilization `>=95%`；
- 权限/确认绕过为 `0`；
- explain + quiz 主用例在有/无 LLM 两种环境均有可解释行为；
- `planner=false` 可无数据迁移回滚。

### Milestone C：真实质量盖章（预计 1–2 天，可与 B 并行准备）

1. 运行真实 provider nightly suite；
2. 刷新完整 CORE 报告；
3. 确认 `llm.calls > 0`、model/cost/latency 可见；
4. Eval 页面显示 commit SHA 和报告新鲜度；
5. 保存失败样本并进入 regression set；
6. 形成 v1.29 发布结论。

---

## 19. 验收清单

### 功能

- [x] 4 个当前误判样本全部正确或进入合理澄清。
- [x] “先解释洋务运动，再出 3 道选择题”生成正确计划并完成。
- [x] “这节课讲了什么”在无上下文时澄清，有教材上下文时直接回答。
- [x] 多轮指代继承和显式话题切换都正确。
- [x] 高风险工具继续要求确认，取消后不执行。
- [x] 随问前后 AutoTutor 状态不变。
- [x] 模型不可用时不空白、不伪成功，能够 fallback 或澄清。

### 质量

- [x] 单意图 accuracy `>=92%`（v1.29.1 最终线）。
- [x] macro-F1 `>=0.90`。
- [x] slot accuracy `>=90%`。
- [x] multi-intent exact match `>=85%`。
- [x] tool selection/input/output utilization 均 `>=95%`。
- [x] 组合计划 completion `>=85%`。
- [x] agent safety / guardrail / permission 全绿。

### 可观测性

- [x] 每个新请求有 routing trace。
- [x] 计划请求的每一步有状态和 latency。
- [x] repair、clarification、partial completion 可聚合。
- [x] 真实模型 suite 能看到 calls、model、fallback、error、cost。
- [x] 新生成报告包含 commit SHA、profile 和 freshness。

### 发布

- [x] `npm run release:gate:fast -- --skip-frontend` 包含新增智能质量 suite。
- [x] 完整 CORE eval 为 PASS，必需 suite 无 `skipped/not_run`。
- [x] 前端 unit/component test 通过。
- [x] 前端 build 通过。
- [x] 学习助手关键 E2E 通过。
- [x] README、SCHEMA、`.env.example` 同步。
- [x] feature flag 回滚验证通过。

---

## 20. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 每轮新增一次 router LLM 调用 | 延迟和成本上升 | 明确低歧义规则直达；router 用 fast 模型；缓存只用于无用户隐私的规范化定义，不缓存个人请求 |
| 模型路由不稳定 | 工具误选 | Pydantic、allowlist、confidence、澄清、shadow 和 golden eval |
| 多步计划扩大失败面 | 部分完成或重复执行 | 最多 3 步、串行、fail-fast、幂等只读优先、step trace |
| confirmation 恢复复杂 | 重复副作用 | 首版限制组合高风险工具；无法安全恢复时不开放 |
| 数据集被规则过拟合 | 离线高分线上低质 | 固定 test、production regression、shadow 对比、人工抽查 |
| fallback 高通过掩盖真实模型失败 | 错误发布判断 | 离线与真实模型分层；NOT_RUN 不算 PASS；报告 LLM calls |
| 旧前端不认识新事件 | 页面异常 | 新增事件、保留旧 intent/final；前端忽略未知事件仍可工作 |
| 上下文带入旧话题 | 答非所问 | 当前问题显式实体优先；话题切换 eval；不把长期兴趣当硬约束 |

---

## 21. 后续版本方向

以下能力不阻塞 v1.29：

### v1.30：上下文与记忆升级

- 滚动会话摘要；
- 实体、目标和未解决问题状态；
- 相关历史消息召回；
- 用户纠正后的 memory 修订和过期策略；
- 上下文 token 预算与压缩指标。

### v1.31：教学策略与学习效果

- 区分概念不懂、知识遗忘、审题失误和猜对；
- 前测、退出票、24 小时后测；
- 掌握概率而不只是答对次数；
- 教学策略 A/B；
- 学习增益、保持率、人工接管率。

### v1.32：更通用的 Agent Runtime

- durable composite plan；
- 多 server MCP routing；
- 可恢复的长任务；
- agent-as-tool；
- 并行只读 fan-out 和结果聚合；
- 更严格的预算、SLO 和告警。

---

## 22. 最终成功定义

v1.29 成功不是“接入了一个更大的模型”，也不是“新增了 Planner 类”。成功必须同时满足：

1. 学生换一种自然说法，路由仍然正确；
2. 信息不足时主动澄清，不错误调用工具；
3. 组合任务能够按受限计划完成，并对部分失败诚实；
4. 所有工具调用继续受 schema、权限、确认、审计和 Trace 约束；
5. AutoTutor 的现有教学闭环和状态中立性不回退；
6. 发布门禁能够捕获智能质量下降，而不是只证明接口还能运行；
7. 真实模型质量与离线 fallback 质量在报告中被清楚区分。

达到以上标准后，EduAgent 才从“强工程、固定流程的垂直 Agent”进一步升级为“能理解自然目标、受控组合能力、可验证完成结果的教育 Agent”。
