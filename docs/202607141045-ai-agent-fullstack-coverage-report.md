# AI Agent 工程师与 AI 全栈工程师能力要求、项目覆盖率与推进方向分析报告

> 生成时间：2026-07-14 10:45
> 修订时间：2026-07-14
> 项目：EduAgent — K-12 中文/历史 AI 教学平台
> 范围：结合 2025-2026 年 AI Agent 工程师、AI 全栈工程师岗位要求与当前仓库能力，评估项目覆盖率、短板与后续推进方向。

---

## 1. 执行摘要

当前 EduAgent 已经不是普通 AI 教育 demo，而是一个具备较强工程纵深的 **AI 教育 Agent 全栈产品**。项目已覆盖 FastAPI 后端、Next.js 前端、RAG、LangGraph-style Agent、工具治理、MCP Server、结构化输出、Trace 可视化、Eval/Smoke/Release Gate、学生/教师双端工作流等关键能力。

综合判断如下。这里的百分比表示“仓库中可见的能力覆盖”，不等同于生产成熟度或求职成功率；由于岗位权重不同，数字应作为区间估算，而不是精确评分。

| 方向 | 覆盖率估算 | 判断 |
|---|---:|---|
| AI Agent 工程师能力 | 约 75%-80% | Agent 工作流、RAG、工具治理、Trace、Eval 基础较强；完整质量状态、MCP Client、durable execution 和生产运行证据仍需加强 |
| AI 全栈工程师能力 | 约 75%-80% | 前后端产品闭环、CI、容器化、组件测试、浏览器 E2E 与依赖安全基线已具备；自动部署、生产监控和真实用户指标不足 |
| RAG/知识库工程 | 约 80% | 历史知识库、教材、OCR/结构化材料、hybrid search、rerank、citation、RAG health/eval 均有基础；不应等同于原生多模态模型能力 |
| Tool Use / MCP | 约 75%-80% | Tool Registry + MCP Server 较好；已补 stdio MCP Client、动态工具发现、权限/确认和外部结果治理，仍缺多 Server routing 与真实第三方接入证据 |
| Eval / AgentOps | 约 75%-80% | smoke/eval/release gate/trace 已成体系，但完整质量报告需刷新，不能仅凭快速 gate 判定整体绿色 |
| 安全治理 | 约 70% | 有 prompt injection、权限、确认、审计；需增强 red team 和策略评测 |
| 场景级多 Agent | 约 60%-65% | 已修正辩论 supervisor 重复阶段并补角色 trace/eval；仍以固定流程为主，缺并行 fan-out、动态委派和统一 runtime |
| 生产化工程 | 约 65%-70% | 已有 GitHub Actions、Docker、Compose、release/readiness gate 和最小 Durable Job worker；缺 CD、IaC、告警、回滚演练和生产 SLO 证据 |
| Claude/Anthropic 专项能力 | 约 45%-55% | 已安装 Anthropic SDK 依赖，但核心运行路径仍是兼容协议/自定义 Node transport，缺原生 tool use、caching 和 Agent SDK 深度实践 |

建议定位：

> 将 EduAgent 打造成“AI Agent 全栈工程作品集”：以教育场景为载体，展示 Agent 工作流、RAG、工具治理、MCP、Eval、Trace、全栈产品化和安全闭环。

后续不建议继续优先堆新页面，而应优先把已有能力变成可重复验证、可部署运行、可量化说明的证据：

1. 刷新完整 CORE eval 并收绿质量基线
2. 修正和增强现有多 Agent 辩论流程及角色级 trace/eval
3. 扩充 Playwright E2E 与前端 component test 覆盖
4. 生产监控、SLO、告警、回滚和部署证据
5. MCP Client 与外部工具治理
6. Durable Agent Job / 分布式执行
7. 按目标岗位选择 Claude 原生 provider adapter

### 1.1 本轮实施状态（2026-07-14）

| 路线图任务 | 状态 | 新增或修正证据 |
|---|---|---|
| 完整 CORE eval | 已完成，未全绿 | 首轮 `18/24 suites`、`102/110 cases`；已修复 PostgreSQL `MAX(a,b)` 兼容问题及离线 suite 被凭证误触发的问题，专项复验均通过；历史人物质量 suite 仍受百炼免费额度耗尽阻塞 |
| 多 Agent 辩论修正 | 已完成 | 清理重复阶段；补正反方、事实核查、裁判、学习教练角色 trace，以及固定轨迹与错误分支 smoke |
| Trajectory / Groundedness / Safety | 已完成 | 补 tool input、tool output utilization、citation groundedness、RAG/tool-output injection、高风险确认和 PII 评测 |
| 前端自动化测试 / CI | 已完成基线 | Vitest component test `6/6` 覆盖高风险工具确认与 TraceTimeline 加载/失败/RAG 详情契约；本机 Playwright Chromium `5/5` 覆盖学生复习/作业/AutoTutor、教师作业、Eval/Trace；两者均接入 CI，E2E 保留失败 trace/video/report artifact |
| MCP Client | 最小闭环已完成 | stdio 初始化、动态 `tools/list`、allowlist、角色/确认、外部结果不可信标记、压缩、trace 和 smoke |
| Durable Agent Job | 最小闭环已完成 | `agent_jobs` 表与 migration、worker、幂等、重试、超时、取消、恢复、轮询 API、周报任务和 smoke |
| 认证与测试隔离 | 已完成 | 修复 FastAPI bearer `credentials` 字段读取；数据库引擎正式支持 `EDU_AGENT_DB_PATH`，认证开启回归与 E2E 均通过 |
| 前端框架与依赖安全 | 已完成 | Next.js `14.2.35 → 16.2.10`、React `18 → 19.2.7`、React Leaflet `4 → 5`；完成 async params、ESLint CLI、Turbopack、PostCSS 安全覆盖迁移，完整 `npm audit` 为 `0 vulnerabilities`，build/unit/E2E 均通过 |
| 容器运行加固 | 配置完成，未实跑 | 前后端非 root、healthcheck、Compose 健康依赖已补；当前机器无 Docker CLI，不能声称镜像构建/Compose smoke 已通过 |
| CD / SLO / 告警 / 回滚 / IaC | 未完成 | 属于下一轮生产环境工作，需部署权限、目标云环境和告警渠道 |

---

## 2. 当前 AI Agent 工程师主流要求

2025-2026 年，AI Agent 工程师已经从“会调用 LLM API”演进为“能构建、评测、监控、安全上线 Agent 系统”的工程岗位。

### 2.1 能力模型

| 能力项 | 具体要求 |
|---|---|
| LLM API 接入 | 熟悉 Claude/OpenAI/云厂商模型 API、流式输出、结构化输出、tool calling、多模型 fallback、成本/延迟控制 |
| Agent 编排 | LangGraph、OpenAI Agents SDK、LlamaIndex、Semantic Kernel、CrewAI、AutoGen 等；掌握 planner/executor、router、critic、reflection、HITL |
| Context Engineering | 上下文组装、压缩、预算、版本管理、tool result summarization、context pollution 控制、模型路由和缓存策略 |
| RAG 工程 | 文档解析、chunking、embedding、向量库、metadata、rerank、hybrid search、grounding、citation、RAG eval |
| Tool Use / MCP | 工具 schema 设计、工具结果压缩、权限控制、错误处理、MCP server/client、resources/prompts/tools |
| 多智能体 | supervisor/worker、agent-as-tool、并行 fan-out、任务队列、共享状态、结果聚合 |
| Eval 能力 | golden set、multi-turn eval、tool eval、trajectory eval、LLM-as-judge、回归评测、安全评测 |
| Observability | trace/span/generation/tool call/token/cost/latency 监控，线上失败案例回放 |
| Safety / Guardrails | prompt injection 防护、RBAC、敏感工具确认、audit log、red team、数据泄露防护 |
| Memory / State | 会话状态、长期记忆、用户画像、任务状态、上下文压缩、隐私删除策略 |
| Durable Execution | 队列、幂等、重试、超时、取消、断点恢复、并发控制、dead-letter、任务状态持久化 |
| 部署运维 | Docker/K8s/serverless、release gate、monitoring、rollback、LLMOps/AgentOps |
| 软件工程 | API contract、系统设计、可靠性、扩展性、测试、代码评审、技术文档与完整 SDLC |

### 2.2 关键趋势

#### 2.2.1 Tool use 正在成为 Agent 工程核心

当前行业更重视工具的“可被 Agent 稳定使用”能力，而不是简单把 API 包成 function。优秀工具需要：

- 面向真实工作流设计，而不是机械映射底层 API；
- 有清晰 schema 和参数语义；
- 有压缩、稳定、可解析的返回结构；
- 有错误处理、权限、审计、确认机制；
- 能通过 eval 反复迭代工具描述、参数和结果格式。

#### 2.2.2 Eval 是 Agent 工程师的分水岭

Agent 评测不能只看最终文本，还需要看：

- 是否选对工具；
- 工具参数是否正确；
- 是否正确利用工具结果；
- 多轮轨迹是否合理；
- 是否遵守安全边界；
- 是否被知识库证据支撑；
- 失败样本是否进入回归集。

#### 2.2.3 Observability / AgentOps 是生产化必备

生产 Agent 需要追踪：

- model generation；
- tool call；
- guardrail；
- handoff；
- latency；
- token/cost；
- eval failure；
- RAG 诊断；
- red team risk。

#### 2.2.4 MCP 正在成为 Agent 工具生态标准之一

MCP 的核心价值是将工具、资源、提示词标准化暴露给 Agent。工程师需要理解：

- `tools/list`；
- `tools/call`；
- resources；
- prompts；
- structuredContent；
- annotations；
- human-in-the-loop；
- access control / rate limit / output sanitization。

---

## 3. 当前 AI 全栈工程师主流要求

AI 全栈工程师更强调把 AI 能力做成真实产品。岗位不一定要求深入模型训练，但要求能完成前端、后端、数据库、云部署、测试、安全和产品交付。

### 3.1 能力模型

| 能力项 | 具体要求 |
|---|---|
| 前端 | React/Next.js/TypeScript、组件化、状态管理、响应式、性能、可访问性 |
| AI 前端体验 | Chat UI、streaming、source citation、file upload、trace viewer、human review console |
| 后端 | Python/FastAPI、Node.js、REST/GraphQL、认证、权限、异步任务、服务集成 |
| 数据库 | PostgreSQL、Redis、MongoDB/DynamoDB、pgvector/vector DB、数据权限与隔离 |
| LLM 集成 | LLM API、RAG、embedding、知识库、tool calling、prompt engineering |
| 云部署 | AWS/GCP/Azure、Docker、K8s、serverless、API Gateway、Secret Manager |
| DevOps | Git、CI/CD、release gate、monitoring、logging、alerting、runbook |
| 测试 | unit、integration、E2E、smoke、regression、AI eval |
| 安全 | JWT/OAuth/RBAC、审计、限流、数据保护、prompt injection 防护 |
| 系统设计 | API contract、并发与性能、可靠性、扩展性、幂等、故障恢复、服务边界 |
| 产品交付 | 需求澄清、MVP、真实用户验证、业务指标、实验取舍、跨团队协作 |

### 3.2 AI 全栈岗位的典型产品能力

AI 全栈工程师作品集需要证明：

1. 能做完整前后端功能，而不是单一 API；
2. 能处理用户角色、权限、状态、数据生命周期；
3. 能设计 AI 产品交互，如流式响应、引用来源、人工审核、确认弹窗；
4. 能做 RAG/知识库/文件上传等 AI 应用基础功能；
5. 能通过测试、CI、监控、部署把项目推向真实可用。
6. 能用任务完成率、人工接管率、延迟、成本和用户反馈证明 AI 功能产生了真实价值。

---

## 4. EduAgent 当前能力覆盖分析

### 4.1 项目概况

EduAgent 是一个 K-12 中文/历史 AI 教学平台，当前实现为双服务应用：

- `backend/`：FastAPI API，提供历史人物对话、作文批改、辩论、历史游戏、AutoTutor、作业、复习、教师分析等能力；
- `frontend/`：Next.js 16 + React 19 App Router 前端，覆盖学习中心、学生端、教师端、历史人物聊天、历史游戏等页面；
- `knowledge_base/`、`textbooks/`：历史语料与教材材料；
- `eval/`：Agent 行为 smoke/eval；
- `scripts/`：索引构建、发布 gate、验证脚本等。

### 4.2 已覆盖能力一览

| 能力 | 覆盖程度 | 当前项目证据 |
|---|---:|---|
| Agent 工作流 | 高 | `backend/agents/history_character.py`、`backend/agents/auto_tutor.py` |
| RAG | 高 | `backend/rag/knowledge_base.py`、`build_index.py`、历史知识库/教材/材料检索 |
| Tool Registry | 高 | `backend/tools/registry.py`、`backend/tools/base.py` |
| 高风险工具确认 | 高 | `backend/tools/confirmation.py`、`frontend/components/ToolConfirmationDialog.tsx` |
| MCP Server | 中高 | `backend/mcp_server.py`、`eval/mcp_server_smoke.py` |
| MCP Client | 中 | `backend/mcp_client.py`、`eval/mcp_client_smoke.py`；当前覆盖 stdio 与本地治理，尚未证明多外部 Server routing |
| Durable Agent Job | 中 | `backend/services/agent_job_service.py`、`backend/agent_job_worker.py`、`backend/alembic/versions/004_agent_jobs.py`、`eval/agent_job_smoke.py` |
| Structured Output | 高 | `backend/structured_output.py` |
| Trace / Observability | 中高 | `backend/tracing.py`、`backend/trace_store.py`、`backend/agent_ops.py`、`frontend/components/TraceTimeline.tsx`；已有 cost/latency 汇总，但覆盖率和生产告警仍需增强 |
| Eval / Smoke | 中高 | `eval/run_core_evals.py`、`scripts/release_gate.py`、`scripts/verify_core.py`；框架完整，但最新完整质量报告需刷新 |
| 安全治理 | 中高 | `backend/security/*`、prompt injection、auth、audit、rate limit |
| 数据建模 | 中高 | `backend/db/schema.py`、Alembic migrations、PostgreSQL/Supabase |
| 前端产品化 | 中高 | `frontend/app/*`、学生/教师双端页面 |
| CI / 容器化 | 中高 | `.github/workflows/ci.yml`、`backend/Dockerfile`、`frontend/Dockerfile`、`docker-compose.yml`、`.env.example` |
| 生产运行 | 中低 | 有 release/readiness gate，但缺自动部署、IaC、队列 worker、告警、回滚演练和 SLO 证据 |
| 场景级多 Agent | 中 | `backend/agents/debate_supervisor.py` 已有正反方、事实核查、裁判和学习教练；仍是固定串行流程，需清理重复阶段并补角色级 trace/eval |
| 通用 Multi-Agent Runtime | 低 | 缺动态委派、并行 fan-out、agent-as-tool、任务恢复、统一消息和状态治理 |
| Claude 原生能力 | 中低 | `anthropic`/`langchain-anthropic` 已安装，但核心调用经 `zode_client.js`，缺原生 tool use、prompt caching、完整 streaming event contract 和 Agent SDK 深度集成 |

---

## 5. 强项分析

### 5.1 Agent 工作流与教学闭环完整

当前项目不是普通 chatbot，而是围绕教育场景形成了多个 Agent 产品闭环：

- 历史人物对话 Agent；
- AutoTutor 自主辅导 Agent；
- 作业-错题-复习-辅导闭环；
- 学生成长报告；
- 教师分析与建议；
- 历史游戏与多人游戏。

关键代码：

- `backend/agents/history_character.py`
- `backend/agents/auto_tutor.py`
- `backend/agents/learning_assistant.py`
- `backend/agents/history_games.py`
- `backend/agents/multiplayer_game.py`

其中 AutoTutor 已体现典型 Agent workflow：规划、执行、观察、判断、反思、重规划、总结。这对 AI Agent 工程师能力证明很强。

### 5.2 Tool Registry / 权限治理能力突出

项目已经有较完整的工具治理中台，覆盖：

- 工具统一注册；
- schema 校验；
- role 权限；
- risk level；
- side effect 标记；
- confirmation token；
- audit log；
- timeout；
- trace 关联。

关键代码：

- `backend/tools/registry.py`
- `backend/tools/base.py`
- `backend/tools/confirmation.py`
- `frontend/components/ToolConfirmationDialog.tsx`

这非常符合当前 Agent 工程中对 tool safety、HITL、governance 的要求。

### 5.3 MCP Server 已具备生态接口能力

项目实现了 MCP Server，并暴露教育工具：

- `search_history_knowledge`
- `get_textbook_lesson`
- `suggest_review_plan`
- `generate_quiz`

关键代码：

- `backend/mcp_server.py`
- `eval/mcp_server_smoke.py`
- `package.json`

这说明项目已经开始从“内部工具”走向“Agent 生态接口”。

### 5.4 Structured Output 能力扎实

项目有统一结构化输出层，支持：

- JSON object/list parsing；
- Pydantic validation；
- parse model；
- repair JSON with LLM；
- fallback；
- `invoke_structured` / `invoke_json`。

关键代码：

- `backend/structured_output.py`

这对题目生成、批改结果、Agent 计划、质量评测等场景很关键。

### 5.5 Trace / AgentOps / Eval 已成体系

项目已经具备：

- trace/span/generation；
- trace store；
- TraceTimeline 前端组件；
- eval runner；
- release gate；
- production RAG health smoke；
- MCP smoke；
- AutoTutor trajectory eval；
- question quality eval；
- weakpoints/review loop smoke。

关键代码：

- `backend/tracing.py`
- `backend/trace_store.py`
- `backend/agent_ops.py`
- `frontend/components/TraceTimeline.tsx`
- `eval/run_core_evals.py`
- `scripts/release_gate.py`
- `scripts/verify_core.py`

静态可见规模：

- `CORE_SUITES = 26`
- `QUICK_SUITES = 20`
- `SMOKE_SUITES = 45`
- `eval/` 顶层 Python 文件约 50+ 个

这使项目具备较强“可评测、可观测、可回归”的工程证明力。

但应区分“评测基础设施覆盖度”和“当前质量状态”：2026-07-14 已刷新完整 CORE，首轮为 `18/24 suites passed`、`102/110 cases passed`。其中 PostgreSQL `MAX(a,b)` 兼容缺陷导致的两个 suite 已修复并专项复验 `9/9`；三个本应离线确定性的 Agent suite 已隔离外部数据库/模型凭证并专项复验 `26/26`；新增 MCP Client 和 Durable Job smoke 也已通过。当前仍不能宣称整体绿色，因为历史人物质量 suite 受百炼免费额度耗尽阻塞；runner 现会将捕获到额度错误的超时明确标记为 `external_model_quota_exhausted`，避免与代码死锁混淆。同期 `npm run release:gate:fast -- --skip-frontend` 为 `46/46 cases`、`10/10 suites`，证明快速试点主路径绿色，但不替代外部模型质量验证。

### 5.6 全栈产品闭环较完整

项目已经覆盖学生端和教师端：

- 学生首页；
- 今日任务；
- 作业；
- 错题本；
- 今日复习；
- AutoTutor；
- 成长报告；
- 教师工作台；
- 班级学情；
- 教师资料库；
- 作业布置；
- 审核页；
- Eval / AgentOps / Trace 可视化。

关键代码：

- `frontend/app/page.tsx`
- `frontend/app/(student)/student/page.tsx`
- `frontend/app/(teacher)/teacher/page.tsx`
- `backend/api/main.py`

这符合 AI 全栈工程师对“完整产品交付”的要求。

### 5.7 CI 与容器化已经具备基础

项目已经存在：

- `.github/workflows/ci.yml`：frontend lint、release gate、quick eval、Docker build、production readiness；
- `backend/Dockerfile`、`frontend/Dockerfile`；
- `docker-compose.yml`；
- `.env.example`。

因此项目不再属于“缺 CI / 缺容器化”。准确评价是：**已有 CI 和容器化基础，但 CD、IaC、镜像发布/扫描、生产告警、SLO、回滚演练和 durable worker 仍缺证据。**

---

## 6. 主要短板与缺口

### 6.1 Claude / Anthropic 原生平台能力不足

当前项目虽然支持 Anthropic-compatible 配置，但核心调用路径更像 provider-agnostic/proxy-first 架构。

相关文件：

- `backend/llm_config.py`
- `backend/zode_client.js`
- `backend/requirements.txt`

目前缺少明显证据：

- Anthropic 官方 SDK 主路径；
- Claude Messages API 原生调用；
- Claude tool use 原生 contract；
- Claude prompt caching；
- Claude context management / extended thinking；
- Claude Agent SDK；
- Claude 原生 MCP connector 或 hosted tool 形态。

如果目标是 Claude/Anthropic 平台方向，这部分建议补强；如果目标是通用 AI Agent 工程师，不应因为缺 Claude 专项能力直接扣减通用能力得分，应优先证明多 provider routing、可靠性、成本/延迟和工具 contract。

### 6.2 场景级多 Agent 已修正，但仍不是通用 Runtime

`backend/agents/debate_supervisor.py` 已经明确实现多角色协作：正方、反方、Fact Checker、Judge、Learning Coach。这证明项目并非“缺显式 supervisor-worker”。

本轮已清理 `stream_debate()` 重复阶段，并补充角色级 trace、citation 要求和固定轨迹/失败分支 eval。当前准确短板是：

- 流程主要由代码固定串行执行，缺动态委派；
- 缺并行 fan-out 和结果聚合；
- 缺 agent-as-tool；
- 缺多 Agent 消息队列、持久化状态和失败恢复；
- 角色级 trace/eval 已有最小基线，但缺质量、成本和延迟的单 Agent 对照实验；
- 缺 partial failure recovery 和跨进程状态恢复。

因此应评价为“已有场景级多 Agent 证据，通用 multi-agent runtime 仍不足”。

### 6.3 MCP Client 已有最小闭环，外部生态证据仍不足

本轮已补 stdio MCP Client、动态 `tools/list`、allowlist、角色/确认策略、结果压缩与不可信标记、trace 和 smoke。仍缺少：

- 外部 MCP Server 接入；
- 多 MCP Server routing；
- HTTP/SSE transport、resources/prompts；
- 真实第三方 MCP Server 接入、凭证隔离和故障演练。

这部分是从“提供工具”升级到“编排工具生态”的关键。

### 6.4 前端 E2E 与 component test 已建立基线

本轮已加入 Playwright 配置、5 条核心页面验收、Vitest + Testing Library 配置、高风险工具确认与 TraceTimeline 的 6 条契约测试，以及对应 GitHub Actions job。当前仍不足的是：

- component test 已覆盖首个高风险交互和 TraceTimeline，但尚未扩展到复杂表单与流式对话；
- 作业提交、AutoTutor 完整生成等模型相关深链路尚未形成稳定离线 fixture；
- 仍需在 CI 连续运行中积累 flaky rate 和失败回放证据。

AI 全栈岗位通常会重视：

- component test；
- E2E test；
- regression test；
- CI 自动执行。

### 6.5 最小 Durable Execution 已完成，CD 和分布式执行仍不足

当前已经有 GitHub Actions CI、前后端 Dockerfile、Docker Compose、release gate、readiness 和 Supabase/PostgreSQL。因此短板不应再写成“缺 Docker/CI”，而应写成：

- 缺自动部署和环境晋级；
- 缺 IaC、镜像 registry 发布和镜像安全扫描；
- 已有数据库 job table + 单进程 worker，以及幂等、重试、超时、取消、失活恢复和失败原因；
- 尚缺 Redis/Temporal/云队列级分布式 worker、租约续期、优先级、并发配额和正式 dead-letter 队列；
- 缺生产日志聚合、指标、告警、SLO 和回滚演练；
- Secret management 和供应商数据传输边界缺少可验证证据。

当前更准确的定位是“较完整 AI 产品 + CI/容器化基础 + 轻量生产化”，还不是完整云原生 Agent 平台。

### 6.6 完整质量状态和在线质量闭环不足

项目已有大量 smoke/eval、trajectory eval 和 trace-to-eval-case 能力，但仍需补齐：

- 刷新并收绿完整 CORE eval；
- tool input correctness、tool output utilization、citation faithfulness、multi-turn trajectory；
- failure taxonomy、历史失败 replay；
- canary/A-B、人工接管率、任务完成率和用户反馈；
- 生产 token/cost/latency SLO 与告警。

### 6.7 真实用户与业务效果证据不足

当前仓库能证明功能和工程闭环，但还不能充分证明：

- 学生任务完成率是否提升；
- AutoTutor 是否改善掌握度；
- 教师审核时间是否下降；
- AI 建议接受率、人工修改率和错误率；
- 单次任务成本、延迟与用户留存之间的取舍。

这些指标是当前 AI 全栈岗位强调“从原型到生产、基于真实用户迭代”的关键证据。

### 6.8 未成年人数据治理需要单独加强

教育项目应补充：学生数据最小化、数据保留/删除、教师/学生/班级隔离、PII 脱敏、trace/prompt 敏感信息治理、模型供应商数据边界和审计策略。这部分比普通应用具有更高的场景重要性。

---

## 7. 推进方向

### 7.1 P0：增强 AI Agent 工程师证明力

#### 方向 1：先把现有多 Agent 辩论做成可信样板

不建议先新增一个庞大的“教师备课六 Agent”。Anthropic 的生产建议是：只有当上下文污染、可并行探索或专业化带来明确收益时，才引入 multi-agent；否则协调成本和故障点可能超过收益。

建议先升级 `backend/agents/debate_supervisor.py`：

- 清理 `stream_debate()` 重复执行阶段；
- 为正反方、Fact Checker、Judge、Learning Coach 增加角色级 trace；
- 事实核查输出 citation；
- 将可独立的评审步骤并行化；
- 对比单 Agent 与多 Agent 的质量、成本、延迟；
- 增加 handoff、aggregation、partial failure、recovery eval。

只有 eval 证明现有场景确实受益后，再抽象 agent-as-tool、动态委派和通用 runtime。

#### 方向 2：刷新质量基线并增强现有 Trajectory Eval

项目已经有 `eval/trajectory_eval.py` 和 `eval/auto_tutor_trajectory_eval.py`，不应再将 trajectory eval 表述为从零补齐。建议优先重新运行完整 CORE eval，并在现有测试上补充：

- tool input correctness；
- tool output utilization；
- multi-turn trajectory；
- historical failure replay；
- online failure taxonomy；
- `eval/rag_groundedness_eval.py`；
- `eval/autotutor_safety_eval.py`

覆盖：

| Eval 类型 | 检查点 |
|---|---|
| Tool selection eval | Agent 是否选对工具 |
| Tool input eval | 工具参数是否正确 |
| Tool output utilization eval | 是否正确使用工具返回 |
| Trajectory eval | 中间步骤是否合理 |
| Safety eval | 高风险工具是否触发确认 |
| RAG groundedness eval | 回答是否被资料支撑 |
| Regression eval | 历史失败样本是否复现修复 |

价值：

- 对标 Anthropic/OpenAI/Microsoft 的 agent eval 方法；
- 将项目从“功能可用”提升到“行为可评测”。

#### 方向 3：Claude/Anthropic 原生路径

建议新增：

- `backend/providers/anthropic_native.py`
- 原生 Messages API adapter；
- 原生 tool use 示例；
- streaming events adapter；
- prompt caching 示例；
- Claude model config；
- Claude-specific smoke test。

价值：

- 保留 provider-agnostic 架构，同时补齐 Claude 专项能力；
- 更贴近 Claude Code / Claude Agent / Anthropic API 方向岗位。

---

### 7.2 P1：增强 AI 全栈工程师证明力

#### 方向 4：补 Playwright E2E

建议先覆盖 5 条核心路径：

1. 学生登录 → 今日任务 → 进入复习；
2. 学生提交作业 → 生成错题 → 进入错题本；
3. AutoTutor 进入 → 生成计划 → 完成 exit ticket；
4. 教师登录 → 创建作业 → 查看完成率；
5. Trace/Eval 页面加载 → 查看一次 agent trace。

建议新增：

- `frontend/playwright.config.ts`
- `frontend/e2e/student-review.spec.ts`
- `frontend/e2e/assignment-flow.spec.ts`
- `frontend/e2e/autotutor.spec.ts`
- `frontend/e2e/teacher-assignment.spec.ts`

价值：

- 明显增强全栈工程证明力；
- 为后续重构提供安全网。

#### 方向 5：在现有 GitHub Actions 上补 CD 与质量晋级

`.github/workflows/ci.yml` 已经覆盖 frontend lint、release gate、quick eval、Docker build 和 production readiness。下一步应补：

- Playwright E2E；
- backend/frontend image push；
- preview/staging 自动部署；
- 环境晋级和审批；
- migration check；
- 镜像/依赖安全扫描；
- smoke 后自动回滚或阻断；
- release evidence artifact。

#### 方向 6：验证现有容器并补生产运行证据

项目已有前后端 Dockerfile、`docker-compose.yml` 和 `.env.example`。下一步应补：

- Compose 一键启动 smoke；
- health/readiness 与依赖启动顺序验证；
- 镜像体积、非 root 用户和漏洞扫描；
- PostgreSQL/pgvector、Redis、migration、RAG index rebuild 的可复现流程；
- 生产日志、指标、告警、SLO、runbook 和回滚演练；
- Terraform/CDK 等 IaC，或至少可复现的云部署配置。

---

### 7.3 P2：从产品原型走向 Agent 平台

#### 方向 7：MCP Client + 外部工具接入

建议实现：

- 连接外部 MCP Server；
- 动态发现 tools；
- 工具权限映射到当前 role/risk_level；
- 外部工具调用 trace；
- 外部工具结果 sanitization；
- MCP tool eval。

价值：

- 从“我提供工具”升级为“我能编排工具生态”；
- 更接近 Claude Desktop / Claude Code / Agent Platform 的真实场景。

#### 方向 8：Durable Agent Job 系统

建议新增：

- `agent_jobs` 表；
- job status：`pending/running/succeeded/failed/cancelled`；
- SSE/polling 查询；
- retry；
- timeout；
- idempotency key；
- cancel；
- concurrency limit；
- dead-letter / failure reason；
- trace_id 绑定；
- 长任务恢复。

可选方案：

- 简单版：PostgreSQL job table + background task；
- 中级版：Redis Queue / RQ / Celery / Arq；
- 高级版：Temporal / cloud queue。

价值：

- 支持长流程生成、批量作业批改、教师报告生成；
- 项目更像生产级 Agent 平台。

#### 方向 9：Agent Red Team / 安全演练集

建议覆盖：

- prompt injection；
- 越权读取；
- 高风险工具绕过；
- RAG 注入；
- 学生隐私泄露；
- 教师/学生角色越权；
- tool output injection；
- 学生数据最小化与删除；
- trace/prompt 中的 PII 脱敏；
- 班级/教师/学生租户隔离；
- 模型供应商数据传输边界。

价值：

- 教育产品涉及未成年人数据，安全治理是重要亮点；
- 符合当前 Agent 岗位对 safety/guardrails 的要求。

---

## 8. 推荐实施路线图

### 第 1 阶段：质量证据收口，1-2 周

目标：把已有 Agent 能力变成可重复验证的绿色基线。

建议任务：

1. 重新运行并收绿完整 CORE eval；
2. 清理多 Agent 辩论重复阶段，补角色级 trace/eval；
3. 在现有 trajectory eval 上增加 tool input/output utilization 和历史失败 replay；
4. 增加 RAG groundedness/citation faithfulness；
5. 增加高风险工具、prompt/RAG/tool-output injection 安全评测。

### 第 2 阶段：全栈与生产证据补强，1-2 周

目标：从“CI/容器化已具备”推进到“核心路径可自动验证和部署”。

建议任务：

1. Playwright E2E 覆盖核心用户路径；
2. 将 E2E、镜像扫描和 release evidence 接入现有 GitHub Actions；
3. Compose smoke、staging 部署、SLO/告警/runbook/回滚演练；
4. 建立任务完成率、人工接管率、延迟、成本等产品与运行指标。

### 第 3 阶段：平台化补强，2-4 周

目标：从 AI 教育应用升级为教育 Agent 平台。

建议任务：

1. MCP Client；
2. Durable Agent Job 系统；
3. IaC、环境晋级和自动部署；
4. 按目标岗位决定是否补 Claude 原生 provider adapter；
5. Agent Red Team 与未成年人数据治理；
6. 只有在 eval 证明收益时，再抽象通用 multi-agent runtime。

---

## 9. 简历/面试表达建议

### 9.1 总体项目描述

可以这样描述项目：

> 我构建了一个面向 K-12 中文/历史教学的 AI Agent 平台 EduAgent，采用 FastAPI + Next.js + PostgreSQL/Supabase + RAG + LangGraph-style Agent 架构，实现学生学习、作业批改、错题复习、AutoTutor 自主辅导、教师分析和教学建议等闭环。项目包含工具注册与权限治理、高风险工具确认、MCP Server、结构化输出修复、Agent Trace 可视化、RAG 健康诊断、trajectory eval、release gate 和多套 smoke/eval，用于保障 Agent 在真实教育场景中的可控性、可观测性和可评测性。

### 9.2 面向 AI Agent 工程师重点讲

重点讲：

- AutoTutor planning/reflection loop；
- Tool registry + confirmation；
- MCP Server；
- RAG + grounded generation；
- Trace + Eval + release gate；
- Prompt injection / safety；
- 学生记忆与个性化学习状态。

### 9.3 面向 AI 全栈工程师重点讲

重点讲：

- Next.js 学生/教师双端；
- FastAPI 后端；
- PostgreSQL/Supabase 数据模型；
- 作业-错题-复习-辅导闭环；
- 前后端 streaming / trace / confirmation UX；
- GitHub Actions CI、前后端 Docker 和 Compose；
- build/lint/smoke/release gate。

---

## 10. 参考来源

### Agent 工程与工具调用

- Anthropic Engineering — Writing effective tools for AI agents
  https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic Engineering — Demystifying evals for AI agents
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic / Claude — Building multi-agent systems: when and how to use them
  https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them
- OpenAI — New tools for building agents
  https://openai.com/index/new-tools-for-building-agents/
- OpenAI Agents SDK — Tools
  https://openai.github.io/openai-agents-python/tools/
- OpenAI Agents SDK — Tracing
  https://openai.github.io/openai-agents-python/tracing/
- OpenAI Agents SDK — Guardrails
  https://openai.github.io/openai-agents-python/guardrails/
- OpenAI API Reference — Evals
  https://developers.openai.com/api/reference/resources/evals
- Model Context Protocol — 2025-11-25 key changes
  https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx
- Model Context Protocol — Specification overview
  https://modelcontextprotocol.io/specification/
- LangChain — State of Agent Engineering
  https://www.langchain.com/state-of-agent-engineering
- LangChain — Multi-turn Evals in LangSmith
  https://www.langchain.com/blog/insights-agent-multiturn-evals-langsmith
- LlamaIndex — Introducing llama-agents
  https://www.llamaindex.ai/blog/introducing-llama-agents-a-powerful-framework-for-building-production-multi-agent-ai-systems

### 云厂商、RAG、监控

- Microsoft Foundry — Monitor agents with the Agent Monitoring Dashboard
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard
- Microsoft Foundry — Agent Evaluators for Generative AI
  https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators
- AWS — Amazon CloudWatch adds generative AI observability
  https://aws.amazon.com/about-aws/whats-new/2025/07/amazon-cloudwatch-generative-ai-observability-preview/
- AWS — RAG on EKS with Amazon Bedrock
  https://aws.amazon.com/blogs/machine-learning/build-scalable-containerized-rag-based-generative-ai-applications-in-aws-using-amazon-eks-with-amazon-bedrock/
- Google Cloud — Introducing Vertex AI RAG Engine
  https://cloud.google.com/blog/products/ai-machine-learning/introducing-vertex-ai-rag-engine
- Google Cloud Architecture — RAG using GKE and Cloud SQL
  https://docs.cloud.google.com/architecture/rag-capable-gen-ai-app-using-gke

### 可访问岗位来源

- Amazon 上海 — Software Development Engineer（full-stack AI agents）
  https://amazon.jobs/en/jobs/10469642/software-development-engineer
- AppsFlyer — AI Engineer（multi-agent、MCP/A2A、distributed execution、CI/CD）
  https://boards.greenhouse.io/embed/job_app?for=appsflyer&token=8128287002
- Planera — Senior AI Agent Engineer（runtime、eval、observability、MCP、streaming）
  https://jobs.ashbyhq.com/planera/d68c8a09-a11d-409e-85ca-5d434caf3fc8
- Ford — AI-Accelerated Full Stack Software Development Engineer
  https://www.careers.ford.com/job/dearborn/ai-accelerated-full-stack-software-development-engineer/48560/95687677648
- Amazon Jobs — Software Development Engineer, Products and Solutions
  https://www.amazon.jobs/en/jobs/10449378/software-development-engineer-products-and-solutions
- Bank of America — Software Engineer III, AI/RAG
  https://origin-careers-pt1.bankofamerica.com/en-us/job-detail/25029882/software-engineer-iii-ai-rag-multiple-locations

---

## 11. 最终判断

当前 EduAgent 最适合的下一阶段定位是：

> AI Agent 全栈工程作品集：以教育场景为载体，展示 Agent 工作流、RAG、工具治理、MCP、Eval、Trace、全栈产品化和安全闭环。

项目已经具备 CI、容器化、trajectory eval 和场景级多 Agent，不应继续把这些能力描述为“完全缺失”。本轮已修正多 Agent 流程，补齐 Playwright 与 Vitest 基线、MCP Client 和最小 Durable Job，完成 Next.js 16 / React 19 安全升级，并刷新了完整质量报告。后续重点是解除外部模型额度阻塞并收绿质量基线，扩充 component test，再推进真实第三方 MCP、分布式 worker、生产监控与部署证据、在线质量指标和未成年人数据治理。

Claude 原生 provider 和通用 multi-agent runtime 应按目标岗位和 eval 结果选择：面向 Anthropic 专项岗位时补 Claude 原生能力；只有当上下文污染、并行探索或专业化带来可测收益时，再投入通用 multi-agent runtime。
