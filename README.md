# EduAgent — K-12 AI 教学辅助平台

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://edu-agent-platform.vercel.app)
[![Backend](https://img.shields.io/badge/backend-render-blue)](https://edu-agent-backend-1e5x.onrender.com/api/debug/llm/health)

**Live Demo：** [edu-agent-platform.vercel.app](https://edu-agent-platform.vercel.app)
> 演示账号：`demo-student` / `demo123`（进入「自主辅导」可直接看 AutoTutor 运行）

---

## 亮点功能：AutoTutor 自主辅导 Agent

> 给定一个学生，Agent 自己决定教什么、怎么教、答错了怎么补——全程可观测、可评测、可干预。

```
plan ──> act ──> observe ──> judge ──┬── pass ──> next_step ──> finalize
                                     └── fail ──> reflect ──> re_plan ──> act
```

与普通固定流水线的核心差异：

- **Plan**：读学生画像 + 错题本，自主生成本节课知识点顺序与教学策略
- **Reflect / Re-plan**：答错时诊断原因（讲得不对 / 题超纲），动态改变后续计划
- **全程 Trace**：每个 node 写入 trace_store，右侧 TraceTimeline 实时可见
- **课后自适应**：掌握的知识点移出错题本，薄弱点进入 SM-2 复习排期

---

## 5 分钟主线 Demo

先灌入稳定演示数据：

```bash
PYTHONPATH=backend python3 scripts/seed_demo_student.py
```

学生主线：

1. 登录 `demo-student` / `demo123`，进入 `/student` 查看今日计划和薄弱点。
2. 打开 `/student/learning-path` 或 `/student/review?tab=weakpoints`，确认错题本已预置「鸦片战争」等知识点。
3. 打开 `/student/auto-tutor?focus=鸦片战争`，让 AutoTutor 围绕指定薄弱点启动教学。
4. 故意答错一次，观察 Agent 进入 `reflect` / `re_plan`，并在右侧 TraceTimeline 看到节点轨迹。
5. 打开 `/eval`，展示 Eval / AgentOps 的 readiness、成功率、trace 与工具调用统计。

教师补充：

1. 登录 `teacher_zhang` / `teacher123`。
2. 打开 `/teacher` 或 `/teacher/assignments`，展示教师端布置作业与班级工作流入口。
3. 如需完整 pilot 教师工作流，可运行 `PYTHONPATH=backend python3 scripts/seed_pilot_demo.py` 后使用脚本输出的 pilot 账号。

---

## 功能全景

### 学生端
| 功能 | 路径 | 说明 |
|------|------|------|
| **自主辅导 AutoTutor** | `/student/auto-tutor` | 自主 plan→reflect→re_plan 闭环 |
| 历史人物对话 | `/history-character` | RAG 取材 + 流式 SSE + 来源引用 |
| 学习助手 | `/student/assistant` | 工具调用 + RAG + 确认治理 |
| 今日复习 | `/student/review` | SM-2 间隔复习调度 |
| 错题本 | `/student/weakpoints` | 薄弱点管理 |
| 学习记忆 | `/student/memory` | Agent 写入的长期记忆 |
| 历史游戏厅 | `/history-games` | 时间线 / 卡牌 / 多人竞技 |
| 历史辩论 | `/history-debate` | 辩论 supervisor agent |
| 历史时空地图 | `/history-map` | 地理事件可视化 |
| 教材学习 | `/student/textbook` | 结构化教材同步 |
| 作业列表 | `/student/assignments` | 教师布置的作业 |
| 成长报告 | `/student/report` | 学习成长分析 |

### 教师端
| 功能 | 路径 | 说明 |
|------|------|------|
| 布置作业 | `/teacher/assignments` | 作业工作流管理 |
| 作文批改 | `/teacher/grading` | 智能批改 + 评分反馈 |
| 学情总览 | `/teacher/students` | 班级薄弱点分析 |
| 资料库 | `/teacher/materials` / `resources` | RAG 材料管理 |

### 可观测性 / 评测
| 功能 | 说明 |
|------|------|
| Agent Trace | TraceTimeline 可视化每个 node 执行状态与耗时 |
| Eval Dashboard | `/eval` 页面，快速查看各 agent 指标、readiness 与 AgentOps 聚合 |
| RAG Inspector | 检索来源面板，每条引用可溯源，并区分 retrieval / generation 失败归因 |
| Tool 确认治理 | 高危工具调用弹出确认对话框 |

---

## 技术架构

```
浏览器 ──> Vercel (Next.js 14) ──fetch──> Render (FastAPI / Docker)
                                                   ├──> Supabase Postgres + pgvector (RAG)
                                                   ├──> Bailian / DashScope (LLM)
                                                   └──> Jina Embeddings v3 (向量化)
```

| 层 | 技术 |
|----|------|
| 前端 | Next.js 14 App Router, TypeScript strict, SSE 流式输出 |
| 后端 | FastAPI, Python 3.12, LangGraph 风格状态图 |
| 数据库 | Supabase Postgres + pgvector（RAG 向量索引） |
| LLM | 阿里云百炼（qwen3.7-plus / deepseek-v4-flash） |
| Embedding | Jina Embeddings v3（1024维，2850文档） |
| 会话存储 | Redis（本地）/ 进程内存兜底（生产） |
| CI/CD | GitHub Actions：frontend lint + release gate + quick-eval；Docker build 在 main/manual 验证 |

---

## 本地开发

```bash
# 1. 克隆并安装依赖
git clone <repo>
cd edu-agent-platform
pip install -r backend/requirements.txt
npm install --prefix frontend

# 2. 复制并填写环境变量
cp .env.example .env.local
# 填写 BAILIAN_API_KEY / DATABASE_URL / EMBED_API_KEY 等

# 3. 启动（后端 :8000 + 前端 :3000）
npm run dev
```

### 重建 RAG 向量索引

```bash
# 本地使用 pgvector（需已配置 DATABASE_URL）
python3 scripts/build_pgvector_index.py

# 或使用本地 Chroma（需本地 embedding 模型）
python3 build_index.py
```

### Smoke / 发布前验证

```bash
npm run test                          # 全套 smoke
npm run test:mcp                      # MCP server 协议 smoke
npm run test:rag-inspector            # RAG Inspector 检索调试 smoke
npm run test:agent-ops                # AgentOps 成本/延迟/fallback 聚合 smoke
npm run test:textbook-trace           # 教材问答 trace / rag_inspector 埋点 smoke
npm run test:autotutor-recovery       # AutoTutor 会话恢复 smoke
npm run test:release-gate             # release gate / readiness summary smoke
npm run release:gate                  # 发布前统一闸门：Python 语法检查 + 后端 smoke + 前端 build
npm run release:gate:fast             # 快速关键路径发布闸门
python3 eval/auto_tutor_trajectory_eval.py  # AutoTutor 轨迹评测

# 生产 RAG / readiness 验收：不属于默认 PR CI，需线上 API_BASE 与认证
API_BASE=https://<后端> SMOKE_USERNAME=<user> SMOKE_PASSWORD=<password> \
  npm run release:gate:prod -- --skip-frontend --ready-url https://<后端>/api/ready
npm run test:prod-rag                 # 显式运行生产 RAG 健康检查
```

健康检查分层：`/api/health` 是 liveness；`/api/ready` 是 shallow readiness，默认不触发外部 LLM/Embedding；`/api/debug/rag/health?deep=true` 与 `production_rag_health_smoke.py` 用于生产 RAG 深度检查。
传入 `--ready-url` 时，release gate 现在会输出 required / failed / warnings 摘要；若带 `--production`、`--ready-require-rag` 或 `--ready-require-external`，会把 RAG / 外部依赖配置作为 blocking readiness check。

AgentOps 的 production summary 现在会额外聚合最近 trace 中的 RAG 诊断口径，包括 `diagnosis_code` 分布和 `failure_stage` 分布，便于区分问题主要发生在检索阶段还是生成阶段；教材问答与历史人物两条链路都已接入该统计。

### MCP Server

EduAgent 提供一个轻量 stdio MCP server，用于展示标准 Agent 工具协议适配。它只暴露现有 Tool Registry 中的 4 个工具，并继续复用 `run_tool()` 的 schema 校验、角色策略、确认元数据、审计与 trace：

| MCP tool | 说明 |
|----------|------|
| `search_history_knowledge` | 检索历史知识库 |
| `get_textbook_lesson` | 读取结构化教材课文 |
| `suggest_review_plan` | 基于学生画像生成复习建议 |
| `generate_quiz` | 基于教材课文生成自测题 |

本地启动：

```bash
npm run mcp:server
```

本地协议 smoke：

```bash
npm run test:mcp
```

---

## 部署

详见 [`docs/202606291600-autotutor-deploy-dev.md`](docs/202606291600-autotutor-deploy-dev.md)

| 服务 | 平台 | 配置文件 |
|------|------|---------|
| 后端 | Render (Docker) | `render.yaml` |
| 前端 | Vercel | `frontend/vercel.json` |
| 数据库 | Supabase | `DATABASE_URL` 环境变量 |

灌入 demo 种子数据：

```bash
PYTHONPATH=backend python3 scripts/seed_demo_student.py
# 账号：demo-student / demo123
```

---

## 项目结构

```
edu-agent-platform/
├── backend/
│   ├── agents/          # Agent 实现（auto_tutor, history_character, ...）
│   ├── api/main.py      # FastAPI 入口
│   ├── rag/             # ChromaDB / pgvector 知识库
│   ├── tools/           # 工具注册 + 治理
│   ├── services/        # weakpoint, SM-2 复习等业务服务
│   └── trace_store.py   # Agent 执行轨迹存储
├── frontend/
│   └── app/
│       ├── (student)/   # 学生端页面
│       └── (teacher)/   # 教师端页面
├── eval/                # Smoke 测试 + 轨迹评测
├── knowledge_base/      # 历史语料库
├── textbooks/           # 结构化教材 YAML
└── scripts/             # 数据处理工具
```
