# EduAgent 项目架构文档

**创建时间：** 2026-06-23
**项目名称：** EduAgent - K-12 中文/历史 AI 教学平台
**最后更新：** 2026-06-30

---

## 目录

- [项目概述](#项目概述)
- [目录结构](#目录结构)
- [后端架构](#后端架构)
- [前端架构](#前端架构)
- [API 接口](#api-接口)
- [数据模型](#数据模型)
- [核心功能](#核心功能)
- [测试](#测试)
- [开发规范](#开发规范)

---

## 项目概述

EduAgent 是一个 K-12 中文/历史 AI 教学平台，采用前后端分离架构：

- **后端：** FastAPI + LangGraph + Postgres/pgvector RAG
- **前端：** Next.js 14 App Router + TypeScript
- **数据存储：** Supabase PostgreSQL（未配置时本地 SQLite 降级）+ pgvector 向量库
- **LLM/Embedding：** 支持 Anthropic、Bailian、DashScope；生产 RAG embedding 走 OpenAI-compatible 托管 API（默认 Jina `jina-embeddings-v3`）

---

## 目录结构

```
edu-agent-platform/
├── backend/                    # 后端服务
│   ├── agents/                # AI 代理模块
│   ├── api/                   # FastAPI 路由
│   ├── homework_grading/      # 作业批改模块
│   ├── materials/             # 多模态资料库
│   ├── rag/                   # RAG 检索模块
│   ├── security/              # 安全模块
│   ├── services/              # 业务服务
│   ├── textbook_learning/     # 教材学习模块
│   ├── tools/                 # 工具注册表
│   ├── utils/                 # 工具函数
│   ├── agent_ops.py           # Agent 运维
│   ├── game_store.py          # 游戏状态存储
│   ├── llm_config.py          # LLM 配置
│   ├── session_store.py       # 会话存储
│   ├── student_profile.py     # 学生档案
│   ├── structured_output.py   # 结构化输出
│   ├── tracing.py             # 链路追踪
│   ├── trace_store.py         # Trace 存储与可视化
│   ├── user_memory.py         # 用户记忆
│   └── zode_client.js         # Node.js LLM 客户端
│
├── frontend/                  # 前端应用
│   ├── app/                   # Next.js App Router
│   │   ├── (student)/         # 学生端页面组
│   │   ├── (teacher)/         # 教师端页面组
│   │   ├── components/        # 共享组件
│   │   ├── history-character/ # 历史人物对话
│   │   ├── history-games/     # 历史游戏
│   │   ├── learning-assistant/# 学习助手
│   │   ├── materials/         # 资料库
│   │   ├── student-dashboard/ # 学生仪表板
│   │   ├── teacher/           # 教师端
│   │   └── ...
│   ├── components/            # 全局组件
│   │   ├── AuthGuard.tsx      # 认证守卫
│   │   ├── GlobalHeader.tsx   # 全局头部
│   │   ├── TraceTimeline.tsx  # Agent 执行轨迹组件
│   │   └── ToolConfirmationDialog.tsx  # 工具确认弹窗组件
│   ├── lib/                   # 工具库
│   └── public/                # 静态资源
│
├── docs/                      # 开发文档
├── eval/                      # 测试脚本
├── knowledge_base/            # 知识库（history/corpus.json、geo_events.json 等静态内容源）
├── scripts/                   # 脚本工具（含 build_pgvector_index.py 离线构建 RAG 向量索引）
├── textbooks/                 # 教材数据
├── .data/                     # 本地 SQLite 开发数据库（未设置 DATABASE_URL 时使用；无 pgvector RAG）
├── build_index.py             # RAG 索引构建入口（转发到 scripts/build_pgvector_index.py）
├── package.json               # 项目配置
├── CLAUDE.md                  # Claude 指导文档
├── PRD.md                     # 产品需求文档
└── schema.md                  # 本文档
```

---

## 后端架构

### 目录结构

```
backend/
├── agents/                    # AI 代理
│   ├── history_character.py       # 历史人物对话代理
│   ├── history_games.py           # 历史游戏代理
│   ├── character_recommender.py   # 人物推荐
│   ├── character_catalog.py       # 人物目录
│   ├── timeline_question_generator.py  # 时间线题目生成
│   ├── card_game.py               # 卡牌游戏
│   ├── multiplayer_game.py        # 多人游戏
│   ├── multiplayer_card_generator.py  # 多人卡牌生成
│   ├── multiplayer_ai_commentary.py  # AI 解说
│   ├── multiplayer_coach.py       # 多人教练
│   ├── essay_grader.py            # 作文批改
│   ├── debate_supervisor.py       # 辩论主持
│   ├── learning_assistant.py      # 学习助手
│   ├── auto_tutor.py              # AutoTutor 自主辅导闭环（plan→act→observe→judge→reflect→re_plan→finalize）
│   └── history_map_agent.py       # 历史地图代理
│
├── api/                       # FastAPI 路由
│   └── main.py                    # 主入口，所有 API 端点
│
├── homework_grading/          # 作业批改
│   ├── schema.py                   # 数据模型
│   ├── service.py                  # 批改服务
│   └── review_store.py             # 审核存储
│
├── materials/                 # 多模态资料库
│   ├── schema.py                   # 数据模型
│   ├── service.py                  # 服务
│   └── store.py                    # 存储层
│
├── rag/                       # RAG 检索
│   ├── knowledge_base.py          # 知识库
│   └── hybrid_search.py            # 混合检索
│
├── security/                  # 安全模块
│   ├── auth.py                    # 认证授权
│   ├── accounts.py                # 账户管理
│   ├── rate_limit.py              # 限流
│   ├── prompt_injection.py        # 提示词注入防护
│   └── audit_log.py               # 审计日志
│
├── services/                  # 业务服务
│   ├── batch_essay_service.py     # 批量作文批改
│   └── weakpoint_service.py       # 错题本服务（掌握度证据计数：答错强化，连续答对达阈值才移除）
│
├── textbook_learning/         # 教材学习
│   ├── schema.py                   # 数据模型
│   ├── service.py                  # 服务
│   ├── prompts.py                  # 提示词
│   └── loader.py                   # 加载器
│
├── tools/                     # 工具注册表
│   ├── registry.py                # 工具注册、权限检查、治理执行
│   ├── confirmation.py            # 确认令牌存储
│   ├── base.py                    # 基础工具
│   ├── character_tools.py         # 人物工具
│   ├── game_tools.py              # 游戏工具
│   ├── history_search.py          # 历史搜索
│   ├── profile_tools.py           # 档案工具
│   ├── quiz_tools.py              # 测验工具
│   └── textbook_tools.py         # 教材工具
│
├── utils/                     # 工具函数
│   └── ...
│
├── agent_ops.py               # Agent 运维
├── game_store.py              # 游戏状态存储
├── llm_config.py              # LLM 配置
├── session_store.py           # 会话存储
├── student_profile.py         # 学生档案
├── structured_output.py       # 结构化输出
├── tracing.py                 # 链路追踪
├── user_memory.py             # 用户记忆
└── zode_client.js             # Node.js LLM 客户端
```

### 核心模块说明

| 模块 | 说明 |
|------|------|
| `agents/` | AI 代理，使用 LangGraph 构建状态图 |
| `api/main.py` | FastAPI 主入口，所有 API 端点 |
| `homework_grading/` | 作业批改，支持拍照上传、OCR、AI 批改 |
| `materials/` | 多模态资料库，支持 PDF/图片上传、解析、RAG |
| `rag/` | RAG 检索，基于 OpenAI-compatible 托管 embedding + PostgreSQL pgvector；未建索引/未配 embedding 时调用方降级 |
| `security/` | 安全模块，认证、限流、防护、审计 |
| `services/` | 业务服务，批量批改、错题本 |
| `textbook_learning/` | 教材学习，章节浏览、AI 问答、测验 |
| `tools/` | 工具注册表，供学习助手调用 |

---

## 前端架构

### 目录结构

```
frontend/
├── app/                       # Next.js App Router
│   ├── (student)/             # 学生端页面组
│   │   ├── history-character/    # 历史人物对话
│   │   ├── history-games/         # 历史游戏
│   │   ├── learning-assistant/   # 学习助手
│   │   ├── materials/            # 资料库
│   │   ├── student-dashboard/     # 学生仪表板
│   │   └── ...
│   │
│   ├── (teacher)/             # 教师端页面组
│   │   ├── teacher/               # 教师端
│   │   │   ├── class-analytics/   # 班级学情分析
│   │   │   ├── dashboard/         # 教师仪表板
│   │   │   ├── grading/           # 批改审核
│   │   │   ├── materials/         # 教师资料库
│   │   │   └── students/          # 学生管理
│   │   └── ...
│   │
│   ├── components/            # 共享组件
│   ├── history-character/     # 历史人物对话
│   ├── history-games/         # 历史游戏
│   │   ├── timeline/              # 时间线游戏
│   │   ├── card-game/             # 卡牌游戏
│   │   └── multiplayer/           # 多人游戏
│   ├── learning-assistant/   # 学习助手
│   ├── materials/            # 资料库
│   ├── student-dashboard/    # 学生仪表板
│   ├── teacher/              # 教师端
│   ├── textbook-learning/    # 教材学习
│   ├── essay-grade/          # 作文批改
│   ├── homework-grading/     # 作业批改
│   ├── history-map/          # 历史地图
│   ├── history-debate/       # 历史辩论
│   ├── register/             # 注册
│   ├── layout.tsx            # 根布局
│   ├── page.tsx              # 首页（含登录）
│   └── globals.css           # 全局样式
│
├── components/               # 全局组件
├── lib/                      # 工具库
├── public/                   # 静态资源
├── next.config.js            # Next.js 配置
├── tsconfig.json             # TypeScript 配置
└── package.json              # 依赖配置
```

### 页面路由

| 路由 | 说明 |
|------|------|
| `/` | 首页 + 登录（叙事 + 学生/教师身份切换、账号登录、一键体验；已登录自动跳工作台，退出后回到此页） |
| `/register` | 注册 |
| `/history-character` | 历史人物对话 |
| `/history-games` | 历史游戏大厅 |
| `/history-games/timeline` | 时间线游戏 |
| `/history-games/card-game` | 卡牌游戏 |
| `/history-games/multiplayer` | 多人游戏 |
| `/learning-assistant` | 学习助手 |
| `/student/auto-tutor` | AutoTutor 自主辅导 |
| `/materials` | 资料库 |
| `/materials/[materialId]` | 资料详情 |
| `/student-dashboard` | 学生仪表板 |
| `/textbook-learning` | 教材学习 |
| `/essay-grade` | 作文批改 |
| `/homework-grading` | 作业批改 |
| `/history-map` | 历史地图 |
| `/history-debate` | 历史辩论 |
| `/teacher/dashboard` | 教师仪表板，显示学生数、待审核作业数（红色角标）、本轮讲评重点 |
| `/teacher/class-analytics` | 班级学情分析，含生成讲评建议和一键复制讲评大纲 |
| `/teacher/materials` | 教师资料库 |
| `/teacher/grading` | 批改审核 |
| `/teacher/students/[id]` | 学生档案 |

---

## API 接口

### 认证授权

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |

### 历史人物对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/history/character/recommend` | 人物推荐 |
| POST | `/api/history/character/chat` | 人物对话 |

### 历史游戏

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/games` | 游戏列表 |
| POST | `/api/history/games/timeline/start` | 开始时间线游戏 |
| POST | `/api/history/games/timeline/submit` | 提交时间线答案 |
| POST | `/api/history/card-game/start` | 开始卡牌游戏 |
| POST | `/api/history/card-game/submit` | 提交卡牌答案 |
| POST | `/api/history/card-game/retry` | 重试卡牌游戏 |
| GET | `/api/history/card-game/report/{student_id}` | 卡牌游戏报告 |
| POST | `/api/history/multiplayer/start` | 开始多人游戏 |
| POST | `/api/history/multiplayer/play` | 玩家出牌 |
| POST | `/api/history/multiplayer/ai-turn` | AI 出牌 |

### 学习助手

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/learning/assistant/tools` | 工具列表 |
| POST | `/api/learning/assistant/chat` | 学习助手对话 |
| POST | `/api/learning/assistant/tool-confirmation/cancel` | 取消工具确认 |

### AutoTutor 自主辅导

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/autotutor/start` | 启动一节自主辅导课：读画像/错题本→自主规划→出首题，返回 session_id + 计划 + trace_id。可选 `focus_tags`（如来自作业错题）会被提到教学计划最前 |
| POST | `/api/autotutor/answer` | 提交当前题作答，驱动 judge→（答错则 reflect→re_plan）/ next_step / finalize |
| GET | `/api/autotutor/session/{session_id}` | 拉取会话当前状态（计划、当前题、反思记录、runtime steps、trace_id） |

### 教材学习

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/textbooks` | 教材列表 |
| GET | `/api/textbooks/{book_id}/toc` | 教材目录 |
| GET | `/api/textbooks/{book_id}/lessons/{lesson_id}` | 课程详情 |
| POST | `/api/textbook-learning/ask` | 教材问答 |
| POST | `/api/textbook-learning/summary` | 课程总结 |
| POST | `/api/textbook-learning/quiz` | 生成测验 |
| POST | `/api/textbook-learning/quiz/submit` | 提交测验 |

### 多模态资料库

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/materials/parse` | 解析资料 |
| POST | `/api/materials/analyze` | 分析资料 |
| POST | `/api/materials/save` | 保存资料 |
| GET | `/api/materials` | 资料列表 |
| GET | `/api/materials/{material_id}` | 资料详情 |
| POST | `/api/materials/{material_id}/ask` | 资料问答 |
| DELETE | `/api/materials/{material_id}` | 删除资料 |

### 作业批改

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/homework/parse` | 解析作业 |
| POST | `/api/homework/grade` | 批改作业 |
| POST | `/api/homework/reviews` | 保存审核 |
| GET | `/api/teacher/homework-reviews` | 审核列表 |
| POST | `/api/teacher/homework-reviews/{review_id}/decision` | 审核决策，并将教师确认/修正结果同步为学习事件与错题本信号 |

### 学生档案

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/students/{student_id}/profile` | 学生档案 |
| GET | `/api/students/{student_id}/review-plan` | 复习计划，聚合学生画像与错题本优先级 |
| GET | `/api/students/{student_id}/learning-path` | 学习路径，聚合复习计划、画像进度与错题本 |
| POST | `/api/students/{student_id}/events` | 记录学习事件 |
| GET | `/api/students/{student_id}/events` | 学习事件列表 |
| GET | `/api/students/{student_id}/memory-entries` | 记忆条目 |
| PATCH | `/api/students/{student_id}/memory-entries/{memory_id}` | 更新记忆条目 |
| DELETE | `/api/students/{student_id}/memory-entries/{memory_id}` | 删除记忆条目 |
| DELETE | `/api/students/{student_id}/events/{event_id}` | 删除学习事件 |
| GET | `/api/students/{student_id}/memory-audit` | 记忆审计 |
| GET | `/api/student/{student_id}/weakpoints` | 错题本 |
| DELETE | `/api/student/{student_id}/weakpoints/{knowledge_tag}` | 删除错题 |
| DELETE | `/api/student/{student_id}/weakpoints` | 清空错题本 |
| GET | `/api/students/{student_id}/review/today` | 获取今日自适应复习任务（无则生成） |
| POST | `/api/students/{student_id}/review/submit` | 提交复习答题结果 |
| GET | `/api/students/{student_id}/mastery-overview` | 知识点掌握度总览 + 连续打卡天数（strength 纳入 correct_streak 加成） |
| GET | `/api/students/{student_id}/today` | 学生今日计划：作业到期(逾期/今日截止)、今日复习余量、薄弱点攻克按优先级合成的待办清单；只读、不触发 LLM |
| GET | `/api/student/{student_id}/learning-report` | 学习成长报告：汇总 SM-2 复习进度、作业批改趋势、每日活跃度、错题统计、AutoTutor 会话数（`?days=14`） |
| GET | `/api/student/{student_id}/assignments` | 学生待办/已完成作业列表（含提交状态与分数） |
| POST | `/api/student/{student_id}/assignments/{assignment_id}/submit` | 学生提交作答，自动批改客观题，主观题标记待评阅 |

### 教师端

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/teacher/students` | 学生列表 |
| GET | `/api/teacher/students/{student_id}/profile` | 学生档案 |
| GET | `/api/teacher/students/{student_id}/events` | 学生学习事件 |
| GET | `/api/teacher/class-analytics` | 班级学情分析 |
| POST | `/api/teacher/assignments/generate-questions` | AI 出题：按知识点批量 RAG 取材并生成单选题 / 判断题 / 简答题草稿，供教师修改确认；每题附带确定性结构质检结果 `quality`（level: ok/warn/error + issues），教师端以徽标标注需修正/可优化的题；可选 `semantic_check=true` 追加 LLM 语义质检（答案是否自洽、题干歧义、干扰项合理性），问题以「语义：」前缀并入 issues，失败/无凭证时优雅降级；语义质检会注入该教师历史上人工判定为 `bad_question` 的题作为 few-shot 反例，使质检随复核越用越准（自改进闭环） |
| POST | `/api/teacher/assignments` | 创建作业（客观题+主观题），指定学生 |
| GET | `/api/teacher/assignments` | 教师作业列表，含完成率、平均分与讲评洞察摘要（待评阅数、薄弱知识点、低正确率题） |
| GET | `/api/teacher/assignments/{assignment_id}/submissions` | 查看一份作业的题目、所有学生提交明细与 `insights` 讲评洞察（提交率、薄弱点、低正确率题及高频错误选项、质检盲区、低分学生），并返回 `review_flags`（题目复核判定）与 `open_blind_spot_count`（未复核盲区数） |
| POST | `/api/teacher/assignments/{assignment_id}/review` | 教师人工评阅学生提交：填写分数与反馈，将 `partial` / 待评阅提交置为 `graded` |
| POST | `/api/teacher/assignments/{assignment_id}/questions/{question_index}/review-flag` | 教师复核质检盲区题：`verdict` = `bad_question`（题目有问题）/ `not_mastered`（学生没掌握），UPSERT 到 `question_review_flags` |
| GET | `/api/teacher/badges` | 教师侧边栏通知徽标：`{pending_review, below_threshold, blind_spots_to_review}`（复用作业列表聚合，`blind_spots_to_review`＝各作业未复核质检盲区数之和，前端 60s 轮询；「布置作业」入口显示 pending_review + blind_spots_to_review 之和） |
| GET | `/api/teacher/quality-dashboard` | 命题质量看板：跨作业聚合 AI 质检分布(error/warn/ok/unchecked)、有效性(主动预警/疑似误报/盲区待复核·确认漏检·其实没掌握)、复核结论分布、高频问题类型、最难题 Top 与近期 few-shot 反例；只读确定性 |
| GET | `/api/student/{student_id}/badges` | 学生侧边栏通知徽标：`{pending_assignments, due_soon, pending_review}`（未提交作业/临近到期/今日复习待完成，前端 60s 轮询） |
| GET | `/api/teacher/materials` | 教师资料库 |
| POST | `/api/teacher/teaching-suggestions` | 教学建议生成 |

### 作文批改

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chinese/essay/grade` | 批改作文 |
| POST | `/api/chinese/essay/review-result` | 提交审核 |
| GET | `/api/chinese/essay/review-stats` | 审核统计 |
| POST | `/api/chinese/essay/grade/batch` | 批量批改 |

### 历史辩论

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/history/debate/start` | 开始辩论 |
| POST | `/api/history/debate/stream` | 流式辩论 |

### 历史地图

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/geo/events` | 地理事件 |
| GET | `/api/history/geo/narrate` | 事件解说 |
| GET | `/api/history/geo/chat` | 地图对话 |

### 调试

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 轻量服务健康检查，不触发 LLM/RAG，供 Render 等部署平台使用 |
| GET | `/api/debug/llm/health` | LLM 健康检查默认浅检查不调用模型；显式 `?deep=true` 才实际调用 fast 模型做连通性诊断 |
| GET | `/api/debug/rag/health` | 生产 RAG 健康检查：验证 PostgreSQL/pgvector、`rag_documents`、embedding API 与直接向量查询 |
| GET | `/api/traces/{trace_id}` | 获取 Agent 执行轨迹 |

### 评估

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agent-ops/summary` | Agent 运维摘要 |
| GET | `/api/eval/suites` | 评估套件列表 |
| GET | `/api/eval/latest` | 最新评估报告 |
| GET | `/api/eval/report/json` | 评估报告 JSON |
| GET | `/api/eval/report/markdown` | 评估报告 Markdown |
| POST | `/api/eval/run` | 运行评估 |
| GET | `/api/eval/history` | 评估历史 |
| GET | `/api/eval/candidate-cases` | 候选测试用例 |
| POST | `/api/eval/save-case` | 保存测试用例 |

---

## 数据模型

### PostgreSQL / SQLite 数据库

后端数据库通过 SQLAlchemy 统一访问，`DATABASE_URL` 设置后使用 PostgreSQL（当前 Supabase），未设置时回退到本地 SQLite。Alembic 迁移位于 `backend/alembic/`，迁移时优先读取 `DIRECT_URL`，应用运行读取 `DATABASE_URL`。RAG 向量检索依赖 PostgreSQL `vector` 扩展；SQLite 本地库仅支持非向量功能与降级路径。`GET /api/debug/rag/health` 会显式验证 pgvector 扩展、`rag_documents` 表、collection 索引条数、embedding API 与直接向量查询，避免业务层降级掩盖生产 RAG 故障。

#### rag_documents 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 向量文档 ID（collection 内全局唯一） |
| collection | TEXT | 集合名，如 `history`、`materials` |
| content | TEXT | 分块文本 |
| metadata | JSONB | 元数据（grade/topic/source/page/owner_key/material_id 等） |
| embedding | vector(1024) | OpenAI-compatible embedding API 生成的向量（默认 Jina `jina-embeddings-v3`，1024 维） |

#### student_profiles 表

| 字段 | 类型 | 说明 |
|------|------|------|
| student_id | TEXT | 学生 ID |
| grade | TEXT | 年级 |
| recent_topics_json | TEXT | 最近学习主题（JSON） |
| recent_lessons_json | TEXT | 最近课程（JSON） |
| weak_topics_json | TEXT | 薄弱点（JSON） |
| strong_topics_json | TEXT | 优势点（JSON） |
| quiz_stats_json | TEXT | 测验统计（JSON，含 average_score 等） |
| game_stats_json | TEXT | 游戏统计（JSON，含 average_score 等） |
| character_interests_json | TEXT | 历史人物兴趣（JSON） |
| interaction_summary_json | TEXT | 交互摘要（JSON） |
| updated_at | TEXT | 更新时间 |

#### learning_events 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 事件 ID |
| student_id | TEXT | 学生 ID |
| session_id | TEXT | 会话 ID |
| feature | TEXT | 功能模块 |
| event_type | TEXT | 事件类型 |
| grade | TEXT | 年级 |
| topic | TEXT | 主题 |
| book_id | TEXT | 教材 ID |
| lesson_id | TEXT | 课程 ID |
| score | REAL | 分数 |
| success | INTEGER | 是否成功 |
| metadata_json | TEXT | 元数据（JSON） |
| created_at | TEXT | 创建时间 |

#### memory_entries 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 记忆 ID |
| student_id | TEXT | 学生 ID |
| type | TEXT | 记忆类型 |
| content_json | TEXT | 内容（JSON） |
| source_feature | TEXT | 来源功能 |
| source_event_id | TEXT | 来源事件 ID |
| confidence | REAL | 置信度 |
| status | TEXT | 状态（enabled/disabled/deleted） |
| reason | TEXT | 记录原因 |
| metadata_json | TEXT | 元数据（JSON） |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |
| last_used_at | TEXT | 最近使用时间 |
| disabled_at | TEXT | 禁用时间 |
| deleted_at | TEXT | 删除时间 |

#### materials 表

| 字段 | 类型 | 说明 |
|------|------|------|
| material_id | TEXT | 资料 ID |
| owner_key | TEXT | 所有者 |
| title | TEXT | 标题 |
| filename | TEXT | 文件名 |
| source_type | TEXT | 来源类型 |
| grade | TEXT | 年级 |
| subject | TEXT | 科目 |
| text | TEXT | 文本内容 |
| pages | TEXT | 页面（JSON） |
| text_chars | INTEGER | 文本字符数 |
| page_count | INTEGER | 页数 |
| chunk_count | INTEGER | 分块数 |
| summary | TEXT | 摘要 |
| created_at | TEXT | 创建时间 |
| expires_at | TEXT | 过期时间 |

#### homework_reviews 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 审核 ID |
| student_id | TEXT | 学生 ID |
| actor_id | TEXT | 提交审核的用户 ID |
| grade_request_json | TEXT | 批改请求（JSON） |
| grade_result_json | TEXT | 批改结果（JSON） |
| needs_human_review | INTEGER | 是否需要人工审核 |
| decision | TEXT | 决策（pending/accepted/edited/rejected） |
| teacher_id | TEXT | 审核教师 ID |
| teacher_note | TEXT | 教师批注 |
| teacher_score | REAL | 教师评分 |
| created_at | TEXT | 创建时间 |
| reviewed_at | TEXT | 审核时间 |

#### weakpoints 表

| 字段 | 类型 | 说明 |
|------|------|------|
| student_id | TEXT | 学生 ID |
| knowledge_tag | TEXT | 知识点标签 |
| wrong_count | INTEGER | 出错次数 |
| last_wrong_at | TEXT | 最近出错时间 |
| source | TEXT | 来源 |

#### accounts 表

| 字段 | 类型 | 说明 |
|------|------|------|
| actor_id | TEXT | 用户 ID |
| username | TEXT | 用户名 |
| password_hash | TEXT | 密码哈希 |
| role | TEXT | 角色（student/teacher/admin） |
| display_name | TEXT | 显示名称 |
| created_at | TEXT | 创建时间 |

#### audit_events 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 审计事件 ID |
| actor_id | TEXT | 操作用户 ID |
| action | TEXT | 操作名称 |
| resource_type | TEXT | 资源类型 |
| resource_id | TEXT | 资源 ID |
| success | INTEGER | 是否成功 |
| metadata_json | TEXT | 元数据（JSON） |
| created_at | TEXT | 创建时间 |

#### assignments 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 作业 ID |
| teacher_id | TEXT | 创建教师 ID |
| title | TEXT | 作业标题 |
| subject | TEXT | 科目 |
| grade | TEXT | 年级 |
| questions_json | TEXT | 题目列表（JSON，支持 single_choice / multiple_choice / true_false / subjective） |
| assignee_ids_json | TEXT | 分配学生 ID 列表（JSON） |
| due_date | TEXT | 截止时间 |
| created_at | TEXT | 创建时间 |

#### assignment_submissions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 提交 ID |
| assignment_id | TEXT | 作业 ID |
| student_id | TEXT | 学生 ID |
| answers_json | TEXT | 学生答案与自动批改结果（JSON） |
| score | REAL | 分数；含主观题时为客观题初始得分，人工评阅后覆盖 |
| status | TEXT | 状态（submitted / partial / graded） |
| submitted_at | TEXT | 提交时间 |
| teacher_feedback | TEXT | 教师人工评语 |
| reviewed_at | TEXT | 人工评阅时间 |

#### question_review_flags 表

教师对质检盲区题的复核判定（每题至多一条，UPSERT）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 标记 ID |
| assignment_id | TEXT | 作业 ID |
| question_index | INTEGER | 题目序号（0 起） |
| teacher_id | TEXT | 复核教师 ID |
| verdict | TEXT | `bad_question`（题目有问题）/ `not_mastered`（学生没掌握） |
| note | TEXT | 可选备注 |
| created_at | TEXT | 复核时间 |

#### 游戏持久化表

| 表 | 说明 |
|------|------|
| game_rounds | 游戏回合记录，含 TTL 过期时间 |
| card_game_wrong_records | 卡牌游戏错题记录 |
| card_game_reports | 卡牌游戏学习报告 |
| review_sessions | 每日自适应复习会话，每学生每天一条，含任务列表与完成进度 |

---

## 核心功能

### 1. 历史人物对话

- 支持历史人物角色扮演
- RAG 检索历史史料
- 流式响应
- 事实卡片生成
- 质量验证

### 2. 历史游戏

- 时间线排序游戏
- 卡牌对战游戏
- 多人"时间巨轮"游戏
- 时间巨轮桌游页面使用 `frontend/public/board-bg.png` 作为沉浸式牌桌背景，公共时间轴、手牌、牌堆与玩家席位收纳在桌面区域内
- 时间巨轮支持玩家本地拖拽排序自己的手牌，也可把手牌拖拽到公共时间轴插入位完成出牌；拖拽时高亮具体插入位置，公共时间轴上的桌面卡牌保持不可拖动；非本人回合仍持续展示自己的手牌但禁用出牌交互
- 时间巨轮页面移除顶部横向 header，保留标题、牌堆来源、重开与大厅按钮为背景桌面上的轻量浮层
- 时间巨轮开局设置面板垂直/水平居中，空局容器显式标记 `timewheel-board--empty` 并使用 fixed 视口定位兜底，配合桌游化分组卡片、当前配置摘要、筹码式选项按钮和强化 CTA
- AI 玩家
- 游戏报告

### 3. 学习助手

- 工具调用
- 工具确认机制
- 流式响应
- 防护机制

### 3.5 AutoTutor 自主辅导（旗舰 agent 闭环）

- **自主规划（Plan）**：读学生画像 + 错题本，用 quality 模型自主生成本节课计划（教哪些知识点、难度、策略、排序理由）；换学生计划不同，非写死流水线。无 LLM 凭证时按错题权重确定性兜底。
- **执行 + 观察（Act/Observe）**：每步通过工具注册表调用 `search_history_knowledge` 取材（走治理/审计/RAG），再据难度出题，等待学生作答。
- **反思 + 重规划（Reflect/Re-plan）**：学生答错 → 反思诊断（讲解不到位 / 题超纲 / 概念没懂）→ 真实修改计划（补讲 / 当前步与后续步降难度 / 重新出题）。设单步重试与全局重规划护栏（≤3）。
- **自适应（Adapt/Finalize）**：课后写 `review_goal` 记忆、按掌握情况记录 learning event、已掌握知识点移出错题本、仍薄弱知识点进错题本（自动进入 SM-2 今日复习池）。
- **全程可观测**：plan / act / reflect / re_plan / finalize 每个 node emit trace step（写入 trace_store，可经 `/api/traces/{trace_id}` 查询），前端 TraceTimeline + runtime steps 实时呈现规划与反思过程。

### 4. 多模态资料库

- PDF/图片上传
- OCR 解析
- RAG 问答
- Owner 隔离
- TTL 清理

### 5. 作业批改

- 拍照上传
- OCR 识别
- AI 批改
- 教师审核
- 教师确认/修正的审核结果会同步为学习事件，并将可信薄弱点写入错题本
- 错题本集成

### 6. 教材学习

- 章节浏览
- AI 问答
- 测验生成
- 学习记录

### 7. 学生档案

- 学情统计
- 记忆管理
- 学习事件
- 复习计划
- 错题本

### 8. 教师端

- 班级学情分析
- 学生管理
- 批改审核
- 教学建议生成
- 教师资料库
- 教师布置作业工作流：AI 按知识点 RAG 出题（单选 / 判断 / 简答）→ 教师修改确认 → 发放给指定学生
- 作业提交详情下钻：教师可查看每个学生的分数、每题答对/错、学生答案与正确答案
- 作业讲评闭环洞察：聚合提交率、待评阅数、低正确率题、薄弱知识点、低分学生与 deterministic 讲评重点
- 教师人工评阅：对含简答题的 `partial` 提交录入 0-100 分与反馈，并将提交状态更新为 `graded`
- 错题本掌握度模型：`weakpoints` 表含 `correct_streak`，答错（`record_weakpoint`）强化并清零连对计数，答对（`record_correct_evidence`）累积证据、连续答对达阈值（默认 2）才移出错题本；作业/AutoTutor/教材/复习四处答对统一走此逻辑，取代旧的"答对即删"；错题本页手动删除仍为硬删除
- 作业错题回流：学生提交客观题后，答错题目的 `knowledge_tag` 自动写入错题本；教师人工评阅主观题后，低分主观题知识点也会写入错题本，供 AutoTutor 后续规划使用
- 作业错题-复习-辅导数据闭环：`submit_assignment` 返回 `wrong_tags`，学生结果页展示答错知识点并提供「今日复习」「AutoTutor 辅导」入口；答错知识点会追加到已存在的今日复习 session（`merge_new_weakpoints_to_today`，标 `pending_generate` 占位），学生打开复习页时 `get_today_session(hydrate=True)` 按需生成占位题的真题并落库（徽标轮询用 `hydrate=False` 只计数、不触发 LLM）；从作业跳转 AutoTutor 时经 `focus_tags` 把该知识点提到教学计划最前
- 基于错题本和学生画像聚合班级高频薄弱点
- 教师首页前置本轮讲评重点，班级学情页展示薄弱点人数占比
- 教学建议生成基于高频薄弱点人数和占比，输出讲评步骤、课堂活动、重点知识点和分层作业建议

---

## 测试

### Smoke Tests

| 测试文件 | 说明 |
|----------|------|
| `material_rag_smoke.py` | 资料 RAG 测试 |
| `material_rag_isolation_smoke.py` | 资料 RAG 隔离测试 |
| `tool_registry_smoke.py` | 工具注册表测试 |
| `learning_assistant_smoke.py` | 学习助手测试 |
| `guardrails_smoke.py` | 防护机制测试 |
| `weakpoints_smoke.py` | 错题本测试（含掌握度模型：连续答对才移除、答错重置连对、未跟踪 tag no-op），8 例 |
| `student_profile_smoke.py` | 学生档案测试 |
| `homework_grading_smoke.py` | 作业批改测试 |
| `learning_closure_smoke.py` | 作业-错题-复习-学情闭环测试 |
| `teacher_features_smoke.py` | 教师功能测试，已接入 `run_core_evals.py`，覆盖班级学情、教师资料库、教学建议 schema 与教师审核结果同步 learning event / weakpoints |
| `assignment_smoke.py` | 教师布置作业工作流测试（创建/列表/学生待办/提交自动批改/查重/权限/人工评阅/讲评洞察/质检盲区命中与排除/盲区教师复核 UPSERT 与校验/bad_question 反例取样与隔离），17 例，已接入 `run_core_evals.py`（SMOKE） |
| `assignment_review_loop_smoke.py` | 作业错题→薄弱点→今日复习→AutoTutor 数据闭环测试（wrong_tags 返回、复习 session 追加、focus_tags 优先规划），5 例，已接入 `run_core_evals.py`（SMOKE） |
| `question_quality_smoke.py` | AI 出题质检测试：结构质检（选项数/答案合法性/题干为空/判断题答案/简答参考答案）+ LLM 语义质检合并（stub LLM：检出/降级/merge 取最高 level）+ few-shot 反例注入 prompt 断言，17 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `notification_badges_smoke.py` | 通知徽标聚合测试（教师待评阅/低分学生/未复核质检盲区统计与复核清零、学生未提交/到期统计），7 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `quality_dashboard_smoke.py` | 命题质量看板跨作业聚合测试（质检分布/有效性漏检误报/复核结论/高频问题/最难题排序/few-shot 反例/teacher 隔离），7 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `today_plan_smoke.py` | 学生今日计划聚合测试（优先级排序/已交排除/逾期置顶/复习余量/薄弱点 focus 编码/DB 集成隔离），8 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `trace_smoke.py` | Agent Runtime 可视化测试 |
| `trajectory_eval.py` | 学习助手工具调用轨迹准确率，已接入 `run_core_evals.py`（CORE/QUICK） |
| `auto_tutor_trajectory_eval.py` | AutoTutor 自主辅导轨迹评测（规划合理性、反思触发正确性、闭环命中、focus_tags 优先规划、连错降难度、空错题本兜底），7 例，已接入 `run_core_evals.py`（CORE/QUICK），离线可跑 |
| `production_rag_health_smoke.py` | 生产 RAG HTTP smoke，显式通过 `API_BASE` 指向线上后端，不进入默认本地 smoke/core 套件 |
| `tool_permission_smoke.py` | 工具权限确认测试 |

### 运行测试

```bash
# 运行主 smoke 套件（同 npm test）
npm test

# CI 后端验证入口（语法检查 + smoke）
PYTHONPATH=backend python3 scripts/verify_core.py --smoke --no-report

# 运行 quick 套件
python3 eval/run_core_evals.py --quick

# 运行学习闭环 smoke
python3 eval/run_core_evals.py --suite learning_closure_smoke

# 运行教师功能 smoke
python3 eval/run_core_evals.py --suite teacher_features_smoke

# 显式运行生产 RAG smoke（不属于默认 npm test；必须指定线上 API_BASE）
API_BASE=https://<render-backend> npm run test:prod-rag

# 若生产开启认证，可提供 JWT 或 smoke 账号
API_BASE=https://<render-backend> API_TOKEN=<jwt> npm run test:prod-rag
API_BASE=https://<render-backend> SMOKE_USERNAME=<user> SMOKE_PASSWORD=<password> npm run test:prod-rag

# 运行单个 legacy smoke 脚本
python3 eval/material_rag_smoke.py
```

---

## 开发规范

### 文档命名

开发文档使用时间戳前缀的 kebab-case 命名：

```
docs/YYYYMMDDHHMM-feature-name-dev.md
```

### 代码风格

- Python: 遵循 PEP 8
- TypeScript: 使用 ESLint
- 注释: 中文注释

### 提交规范

- 新增功能: 更新 schema.md
- 修改接口: 更新 API 文档
- 新增页面: 更新路由文档

### Schema 更新

当新增或修改功能时，必须同步更新本 schema.md 文件：

1. 更新目录结构
2. 更新 API 接口列表
3. 更新数据模型
4. 更新核心功能说明
5. 更新测试列表

---

## 部署

线上方案：**Vercel（前端）+ Render（后端 Docker）+ Supabase（Postgres）**。详见 [`docs/202606291600-autotutor-deploy-dev.md`](docs/202606291600-autotutor-deploy-dev.md)。

| 文件 | 作用 |
|------|------|
| `render.yaml` | Render Blueprint：后端 web service（Docker）+ env 清单 |
| `frontend/vercel.json` | Vercel 框架/构建声明（Root Directory 设为 `frontend`） |
| `backend/Dockerfile` | 后端镜像（uvicorn `api.main:app`） |
| `frontend/Dockerfile` | 前端多阶段 standalone 镜像（自托管备用） |
| `frontend/next.config.js` | `output:"standalone"` + 路由 redirects |
| `.dockerignore` / `frontend/.dockerignore` | 瘦身 Docker 构建上下文 |
| `docker-compose.yml` | 本地一键起 redis + backend + frontend |
| `scripts/seed_demo_student.py` | 灌 demo 学生（demo-student/demo123）+ 预置错题本 |
| `scripts/build_pgvector_index.py` | 离线构建历史 RAG pgvector 索引（corpus.json → OpenAI-compatible embedding → rag_documents） |

关键环境变量：`NEXT_PUBLIC_API_BASE_URL`（前端→后端）、`FRONTEND_ORIGIN`（后端 CORS 放行自定义域名，`*.vercel.app` 已由正则放行）、`DATABASE_URL`/`DIRECT_URL`、`BAILIAN_API_KEY`/`BAILIAN_BASE_URL`、`EMBED_API_BASE`（Render 默认 Jina `https://api.jina.ai/v1`）、`EMBED_API_KEY`、`EMBED_MODEL`（Render 默认 `jina-embeddings-v3`）、`EMBED_TASK`（Jina 使用 `text-matching`）、`EMBED_DIM`（默认 `1024`）、`ANTHROPIC_AUTH_TOKEN` 等 LLM 凭证。生产 RAG 使用托管 embedding + pgvector；未建索引或 embedding API 不可用时，人物对话/游戏/学习助手走降级路径。production smoke 使用的 `API_BASE`、`API_TOKEN`/`AUTH_TOKEN`、`SMOKE_USERNAME`、`SMOKE_PASSWORD`、`RAG_HEALTH_COLLECTION` 是验收脚本环境变量，不是必须写入 Render 的应用环境变量。

---

## 版本历史

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-06-23 | 1.0.0 | 初始版本，记录项目完整架构 |
| 2026-06-23 | 1.1.0 | 添加下一步产品方向分析 |
| 2026-06-23 | 1.2.0 | 添加 Agent Runtime 可视化功能（trace_store、TraceTimeline 组件） |
| 2026-06-23 | 1.3.0 | 添加工具权限治理和确认机制（confirmation.py、ToolConfirmationDialog） |
| 2026-06-24 | 1.4.0 | 修正学生画像/错题本真实 schema，补充学习闭环 API 与 smoke test |
| 2026-06-24 | 1.5.0 | 增强学生/教师端闭环入口，教师功能 smoke 接入统一评估 runner |
| 2026-06-24 | 1.6.0 | 教师作业审核结果同步学习事件与错题本，扩展 teacher_features_smoke 覆盖审核闭环 |
| 2026-06-26 | 1.7.0 | 优化时间巨轮多人桌游页面，使用 board-bg.png 作为桌面背景并重排卡牌/牌堆/玩家席位避免重叠 |
| 2026-06-26 | 1.8.0 | 时间巨轮新增玩家手牌本地拖拽排序，并支持拖拽手牌到公共时间轴插入位完成出牌；拖拽时高亮具体插入位置，桌面公共时间轴卡牌保持不可拖动 |
| 2026-06-26 | 1.9.0 | 时间巨轮移除顶部横向 header，将标题和操作按钮改为背景桌面浮层 |
| 2026-06-26 | 1.10.0 | 优化时间巨轮开局设置展示与交互，表单垂直/水平居中，增加配置摘要、桌游化分组卡片和筹码式选项按钮 |
| 2026-06-26 | 1.10.1 | 修正时间巨轮空局容器 class，确保开局设置面板视口 fixed 居中兜底样式命中 |
| 2026-06-26 | 1.10.2 | 时间巨轮非本人回合持续展示玩家手牌，仅禁用点击与拖拽出牌交互 |
| 2026-06-29 | 1.11.0 | AutoTutor 上线部署配置：render.yaml + vercel.json + .dockerignore + 前端 standalone 构建 + CORS 经 FRONTEND_ORIGIN/*.vercel.app 放行；新增部署文档 |
| 2026-06-29 | 1.12.0 | RAG 从本地 BGE/Chroma 迁移到 OpenAI-compatible 托管 embedding（默认 Jina）+ PostgreSQL pgvector，新增 rag_documents 表与 build_pgvector_index.py 离线建索引脚本 |
| 2026-06-30 | 1.13.0 | 新增生产 RAG 健康检查端点与显式 production smoke，验证托管 embedding + Postgres/pgvector + rag_documents 索引链路；补齐 CI 后端验证入口并让 RAG 依赖评测在无 sources 时跳过 |
| 2026-07-01 | 1.14.0 | 新增学生学习成长报告：后端 `GET /api/student/{id}/learning-report`（汇总 SM-2、作业批改、活跃度、AutoTutor、错题本）；前端 `/student/report` 页面含热图+柱状图+作业趋势+错题排行；侧边栏与移动导航新增「成长报告」入口 |
| 2026-07-01 | 1.15.0 | 新增教师布置作业工作流：`assignments`/`assignment_submissions` 表；5 个 API（教师创建/列表/提交明细，学生待办/提交）；客观题自动批改+主观题待评阅；前端 `/teacher/assignments` 出题页 + `/student/assignments` 作业本；新增 `assignment_smoke.py`（8 例） |
| 2026-07-01 | 1.15.1 | 修复 `assignment_submissions` 兼容旧 SQLite 的列补齐逻辑；新增 `/api/health` 轻量健康检查并改用它作为 Render/keep-alive 探针；`/api/debug/llm/health` 默认改为浅检查，显式 `?deep=true` 才调用模型，避免旧探针因 LLM 配额耗尽导致部署健康检查失败 |
| 2026-07-02 | 1.16.0 | 补齐学生「学习路径」页 `/student/learning-path`（此前仅移动端「更多」入口存在但页面缺失致 404）：前端调用已有 `GET /api/students/{id}/learning-path`，渲染掌握度概览、按错题掌握度排序的优先攻克时间线（进度条 + `correct_streak` 连对进度）、推荐行动列表、去复习/针对性辅导（透传 `?focus=` 到 AutoTutor）联动 CTA 与空态；桌面侧边栏「我的学情」分组新增该入口。后端零改动 |
| 2026-07-02 | 1.16.1 | 教师作业讲评视图呈现每题高频错误选项：`compute_assignment_insights` 早已计算 `common_wrong_answers`（学生最常错选的干扰项及人数），此前前端仅声明类型未渲染，现于「低正确率题」卡片下追加「最多错选『X』· N人」提示，直接点出班级共性误区，辅助讲评。后端零改动 |
| 2026-07-02 | 1.16.2 | 质检有效性回路：AI 出题的 `quality` 质检结论此前建作业时被 Pydantic 静默丢弃，现 `AssignmentQuestion` 保留 `quality` 并随 `questions_json` 持久化；`compute_assignment_insights` 新增 `quality_blind_spots`（AI 判为合格 ok/未查、但真实正确率 <40% 且作答样本 ≥3 的客观题 = 质检盲区），`_compact_insights` 加 `quality_blind_spot_count`；教师端「低正确率题」命中盲区的题追加「⚠ 质检盲区」徽标提示复核题目本身；`assignment_smoke.py` 加盲区命中/排除用例（12→14 例） |
| 2026-07-02 | 1.16.3 | 质检盲区教师复核：新增 `question_review_flags` 表与 `POST /api/teacher/assignments/{id}/questions/{index}/review-flag` 端点，教师对盲区题给判定（`bad_question` 题目有问题 / `not_mastered` 学生没掌握，UPSERT）；`get_assignment_submissions` 返回加 `review_flags` 与 `open_blind_spot_count`；教师端盲区题加「题目有问题 / 学生没掌握」按钮，判定后徽标相应变为「已标记题目问题」或「学生未掌握」；`assignment_smoke.py` 加复核命中/UPSERT/校验用例（14→16 例） |
| 2026-07-02 | 1.16.4 | 未复核质检盲区接入教师通知徽标：`list_teacher_assignments` 每份加 `open_blind_spot_count`（盲区扣除已复核），`get_teacher_badges` 加 `blind_spots_to_review` 汇总；侧边栏 `navBadgeCount`/`badgeOf` 支持 `badgeKeys` 多键求和，「布置作业」入口显示 `pending_review + blind_spots_to_review`，教师无需进详情页即可被提醒去复核盲区；`notification_badges_smoke.py` 加盲区计数/复核清零用例（6→7 例） |
| 2026-07-02 | 1.16.5 | 语义质检自改进闭环：新增 `get_bad_question_examples(teacher_id)`（取该教师历史上人工判为 `bad_question` 的题干+备注，teacher 隔离、去重）；`check_question_semantic` 加 `bad_examples` 参数，将其作为 few-shot 反例注入 system prompt（前 3 条截断，默认 None 行为不变）；`generate-questions` 在 `semantic_check` 时取一次反例传入，使语义质检随教师复核越用越准；`question_quality_smoke` 加注入断言/回归（15→17），`assignment_smoke` 加反例取样/隔离（16→17 例） |
| 2026-07-02 | 1.16.6 | 命题质量看板：新增 `services/quality_dashboard.py` 的 `get_teacher_quality_dashboard` 跨作业聚合 + `GET /api/teacher/quality-dashboard`；前端 `/teacher/quality-dashboard` 看板页 + 侧边栏「系统运维」入口；新增 `quality_dashboard_smoke.py`（7 例）。把散落在单份作业的质检数据升维成教师可决策的命题质量画像 |
| 2026-07-02 | 1.16.7 | 学生今日计划：新增 `services/today_plan.py`（build_today_plan 纯函数 + get_student_today_plan）与 `GET /api/students/{id}/today`，把作业到期/今日复习/薄弱点按优先级(逾期>今日截止>复习>未来作业>薄弱点)合成待办；前端 `TodayPlanCard` 接入学生首页，补上此前首页无作业提醒的缺口；新增 `today_plan_smoke.py`（8 例）|

---

## 下一步产品方向

详见 [`docs/202606231148-next-product-direction-analysis.md`](docs/202606231148-next-product-direction-analysis.md)

### 推荐优先级

| 优先级 | 方向 | 说明 |
|--------|------|------|
| P0 | Agent Runtime 可视化 | 统一 trace event schema，学习助手页面增加 step timeline |
| P0 | Tool Permission / Confirmation Demo | 强制 role / confirmation 检查，新增 high-risk demo tool |
| P0 | Eval Dashboard 增强 | 展示关键指标，一键运行 quick eval |
| P1 | RAG 可解释检索面板 | 展示 retrieval debugging、grounding、citation |
| P1 | Agent Memory 管理页面 | 展示长期记忆策略、用户控制、隐私意识 |
| P1 | 学习路径优化 | 基于错题本的智能推荐，个性化学习计划生成 |

### 总体目标

> 将项目从"功能完整的教育 AI 应用"升级为"可评测、可观测、可治理的教育 Agent 工程作品集"。
