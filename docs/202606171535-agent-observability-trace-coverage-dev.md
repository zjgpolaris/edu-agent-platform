# EduAgent Agent 可观察性完善开发文档

## 1. 背景

当前 EduAgent 已完成 Agent Runtime 可视化、Tool Governance、Eval Dashboard、RAG Inspector 和 Memory Center 五个核心迭代，整体工程能力已初步成型。

但以下问题影响作品集展示质量：

- Trace 覆盖率仅 12%（23/200 events），AgentOps 页面标注 `needs attention`。
- Trace-to-Eval 流程最后一步"缺少字段: payload"，保存按钮不可用，闭环未打通。
- 历史人物 Smoke suite SKIPPED（0/1 cases），核心功能无回归保障。
- `essay_grader.py` 和 `debate_supervisor.py` 不在统一 trace 体系内。

本文档描述修复上述问题的开发计划。

## 2. 总体目标

> 将 EduAgent 的 Agent 可观察性从"局部可观测"升级为"全链路统一可观测"，并打通 Trace → Audit → Eval 的生产闭环。

## 3. P0：Trace 覆盖率修复

### 3.1 问题

目前只有 `learning_assistant.py` 使用 `trace_context()` 包裹请求，其他 agent 的调用均未绑定 trace_id，导致 Audit Events 和 Learning Events 中大量条目无法关联 trace，覆盖率 12%。

### 3.2 涉及模块

| 模块 | 当前状态 |
|---|---|
| `backend/agents/history_character.py` | 无 `trace_context()` |
| `backend/agents/essay_grader.py` | 无 `trace_context()` |
| `backend/agents/debate_supervisor.py` | 无 `trace_context()` |
| `backend/api/main.py` | 各路由未注入 trace_id |

### 3.3 方案

在 `backend/api/main.py` 的各 agent 路由入口处注入 `trace_context()`，与 `learning_assistant.py` 保持一致的模式：

```python
# 参考 learning_assistant.py 的已有实现
from tracing import trace_context, current_trace_id

async def history_character_chat(...):
    with trace_context(trace_id=..., user_id=actor.actor_id, ...):
        # 原有逻辑
```

每个路由需传入：
- `trace_id`：从请求 header 读取或生成新 UUID
- `user_id`：从 `actor.actor_id` 获取
- `session_id`：从请求中获取
- `metadata`：feature 名称（`history_character` / `essay_grader` / `debate`）

### 3.4 验收标准

- Trace 覆盖率从 12% 提升至 70% 以上。
- AgentOps 页面 `partial_trace_coverage` 标签消失或覆盖率标注变绿。
- 历史角色对话的 audit log 条目有 `trace_id` 字段。

## 4. P1：Trace-to-Eval 闭环打通

### 4.1 问题

`eval/page.tsx` 底部 Trace-to-Eval 面板已能从 audit log 中提取 `tool.confirmation_required` 事件，但最后一条显示"缺少字段: payload"，保存按钮置灰，无法写入 eval dataset。

### 4.2 涉及模块

- `backend/tools/registry.py`：`record_audit_event()` 调用处，确认 `metadata` 是否包含完整 payload
- `backend/api/main.py`：Trace-to-Eval 保存接口
- `frontend/app/eval/page.tsx`：保存按钮逻辑

### 4.3 方案

**后端**：检查 `registry.py` 中 `tool.confirmation_required` 事件的 `metadata_json`，确保包含以下字段：

```json
{
  "tool_name": "delete_demo_memory",
  "risk_level": "high",
  "payload": { "student_id": "...", "memory_id": "..." },
  "confirmation_token": "...",
  "required_role": "student"
}
```

若 `payload` 字段缺失，在 `registry.py` 记录审计事件时将 `tool_input`（已有）写入 `payload` 键。

**后端接口**：新增或确认 `POST /api/eval/cases` 接口，接收 Trace-to-Eval 保存请求，将事件写入 `eval/dataset/` 目录下的 JSONL 文件。

**前端**：保存成功后刷新 Trace-to-Eval 列表，已保存条目标注 `saved` 状态。

### 4.4 推荐 eval case 结构

```json
{
  "id": "case_auto_20260617_001",
  "source": "trace_to_eval",
  "suite": "tool_permission_eval",
  "category": "tools",
  "trace_id": "39fa7120824148c2ba49b0a37506b82d",
  "audit_event_id": "...",
  "tool_name": "delete_demo_memory",
  "input": { "student_id": "student_001", "memory_id": "demo_wrong_memory_001" },
  "expected": "confirmation_required",
  "created_at": "2026-06-17T15:29:00+08:00"
}
```

### 4.5 验收标准

- Trace-to-Eval 面板所有条目"payload"字段完整，无"缺少字段"提示。
- 点击保存后，case 写入 `eval/dataset/` 并展示 `saved` 标注。
- 下次运行 eval 时，自动保存的 case 参与 `tool_permission_eval` suite 回归。

### 4.6 作品集价值

Trace-to-Eval 闭环是区别于普通 eval 的核心亮点：

```
生产请求触发 tool.confirmation_required
  ↓
audit log 自动捕获
  ↓
Trace-to-Eval 面板一键保存为 eval case
  ↓
下次 eval run 自动回归
```

这是"生产观测反哺质量体系"的完整演示。

## 5. P2：历史人物 Smoke 修复

### 5.1 问题

`历史人物 Smoke` suite 状态为 SKIPPED（0/1 cases），说明该 case 在执行前被跳过，可能原因：
- 依赖的服务未启动（Chroma / embedding model）
- case 本身有前置条件未满足
- `eval/run_core_evals.py` 中该 suite 被条件跳过

### 5.2 涉及模块

- `eval/run_core_evals.py`：历史人物 suite 定义
- `backend/agents/history_character.py`：被测 agent
- `eval/history_character_smoke.py`：原有 smoke 脚本（若存在）

### 5.3 方案

1. 定位 skip 原因：检查 `run_core_evals.py` 中该 suite 的 skip 条件。
2. 若是 embedding model 路径问题：在 CI/eval 环境中提供 mock embedding，或为该 suite 增加 `requires_embedding: true` 标注并在报告中说明。
3. 若是依赖问题：在 suite 前增加服务健康检查，unhealthy 时标注 `skipped(infra)` 而非静默跳过。

### 5.4 验收标准

- 历史人物 Smoke suite 在本地运行时有明确状态（PASSED 或带原因的 SKIPPED）。
- 若需要 embedding model，skip 原因在 eval report 中可见。

## 6. P3：Essay / Debate Agent 接入 Trace 体系

### 6.1 目标

将作文批改和辩论 supervisor 纳入统一 trace 体系，使 AgentOps 能覆盖全部 agent 功能。

### 6.2 方案

与 P0 方案一致：在 `/api/chinese/essay/grade` 和 `/api/history/debate/start` 路由入口注入 `trace_context()`，并在 agent 内部关键节点调用 `start_span() / end_span()`。

不需要像 `learning_assistant.py` 那样完整的 RuntimeStep timeline——仅需 trace_id 绑定和基本 span 即可。

### 6.3 验收标准

- 作文批改和辩论请求的 audit log 条目有 `trace_id`。
- AgentOps Top features 中出现 `essay_grader` 和 `debate`。

## 7. 实施顺序

| 阶段 | 工作 | 预估工时 |
|---|---|---|
| P0 | Trace 覆盖率修复（4 个 agent 路由接入） | 1-2 天 |
| P1 | Trace-to-Eval payload 修复 + 保存接口 | 1 天 |
| P2 | 历史人物 Smoke 修复 | 半天 |
| P3 | Essay / Debate trace 接入 | 1 天 |

## 8. 验证路径

完成后演示链路：

```
1. 打开学习助手，提问
   → Timeline 有 7 步，trace_id 展示
   
2. 打开历史角色对话，提问
   → AgentOps 覆盖率提升，audit log 有 trace_id

3. 打开 Eval Dashboard，运行 quick eval
   → 历史人物 Smoke 不再 SKIPPED
   
4. 触发 delete_demo_memory 确认流程
   → Trace-to-Eval 面板出现新条目，点击保存成功
   
5. 重新运行 eval
   → 自动保存的 case 参与回归，tool_permission_eval 多一个 case
```

## 9. 完成定义

- Trace 覆盖率 ≥ 70%，AgentOps 不再显示 `needs attention`。
- Trace-to-Eval 保存流程可端到端跑通。
- 历史人物 Smoke 有明确通过或带原因的跳过状态。
- 作文批改和辩论请求出现在 AgentOps trace 记录中。
