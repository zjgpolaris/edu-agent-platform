# EduAgent — K-12 AI 教学辅助平台

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://edu-agent-platform.vercel.app)
[![Backend](https://img.shields.io/badge/backend-render-blue)](https://edu-agent-backend-1e5x.onrender.com/api/debug/llm/health)

**Live Demo：** [edu-agent-platform.vercel.app](https://edu-agent-platform.vercel.app)
> 一键体验账号：`pilot-student` / `pilot123`（首页按钮会直达 AutoTutor Agent 主线）

---

## 亮点功能：AutoTutor 自主辅导 Agent

> 给定一个学生，Agent 自己决定教什么、怎么教、答错了怎么补——全程可观测、可评测、可干预。

```
plan ──> act ──> observe ──> judge ──┬── pass ──> next_step ──> exit_ticket ──> evidence ──> finalize
                                     └── fail ──> reflect ──> re_plan ──> act
```

与普通固定流水线的核心差异：

- **Plan**：读学生画像 + 错题本，自主生成本节课知识点顺序与教学策略
- **Reflect / Re-plan**：答错时诊断原因（讲得不对 / 题超纲），动态改变后续计划
- **全程可观测**：每个 node 写入 trace_store；Demo 账号在线上看到会话级授权、脱敏后的 Agent 决策旅程
- **来源可解释**：决策旅程与教师证据明确区分主模型、备用模型和确定性安全降级，不把 fallback 包装成模型结果
- **退出票证据**：教学结束前必须完成 exit ticket，结果写入 learning_events、错题/掌握度、复习与教师端辅导效果看板
- **课后自适应**：掌握的知识点移出错题本，薄弱点进入 SM-2 复习排期

---

## 5 分钟主线 Demo

先灌入稳定演示数据：

```bash
PYTHONPATH=backend python3 scripts/seed_pilot_demo.py
```

学生主线：

1. 在首页点击「Pilot 学生A · 体验 Agent 自主辅导」，系统使用 `pilot-student / pilot123` 登录并开始一节全新的「洋务运动目的」课程。
2. 查看本节目标、可信内容与右侧脱敏的 Agent 决策旅程。
3. 故意答错一次，观察 `judge → reflect → re-plan → reteach`。
4. 完成调整后的练习与不同题目的「退出票检验」。
5. 查看掌握层级、错题/复习回流与教师端可见的学习证据；刷新页面会恢复同一会话。
6. 点击「切换教师视角查看证据」，使用 Pilot 教师一键登录，按同一 session 查看反思、重规划和退出票证据。
7. 点击「重新演示」或重新从首页进入，可创建新会话，不需要重新执行 seed。
8. 如需展示 Eval / AgentOps，使用 `scripts/bootstrap_admin.py` 创建的管理员单独登录 `/eval`；学生账号不能访问管理员数据。

教师补充：

1. 登录 `pilot-teacher` / `pilot123`。
2. 打开 `/teacher` 或 `/teacher/assignments`，展示教师端布置作业与班级工作流入口。
3. 查看 Pilot 作业、欠交队列、质检盲区与 AutoTutor 辅导效果。

---

## 功能全景

### 学生端
| 功能 | 路径 | 说明 |
|------|------|------|
| **自主辅导 AutoTutor** | `/student/auto-tutor` | 自主 plan→reflect→re_plan 闭环 |
| 历史人物对话 | `/student/history/chat` | RAG 取材 + 流式 SSE + 来源引用 |
| **随问 · 学习助手** | `/student/assistant` | 混合语义路由 + 主动澄清 + 最多 3 步受限计划 + RAG / 工具确认治理 |
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
浏览器 ──> Vercel (Next.js 16 / React 19) ──fetch──> Render (FastAPI / Docker)
                                                   ├──> Supabase Postgres + pgvector (RAG)
                                                   ├──> Bailian / DashScope (LLM)
                                                   └──> Jina Embeddings v3 (向量化)
```

| 层 | 技术 |
|----|------|
| 前端 | Next.js 16 App Router、React 19、TypeScript strict、SSE 流式输出 |
| 后端 | FastAPI、Python 3.12；LangChain 模型集成与结构化输出；局部 LangGraph 状态图 |
| 数据库 | Supabase Postgres + pgvector（RAG 向量索引） |
| LLM | 阿里云百炼（qwen3.7-plus / deepseek-v4-flash） |
| Embedding | Jina Embeddings v3（1024维，2850文档） |
| 会话存储 | Redis（本地）/ 进程内存兜底（生产） |
| CI/CD | GitHub Actions：frontend lint + release gate + quick-eval；Docker build 在 main/manual 验证 |

AutoTutor 的 `autotutor_sessions` CAS 与领域事务仍是唯一业务写入边界。v1.49.3 加固 LangGraph active transition canary：`EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy|shadow|active_canary`，新会话仅在 schema 016、observation health、完整部署 commit、服务端可信 verified runtime cohort 和稳定 bucket 全部通过后选择 Graph；存量 Graph 会话在 admission revoked 或 kill switch 后会在 Provider 前永久降级 Legacy。assigned/selected executor、assignment/admission/fallback reason 粘性保存并写入 PII-free telemetry。active BPS 默认 0、production 本版硬上限 1%，任一不安全配置均 fail-closed。Graph 只接管 transition compute，不引入 PostgreSQL checkpointer/interrupt，也不接管学习证据事务。旧 `EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED=true` 在新 mode 未配置时仍兼容映射到 Shadow。

AutoTutor Canary 运维顺序固定为：先合并不可变 commit，并在 `BPS=0` 下升级到 migration 016；部署后通过手工触发的 `AutoTutor Production Verification` workflow 核对 commit、runtime schema、observation health、verified cohort 与至少 100 条 control transitions，再人工审批最多 `100 BPS` 的 Canary。达到至少 100 个 committed Graph transitions 后，使用 exact UTC window 生成 hash-sealed snapshot，完成 restart/writer-failure/kill-switch/rollback 四项演练，并将 schema v3 evidence 持久化。AgentOps 只显示脱敏后的 phase、blocker、进度和配置指纹；workflow 只读生产状态，不自动修改 Render 配置。任一 blocker 出现时立即设置 kill switch，或恢复 `EXECUTOR_MODE=legacy`、`BPS=0`；已提交 transition 不重放，015/016 的 nullable 遥测列无需回滚。完整操作与验收标准见 `docs/20260902-autotutor-canary-production-verification-v1494-spec.md`。

---

## 本地开发

```bash
# 1. 克隆并安装依赖（后端使用项目级 .venv）
git clone <repo>
cd edu-agent-platform
npm run setup:backend
npm install --prefix frontend

# 2. 复制并填写环境变量
cp .env.example .env.local
# 填写 BAILIAN_API_KEY / DATABASE_URL / EMBED_API_KEY 等

# 3. 启动（后端 :8000 + 前端 :3000）
npm run dev
```

`npm run dev` 会优先使用 `.venv/bin/python`，并在启动前检查后端依赖；依赖缺失时不会再先显示“services started”或启动后立即连带关闭前端。也可以用 `PYTHON_BIN=/path/to/python npm run dev` 显式选择已有环境。

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
npm run test:autotutor-quality        # AutoTutor 教学内容 groundedness / 重教差异质量评测
npm run test:assistant-multiturn      # 随问多轮上下文 / 会话隔离 smoke
npm run test:autotutor-handoff        # AutoTutor 课中随问 handoff smoke
npm run test:release-gate             # release gate / readiness summary smoke
npm run release:gate                  # 发布前统一闸门：Python 语法检查 + 后端 smoke + 前端 build
npm run release:gate:fast             # 快速关键路径发布闸门
python3 eval/auto_tutor_trajectory_eval.py  # AutoTutor 轨迹评测（含退出票闭环）
python3 eval/autotutor_teaching_quality_eval.py # AutoTutor 教学内容质量评测
python3 eval/tutor_effectiveness_smoke.py   # AI 辅导效果/退出票证据聚合

# 生产 RAG / readiness 验收：不属于默认 PR CI，需线上 API_BASE 与认证
API_BASE=https://<后端> SMOKE_USERNAME=<user> SMOKE_PASSWORD=<password> \
  npm run release:gate:prod -- --skip-frontend --ready-url https://<后端>/api/ready
npm run test:prod-rag                 # 显式运行生产 RAG 健康检查
```

健康检查分层：`/api/health` 是 liveness；`/api/ready` 是 shallow readiness，默认不触发外部 LLM/Embedding；`/api/debug/rag/health?deep=true` 与 `production_rag_health_smoke.py` 用于生产 RAG 深度检查。
传入 `--ready-url` 时，release gate 现在会输出 required / failed / warnings 摘要；若带 `--production`、`--ready-require-rag` 或 `--ready-require-external`，会把 RAG / 外部依赖配置作为 blocking readiness check。

当前项目按单环境 Agent Demo 部署：代码推送到 `main` 后先运行常规 CI，再由 Render 直接从 Git 仓库自动构建和发布。不要求 GHCR 镜像 digest、独立 staging、Render Deploy Hook 或生产灰度证据。Runtime v2 默认关闭，需要演示时通过 Render 环境变量显式开启；`--ready-require-runtime` 仅保留为可选的高级诊断，不属于 Demo 发布门禁。

生产启动入口先验证 `EDU_AGENT_AUTH_REQUIRED=true` 和至少 32 字节的随机 `JWT_SECRET`，再在 PostgreSQL advisory lock 下执行 Alembic `upgrade head`，确认 revision `013` 与 Runtime schema 完整后才启动 API。Render 必须配置 `DIRECT_URL`（Supabase direct/session connection）；普通 `DATABASE_URL` 继续供业务请求使用，transaction pooler 不承担 migration/advisory lock。认证或迁移失败都会输出结构化失败摘要并以非零状态退出；不要通过关闭认证或跳过迁移来恢复服务。

```bash
# SQLite：成功迁移、重复执行 no-op、失败时拒绝启动
PYTHONPATH=backend python3 eval/backend_startup_migration_smoke.py
PYTHONPATH=backend python3 eval/backend_startup_migration_failure_smoke.py

# 只对一次性 PostgreSQL 演练库执行；该库必须停留在 revision 003
DATABASE_URL=postgresql://... PYTHONPATH=backend \
  python3 eval/postgres_upgrade_rehearsal.py
DATABASE_URL=postgresql://... PYTHONPATH=backend \
  python3 eval/postgres_migration_lock_smoke.py
```

Runtime 开启时必须显式提供 `EDU_AGENT_RUNTIME_V2_CONFIG_VERSION`；空值和旧的 `v1.33-control` 默认值均 fail-closed。Run 由服务端写入 `deployed_commit` 与 `environment`，per-agent gate 只统计 provenance 完整且与当前部署一致的样本，coverage 不足 100% 时状态保持 `unknown`。

生产首次启用认证前，用一次性环境变量创建管理员；脚本不会输出密码、Hash 或连接串，已有管理员默认 no-op。公开 Pilot 固定为 `demo`，自助注册和历史账户默认为 `unverified`，都不会贡献 rollout 样本。受控试点学生只能逐个审批或撤销：

```bash
ADMIN_USERNAME=<secret> ADMIN_PASSWORD=<至少12字符> \
DATABASE_URL=<direct-or-session-url> PYTHONPATH=backend \
  python3 scripts/bootstrap_admin.py

DATABASE_URL=<direct-or-session-url> PYTHONPATH=backend \
  python3 scripts/set_rollout_cohort.py \
  --actor-id <student-id> --cohort verified --reason approved_pilot

DATABASE_URL=<direct-or-session-url> PYTHONPATH=backend \
  python3 scripts/set_rollout_cohort.py \
  --actor-id <student-id> --cohort unverified --reason rollout_revoked
```

v1.42 增加了只读灰度操作面。管理员可通过 `GET /api/admin/agent-runtime/rollout-status?agent_type=history_character` 查看当前 phase、control/shadow 样本进度、hard blockers 与唯一建议动作；Eval 页复用 AgentOps summary 展示相同口径。切换 Shadow 前先运行配置预检，生产最小样本数不可低于 100：

```bash
PYTHONPATH=backend python3 scripts/validate_runtime_rollout_config.py \
  --phase control --agent-type history_character

API_TOKEN=<短期admin-token> PYTHONPATH=backend \
  python3 scripts/validate_runtime_rollout_config.py \
  --phase shadow --agent-type history_character \
  --status-url https://<后端>/api/admin/agent-runtime/rollout-status
```

生产级不可变镜像、staging canary、Runtime evidence 和自动放量工作流未在 Demo 项目中启用。相关运行时观测字段与本地验证脚本仍保留，便于展示 Agent 生命周期、工具幂等和故障降级，但不会阻断普通 Git 部署。

`duplicate_side_effect_prevented` 与 `tool.idempotent_replay` 是幂等保护生效的观测计数，不等同于重复副作用；只有 `duplicate_side_effect_executed` 会触发重复副作用阻断。

本地 Docker Compose 现在默认启动 PostgreSQL 16 + pgvector，并先执行 Alembic migration 再启动后端：

```bash
docker compose up --build

# 或对已配置的 PostgreSQL 单独执行 migration/readiness 验证
make verify-postgres
```

AgentOps 的 production summary 现在会额外聚合最近 trace 中的 RAG 诊断口径，包括 `diagnosis_code` 分布和 `failure_stage` 分布，便于区分问题主要发生在检索阶段还是生成阶段；教材问答与历史人物两条链路都已接入该统计。

### 随问智能路由与受限计划（v1.29）

学习助手使用“安全规则 → 确定性候选 → 可选结构化语义路由 → 槽位澄清 → allowlist 计划执行 → 证据检查”的链路。组合请求（例如“先解释洋务运动，再出 3 道选择题”）只会生成最多 3 步的确定性计划；工具仍统一经过 Tool Registry、Pydantic 参数校验、角色权限和高风险确认。空检索或只读工具失败最多执行一次受控 repair，不会无限重试。

新能力默认采用安全灰度配置：

```bash
EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED=false
EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE=true
EDU_AGENT_ASSISTANT_ROUTER_CONFIDENCE_THRESHOLD=0.65
EDU_AGENT_ASSISTANT_PLANNER_ENABLED=false
```

离线质量验证：

```bash
PYTHONPATH=backend python3 eval/intent_accuracy_eval.py   # 300 条路由/槽位/澄清 case
PYTHONPATH=backend python3 eval/trajectory_eval.py        # 单工具、组合计划、澄清轨迹
npm run release:gate:fast -- --skip-frontend             # 已包含学习助手与 AutoTutor 智能质量门禁

# 手动 / nightly 真实模型盖章；无真实调用证据时以 NOT_RUN 失败退出，不会显示绿色 PASS
PYTHONPATH=backend python3 eval/run_core_evals.py --require-real-llm
```

Eval 报告会记录 commit SHA、suite profile、真实 LLM 调用状态和生成时间；`/eval` 会对 commit 不一致或超过 7 天的报告标记 `STALE`，并分别展示 skipped / not-run / infra-failed / quality-failed。

### 真实证据、稳定灰度与发布封印（v1.30）

v1.30 将运行、评测和 demo 事件在查询层分域，AgentOps 只用指定时间窗内的 runtime 样本判断 readiness；确认、权限拒绝等预期控制结果不再算作系统故障。语义路由和组合 Planner 使用稳定哈希桶独立灰度，支持 shadow、万分比流量、版本化 salt、高风险规则直达和 kill switch。

历史检索、教材问答与出题在 final 前执行确定性证据核验。回答必须能映射到标准化 source ID；缺少来源或映射时会降级为 partial/failed，并通过 `verification_start`、`verification_result` 和 final 的 `verification_summary` 对前端公开。

评测报告使用 schema v3，每次运行生成唯一 `eval_run_id`，真实 LLM 调用只接受当前 suite 输出的 run-scoped 计数，历史 AgentOps 调用不能为本次发布盖章。日常离线评测的 seal 明确为 `not_applicable`；dirty revision、缺少盲测、fallback-only 或无真实模型证据都会使强制 release seal 失败。

```bash
# 日常离线回归
PYTHONPATH=backend python3 eval/run_core_evals.py --quick --profile offline

# 私有盲测：路径必须在仓库之外，报告只输出聚合指标
EDU_AGENT_BLIND_EVAL_PATH=/secure/path/blind.jsonl \
PYTHONPATH=backend python3 eval/run_core_evals.py --profile blind --require-clean-revision

# 当前 run 的真实语义路由证据
PYTHONPATH=backend python3 eval/run_core_evals.py \
  --profile real_llm --require-real-llm --require-clean-revision

# 研究用途的外部真实学生 OOD 安全证据（原始数据必须位于仓库之外）
# 当前适配 Eedi Question-Anchored-Tutoring-Dialogues-2k CSV；仅输出聚合指标，
# 不能替代中文 in-domain blind 或真实 LLM 证据。
EDU_AGENT_EXTERNAL_OOD_PATH=/secure/path/eedi-test.csv \
PYTHONPATH=backend python3 eval/run_core_evals.py \
  --suite learning_assistant_external_ood_eval --profile production_canary
```

### 历史检索人工相关性复核（v1.31）

生产检索的 Recall@5、MRR 和 nDCG 只接受教研人员对稳定 `source_id` 给出的 `0/1/2` 相关性标签：`0` 为无关，`1` 为实体相关但不能回答目标维度，`2` 为可直接支持答案。系统生成的 `entity_match` 或 `answer_bearing` 不能作为自己的质量标签。

```bash
# 查看聚合复核状态
npm run history:review -- status

# 使用当前检索版本导出候选快照；复核包建议放在仓库之外
npm run history:review -- export --output /secure/path/history-retrieval-review.jsonl

# 教研填写 decision / reviewer_id / reviewed_at / judgments 后先做只读校验
npm run history:review -- apply --input /secure/path/history-retrieval-review.jsonl

# 确认无误后原子写回 reviewed 标签
npm run history:review -- apply --input /secure/path/history-retrieval-review.jsonl --write
```

复核包带有 case fingerprint 和候选快照 hash；问题、标签或候选内容变化后，旧包不能写回。生产质量评测要求当前 top source 全部存在人工判断，出现新的未标注 source ID 时会返回 `NOT_RUN`，必须重新导出和复核，避免索引变化后继续沿用失效标签。

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
PYTHONPATH=backend python3 scripts/seed_pilot_demo.py
# 学生：pilot-student / pilot123
# 教师：pilot-teacher / pilot123
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
