# EduAgent 项目架构文档

**创建时间：** 2026-06-23
**项目名称：** EduAgent - K-12 中文/历史 AI 教学平台
**最后更新：** 2026-07-14

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
- **前端：** Next.js 16 App Router + React 19 + TypeScript
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
│   ├── mcp_server.py          # stdio MCP 工具协议适配
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
├── eval/                      # 测试脚本（含 mcp_server_smoke.py）
├── knowledge_base/            # 知识库（history/corpus.json、geo_events.json 等静态内容源）
├── scripts/                   # 脚本工具（含 build_pgvector_index.py 离线构建 RAG 向量索引、seed_pilot_demo.py 试点主路径数据）
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
│   ├── auto_tutor.py              # AutoTutor 自主辅导闭环（plan→act→observe→judge→reflect→re_plan→exit_ticket→evidence→finalize）
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
│   ├── assignment_service.py      # 作业生命周期（创建/提交/自动批改/洞察/质检盲区/复核）
│   ├── batch_essay_service.py     # 批量作文批改
│   ├── completion_overview.py     # 教师班级作业完成情况：跨作业按学生聚合已交/欠交/逾期（纯函数+装配）
│   ├── quality_dashboard.py       # 命题质量看板：跨作业聚合 AI 质检分布/有效性/复核结论（只读确定性）
│   ├── question_quality.py        # AI 出题结构质检 + LLM 语义质检（opt-in，few-shot 自改进）
│   ├── review_service.py          # SM-2 自适应复习调度（wrong_count>=2 时自动改用变式题）
│   ├── today_plan.py              # 学生今日计划：作业到期/复习/薄弱点按优先级合成待办（纯函数+装配）
│   ├── lecture_review_service.py  # 讲评课 AI 辅助：跨作业聚合错误→LLM 生成讲解提示/板书关键词/即时练习形式
│   ├── teacher_today_queue.py     # 教师今日教学队列：聚合待复核、质检盲区、欠交/逾期、薄弱点与共性错题
│   ├── variant_service.py         # 错题变式生成：wrong_count>=VARIANT_THRESHOLD 时 LLM 生成同 tag 不同题面变式题，含当日缓存
│   ├── knowledge_graph_service.py # 知识图谱前置依赖：静态 DAG + 画像/错题推导节点状态（mastered/weak/available/locked）、下一步建议、薄弱点风险预测（前置链含 weak 的下游高风险点）与班级地基薄弱点聚合（aggregate_class_risks）
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
├── mcp_server.py              # stdio MCP 工具协议适配
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
| `mcp_server.py` | 轻量 stdio MCP server，向标准 Agent/MCP 客户端暴露 `search_history_knowledge`、`get_textbook_lesson`、`suggest_review_plan`、`generate_quiz` 4 个只读/低风险教育工具，并复用 Tool Registry 的 schema 校验、角色策略、确认元数据、审计与 trace；可用 `npm run mcp:server` 启动 |

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
| `/` | 首页 + 登录（叙事 + 学生/教师身份切换、账号登录、一键体验；v1.25 起一键体验改为真实登录 pilot-student / pilot-teacher seed 账号；已登录自动跳工作台，退出后回到此页） |
| `/register` | 注册 |
| `/history-character` | 历史人物对话 |
| `/history-games` | 历史游戏大厅 |
| `/history-games/timeline` | 时间线游戏 |
| `/history-games/card-game` | 卡牌游戏 |
| `/history-games/multiplayer` | 多人游戏 |
| `/learning-assistant` | 学习助手 |
| `/student` | 学生学习工作台，含继续学习主卡（基于今日计划最高优先级任务）、今日计划、本周小结和 Agent 能力入口 |
| `/student/auto-tutor` | AutoTutor 自主辅导 |
| `/student/review` | 复习中心：`tab=review` 今日任务（SM-2 自适应练习，区分加载失败/真空态，提交失败可重试），`tab=weakpoints` 错因档案馆/错题库（掌握度热力图、重点攻克、AutoTutor 精讲跳转）；旧 `/student/weakpoints` 仅作重定向安全网 |
| `/student/materials` | 学习资料中心：`tab=materials` 我的资料上传/管理，`tab=textbook` 教材目录；资料/教材 tab 在移动端吸顶横向滚动；旧 `/student/textbook` 仅作重定向安全网 |
| `/student/dashboard` | 学情总览：`tab=dashboard` 学情速览，`tab=report` 成长报告；`/student/report` 保留直达但不作为导航主入口 |
| 学生/教师移动端导航 | 4 个高频底栏入口 + “更多”抽屉，支持当前更多项高亮、通知红点和关闭按钮 |
| `/materials` | 资料库 |
| `/materials/[materialId]` | 资料详情 |
| `/student-dashboard` | 学生仪表板 |
| `/textbook-learning` | 教材学习；学生智能练习 `/student/quiz` 复用教材测验生成能力，前端区分教材/课次加载中、加载失败、暂无可练习教材，并解释开始按钮禁用原因 |
| `/essay-grade` | 作文批改 |
| `/homework-grading` | 作业批改 |
| `/history-map` | 历史地图 |
| `/history-debate` | 历史辩论 |
| `/teacher` | 教师协同工作台，含今日教学队列、批改摘要、作业完成情况和班级成员入口 |
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
| POST | `/api/autotutor/answer` | 提交当前题作答，驱动 judge→（答错则 reflect→re_plan）/ next_step；最后教学步骤后进入 `phase=exit_ticket` 退出票检验，退出票作答后才 finalize 并写入学习证据 |
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
| GET | `/api/students/{student_id}/learning-path` | 学习路径，聚合复习计划、画像进度与错题本；`graph` 字段返回知识点前置依赖图（nodes/edges/next_recommended/counts）+ `at_risk` 风险预测（前置链含 weak 的下游高风险点），前端渲染分层"知识地图"与"风险预警" |
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
| GET | `/api/students/{student_id}/preferences` | 读取学生 AI 学伴偏好（pace/style/interaction/difficulty 等，选项 schema 由后端统一定义） |
| PUT | `/api/students/{student_id}/preferences` | 保存学生 AI 学伴偏好，AutoTutor 规划时注入偏好提示 |
| GET | `/api/preferences/schema` | 学习偏好配置 schema：返回维度、选项、默认值，供前端动态渲染 |
| POST | `/api/students/{student_id}/weakpoints/{knowledge_tag}/analyze` | 对某薄弱知识点做根因诊断（concept/memory/comprehension/careless），LLM 失败时规则降级 |
| GET | `/api/students/{student_id}/weakpoints/{knowledge_tag}/root-cause` | 获取某薄弱知识点最近一次根因诊断结果 |
| GET | `/api/students/{student_id}/root-cause/summary` | 根因诊断汇总：按根因类型统计分布与最近记录 |
| PUT | `/api/teacher/assignments/{assignment_id}/difficulty-groups` | 为作业的学生设置难度分层（`{student_id: "easy"/"medium"/"hard"}`），传 `{}` 清除分层 |
| GET | `/api/student/{student_id}/assignments/{assignment_id}/my-questions` | 返回学生应作答的题目：有分层按难度筛选，无分层返回全部，降级（无匹配题）返回全部 |
| GET | `/api/students/{student_id}/review/variant-question` | 为指定 tag 生成（或返回今日缓存的）变式题；`wrong_count>=2` 时复习 session 也自动使用（`?tag=xxx`） |
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
| GET | `/api/teacher/class-wrong-analysis` | 跨作业题目级错误聚合：按答错学生数降序展示最难的题（prompt/accuracy/student_count_wrong/wrong_options/来源作业），`?limit_assignments=10&top_n=15` |
| GET | `/api/teacher/tutor-effectiveness` | 班级 AI 辅导效果：从 learning_events 聚合 `auto_tutor_step` 与 `auto_tutor_exit_ticket`，按知识点统计辅导次数、过程掌握率、退出票数/通过率、active_students 与 students_with_exit_ticket，`?days=30` |
| GET | `/api/teacher/class-risk-analysis` | 班级「地基薄弱点」：逐生 build_graph+predict_risks，按卡点前置聚合，返回 foundations（tag/weak_students/at_risk_students/downstream_risk_count/impact，按 impact 降序）定位需系统讲解的根节点 |
| GET | `/api/students/{student_id}/tutor-effectiveness` | 学生自己的辅导效果：按知识点统计过程掌握率、退出票数/通过率、最近退出票时间 + 是否仍在错题本，`?days=30` |
| POST | `/api/teacher/assignments/generate-questions` | AI 出题：按知识点批量 RAG 取材并生成单选题 / 判断题 / 简答题草稿，供教师修改确认；每题附带确定性结构质检结果 `quality`（level: ok/warn/error + issues），教师端以徽标标注需修正/可优化的题；可选 `semantic_check=true` 追加 LLM 语义质检（答案是否自洽、题干歧义、干扰项合理性），问题以「语义：」前缀并入 issues，失败/无凭证时优雅降级；语义质检会注入该教师历史上人工判定为 `bad_question` 的题作为 few-shot 反例，使质检随复核越用越准（自改进闭环） |
| POST | `/api/teacher/assignments` | 创建作业（客观题+主观题），指定学生 |
| GET | `/api/teacher/assignments` | 教师作业列表，含完成率、平均分与讲评洞察摘要（待评阅数、薄弱知识点、低正确率题） |
| GET | `/api/teacher/assignments/{assignment_id}/submissions` | 查看一份作业的题目、所有学生提交明细与 `insights` 讲评洞察（提交率、薄弱点、低正确率题及高频错误选项、质检盲区、低分学生），并返回 `review_flags`（题目复核判定）与 `open_blind_spot_count`（未复核盲区数） |
| POST | `/api/teacher/assignments/{assignment_id}/review` | 教师人工评阅学生提交：填写分数与反馈，将 `partial` / 待评阅提交置为 `graded` |
| POST | `/api/teacher/assignments/{assignment_id}/questions/{question_index}/review-flag` | 教师复核质检盲区题：`verdict` = `bad_question`（题目有问题）/ `not_mastered`（学生没掌握），UPSERT 到 `question_review_flags` |
| GET | `/api/teacher/badges` | 教师侧边栏通知徽标：`{pending_review, below_threshold, blind_spots_to_review}`（复用作业列表聚合，`blind_spots_to_review`＝各作业未复核质检盲区数之和，前端 60s 轮询；「布置作业」入口显示 pending_review + blind_spots_to_review 之和） |
| GET | `/api/teacher/quality-dashboard` | 命题质量看板：跨作业聚合 AI 质检分布(error/warn/ok/unchecked)、有效性(主动预警/疑似误报/盲区待复核·确认漏检·其实没掌握)、复核结论分布、高频问题类型、最难题 Top 与近期 few-shot 反例；只读确定性 |
| GET | `/api/teacher/completion-overview` | 班级作业完成情况：跨作业按学生聚合 已交/欠交/逾期(掉队优先) + 班级摘要(总体提交率/有逾期学生数/已全交数)；只读确定性 |
| GET | `/api/teacher/today-queue` | 教师今日教学队列：后端聚合待复核、质检盲区、欠交/逾期、班级薄弱点与共性错题，返回已排序行动项、summary 与 source_errors；教师首页单接口消费 |
| GET | `/api/student/{student_id}/badges` | 学生侧边栏通知徽标：`{pending_assignments, due_soon, pending_review}`（未提交作业/临近到期/今日复习待完成，前端 60s 轮询） |
| GET | `/api/teacher/materials` | 教师资料库 |
| POST | `/api/teacher/teaching-suggestions` | 教学建议生成 |
| POST | `/api/teacher/lecture-review` | 讲评课 AI 辅助：跨最近 5 份作业聚合错误分布，LLM 为每个高频错误知识点生成讲解提示/板书关键词/即时练习形式；前端作业管理页「AI 讲评稿」面板展示+一键复制 |
| POST | `/api/teacher/urge-students` | 向欠交学生发送站内催办通知（最多50人/次），写入 `student_notifications` 表 |
| GET | `/api/students/{student_id}/notifications` | 学生读取自己的通知列表（`?unread_only=true&limit=N`）|
| POST | `/api/students/{student_id}/notifications/{notification_id}/read` | 将学生的一条未读通知标为已读，用于横幅单条关闭 |
| POST | `/api/students/{student_id}/notifications/read-all` | 将该学生所有未读通知标为已读 |

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
| GET | `/api/health` | 轻量 liveness 检查，不触发 LLM/RAG，供 Render 等部署平台使用 |
| GET | `/api/ready` | 发布前 readiness 浅检查：聚合 DB、LLM 配置、RAG 浅状态和最新 eval 摘要；默认不触发外部 LLM/Embedding，`?require_rag=true` 时把 RAG 浅检查纳入硬门槛 |
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
| POST | `/api/eval/run` | 运行评估；统一调用 `eval/run_core_evals.py` 的 suite 注册与报告生成，不再使用旧 mock report_generator 路径 |
| GET | `/api/eval/history` | 评估历史 |
| GET | `/api/eval/candidate-cases` | 候选测试用例 |
| POST | `/api/eval/save-case` | 保存测试用例 |

---

## 数据模型

### PostgreSQL / SQLite 数据库

后端数据库通过 SQLAlchemy 统一访问，`DATABASE_URL` 设置后使用 PostgreSQL（当前 Supabase），未设置时回退到本地 SQLite。默认 SQLite 路径按运行布局解析：本地源码树使用仓库根目录 `.data/edu_agent.sqlite3`，Docker/Render 镜像中使用 `/app/.data/edu_agent.sqlite3`，也可用 `EDU_AGENT_DB_PATH` 显式覆盖，避免容器中误写根目录 `/.data`。Alembic 迁移位于 `backend/alembic/`，迁移时优先读取 `DIRECT_URL`，应用运行读取 `DATABASE_URL`。RAG 向量检索依赖 PostgreSQL `vector` 扩展；SQLite 本地库仅支持非向量功能与降级路径。`GET /api/debug/rag/health` 会显式验证 pgvector 扩展、`rag_documents` 表、collection 索引条数、embedding API 与直接向量查询，避免业务层降级掩盖生产 RAG 故障。

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

AutoTutor 关键事件类型：`auto_tutor_step` 表示教学过程步骤；`auto_tutor_exit_ticket` 表示课后退出票检验结果，用于学生/教师辅导效果聚合、错题/掌握度证据与复习闭环。

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
| correct_streak | INTEGER | 连续答对次数；答错时清零，达到掌握阈值后移出错题本 |

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

#### student_notifications 表

学生站内通知表；`read_at IS NULL` 表示未读。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 通知 ID |
| student_id | TEXT | 接收学生 ID |
| teacher_id | TEXT | 发送教师 ID |
| message | TEXT | 通知内容 |
| assignment_ids_json | TEXT | 关联作业 ID 列表（JSON） |
| created_at | TEXT | 创建时间 |
| read_at | TEXT | 已读时间，空值表示未读 |

#### learning_preferences 表

学生 AI 学伴偏好表；选项维度与默认值由 `GET /api/preferences/schema` 返回，表内只保存学生当前选择。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增 ID |
| student_id | TEXT | 学生 ID（唯一） |
| preferences_json | TEXT | 偏好选择（JSON） |
| updated_at | TEXT | 更新时间 |

#### root_cause_records 表

薄弱点根因诊断历史表；`root_cause` 枚举为 `concept` / `memory` / `comprehension` / `careless`。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增 ID |
| student_id | TEXT | 学生 ID |
| knowledge_tag | TEXT | 知识点标签 |
| question_text | TEXT | 题干 |
| student_answer | TEXT | 学生答案 |
| correct_answer | TEXT | 正确答案 |
| root_cause | TEXT | 根因类型 |
| confidence | REAL | 诊断置信度 |
| analyzed_at | TEXT | 诊断时间 |

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
| review_sessions | 每日自适应复习会话，每学生每天一条，含任务列表与完成进度；`tasks_json` 可包含 `pending_generate=true` 占位题，首页/徽标/今日计划使用 `hydrate=false` 只读不触发 LLM，复习页使用 `hydrate=true` 时才按需生成真题并落库 |

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
- 学生首页继续学习主卡：复用 `GET /api/students/{id}/today` 的今日计划，按逾期作业/今日截止作业/今日复习/薄弱点优先级展示一个明确下一步动作，并在无待办时推荐教材或历史人物对话；`useStudentWorkbenchData` 将首页 profile/review-plan/today 聚合为单次数据加载，`ContinueLearningCard` 与 `TodayPlanCard` 共享同一份今日计划，避免重复请求和状态不一致；v1.25 起主卡补充推荐理由与待交作业/今日复习/薄弱点 summary chips，仍只读 `/today`，不 hydrate 复习题、不在首页自动启动 AutoTutor/LLM
- 学生端 `TabShell`：`/student/review`、`/student/materials`、`/student/dashboard` 复用统一 query tab 壳，默认 tab 不写 URL，非默认 tab 可刷新保留，并带 ARIA tab 语义与移动端横向滚动/吸顶样式
- 学习偏好设置由后端 schema 驱动：`/student/settings` 读取 `GET /api/preferences/schema` 渲染维度和选项，再合并学生已保存偏好，避免前后端双写漂移
- 学生作业提交前未答校验：在 `/student/assignments` 提交前列出未作答题号，学生可继续检查或确认仍然提交，避免无感提交空答案
- 学习资源教材目录请求携带认证凭证，区分教材为空与加载失败；复习页移除 Google Fonts 外链，统一使用全局字体变量；周报接口失败时展示可理解失败态而非静默消失
- 学生复习/智能练习状态反馈：今日复习页区分接口加载失败与真实无任务，复习提交失败显示可重试错误；智能练习页区分教材/课次加载中、加载失败、暂无可练习教材，并在开始按钮下方解释禁用原因（纯前端 UX，无后端 API 变化）

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
- 教师首页今日教学队列：`GET /api/teacher/today-queue` 后端聚合待复核批改、未复核质检盲区、作业欠交/逾期、班级高频薄弱点与共性错题，返回已排序行动项、summary 与 source_errors；`TeacherTodayQueue` 前端单接口消费，给出教师当天优先处理动作；质检盲区来自 `GET /api/teacher/quality-dashboard` 的 `effectiveness.blind_spots_open`，讲评材料生成仅保留入口，不在首页自动触发 LLM
- 教师作业管理体验：作业列表区分初始加载、加载失败、真实空列表和刷新失败保留旧数据，提供重试/新建作业 CTA；移动端作业列表、讲评洞察、学生答案、人工评阅和创建表单在 640px 以下改为更易触屏阅读与操作的纵向布局（纯前端 UX，无后端 API 变化）
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
| `knowledge_graph_smoke.py` | 知识图谱前置依赖测试（根节点 available、前置未掌握则 locked+locked_by、前置掌握解锁、错题标 weak、next_recommended 优先级、DAG 无环、图外孤立错题纳入、counts 一致）+ 薄弱点风险预测（前置链含 weak 则下游 at_risk、无 weak 时为空、weak 节点不重复计入、风险分反映 weak 前置数并降序）+ 班级地基薄弱点聚合（多生共享前置累加影响面、无 weak 返回空、按 impact 降序），16 例离线，已接入 `run_core_evals.py`（CORE/SMOKE） |
| `student_profile_smoke.py` | 学生档案测试 |
| `homework_grading_smoke.py` | 作业批改测试 |
| `learning_closure_smoke.py` | 作业-错题-复习-学情闭环测试 |
| `teacher_features_smoke.py` | 教师功能测试，已接入 `run_core_evals.py`，覆盖班级学情、教师资料库、教学建议 schema 与教师审核结果同步 learning event / weakpoints |
| `assignment_smoke.py` | 教师布置作业工作流测试（创建/列表/学生待办/提交自动批改/查重/权限/人工评阅/讲评洞察/质检盲区命中与排除/盲区教师复核 UPSERT 与校验/bad_question 反例取样与隔离），17 例，已接入 `run_core_evals.py`（SMOKE） |
| `assignment_review_loop_smoke.py` | 作业错题→薄弱点→今日复习→AutoTutor 数据闭环测试（wrong_tags 返回、复习 session 追加、focus_tags 优先规划），5 例，已接入 `run_core_evals.py`（SMOKE） |
| `question_quality_smoke.py` | AI 出题质检测试：结构质检（选项数/答案合法性/题干为空/判断题答案/简答参考答案）+ LLM 语义质检合并（stub LLM：检出/降级/merge 取最高 level）+ few-shot 反例注入 prompt 断言，17 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `notification_badges_smoke.py` | 通知徽标聚合测试（教师待评阅/低分学生/未复核质检盲区统计与复核清零、学生未提交/到期统计），7 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `quality_dashboard_smoke.py` | 命题质量看板跨作业聚合测试（质检分布/有效性漏检误报/复核结论/高频问题/最难题排序/few-shot 反例/teacher 隔离），7 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `pilot_path_smoke.py` | v1.25/v1.26 试点主路径测试：验证 `seed_pilot_demo.py` 幂等、pilot 账号登录、学生今日计划/AutoTutor focus 链接、教师待复核/欠交/质检盲区信号、`/api/teacher/today-queue` 后端聚合队列、通知去重、review 占位任务不触发 LLM，以及 pilot seed 预置的 AutoTutor 退出票学习证据，8 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `today_plan_smoke.py` | 学生今日计划聚合测试（优先级排序/已交排除/逾期置顶/复习余量/薄弱点 focus 编码/DB 集成隔离），8 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `completion_overview_smoke.py` | 教师班级完成情况聚合测试（逐生计数/逾期判定/掉队排序/班级摘要/DB 集成隔离），6 例离线，已接入 `run_core_evals.py`（SMOKE） |
| `trace_smoke.py` | Agent Runtime 可视化测试 |
| `readiness_smoke.py` | Readiness / Eval 路由测试：验证 `/api/ready` 浅检查结构，以及 `/api/eval/latest`、`/api/eval/run` 只注册新版 `run_core_evals.py` 路由，避免旧 mock report_generator 遮蔽 |
| `trajectory_eval.py` | 学习助手工具调用轨迹准确率，已接入 `run_core_evals.py`（CORE/QUICK） |
| `auto_tutor_trajectory_eval.py` | AutoTutor 自主辅导轨迹评测（规划合理性、反思触发正确性、闭环命中、focus_tags 优先规划、连错降难度、空错题本兜底、退出票 finalize 前检验、退出票 learning event 与错题回流），11 例，已接入 `run_core_evals.py`（CORE/QUICK），离线可跑 |
| `production_rag_health_smoke.py` | 生产 RAG HTTP smoke，显式通过 `API_BASE` 指向线上后端，不进入默认本地 smoke/core 套件 |
| `tool_permission_smoke.py` | 工具权限确认测试 |
| `mcp_server_smoke.py` | MCP stdio 协议 smoke：验证 initialize、tools/list、教材读取、历史检索与未暴露工具拒绝；可通过 `npm run test:mcp` 单独运行 |

### 运行测试

```bash
# 运行主 smoke 套件（同 npm test）
npm test

# 运行 MCP server 协议 smoke
npm run test:mcp

# 本地启动 stdio MCP server
npm run mcp:server

# CI 后端验证入口（语法检查 + smoke）
PYTHONPATH=backend python3 scripts/verify_core.py --smoke --no-report

# 运行 quick 套件
python3 eval/run_core_evals.py --quick

# 发布前统一闸门：Python 语法检查 + 后端 smoke + 前端 build；默认 PR CI 主门禁复用该入口
npm run release:gate

# 本地快速发布闸门：关键试点/教师/今日计划 smoke + 前端 build
npm run release:gate:fast

# 生产发布闸门：在本地闸门后追加 production RAG smoke（需线上 API_BASE + token 或 smoke 账号；不属于默认 PR CI）
API_BASE=https://<render-backend> SMOKE_USERNAME=<user> SMOKE_PASSWORD=<password> npm run release:gate:prod

# 可选：发布闸门追加线上 readiness 浅检查（不触发外部 LLM/Embedding）
npm run release:gate:fast -- --ready-url https://<render-backend>/api/ready

# GitHub Actions 手动 production-readiness job 等价命令：跳过重复前端 build，检查线上 /api/ready 与 production RAG
API_BASE=https://<render-backend> SMOKE_USERNAME=<user> SMOKE_PASSWORD=<password> npm run release:gate:prod -- --skip-frontend --ready-url https://<render-backend>/api/ready

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
| `scripts/seed_pilot_demo.py` | 灌 v1.25 试点主路径数据：pilot 教师/学生账号、作业提交、错题、review 占位任务与通知，支持重复运行幂等演示 |
| `scripts/release_gate.py` | 发布前统一闸门：Python 语法检查、后端 smoke/关键 smoke、前端 build；默认 PR CI 主门禁复用该入口，可选生产 RAG smoke；配合 `/api/ready` 做线上浅 readiness 检查 |
| `scripts/build_pgvector_index.py` | 离线构建历史 RAG pgvector 索引（corpus.json → OpenAI-compatible embedding → rag_documents） |

关键环境变量：`NEXT_PUBLIC_API_BASE_URL`（前端→后端）、`FRONTEND_ORIGIN`（后端 CORS 放行自定义域名，`*.vercel.app` 已由正则放行）、`DATABASE_URL`/`DIRECT_URL`、`BAILIAN_API_KEY`/`BAILIAN_BASE_URL`、`EMBED_API_BASE`（Render 默认 Jina `https://api.jina.ai/v1`）、`EMBED_API_KEY`、`EMBED_MODEL`（Render 默认 `jina-embeddings-v3`）、`EMBED_TASK`（Jina 使用 `text-matching`）、`EMBED_DIM`（默认 `1024`）、`ANTHROPIC_AUTH_TOKEN` 等 LLM 凭证。生产 RAG 使用托管 embedding + pgvector；未建索引或 embedding API 不可用时，人物对话/游戏/学习助手走降级路径。默认 PR CI 不要求生产 `API_BASE`、线上 RAG、真实 LLM deep health 或生产认证；production smoke / `npm run release:gate:prod` / 手动 `production-readiness` 使用的 `API_BASE`、`API_TOKEN`/`AUTH_TOKEN`、`SMOKE_USERNAME`、`SMOKE_PASSWORD`、`RAG_HEALTH_COLLECTION` 是验收脚本环境变量，不是必须写入 Render 的应用环境变量。

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
| 2026-07-02 | 1.16.8 | 教师班级作业完成情况：新增 `services/completion_overview.py`（compute_class_completion 纯函数 + get_class_completion_overview）与 `GET /api/teacher/completion-overview`，跨作业按学生聚合 已交/欠交/逾期(掉队优先)；前端 `ClassCompletionCard` 接入教师首页，补上此前只有作业维度完成率、缺学生维度催办视图的缺口；新增 `completion_overview_smoke.py`（6 例）。与学生「今日计划」形成师生对称 |
| 2026-07-03 | 1.17.0 | 错题变式生成：新增 `services/variant_service.py`（generate_variant / get_or_create_variant / get_cached_variant，当日缓存+LLM降级）；`review_service._pick_question` 当 `wrong_count>=VARIANT_THRESHOLD(2)` 时自动改用变式题替代重复原题；新增 `GET /api/students/{id}/review/variant-question?tag=xxx`；新增 `variant_question_smoke.py`（6 例）。补上「背了就忘、只会认题面」的复习盲区 |
| 2026-07-03 | 1.17.1 | 讲评课 AI 辅助升级：新增 `services/lecture_review_service.py`（aggregate_teacher_errors 跨作业聚合错误分布 + generate_lecture_review LLM 批量生成讲解提示/板书关键词/即时练习形式）；新增 `POST /api/teacher/lecture-review`；教师作业管理页新增「AI 讲评稿」折叠面板，按知识点展示讲评卡片，支持一键复制全文；新增 `lecture_review_smoke.py`（6 例）。把散落的错题数据升维为教师可直接用的备课素材 |
| 2026-07-03 | 1.17.2 | 知识点掌握度热力图：新增 `GET /api/teacher/class-mastery-heatmap`（聚合所有学生错题本 → 按 tag 统计 student_count/avg_wrong/avg_strength）；学生错题本页顶部加彩色磁贴热力图（红=薄弱/黄=学习中/绿=掌握，点击跳转 AutoTutor）；教师班级学情页新增班级热力图面板（按 student_count 排序，hover 显示统计）；新增 `mastery_heatmap_smoke.py`（5 例）|
| 2026-07-03 | 1.17.3 | 出题难度维度：`GeneratedQuestion` 新增 `difficulty` 字段并写入题目 JSON；`compute_assignment_insights` 加 `difficulty_distribution` 统计（easy/medium/hard 计数）；前端作业洞察面板展示难度分布 chip；答题详情每题加难度 badge；AI 出题结果携带难度回传前端 `DraftQuestion`；新增 `difficulty_smoke.py`（5 例）。不影响存量题目（无 difficulty 字段时全为 0，向后兼容）|
| 2026-07-03 | 1.17.4 | 学生学习日历：新建 `/student/calendar` 页面（GitHub 贡献图风格热力图，9 周 × 7 天格子）；复用成长报告 API 的 `activity_by_day`/`review_by_day`/`streak_days`，无需新接口；摘要行展示连续打卡/活跃天数/复习率/错题数/辅导次数；格子带颜色深浅（0=灰/1-2=浅绿/3-5=中绿/6-9=深绿/10+=最深），复习任务叠加橙/绿边框；桌面侧边栏 + 移动端「更多」列表均添加「学习日历」入口；新增 `calendar_smoke.py`（5 例）|
| 2026-07-03 | 1.17.5 | 催办通知实际发送：新增 `services/notification_service.py`（send_urge_notification/get_student_notifications/mark_notification_read/mark_all_read/get_unread_count，`student_notifications` 表）；新增 `POST /api/teacher/urge-students`、`GET /api/students/{id}/notifications`、`POST /api/students/{id}/notifications/read-all`；`ClassCompletionCard` 加「一键催办」按钮+自定义消息输入框；`TodayPlanCard` 展示老师催办通知横幅（可关闭，后台静默已读）；新增 `urge_notification_smoke.py`（6 例）。补上「有数据但无行动」的催办断点 |
| 2026-07-03 | 1.17.6 | 学生分层作业：`assignments` 表新增 `difficulty_groups_json` 字段（{student_id: "easy"\|"medium"\|"hard"}）；新增 `set_difficulty_groups`/`get_questions_for_student`/`_parse_difficulty_groups`；`list_student_assignments` 返回 `my_difficulty`；新增 `PUT /api/teacher/assignments/{id}/difficulty-groups` + `GET /api/student/{sid}/assignments/{aid}/my-questions`；教师作业详情加「学生难度分层」紫色面板（含学生下拉选择器+保存）；学生作业列表加难度组标签，开题时自动拉过滤后的题目（无匹配则降级全量）；新增 `tiered_assignment_smoke.py`（6 例）|
| 2026-07-03 | 1.17.7 | 错题班级聚合视图：`aggregate_class_wrong_questions` 跨最近N份作业聚合题目粒度答错率（主观题过滤，wrong_options 高频错选）；新增 `GET /api/teacher/class-wrong-analysis`；教师班级学情页新增「全班难题榜」表格（按答错学生数降序，正确率色标，高频错选，来源作业）；新增 `class_wrong_analysis_smoke.py`（5 例）。补上「知道知识点弱，但不知道哪道题最难」的盲区 |
| 2026-07-03 | 1.17.8 | AI 辅导效果追踪：新增 `services/tutor_effectiveness_service.py`（从 learning_events 的 auto_tutor_step 记录聚合，无需改 AutoTutor 逻辑）；学生视角 get_student_tutor_effectiveness（按知识点统计辅导次数/掌握率/still_weak）；班级视角 get_class_tutor_effectiveness（active_students/整体掌握率/按知识点）；新增 `GET /api/teacher/tutor-effectiveness` + `GET /api/students/{id}/tutor-effectiveness`；教师班级学情页新增「AI 辅导效果」彩色磁贴面板（4指标 + 知识点掌握率色块）；新增 `tutor_effectiveness_smoke.py`（5 例，v1.26 扩展到退出票证据聚合）|

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
| 2026-07-03 | 1.18.0 | 每日签卡挑战 + 成就系统：新增 `services/check_in_service.py`（打卡记录、连续天数、累计天数、成就解锁逻辑）；5 个成就配置（初来乍到/铜银金牌学者/百日坚持）；新增 `check_ins` 表（student_id/check_in_date/summary）+ `achievements` 表（student_id/achievement_key/unlocked_at）；新增 4 个 API 端点（`POST /api/students/{id}/check-in`、`GET /api/students/{id}/check-in/status`、`GET /api/students/{id}/achievements`、`GET /api/students/{id}/check-in/history`）；TodayPlanCard 新增打卡按钮 + 连续天数显示 + 成就弹窗；新增成就墙页面 `/student/achievements`（已解锁/努力解锁带进度条、打卡面板）；侧边栏「我的学情」新增「我的成就」入口；新增 `check_in_smoke.py`（8 例）|
| 2026-07-03 | 1.18.1 | AI 学伴偏好配置：新增 `services/learning_preference_service.py`（SQLAlchemy，learning_preferences 表，4个维度：pace/style/interaction/difficulty，每维度3个选项）；`build_preference_prompt` 生成 prompt 注入片段；`auto_tutor.py _generate_plan` 注入偏好 prompt；新增 3 个 API（`GET/PUT /api/students/{id}/preferences`、`GET /api/preferences/schema`）；新增偏好设置页 `/student/settings`（多选按钮 UI，即时保存）；侧边栏「我的学情」新增「偏好设置」入口；新增 `preference_smoke.py`（6 例）|
| 2026-07-03 | 1.18.2 | 薄弱点根因诊断：新增 `services/root_cause_service.py`（SQLAlchemy，root_cause_records 表，4种根因分类：concept/memory/comprehension/careless）；`analyze_root_cause` 调用 LLM 分类错误原因（失败时降级为规则推断）；`get_latest_root_cause` 获取诊断结果；`get_root_cause_summary` 统计根因分布；新增 3 个 API（`POST /api/students/{id}/weakpoints/{tag}/analyze`、`GET /api/students/{id}/weakpoints/{tag}/root-cause`、`GET /api/students/{id}/root-cause/summary`）；新增 `root_cause_smoke.py`（8 例，含 LLM 调用降级测试）|
| 2026-07-03 | 1.18.3 | 教师端班级知识热力图 2D 矩阵：新增 `GET /api/teacher/class-knowledge-matrix` 端点（学生×知识点矩阵，strength 0.1-1.0，按薄弱人数降序，缺失知识点默认1.0，最多50个知识点）；新增 `class_matrix_smoke.py`（5/5 passed）；前端 API 已就绪，UI 可视化作为后续优化|
| 2026-07-03 | 1.18.7 | 知识图谱可视化收尾：新建 `/teacher/class-analytics/knowledge-matrix` 页面（调用 `GET /api/teacher/class-knowledge-matrix`，学生×知识点 2D 热力图，红/黄/绿三色区分薄弱/学习中/掌握，hover tooltip，左列+表头固定支持横向滚动）；班级学情页新增「查看详细矩阵 →」入口按钮。学生学习路径页在现有分层芯片布局上叠加 SVG 连线层（`data-node-tag` 动态定位 + 带箭头虚线边），展示知识点前置依赖方向，无新依赖，后端零改动；build 57/57 |
| 2026-07-03 | 1.19.0 | Eval Dashboard 升级：后端新增 `GET /api/eval/run-stream?suite=` SSE 流式端点（逐 suite 推送 start/running/suite_done/suite_error/done 事件）；前端 `run()` 改为 EventSource 订阅，新增黑色终端风格实时日志区（⟳运行中 → ✓/✗结果 → 完成汇总），新增 `runLog`/`runTotal` 状态；build 57/57 |
| 2026-07-03 | 1.20.0 | RAG Inspector 面板：后端 `materials/schema.py` 新增 `RagDebugChunk`/`RagDebugInfo`，`MaterialAnswerResponse` 添加 `rag_debug` 字段，`MaterialQuestionRequest` 添加 `debug: bool`；`answer_material_question` 在 `debug=True` 时填充 chunk 相关度/来源/mode 调试信息；前端资料详情页问答请求自动附带 `debug:true`，答案区域下方新增可折叠 RAG Inspector 面板（query 展示 + 每 chunk score 进度条 + 来源 + 片段预览，黑色终端风格）；build 57/57 |
| 2026-07-06 | 1.20.1 | Eval Dashboard 失败 case 下钻：前端 eval 页 suite 行头新增迷你通过率进度条（绿/黄/红按 pass_rate 上色）；结果区新增「只看失败」过滤开关（隐藏全通过 suite）；失败用例卡片重构为终端风格 EXPECTED/ACTUAL 双栏对比块（绿=预期/红=实际，等宽字体 + 独立滚动），case 头部展示 name/reason/category/trace/query。纯前端，复用既有 `normalizeFailedCase`/`formatUnknown`，后端零改动 |
| 2026-07-06 | 1.20.2 | Eval 回归对比：前端 eval 页新增 `RegressionDiff` 组件，对比 `/api/eval/history` 最近相邻两次 run 的整体通过率 + 6 项顶层指标（任务成功率/检索命中率/来源正确率/工具schema合规/护栏通过率/格式合规率/平均延迟），四列表格展示 上次→本次→变化，delta 带 ▲▼→ 箭头与绿(改善)/红(退化)/灰(持平)上色（延迟维度低更好，反向判定）；渲染于 TrendBar 下方，快照不足 2 次时不显示。纯前端，复用既有 HistorySnapshot 快照数据，后端零改动 |
| 2026-07-06 | 1.20.3 | Eval 回归告警：前端 eval 页新增 `detectRegression`（比较最近相邻两次快照的整体通过率，跌破 warn 2pt / error 8pt 阈值或「由通过转失败」即触发）+ `snapRate` helper；新增 `regressionAlert` 状态，在页面加载与每次 run 的 done 事件刷新 history 后重新判定；标题下 AgentOpsPanel 后渲染彩色告警横幅（🔴严重/🟠提示，展示 上次→本次通过率 + delta，引导用「只看失败」排查，可关闭）。纯前端，复用既有快照数据，后端零改动 |
| 2026-07-06 | 1.20.4 | 材料 RAG Inspector 引用追踪（used_in_answer）：`build_material_answer_messages` 加要求让 LLM 用 `[片段N]` 标注引用来源（N 对应检索片段序号，与历史对话侧 `[史料N]` 机制统一）；新增模块级 `_chunk_cited(answer_text, index)` 正则判定（`片段\s*0*{i}(?!\d)`，容错空格/前导零、避免片段1 误命中片段10），`answer_material_question` 的 debug chunk `used` 由硬编码 True 改为按实际引用判定；schema 注释同步；前端 Inspector 头部显示「N 片段检索 · M 已引用」，每 chunk 区分「✓ 已引用 / ○ 未引用」（未引用降透明度 0.6），Chunk→片段 中文化；`material_rag_smoke.py` 新增 `chunk_citation_detection` 用例（3→4 例，覆盖命中/边界/容错/空串）|
| 2026-07-06 | 1.21.0 | 错题本 → AutoTutor 带根因追问：打通此前孤立的根因诊断（v1.18.2）与自主辅导。后端 `AutoTutorStartRequest` + `start_session` + `_generate_plan` 新增可选 `focus_reason`，在规划 prompt 注入错因并给出对应教学策略（概念模糊→重讲概念、知识遗忘→带背再检验、审题失误→圈画关键词、粗心→提示复查）；`/api/autotutor/start` 透传。前端错题本页 `WeakCard` 每条错题新增「AutoTutor 精讲 →」入口（跳 `?focus={tag}`，补上此前仅「复习→」通用问答、无自主辅导入口的缺口）；AutoTutor 落地页在带 focus 时拉 `GET /api/students/{id}/weakpoints/{tag}/root-cause`，有诊断则展示错因横幅并作为 `focus_reason` 注入 start（无诊断静默降级为纯 focus 规划）。`auto_tutor_trajectory_eval` 7/7 无回归|
| 2026-07-06 | 1.22.0 | 学生周报：新增 `services/weekly_summary_service.py`（`_collect_metrics` 聚合最近 7 天活跃天数/连续打卡/复习完成率/作业均分/AutoTutor 会话/错题 top，`_llm_narrative` 调 LLM 生成温暖小结+下周建议、失败降级 `_rule_based_narrative` 规则模板，`build_weekly_summary` 组装）；新增 `GET /api/students/{id}/weekly-summary`（LLM 优先，`generated_by` 标记 llm/rule）；前端新增 `WeeklySummaryCard` 组件接入学生首页（`TodayPlanCard` 下方，小结段 + 指标 chips + 下周建议列表，无数据/失败静默不显）；新增 `weekly_summary_smoke.py`（6 例，纯离线覆盖规则文案/建议触发/组装/LLM 优先/降级）|
| 2026-07-06 | 1.22.1 | 学生端导航重叠入口收束：`/student/review` 合并今日任务与错题库（`tab=weakpoints`），错题库升级为「错因档案馆」视觉与跳转核查；`/student/materials` 合并资料上传与教材目录（`tab=textbook`）；`/student/dashboard` 合并学情速览与成长报告（`tab=report`）；内部链接移除旧 `/student/weakpoints`、`/student/textbook`、`/student/report` href，旧页面仅保留 redirect 安全网；build 57/57 |
| 2026-07-06 | 1.22.2 | 修复错题库/学习路径点击 `AutoTutor 精讲` 观感无响应：`/student/auto-tutor?focus=...` 进入后等待根因诊断查询完成即自动启动针对性辅导规划，并在 focus 切换时重置会话状态；保留无根因时纯 focus 降级；build 57/57 |
| 2026-07-06 | 1.22.3 | UX 优化：移动端“更多”抽屉新增标题与关闭按钮、当前更多页同步高亮到底栏、抽屉项显示通知红点；复习中心/学习资料 tab 在移动端吸顶横向滚动，减少切换后迷失；侧边栏分组按钮补 `type=button` 与 `aria-expanded`；`git diff --check` 通过，lint/typecheck 因工具安全分类服务临时不可用未运行 |
| 2026-07-06 | 1.22.4 | UX 优化第二轮：学生首页 `TodayPlanCard`/`WeeklySummaryCard` 增加骨架屏，避免接口加载期间首屏内容跳变；今日无待办状态补“读一课教材/找历史人物聊聊”下一步 CTA；复习中心空状态补“去完成作业/做智能练习”入口，答题按钮未选择时明确提示“先选择一个答案”，选项增加 `aria-pressed`；教材目录加载态改为卡片骨架屏 |
| 2026-07-06 | 1.23.0 | 学生工作台 UX alpha：新增 `ContinueLearningCard` 接入 `/student` 首页，基于今日计划最高优先级任务展示“继续学习”主动作；教材目录 tab 请求补认证头并区分失败态；复习页移除 Google Fonts 外链改用全局字体变量；周报加载失败时显示失败态；学生作业提交前增加未答题号提示，可继续检查或确认仍然提交 |
| 2026-07-07 | 1.24.0 | UX 一致性与工作台聚合：新增学生首页 `useStudentWorkbenchData`，让继续学习卡和今日计划共享同一份 `/today` 数据；新增学生端 `TabShell` 统一复习中心/学习资源/学情总览 tab；通知横幅单条关闭新增 `POST /api/students/{id}/notifications/{notification_id}/read`，不再误标全部已读；偏好设置改为读取后端 `/api/preferences/schema` 动态渲染；教师首页新增 `TeacherTodayQueue`，聚合待复核、欠交/逾期、薄弱点和共性错题 |
| 2026-07-07 | 1.25.0 | 试点主路径 v1：新增 `scripts/seed_pilot_demo.py` 灌 pilot 教师/学生、作业提交、错题、review 占位任务与通知；学生 `ContinueLearningCard` 增加推荐理由和今日计划 summary chips；教师 `TeacherTodayQueue` 接入命题质量看板的未复核质检盲区；新增 `pilot_path_smoke.py`（6 例）验证 seed 幂等、学生今日计划、教师待办信号与不触发 LLM 的 review 占位链路 |
| 2026-07-08 | 1.25.1 | CI Release Gate 收口：GitHub Actions 默认 PR/push 主门禁改为 `release-gate` 统一执行 `npm run release:gate`，前端 lint 独立快速反馈，quick-eval 保留为报告信号，Docker build 移至 main/manual；新增手动 `production-readiness` job 通过 `ready_url` 串联 `release:gate:prod --skip-frontend --ready-url`；修正 `Makefile verify-core-full` 转发到 `scripts/release_gate.py`；README/CI 文档/部署文档同步 release gate 与 shallow readiness / production RAG strict gate 边界 |
| 2026-07-13 | 1.26.0 | AutoTutor 退出票与学习证据闭环：`auto_tutor.py` 新增 `phase=lesson/exit_ticket/completed`、`exit_ticket_result` 与 `evidence`，最后教学步骤后先进入退出票检验，退出票作答后才 finalize；`learning_events` 新增 `auto_tutor_exit_ticket` 语义并回写 `record_correct_evidence` / `record_weakpoint(source=auto_tutor_exit_ticket)`；`tutor_effectiveness_service.py` 统计退出票数/通过率与 `students_with_exit_ticket`；学生 AutoTutor 完成态展示学习证据卡，教师班级学情页展示退出票证据聚合；demo/pilot seed 预置退出票证据；扩展 `auto_tutor_trajectory_eval.py`、`tutor_effectiveness_smoke.py`、`pilot_path_smoke.py` |
| 2026-07-14 | 1.26.1 | UX 状态反馈优化：学生复习页补加载失败/提交失败可重试反馈，智能练习页补教材/课次加载失败、空态与按钮禁用原因；教师作业列表补初始加载、错误重试、行动型空态与刷新失败保留旧数据提示，教师作业管理页 640px 以下优化列表、讲评洞察、答案与评阅/创建表单布局；同步前端技术栈为 Next.js 16 + React 19。纯前端 UX，后端 API 无变化 |
| 2026-07-14 | 1.26.2 | 修复 Render/Docker 默认 SQLite 路径：`backend/db/engine.py` 按运行布局解析默认 `.data`，本地源码树使用仓库根 `.data/edu_agent.sqlite3`，Docker 镜像使用 `/app/.data/edu_agent.sqlite3`，并仅在 SQLite fallback 时创建目录，避免未设置 `DATABASE_URL` 的部署环境尝试创建 `/.data` 导致 PermissionError |

