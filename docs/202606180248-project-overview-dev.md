# EduAgent 项目开发文档

**更新日期**: 2026-06-18

---

## 1. 项目定位

EduAgent 是面向初中的 AI 教学平台，当前以历史/语文科目为主，包含教材同步、历史角色对话、游戏化练习、材料学习、作文批改、学习助手和学情分析七个核心场景。

同时作为 AI Agent 工程作品集，项目覆盖 LangGraph workflow、RAG、多模态文档处理、Tool Calling、流式交互、Eval、AgentOps 和 Guardrails 等核心工程能力。

---

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 14 App Router · TypeScript strict |
| 后端 | FastAPI · Python 3.12 |
| Agent 框架 | LangGraph 状态图 |
| LLM 调用 | `backend/llm_config.py` → `zode_client.js`（支持 Anthropic / Bailian / DashScope）|
| RAG | Chroma + BGE-large-zh-v1.5（CPU）|
| Session 存储 | Redis（优先）/ 内存 fallback |
| 追踪 | Langfuse（`backend/tracing.py`）|
| 认证 | JWT，`backend/security/auth.py` |

---

## 3. 路由结构

### 学生端（带侧边栏，`/(student)/layout.tsx`）

```
/student                    今日学习仪表盘
/student/textbook           教材同步学习（→ textbook-learning/）
/student/materials          资料学习（→ material-upload/）
/student/assistant          学习助手（→ learning-assistant/）
/student/history/chat       人物对话馆（→ history-character/）
/student/history/debate     历史辩论场（→ history-debate/）
/student/history/games      历史游戏厅（→ history-games/）
/student/history/map        历史地图（→ history-map/）
/student/dashboard          学情分析（→ student-dashboard/）
/student/quiz               智能练习（→ quiz-practice/）
/student/memory             记忆中心（→ memory/）
```

### 游戏子页面（无侧边栏，独立路由）

```
/history-games/multiplayer  时间巨轮（多人对战，返回 /student/history/games）
/history-games/card-game    AI 卡牌游戏（返回 /student/history/games）
```

> `/history-games/timeline` 与 multiplayer 机制高度重叠，待评估是否保留。

### 教材子页面（无侧边栏）

```
/textbook-learning/[bookId]                    教材目录（返回 /student/textbook）
/textbook-learning/[bookId]/[lessonId]         课文学习页
```

### 教师端（带侧边栏，`/(teacher)/layout.tsx`）

```
/teacher                    班级总览
/teacher/grading?tab=essay  作文批改
/teacher/grading?tab=homework 拍照批改
/teacher/materials          资料生成
/teacher/resources          资源库
/teacher/students/[id]      学生详情
```

---

## 4. 后端模块

### Agent 模块（`backend/agents/`）

| 文件 | 功能 |
|---|---|
| `history_character.py` | 历史角色对话：RAG 检索 → 一人称教学 → 质量校验 → fact_card。SSE 流式输出。|
| `learning_assistant.py` | 学习助手：意图识别 → Tool 路由 → 结果整合 |
| `essay_grader.py` | 作文批改：LangGraph 状态图 |
| `debate_supervisor.py` | 历史辩论：多 Agent 裁判编排 |
| `multiplayer_game.py` | 时间巨轮多人对战逻辑 |
| `card_game.py` | AI 卡牌游戏判题 |
| `history_map_agent.py` | 历史地图问答 |
| `history_games.py` | 游戏定义注册表 + 游戏 round 管理 |

### Tool 系统（`backend/tools/`）

- `base.py`：`ToolSpec`（含 schema、`risk_level`、`required_role`、`requires_confirmation`）
- `registry.py`：`run_tool()` 统一执行入口
- 工具文件：`history_search`、`textbook_tools`、`quiz_tools`、`profile_tools`、`game_tools`、`character_tools`

### 安全（`backend/security/`）

- `auth.py`：JWT 认证
- `rate_limit.py`：速率限制
- `prompt_injection.py`：Prompt 注入检测
- `audit_log.py`：操作审计，关联 `trace_id`

### 数据持久化

- `session_store.py`：对话历史（Redis / 内存）
- `student_profile.py`：学生学情画像
- `user_memory.py`：长期用户记忆
- `game_store.py`：游戏 round 状态

---

## 5. RAG 与知识库

- 历史知识库：`knowledge_base/history/corpus.json` → Chroma（`.chroma/`）
- 索引构建：`python3 build_index.py`
- 教材来源：`textbooks/structured/*.yaml`（YAML 结构化知识点）
- 转换流程：`python3 scripts/parse_textbook.py && python3 build_index.py`
- 嵌入模型：`BAAI/bge-large-zh-v1.5`（本地 CPU）
- 检索前缀：`为这个句子生成表示以用于检索相关文章：`

---

## 6. LLM 配置

通过 `.env.local` 配置：

```
LLM_PROVIDER=anthropic | bailian | dashscope
ANTHROPIC_API_KEY=...
LLM_MODEL_FAST=claude-haiku-4-5-20251001
LLM_MODEL_QUALITY=claude-sonnet-4-6
LLM_MODEL_REASONING=claude-opus-4-6
```

调用链：`llm_config.py` → `zode_client.js`（Node 子进程）

---

## 7. 开发命令

```bash
# 安装依赖
pip install -r backend/requirements.txt
npm install --prefix frontend

# 启动（需 .env.local）
npm run dev                     # 同时启动 backend:8000 + frontend:3000
npm run dev:backend             # 仅后端
npm run dev:frontend            # 仅前端

# 构建索引
python3 build_index.py

# Eval
python3 eval/run_core_evals.py  # 运行所有核心评测
python3 eval/history_character_smoke.py
```

---

## 8. Eval 与可观测性

- Eval 脚本：`eval/` 目录，`run_core_evals.py` 生成 `eval/reports/latest.json`
- Eval 前端：`/eval` 页面展示评测结果
- Tracing：Langfuse，`backend/tracing.py` 封装 span/generation
- AgentOps：`backend/agent_ops.py`，汇总运行数据

---

## 9. 当前能力完成度

| 模块 | 完成度 | 备注 |
|---|---|---|
| 前端产品化（侧边栏导航）| 高 | 2026-06-17 完成 UX 重排布 |
| LangGraph Agent Workflow | 高 | character、essay、debate 均已落地 |
| RAG 检索 | 高 | 历史知识库 + 用户材料双路径 |
| 流式 SSE 交互 | 高 | character chat 已完整实现 |
| 多模态文档处理 | 中高 | 材料上传 OCR 转写已完成 |
| Tool Calling | 中 | 工具注册完善，schema-first 待强化 |
| Eval / 回归测试 | 中高 | 脚本完整，CI 闭环待建 |
| Guardrails | 中 | 基线安全完备，工具级治理待加强 |
| AgentOps / 可观测 | 中 | Langfuse 接入，trace-to-eval 闭环待做 |
| 部署 | 中 | 有 Dockerfile，CI/CD 待建 |

---

## 10. 下一阶段优先事项

1. **P0** 删除冗余游戏页面（timeline），游戏厅仅保留 multiplayer + card-game
2. **P0** Agent 执行轨迹可视化（学习助手 trace 展示）
3. **P0** Eval Dashboard 作品集化（指标趋势图、回归对比）
4. **P1** Tool Governance 前端演示（risk_level、confirmation 流程可见）
5. **P1** RAG Inspector（检索命中、rerank 分数可视化）
6. **P2** CI eval 自动化（commit → eval → report）
