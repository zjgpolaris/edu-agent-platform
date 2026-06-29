# EduAgent — AI Agent 工程作品集文档

**创建时间：** 2026-06-22  
**项目定位：** K-12 历史·语文 AI 学习平台 · AI Agent 工程师作品集

---

## 一、项目概述

EduAgent 是一个面向 K-12 历史与语文学习的垂直教育 Agent 平台。核心目标不是单纯的功能覆盖，而是通过生产级 Agent 工程能力的落地，展示 AI Agent 工程师的系统设计与实现水平。

> 把 EduAgent 从"功能完整的教育 AI 应用"升级为"可评测、可观测、可治理、可迭代的教育 Agent 工程作品集"。

### 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | FastAPI + LangGraph + Chroma + SQLite + Redis |
| 前端 | Next.js 14 App Router + TypeScript strict |
| LLM | Anthropic Claude（通过 `llm_config.py` 统一路由） |
| Embedding | BGE-large-zh（本地 CPU） |
| 可观测性 | Langfuse + 自建 AgentOps |
| CI/CD | GitHub Actions（4-job pipeline） |

---

## 二、Agent 工程能力清单

### 2.1 Agent 执行轨迹可视化

学习助手右侧 **Agent Observability 面板**，4个 tab：

| Tab | 内容 |
|-----|------|
| Timeline | 每步名称、状态、延迟、metadata；失败步红色高亮 |
| RAG Inspector | 召回 chunks、score、source_mode；相关性条形图 |
| Tools | 工具注册表、risk_level、requires_confirmation、当前执行中高亮 |
| Memory | 本次回答使用了哪些记忆及原因，链接 Memory Center |

后端统一 step schema（SSE `runtime_step` 事件）：

```json
{
  "trace_id": "abc123",
  "agent_name": "learning_assistant",
  "step_name": "Tool Execution",
  "sequence": 4,
  "status": "success",
  "latency_ms": 220,
  "metadata": { "tool_name": "search_history_knowledge", "risk_level": "low" }
}
```

### 2.2 Tool Permission / Confirmation

`ToolSpec` 治理字段实际参与执行决策：

| risk_level | 行为 |
|------------|------|
| low | 直接执行 |
| medium | 执行 + 强制 audit |
| high | 前端确认弹窗，未确认拒绝执行 |

`required_role` 不匹配时返回 `role_denied`；`requires_confirmation=true` 时返回 `confirmation_required`，前端展示确认卡片，用户决策后重新提交。所有决策写入 audit log。

### 2.3 Trace Coverage

`ContextVar` 在 `run_in_threadpool` 中不可靠传播（coverage 0%）的修复方案：

1. `tracing.py` 新增 `bind_trace_id(trace_id)`
2. `main.py` 在两条路径中注入 `request_data["trace_id"] = trace_id`
3. `learning_assistant.py` 生成器启动时调用 `bind_trace_id(req.get("trace_id"))`

### 2.4 Agent Memory 管理

`/memory`（Memory Center）：

- Student Profile：strong / weak / recent topics，character interests
- Typed Memory Entries：type、content、confidence、source_feature、last_used_at；支持禁用/删除
- Learning Events：完整事件历史，支持删除
- Audit Trail：记忆操作审计日志

### 2.5 AgentOps Summary

`/eval` 页面 AgentOps 面板：trace 关联率、audit 事件分布、学习事件分布、工具调用统计、最近 trace 列表。

---

## 三、核心业务功能

### 3.1 统一学习助手

LangGraph-style 意图路由 + 工具调用：

| 意图 | 工具 | 说明 |
|------|------|------|
| textbook_qa | get_textbook_lesson | 教材段落检索 |
| history_search | search_history_knowledge | RAG 史料检索 |
| quiz_generation | generate_quiz | 出题 + 答对删错题本 |
| character_recommendation | recommend_character | 个性化人物推荐 |
| timeline_game | start_timeline_game | 跳转时间线游戏 |
| memory_delete_demo | delete_demo_memory | 高风险工具演示 |

### 3.2 拍照作业批改 + 教师审核流（Human-in-the-loop）

```
上传图片/PDF → OCR → 题目抽取 → 人工校对 → AI 批改
  → 自动写入 weakpoints
  → 自动保存 homework_reviews（decision=pending）
  → 教师端"待审核"列表（ /teacher/grading?tab=reviews ）
  → accept / edit score / reject + 备注
  → reject/edit → "加入回归测试" → eval/datasets/
```

### 3.3 错题本闭环

```
批改/游戏答题/测验答错 → POST weakpoints
  → 错题本页面（按频率+来源分类）
  → 学习助手生成复习题 → 答对 DELETE weakpoint → "✅ 已从错题本移除"
```

### 3.4 多 Agent 历史辩论（5 agents）

```
正方 × 3轮 → 反方 × 3轮
  → Fact Checker（史实核查）
  → Judge（三维度评分 + 宣判）
  → Learning Coach（转化为3条学习建议）
```

每个 agent 输出实时可见，SSE 流式传输。

### 3.5 其他功能

- 历史人物对话（RAG + 质量验证 + fact-card）
- 教材阅读 + AI 问答（带来源引用）
- 历史游戏（时间线 / 卡牌 / 多人）
- 历史地图叙事
- 学生画像 + 个性化复习方案

---

## 四、Evaluation Engineering

### Quick Eval Suite（8个，全部离线可运行）

| Suite | 类别 |
|-------|------|
| history_character_smoke | agent |
| rag_retrieval_eval | rag |
| material_rag_smoke | rag |
| tool_registry_smoke | tools |
| learning_assistant_smoke | tools |
| guardrails_smoke | safety |
| weakpoints_smoke | memory |
| trajectory_eval | agent |

### 核心指标

`task_success_rate` / `retrieval_hit_rate` / `tool_schema_validity` / `guardrail_pass_rate` / `format_validity` / `avg_latency_ms`

### Trace-to-Eval 回流

教师 reject → `POST /api/eval/save-case` → `eval/datasets/homework_grading_smoke_cases.json` → 下次 eval 自动覆盖

---

## 五、CI/CD

```yaml
jobs:
  frontend:       # lint + build（Node 20）
  backend-verify: # pip install + verify_core.py --smoke
  quick-eval:     # run_core_evals.py --quick → 上传报告 + PR 评论
  docker-build:   # backend/Dockerfile + frontend/Dockerfile
```

---

## 六、Portfolio 演示顺序

1. 学习助手输入"鸦片战争为什么重要？" → 观察 Timeline step，展开 tool call
2. 输入"帮我出1道练习题" → 选择正确答案 → "✅ 已从错题本移除"
3. 切换 RAG Inspector → 看召回 chunks 和 score
4. 切换 Memory tab → 看"本次使用了哪些记忆"
5. 打开历史辩论 → 输入辩题 → 看5个 agent 依次运行
6. 打开 Eval 页面 → 看 quick eval 报告和 AgentOps 面板
7. 打开教师端"待审核" → accept/reject + "加入回归测试"

---

## 七、关键文件索引

```
backend/
  agents/learning_assistant.py   # 核心 Agent
  agents/debate_supervisor.py    # 5-Agent 辩论
  homework_grading/review_store.py # 教师审核存储
  tracing.py                     # trace_context + bind_trace_id
  agent_ops.py                   # AgentOps summary
  tools/registry.py              # 工具执行 + 权限

frontend/app/
  learning-assistant/            # 统一学习助手（4tab 观察面板）
  history-debate/                # 多Agent辩论
  homework-grading/              # 拍照批改
  memory/                        # Memory Center
  eval/                          # Eval Dashboard
  (teacher)/teacher/grading/     # 教师审核流

eval/
  run_core_evals.py              # Eval runner
  reports/latest.json            # 最新报告

.github/workflows/ci.yml         # CI/CD pipeline
```
