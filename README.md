# EduAgent — K-12 AI 教学辅助平台

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://edu-agent-platform.vercel.app)
[![Backend](https://img.shields.io/badge/backend-render-blue)](https://edu-agent-backend-1e5x.onrender.com/api/debug/llm/health)

**Live Demo：** [edu-agent-platform.vercel.app](https://edu-agent-platform.vercel.app)
> 演示账号：`demo-student` / `demo123`（进入「自主辅导」可直接看 AutoTutor 运行）

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
- **全程 Trace**：每个 node 写入 trace_store，右侧 TraceTimeline 实时可见
- **退出票证据**：教学结束前必须完成 exit ticket，结果写入 learning_events、错题/掌握度、复习与教师端辅导效果看板
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
5. 答完教学步骤后完成「退出票检验」，确认学习证据写入错题/复习与教师端分析。
6. 打开 `/eval`，展示 Eval / AgentOps 的 readiness、成功率、trace 与工具调用统计。

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

Runtime v2 灰度发布还需显式加入 `--ready-require-runtime`。该检查要求部署 commit/config、Alembic 011 schema 和当前版本 rollout evidence 一致；Runtime 关闭、样本不足或证据未运行都不会显示为通过。生产镜像不内置 Eval 目录，真实 LLM/RAG 聚合报告通过 `scripts/build_rollout_evidence.py` 绑定 control baseline 后写入 `agent_release_evidence`。

v1.41 的生产启动入口会先在 PostgreSQL advisory lock 下执行 Alembic `upgrade head`，确认 revision `011` 与 Runtime schema 完整后才启动 API。Render 必须配置 `DIRECT_URL`（Supabase direct/session connection）；普通 `DATABASE_URL` 继续供业务请求使用，transaction pooler 不承担 migration/advisory lock。迁移失败会输出结构化失败摘要并以非零状态退出；不要通过跳过迁移来恢复服务，应先检查数据库快照、连接和 migration 日志。本地或 CI 可分别验证：

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

v1.42 增加了只读灰度操作面。管理员可通过 `GET /api/admin/agent-runtime/rollout-status?agent_type=history_character` 查看当前 phase、control/shadow 样本进度、hard blockers 与唯一建议动作；Eval 页复用 AgentOps summary 展示相同口径。切换 Shadow 前先运行配置预检，生产最小样本数不可低于 100：

```bash
PYTHONPATH=backend python3 scripts/validate_runtime_rollout_config.py \
  --phase control --agent-type history_character

API_TOKEN=<admin-token> PYTHONPATH=backend \
  python3 scripts/validate_runtime_rollout_config.py \
  --phase shadow --agent-type history_character \
  --status-url https://<后端>/api/admin/agent-runtime/rollout-status
```

GitHub Actions 的手动工作流 **Runtime Rollout Preflight** 只验证部署 commit、control baseline、线上聚合状态和建议的 history-only Shadow 配置，并产出脱敏 promotion plan；它不会修改 Render 环境变量或流量。`EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED` 必须保持 `false`，其他 Agent 的 BPS 必须为 0。配置不一致、样本不足或线上状态不可用时预检 fail-closed。

生产 evidence 使用 GitHub Actions 的手动工作流 **Runtime Rollout Evidence**，由受保护的 `production` environment 审批后执行。它会校验线上 commit、运行 offline/real-LLM/production-RAG 三类 profile、持久化 hash-bound aggregate evidence，再要求 strict readiness 和 per-agent gate PASS。control 与 shadow 的状态语义如下：

- `pass`：证据、provenance、样本和安全/一致性/延迟阈值全部满足；
- `warn`：证据完整，但非阻断阈值进入观察区；
- `unknown`：schema、证据、provenance、baseline 或样本不足，不得放量；
- `fail`：出现重复副作用、非法状态迁移、高风险违规或质量阈值越线，必须停止。

本地 deterministic/CI 通过仅代表 **Development Complete**。生产 revision `011`、control ≥100、shadow ≥100、gate PASS 以及后续 48 小时稳定观察完成前，Operational 状态仍为 `NOT_RUN/unknown`。

```bash
# 三份报告必须来自同一 clean deployed commit，且生成时间不超过 7 天。
# control baseline 只读取同环境、同 commit/config 的服务端聚合观测，不读取客户端耗时。
PYTHONPATH=backend python3 scripts/build_rollout_evidence.py \
  --agent-type history_character \
  --config-version v1.40-history-shadow \
  --runtime-mode shadow \
  --deployed-commit "$RENDER_GIT_COMMIT" \
  --environment staging \
  --baseline-config-version v1.40-history-control \
  --baseline-commit <control-commit> \
  --minimum-samples 100 \
  --offline-report /secure/evidence/offline.json \
  --real-llm-report /secure/evidence/real-llm.json \
  --production-rag-report /secure/evidence/production-rag.json \
  --output /secure/evidence/rollout-evidence.json \
  --persist
```

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
