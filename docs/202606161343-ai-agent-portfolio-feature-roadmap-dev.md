# EduAgent AI Agent 工程师作品集 Feature Roadmap

本文档用于规划 EduAgent 作为 AI Agent 工程师作品集时，下一阶段最值得补齐的功能。重点不是继续扩展教育业务功能，而是让项目更清楚地展示生产级 Agent 工程能力：workflow、tool governance、RAG 可解释性、eval、AgentOps、memory、guardrails 和 human-in-the-loop。

## 1. 总体方向

EduAgent 当前已经具备较完整的垂直教育 Agent 产品雏形，包括历史角色对话、材料学习、作文批改、历史游戏、学生画像、学习助手、RAG、多模态材料处理、基础 eval 和 AgentOps。

如果目标是作品集，下一阶段应优先做能让面试官一眼看懂工程能力的功能：

1. Agent 执行过程是否可观察。
2. 工具调用是否有 schema、权限、风险等级和确认机制。
3. RAG 回答是否能解释检索、引用和 grounding。
4. Agent 是否有自动化 eval 和 regression 机制。
5. 线上失败是否能沉淀为评测样本。
6. 记忆系统是否可查看、可删除、可解释。
7. 多 Agent / human-in-the-loop 是否有明确工程边界。

推荐总体目标：

> 把 EduAgent 从“功能完整的教育 AI 应用”升级为“可评测、可观测、可治理、可迭代的教育 Agent 工程作品集”。

## 2. Feature 优先级总览

| 优先级 | Feature | 作品集价值 | 当前基础 | 推荐程度 |
| --- | --- | --- | --- | --- |
| P0 | Agent 执行轨迹可视化 | 展示 Agent runtime、workflow、trace、tool trajectory | 已有 SSE、Langfuse、AgentOps summary | 最高 |
| P0 | Tool Permission / Confirmation Demo | 展示工具治理、安全边界、human confirmation | 已有 ToolSpec、risk_level、required_role | 最高 |
| P0 | Eval Dashboard 增强 | 展示 Evaluation Engineering 和 regression 能力 | 已有 eval runner、eval 页面 | 最高 |
| P1 | RAG 可解释检索面板 | 展示 retrieval debugging、grounding、citation | 已有 Chroma、rerank、sources | 高 |
| P1 | Agent Memory 管理页面 | 展示长期记忆策略、用户控制、隐私意识 | 已有 student_profile、user_memory | 高 |
| P1 | Multi-Agent 教学辩论升级 | 展示多 Agent 编排、裁判、事实核查 | 已有 debate_supervisor | 中高 |
| P1 | Human-in-the-loop 教师审核流 | 展示生产场景下的人机协作和反馈闭环 | 已有作文批改、教师端页面 | 中高 |
| P2 | Prompt / Agent 配置实验台 | 展示 prompt iteration、A/B eval、模型路由 | 已有模型配置和 eval | 中 |
| P2 | Trace-to-Eval 失败样本回流 | 展示 AgentOps 到 Eval 的闭环 | 已有 AgentOps summary 和 eval datasets | 高但实现稍重 |
| P2 | CI/CD + 自动 eval | 展示工程交付能力 | 已有 npm verify、Dockerfile | 高 |

## 3. P0 Feature 详细设计

### 3.1 Agent 执行轨迹可视化

#### 目标

为学习助手、历史角色对话、作文批改等核心 Agent 增加可视化执行轨迹，让用户和面试官能看到一次 Agent 请求背后的完整过程。

#### 建议展示内容

每次请求生成一个 `trace_id`，前端展示：

- 用户输入。
- Agent 名称。
- 当前 step。
- 意图识别结果。
- 检索到的资料。
- 工具选择。
- 工具入参。
- 工具返回。
- LLM 模型名称。
- 是否写入 memory / student profile。
- 最终回答。
- 总耗时。
- 成功 / 失败状态。

#### 示例 UI

```text
Trace: trace_abc123

1. Receive User Query
   status: success
   latency: 12ms

2. Intent Detection
   intent: material_qa
   confidence: 0.86

3. Retrieve Context
   source: material_rag
   retrieved_chunks: 5

4. Tool Execution
   tool: search_history_knowledge
   risk_level: low
   status: success
   latency: 220ms

5. Answer Synthesis
   model: fast
   status: success
   latency: 1800ms

6. Memory Update
   wrote_event: true
   feature: learning_assistant
```

#### 后端建议

统一事件结构：

```json
{
  "trace_id": "trace_abc123",
  "agent_name": "learning_assistant",
  "step_name": "tool_execution",
  "event_type": "tool_result",
  "status": "success",
  "latency_ms": 220,
  "metadata": {
    "tool_name": "search_history_knowledge",
    "risk_level": "low"
  }
}
```

#### 作品集亮点

这个 feature 可以直接说明你理解：

- Agent 不是黑盒聊天。
- Tool trajectory 需要被记录。
- 生产问题需要通过 trace 定位。
- 前端需要展示 Agent 当前在做什么。

#### 验收标准

- 至少学习助手页面能展示完整 step timeline。
- 每个 step 有 status、latency、metadata。
- 工具调用 step 能展示 tool_name、risk_level、input summary、result summary。
- 失败时能显示 error_code 和失败 step。

### 3.2 Tool Permission / Confirmation Demo

#### 目标

把已有 `ToolSpec` 中的治理字段真正变成可运行闭环：工具执行前检查角色、风险等级和确认状态。

当前项目已有基础：

- `risk_level`
- `side_effect`
- `required_role`
- `requires_confirmation`
- `audit_enabled`
- Pydantic input schema

下一步要让这些字段实际参与执行决策。

#### 建议能力

1. low risk 工具直接执行。
2. medium risk 工具允许执行，但必须 audit。
3. high risk 工具必须前端确认。
4. required_role 不满足时拒绝执行。
5. confirmation 未完成时返回 `confirmation_required`。
6. 所有拒绝和确认结果进入 audit log。

#### 示例工具

可以新增一个作品集演示用高风险工具：

```text
delete_student_memory
risk_level: high
side_effect: write
required_role: student
requires_confirmation: true
```

注意该工具可以先做安全模拟，例如只删除测试学生或只删除一条 demo memory，避免真实破坏数据。

#### 推荐返回结构

```json
{
  "tool_name": "delete_student_memory",
  "ok": false,
  "error": {
    "code": "confirmation_required",
    "message": "该工具会删除学生记忆，需要用户确认。",
    "retryable": false
  },
  "metadata": {
    "risk_level": "high",
    "required_role": "student",
    "confirmation_token": "confirm_123"
  }
}
```

#### 前端体验

学习助手工具轨迹中展示：

```text
Agent 想调用高风险工具：delete_student_memory
原因：删除一条错误学习记忆
风险等级：high
影响：会修改学生长期画像

[确认执行] [取消]
```

#### 作品集亮点

这个 feature 可以展示：

- Tool use 不是简单函数调用。
- Agent 的行动必须有后端硬边界。
- 高风险工具必须 human-in-the-loop。
- 权限治理不能只写在 prompt 中。

#### 验收标准

- `run_tool()` 或上层执行入口强制检查 role。
- `requires_confirmation=true` 时不直接执行工具。
- 前端能展示确认弹窗或确认卡片。
- audit log 记录 allow / deny / confirmation_required。
- eval 中增加至少 3 个工具权限 case。

### 3.3 Eval Dashboard 增强

#### 目标

把已有 eval runner 和 eval 页面升级为作品集级 Evaluation Engineering 展示页。

#### 建议增强内容

- Core suites 总览。
- 每个 suite 的 pass / fail / skipped。
- 每个 suite 的 category：agent、rag、tools、safety、memory。
- 最近失败 case。
- 关键指标：
  - task_success_rate
  - retrieval_hit_rate
  - source_correctness
  - tool_schema_validity
  - guardrail_pass_rate
  - format_validity
  - latency
- 一键运行 quick eval。
- 下载 `latest.json` 和 `latest.md`。

#### 进一步亮点

增加“失败样本回流”：

```text
Failed Case
- suite: rag_retrieval_eval
- query: 秦始皇统一文字有什么影响？
- reason: missing expected source

[加入 regression dataset]
```

#### 作品集亮点

这个 feature 可以展示：

- 你会用 eval 管理 Agent 质量。
- 你理解 smoke test 和 quality eval 的区别。
- 你能把 prompt / RAG / tool 变更纳入回归测试。
- 你有 Agent 迭代闭环，而不是靠手测。

#### 验收标准

- eval 页面能展示最新报告。
- 后端 API 能触发 quick eval 或读取报告。
- `eval/reports/latest.json` 和 `eval/reports/latest.md` 能稳定生成。
- 至少展示 tools / rag / safety 三类指标。
- 失败 suite 有明确 failed cases。

## 4. P1 Feature 详细设计

### 4.1 RAG 可解释检索面板

#### 目标

为历史知识库、教材问答、材料问答增加 RAG Inspector，让检索和引用过程可解释。

#### 建议展示内容

- 原始 query。
- query rewrite 结果，如有。
- top-k retrieved chunks。
- vector score。
- rerank score。
- chunk title / source / page / section。
- 哪些 chunk 被用于最终回答。
- 答案中的 citation 对应来源。
- 未引用 chunk 的原因，如低相关、重复、冲突。

#### 示例 UI

```text
Query: 商鞅变法为什么能增强秦国实力？

Retrieved Chunks
1. 《中国历史七年级上册》商鞅变法
   vector_score: 0.82
   rerank_score: 0.91
   used: yes

2. 秦统一六国背景
   vector_score: 0.75
   rerank_score: 0.62
   used: no
   reason: background only

Answer Citations
- “奖励耕战” → chunk 1
- “确立县制” → chunk 1
```

#### 作品集亮点

展示你理解 RAG 的难点不只是“能检索”，而是：

- 检索质量可调试。
- 引用来源可追溯。
- 模型回答要 grounding。
- RAG 失败需要能定位是 retrieval、rerank 还是 generation 问题。

#### 验收标准

- 至少材料问答或历史角色问答支持 inspector。
- 每个 source 有 score 和 metadata。
- 最终答案能展示来源引用。
- eval 中有 retrieval hit rate 指标。

### 4.2 Agent Memory 管理页面

#### 目标

把学生画像和长期记忆做成可查看、可删除、可解释的 memory 管理体验。

#### 页面建议

```text
Memory Center

Student Profile
- strong topics
- weak topics
- recent activities
- learning preferences

Memory Entries
- content
- type
- source feature
- created_at
- last_used_at
- confidence
- actions: delete / disable

Used in Current Answer
- memory id: mem_001
- reason: 用于判断学生最近薄弱点
```

#### 建议记忆类型

- weak_point
- interest
- learning_preference
- recent_mistake
- teacher_note
- review_goal

#### 作品集亮点

展示你理解 memory 设计包括：

- 记什么。
- 什么时候记。
- 什么时候召回。
- 如何删除和过期。
- 如何解释这次用了哪些 memory。

#### 验收标准

- 用户能查看学生画像和学习事件。
- 用户能删除或禁用一条 memory。
- Agent 回答能显示使用了哪些 memory。
- audit log 记录 memory 删除行为。

### 4.3 Multi-Agent 教学辩论升级

#### 目标

把历史辩论升级成多 Agent 协作展示：正方、反方、事实核查、裁判、教学总结。

#### 推荐流程

```text
Debater Pro
  ↓
Debater Con
  ↓
Fact Checker
  ↓
Judge
  ↓
Learning Coach Summary
```

#### Agent 角色

| Agent | 职责 |
| --- | --- |
| Pro Debater | 支持命题，提出论据 |
| Con Debater | 反对命题，提出反例 |
| Fact Checker | 检查历史事实和来源 |
| Judge | 根据论据质量评分 |
| Learning Coach | 转换成学生可理解的学习总结 |

#### 作品集亮点

这个 feature 可以展示：

- 多 Agent 分工。
- 结果仲裁。
- 事实核查。
- 教育场景下的多步骤任务合成。

#### 验收标准

- 前端能看到每个 Agent 的输出。
- Fact checker 能引用 RAG sources。
- Judge 输出结构化评分。
- Learning coach 生成最终学习建议。

### 4.4 Human-in-the-loop 教师审核流

#### 目标

让教师可以审核 Agent 的作文批改结果，并把教师修改沉淀为反馈数据。

#### 推荐流程

```text
Student submits essay
  ↓
Agent grades essay
  ↓
Teacher reviews
  ↓
Teacher accepts / edits / rejects
  ↓
Feedback stored
  ↓
Future eval / prompt iteration uses feedback
```

#### 作品集亮点

展示生产 Agent 的重要现实：

- 不是所有结果都应该自动生效。
- 高影响教育反馈需要教师审核。
- 人类反馈可以进入持续改进闭环。

#### 验收标准

- 教师端能查看 Agent 批改结果。
- 教师能修改分数和评语。
- 系统记录 teacher feedback。
- eval 或报告中能统计 accept / edit / reject 比例。

## 5. P2 Feature 详细设计

### 5.1 Prompt / Agent 配置实验台

#### 目标

提供一个内部实验页面，用同一批 eval cases 对比不同 prompt、模型和工具配置。

#### 建议功能

- 选择 Agent。
- 选择 prompt version。
- 选择模型。
- 调整 temperature / max tokens。
- 开关某些工具。
- 运行 selected eval suite。
- 对比两个版本结果。

#### 示例结果

```text
History Character Agent

Prompt v1
- pass rate: 72%
- avg latency: 2.1s
- hallucination risk: medium

Prompt v2
- pass rate: 84%
- avg latency: 2.8s
- hallucination risk: low
```

#### 作品集亮点

展示 Agent 不是一次性 prompt，而是持续实验、评估和迭代。

### 5.2 Trace-to-Eval 失败样本回流

#### 目标

从 AgentOps trace 或 audit log 中选择失败请求，自动生成 eval case 草稿。

#### 推荐流程

```text
Failed trace
  ↓
Extract user input, agent output, tool calls, retrieved docs
  ↓
Generate eval case draft
  ↓
Human review
  ↓
Save to eval/datasets/*.json
```

#### 作品集亮点

这是 AgentOps 和 Evaluation 的闭环能力：线上失败不是只看日志，而是能沉淀为回归测试。

### 5.3 CI/CD + 自动 Eval

#### 目标

增加 GitHub Actions 或等价 CI，让项目体现持续交付能力。

#### 推荐 CI 步骤

```text
1. frontend lint
2. frontend build
3. backend import check
4. python eval/run_core_evals.py --quick
5. docker build backend
6. docker build frontend
```

#### 作品集亮点

展示项目不是本地演示，而是可持续维护的工程项目。

## 6. 推荐实施顺序

如果时间有限，建议只做前三个：

1. Agent 执行轨迹可视化。
2. Tool Permission / Confirmation Demo。
3. Eval Dashboard 增强。

这三个功能最能把 EduAgent 从“教育 AI 应用”升级成“AI Agent 工程作品集”。

推荐 3 个迭代：

### Iteration 1：Agent Runtime 可视化

- 统一 trace event schema。
- 学习助手页面增加 step timeline。
- 工具调用展示 tool metadata。
- 失败 step 可视化。

### Iteration 2：Tool Governance

- 强制 role / confirmation 检查。
- 新增 high-risk demo tool。
- 前端确认卡片。
- audit log 记录决策。
- tool permission eval cases。

### Iteration 3：Eval & AgentOps 展示

- 稳定生成 eval reports。
- eval dashboard 展示指标。
- AgentOps summary 增强 latency / tool failure / trace coverage。
- 失败 case 展示与回流入口。

## 7. 不建议优先投入的方向

当前阶段不建议继续优先做：

- 更多学科页面。
- 更多游戏类型。
- 更多普通聊天入口。
- 更复杂的学校 / 班级 / 组织管理。
- 复杂商业化权限套餐。
- 大量静态 dashboard。

原因：这些更偏教育 SaaS 产品扩展，对 AI Agent 工程师作品集的边际加分不如 runtime、eval、tool governance、RAG inspector 和 AgentOps。

## 8. 作品集展示话术

完成上述 feature 后，可以这样介绍 EduAgent：

> EduAgent 是一个面向 K-12 历史与语文学习的垂直教育 Agent 平台。它不仅支持角色对话、材料学习、作文批改和游戏化学习，还重点实现了生产级 Agent 工程能力：LangGraph 工作流、RAG grounding、schema-first tool calling、工具权限治理、human confirmation、Agent trace 可视化、Eval dashboard、AgentOps summary 和学生长期记忆管理。

面试展示时建议按以下顺序演示：

1. 打开学习助手，提出一个需要工具调用的问题。
2. 展示 Agent step timeline。
3. 点开某个 tool call，看 input schema、risk level、result 和 latency。
4. 触发一个 high-risk tool，展示 confirmation。
5. 打开 RAG inspector，看 retrieved chunks 和 citations。
6. 打开 eval dashboard，看 pass rate 和 failed cases。
7. 打开 AgentOps summary，看 trace coverage、audit events 和 tool failures。
8. 打开 memory 页面，看学生画像和本次回答使用的记忆。

## 9. 最终建议

当前 EduAgent 已经有足够的教育业务功能。下一阶段最应该做的是把已有 Agent 能力“显性化”和“工程化”：

- 让 Agent 执行过程可见。
- 让工具调用有硬权限边界。
- 让 RAG 检索和引用可解释。
- 让 eval 报告成为稳定产物。
- 让线上失败能回流为 regression case。

如果这些补齐，EduAgent 作为 AI Agent 工程师作品集的完成度可以从当前约 85% 提升到 90%+，并且会比单纯功能丰富的 AI 应用更能体现工程深度。
