# EduAgent 下一阶段 Agent 工程能力开发文档

## 1. 背景

EduAgent 当前已经具备较完整的教育 Agent 产品雏形，包括历史角色对话、材料学习、作文批改、历史游戏、学习助手、RAG、多模态材料处理、学生画像、基础 eval 和 AgentOps 能力。

下一阶段的重点不应继续横向扩展更多教育业务页面，而应围绕 AI Agent 工程师作品集目标，把已有能力显性化、工程化、可演示化。

核心目标是把 EduAgent 从“功能完整的教育 AI 应用”升级为：

> 可观察、可评测、可治理、可解释、可持续迭代的教育 Agent 工程作品集。

## 2. 当前基础

项目当前已经具备以下可复用基础：

| 能力 | 当前基础 | 说明 |
| --- | --- | --- |
| Agent 编排 | `backend/agents/learning_assistant.py` | 学习助手已有 intent 到 tool 的编排流程 |
| Tool schema | `backend/tools/base.py` | `ToolSpec` 已包含 schema、风险等级、权限字段 |
| Tool 执行入口 | `backend/tools/registry.py` | `run_tool()` 已作为统一工具执行入口 |
| Tool governance 元数据 | `risk_level`、`required_role`、`requires_confirmation` | 字段已存在，但需要加强运行时闭环和前端展示 |
| Audit log | `backend/security/audit_log.py` | 已能记录审计事件，并可关联 `trace_id` |
| Trace / Langfuse | `backend/tracing.py` | 已具备 trace、span、generation 封装 |
| AgentOps summary | `backend/agent_ops.py`、`/api/agent-ops/summary` | 已能汇总部分运行数据 |
| Eval runner | `eval/run_core_evals.py` | 已能生成 `eval/reports/latest.json` 和 `latest.md` |
| Eval dashboard | `frontend/app/eval/page.tsx` | 已有基础评测展示页面 |
| RAG | `backend/rag/knowledge_base.py`、`backend/rag/rerank.py` | 已有检索、metadata、rerank 基础 |
| Memory | `backend/student_profile.py`、`backend/user_memory.py` | 已有学生画像和长期记忆封装 |
| 学习助手页面 | `frontend/app/learning-assistant/page.tsx` | 最适合作为 Agent 工程能力展示入口 |

## 3. 下一阶段总体范围

下一阶段建议分为 4 个迭代：

1. Agent Runtime 可视化。
2. Tool Governance 与 Human Confirmation。
3. Eval Dashboard 作品集化。
4. RAG Inspector 与 Memory Center。

其中前 3 个为 P0，建议优先完成；第 4 个为 P1，用于补齐 RAG 和 Memory 的可解释展示。

## 4. P0-1：Agent Runtime 可视化

### 4.1 目标

在学习助手中展示一次 Agent 请求背后的完整执行轨迹，让用户和面试官能看到 Agent 如何完成任务。

### 4.2 页面入口

优先改造：

- `frontend/app/learning-assistant/page.tsx`

### 4.3 后端涉及模块

- `backend/agents/learning_assistant.py`
- `backend/tools/registry.py`
- `backend/tracing.py`
- `backend/security/audit_log.py`
- `backend/api/main.py`

### 4.4 推荐事件结构

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
    "risk_level": "low",
    "input_summary": "查询商鞅变法相关知识",
    "result_summary": "返回 3 条教材相关片段"
  }
}
```

### 4.5 前端展示

学习助手回答区域旁边或下方增加 Agent Timeline：

```text
Trace: trace_abc123

1. Receive User Query
   status: success
   latency: 8ms

2. Intent Detection
   intent: material_qa
   confidence: 0.86

3. Tool Selection
   selected_tool: search_history_knowledge
   risk_level: low

4. Tool Execution
   status: success
   latency: 220ms
   result: 返回 3 条教材片段

5. Answer Synthesis
   model: fast
   status: success
   latency: 1800ms

6. Memory Update
   wrote_event: true
```

### 4.6 验收标准

- 每次学习助手请求都有 `trace_id`。
- 前端能展示完整 step timeline。
- 每个 step 至少包含 `status`、`latency_ms`、`metadata`。
- 工具调用 step 能展示 `tool_name`、`risk_level`、input summary、result summary。
- LLM step 能展示 model 和耗时。
- 失败时能展示 failed step、error code 和错误摘要。

### 4.7 作品集价值

该功能用于展示：

- Agent 不是黑盒聊天。
- Agent runtime 可以被观测和调试。
- 工具轨迹、模型调用、记忆写入都可以被统一记录。
- 生产环境中的 Agent 问题可以通过 trace 定位。

## 5. P0-2：Tool Governance 与 Human Confirmation

### 5.1 目标

把已有 `ToolSpec` 中的治理字段变成真实运行时机制：工具执行前必须经过权限、风险等级和确认状态检查。

### 5.2 后端涉及模块

- `backend/tools/base.py`
- `backend/tools/registry.py`
- `backend/security/audit_log.py`
- `backend/api/main.py`

### 5.3 运行规则

| 条件 | 行为 |
| --- | --- |
| low risk | 可直接执行 |
| medium risk | 可执行，但必须写 audit log |
| high risk | 必须前端确认后才能执行 |
| required_role 不满足 | 直接拒绝执行 |
| requires_confirmation 为 true 且未确认 | 返回 `confirmation_required` |
| 用户取消确认 | 不执行工具，并记录 audit log |

### 5.4 推荐新增 demo 工具

新增一个安全的高风险演示工具，例如：

```text
delete_demo_memory
risk_level: high
side_effect: write
required_role: student
requires_confirmation: true
audit_enabled: true
```

该工具建议只操作 demo memory 或测试数据，避免真实删除用户核心数据。

### 5.5 推荐返回结构

```json
{
  "tool_name": "delete_demo_memory",
  "ok": false,
  "error": {
    "code": "confirmation_required",
    "message": "该工具会删除一条学生记忆，需要用户确认。",
    "retryable": false
  },
  "metadata": {
    "risk_level": "high",
    "required_role": "student",
    "confirmation_token": "confirm_123"
  }
}
```

### 5.6 前端交互

学习助手 timeline 中展示确认卡片：

```text
Agent 想调用高风险工具：delete_demo_memory

原因：删除一条错误的学习记忆
风险等级：high
影响范围：会修改学生长期画像

[确认执行] [取消]
```

### 5.7 Audit log 要求

至少记录以下事件：

- tool_allowed
- tool_denied
- confirmation_required
- confirmation_confirmed
- confirmation_cancelled
- role_denied

### 5.8 Eval 要求

增加至少 3 个工具权限 case：

1. low risk 工具可执行。
2. role 不满足时拒绝执行。
3. high risk 工具未确认时返回 `confirmation_required`。

### 5.9 验收标准

- `run_tool()` 或上层工具执行入口强制检查 role。
- `requires_confirmation=true` 时不会直接执行工具。
- 前端能展示确认卡片。
- 用户确认后工具才执行。
- audit log 记录 allow、deny、confirmation_required、confirmed、cancelled。
- eval 中包含工具权限回归 case。

### 5.10 作品集价值

该功能用于展示：

- Tool use 不是简单函数调用。
- Agent 的行动必须有后端硬边界。
- 高风险工具必须 human-in-the-loop。
- 权限治理不能只依赖 prompt。

## 6. P0-3：Eval Dashboard 作品集化

### 6.1 目标

把已有 eval runner 和 eval 页面升级为 Evaluation Engineering 展示页，让评测结果、失败样本和关键指标可视化。

### 6.2 涉及模块

- `eval/run_core_evals.py`
- `eval/reports/latest.json`
- `eval/reports/latest.md`
- `frontend/app/eval/page.tsx`
- `backend/api/main.py`

### 6.3 Dashboard 展示内容

建议增加：

- Core suites 总览。
- 每个 suite 的 pass / fail / skipped。
- 每个 suite 的 category：agent、rag、tools、safety、memory。
- 最近失败 case。
- 关键指标卡片。
- quick eval 按钮。
- 下载 `latest.json` 和 `latest.md`。

### 6.4 关键指标

建议至少展示：

- task_success_rate
- retrieval_hit_rate
- source_correctness
- tool_schema_validity
- guardrail_pass_rate
- format_validity
- avg_latency_ms

### 6.5 Failed Case 展示

示例：

```text
Failed Case
- suite: rag_retrieval_eval
- category: rag
- query: 秦始皇统一文字有什么影响？
- reason: missing expected source
- expected: 包含“统一文字促进政令推行和文化交流”
- actual: 只回答了文化影响，缺少政令推行
```

### 6.6 报告结构建议

`eval/reports/latest.json` 建议包含：

```json
{
  "generated_at": "2026-06-16T13:49:00+08:00",
  "summary": {
    "total": 24,
    "passed": 21,
    "failed": 2,
    "skipped": 1,
    "pass_rate": 0.875
  },
  "metrics": {
    "task_success_rate": 0.9,
    "retrieval_hit_rate": 0.83,
    "tool_schema_validity": 1.0,
    "guardrail_pass_rate": 0.95,
    "format_validity": 0.92,
    "avg_latency_ms": 1850
  },
  "suites": [
    {
      "name": "tool_permission_eval",
      "category": "tools",
      "passed": 3,
      "failed": 0,
      "skipped": 0,
      "failed_cases": []
    }
  ]
}
```

### 6.7 验收标准

- eval 页面能读取并展示最新报告。
- 后端 API 能触发 quick eval 或读取 report。
- `eval/reports/latest.json` 和 `latest.md` 能稳定生成。
- 至少展示 tools、rag、safety 三类指标。
- 失败 suite 有明确 failed cases。
- dashboard 能展示 pass rate、latency 和失败原因。

### 6.8 作品集价值

该功能用于展示：

- Agent 质量不是靠手测维护。
- Prompt、RAG、tool、guardrail 变更可以纳入回归测试。
- 项目具备持续迭代和质量管理能力。

## 7. P1-1：RAG Inspector

### 7.1 目标

为历史角色问答、学习助手或材料问答增加 RAG Inspector，让检索过程、引用来源和 grounding 结果可解释。

### 7.2 涉及模块

- `backend/rag/knowledge_base.py`
- `backend/rag/rerank.py`
- `backend/agents/history_character.py`
- `backend/agents/learning_assistant.py`
- `frontend/app/history-character/page.tsx`
- `frontend/app/learning-assistant/page.tsx`

### 7.3 展示内容

- 原始 query。
- query rewrite 结果，如有。
- top-k retrieved chunks。
- vector score。
- rerank score。
- chunk title / source / page / section。
- 是否用于最终回答。
- 答案 citation 对应的 source。
- 未使用 chunk 的原因。

### 7.4 验收标准

- 至少一个问答入口支持 inspector。
- 每个 source 有 score 和 metadata。
- 最终答案能展示来源引用。
- eval 中有 retrieval hit rate 指标。

## 8. P1-2：Memory Center

### 8.1 目标

把学生画像和长期记忆做成可查看、可删除、可解释的 memory 管理体验。

### 8.2 涉及模块

- `backend/student_profile.py`
- `backend/user_memory.py`
- `backend/security/audit_log.py`
- `frontend/app/memory/page.tsx`

### 8.3 页面内容

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

### 8.4 记忆类型建议

- weak_point
- interest
- learning_preference
- recent_mistake
- teacher_note
- review_goal

### 8.5 验收标准

- 用户能查看学生画像和学习事件。
- 用户能删除或禁用一条 memory。
- Agent 回答能显示使用了哪些 memory。
- audit log 记录 memory 删除行为。

## 9. 推荐实施顺序

### Iteration 1：Agent Runtime 可视化

优先级：最高。

交付内容：

1. 统一 trace event schema。
2. 学习助手后端返回 trace events。
3. `run_tool()` 记录 tool execution event。
4. 学习助手前端展示 timeline。
5. 失败 step 可视化。

完成后演示路径：

1. 打开学习助手。
2. 输入一个需要工具调用的问题。
3. 查看 Agent timeline。
4. 展示 tool input、risk level、result 和 latency。

### Iteration 2：Tool Governance

优先级：最高。

交付内容：

1. 强制 role / confirmation 检查。
2. 新增 high-risk demo tool。
3. 前端确认卡片。
4. audit log 记录治理决策。
5. 增加 tool permission eval cases。

完成后演示路径：

1. 触发 high-risk demo tool。
2. 查看 confirmation_required。
3. 点击确认。
4. 查看工具执行结果和 audit log。

### Iteration 3：Eval Dashboard 作品集化

优先级：最高。

交付内容：

1. 规范 eval report schema。
2. 增加指标卡片。
3. 展示 failed cases。
4. 增加 tools / rag / safety 分类。
5. 支持 quick eval 和报告下载。

完成后演示路径：

1. 打开 eval dashboard。
2. 查看 pass rate 和核心指标。
3. 点击 failed case。
4. 展示失败原因和 regression 价值。

### Iteration 4：RAG Inspector + Memory Center

优先级：高。

交付内容：

1. 问答页面展示 retrieved chunks。
2. 展示 vector score / rerank score / citation。
3. 新增 memory center。
4. 支持 memory 删除或禁用。
5. 回答中展示 used memory。

完成后演示路径：

1. 提出一个历史知识问题。
2. 展示 RAG inspector。
3. 查看引用来源。
4. 打开 memory center。
5. 删除或禁用一条 memory。

## 10. 暂不优先投入的方向

下一阶段暂不建议优先投入：

- 更多学科页面。
- 更多游戏类型。
- 更多普通聊天入口。
- 复杂学校 / 班级 / 组织管理。
- 商业化套餐权限。
- 大量静态 dashboard。

原因是这些更偏教育 SaaS 产品扩展，对 AI Agent 工程师作品集的边际加分不如 runtime、tool governance、eval、RAG inspector 和 memory explainability。

## 11. 最小可交付版本

如果只做一个最小但完整的下一阶段版本，建议锁定以下 3 个成果：

1. Learning Assistant Trace Timeline。
2. High-risk Tool Confirmation Demo。
3. Eval Dashboard 2.0。

这三个成果可以形成清晰演示链路：

```text
学习助手提问
  ↓
展示 Agent trace timeline
  ↓
点开 tool call 查看 schema / risk / latency
  ↓
触发 high-risk tool confirmation
  ↓
打开 eval dashboard 查看回归测试和失败 case
```

## 12. 面试展示话术

完成后可以这样介绍 EduAgent：

> EduAgent 是一个面向 K-12 历史与语文学习的教育 Agent 平台。它不仅支持角色对话、材料学习、作文批改和游戏化学习，还实现了生产级 Agent 工程能力：Agent trace 可视化、schema-first tool calling、工具权限治理、human confirmation、audit log、RAG grounding、eval dashboard、AgentOps summary 和学生长期记忆管理。

推荐演示顺序：

1. 打开学习助手，提出一个需要工具调用的问题。
2. 展示 Agent step timeline。
3. 点开 tool call，查看 input schema、risk level、result 和 latency。
4. 触发 high-risk tool，展示 confirmation。
5. 打开 eval dashboard，查看 pass rate 和 failed cases。
6. 打开 AgentOps summary，查看 trace coverage、audit events 和 tool failures。
7. 打开 RAG inspector，查看 retrieved chunks 和 citations。
8. 打开 memory center，查看学生画像和本次回答使用的记忆。

## 13. 完成定义

下一阶段完成后，项目应满足：

- Agent 执行过程可见。
- 工具调用有后端强制权限边界。
- 高风险工具有人类确认机制。
- eval 报告稳定生成并可视化。
- RAG 检索和引用可解释。
- 长期记忆可查看、可删除、可解释。
- audit log 和 AgentOps 能支撑调试与作品集展示。

达到这些标准后，EduAgent 的作品集定位会从“教育 AI 应用”明显升级为“生产级 Agent 工程能力展示项目”。
