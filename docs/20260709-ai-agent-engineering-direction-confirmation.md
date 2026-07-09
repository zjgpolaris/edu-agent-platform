# EduAgent 后续方向确认文档

**确认日期：** 2026-07-09  
**项目定位：** 面向 AI Agent 工程师 / AI 全栈工程师求职与作品集展示的垂直教育 Agent 平台  
**核心结论：** 当前项目已经具备 AI Agent 工程作品集主体能力，下一阶段不继续横向堆教育功能，优先把质量、协议、可观测、评测和生产化证据打磨到可展示、可复盘、可面试解释的程度。

---

## 1. 背景与判断

当前 EduAgent 已经不是简单的 AI Demo，而是一个较完整的 AI 教育 Agent 产品：

- 前端：Next.js 14 App Router + TypeScript。
- 后端：FastAPI + Python 3.12。
- Agent：AutoTutor 自主辅导闭环、学习助手、历史人物对话、作文批改、辩论与游戏化学习。
- RAG：教材 / 历史知识库、pgvector / Chroma、本地与生产两套检索路径。
- Tool：统一工具注册、Pydantic schema、风险等级、角色权限、确认治理、审计日志。
- Memory：学生画像、错题本、长期学习记忆、SM-2 复习排期。
- Eval / Observability：Eval runner、Eval Dashboard、TraceTimeline、AgentOps summary、CI quick eval。
- 部署：Vercel 前端、Render 后端、Supabase Postgres、Docker、GitHub Actions。

按照当前市场对 AI Agent 工程师的要求，项目已经覆盖了核心能力的 75% - 80%。按照 AI 全栈工程师的要求，项目覆盖约 70% - 75%。

当前主要短板不是功能数量，而是：

1. 质量评测还没有稳定达到作品集级别的确定性。
2. RAG 指标和教材问答质量仍有明显波动。
3. Tool / Agent 能力虽然自研完整，但缺少 MCP 等标准协议展示。
4. AgentOps 还需要更强的成本、延迟、失败归因和发布决策视角。
5. 主线演示流程还需要收敛成一个可一口气讲清楚的闭环。

---

## 2. 后续方向总原则

### 2.1 不再优先横向扩展

暂不优先投入以下方向：

- 更多学科。
- 更多普通聊天入口。
- 更多游戏类型。
- 复杂学校 / 班级 / 组织管理。
- 商业化套餐、计费、复杂角色体系。
- 大量静态 dashboard。

这些方向更偏教育 SaaS 扩展，对 AI Agent 工程师作品集的边际收益低于可靠性、协议化、评测和生产治理。

### 2.2 优先强化工程证据

后续开发优先服务于以下目标：

- 能证明 Agent 真的在规划、调用工具、观察结果、反思和重规划。
- 能证明回答是 grounded 的，并且检索质量可评测。
- 能证明工具调用是可治理、可确认、可审计的。
- 能证明系统上线前有质量闸门，而不是靠手动演示。
- 能证明失败可以被定位、归因和回归验证。
- 能证明这是一个完整产品，而不是孤立后端脚本或聊天框。

---

## 3. 推荐主线

后续建议围绕一条主线建设：

> 教师上传材料 / 布置作业 -> 学生完成学习或作业 -> AI 批改与错因诊断 -> 写入错题与记忆 -> AutoTutor 针对薄弱点补救 -> 复习计划更新 -> 教师查看班级闭环报告。

这条主线能同时展示：

- AI 全栈产品能力。
- RAG 与材料管理。
- Agent planning / reflection / re-plan。
- Tool calling 与权限治理。
- Memory 与个性化。
- Eval / Trace / AgentOps。
- 教师端与学生端的真实业务闭环。

后续功能若不能增强这条主线，默认降级为 P2 或暂缓。

---

## 4. P0：质量与评测稳定化

### 4.1 目标

把项目从“功能能跑”推进到“质量可证明”。最新 eval 报告中仍存在失败 suite，RAG 相关指标也偏低，因此 P0 第一阶段应先稳定质量。

### 4.2 范围

重点处理：

- `history_character_eval` 失败。
- `textbook_qa_eval` 失败。
- `rag_retrieval_eval` skipped 或不稳定。
- `retrieval_hit_rate` / `source_correctness` 偏低。
- LLM 空响应、fallback、超时、格式修复等不稳定路径。

### 4.3 推荐工作

1. 梳理当前 eval case 与失败原因。
2. 将 LLM 空响应、provider fallback、结构化输出 repair 做成明确降级策略。
3. 对教材问答建立更小但稳定的 golden dataset。
4. 对 RAG retrieval 增加可重复的本地 smoke，不依赖不可控线上状态。
5. 将失败样本沉淀到 `eval/datasets/`，避免只修一次。
6. 在 `eval/reports/latest.md` 中让失败原因更短、更面试友好。

### 4.4 验收标准

- `npm run test` smoke 通过。
- `eval/reports/latest.md` Overall 为 PASS。
- `history_character_eval` 通过。
- `textbook_qa_eval` 通过。
- `rag_retrieval_eval` 不再无理由 skipped。
- `retrieval_hit_rate >= 0.8`。
- `source_correctness >= 0.8`。
- `tool_schema_validity = 1.0`。
- `guardrail_pass_rate = 1.0`。

---

## 5. P0：作品集级 AgentOps 面板

### 5.1 目标

把 Agent 的运行质量变成可展示的工程指标，而不只是开发者日志。

### 5.2 范围

在现有 `/eval` 或独立 AgentOps 区域展示：

- task success rate。
- tool success rate。
- retrieval hit rate。
- source correctness。
- p50 / p95 latency。
- average cost per request / per session。
- LLM fallback 次数。
- tool failure top N。
- failed suites / failed cases。
- trace coverage。
- 最近 Agent session 列表。

### 5.3 推荐工作

1. 扩展 `backend/agent_ops.py`，加入 latency、失败归因、工具成功率、模型调用摘要。
2. 将 cost estimator 接入 AgentOps 汇总。
3. Eval Dashboard 增加“发布是否可放行”的 readiness summary。
4. 让每个失败指标能点击到 trace 或 failed case。

### 5.4 验收标准

- `/eval` 页面能展示 AgentOps summary。
- 能看到最近 20 条 Agent session。
- 每条 session 能看到 trace_id、agent_name、status、latency、tool_count、error_summary。
- 能区分 RAG 失败、LLM 失败、tool 失败、guardrail 拦截。
- 能用一屏解释“当前系统是否达到可发布状态”。

---

## 6. P0：主线演示流程收敛

### 6.1 目标

把项目从“功能很多”收敛成“一个强主线 + 多个支撑能力”，用于面试、作品集 README、Demo 视频和技术讲解。

### 6.2 推荐演示脚本

1. 使用 demo student 登录。
2. 打开学生首页，看到今日计划和薄弱点。
3. 从某个薄弱点进入 AutoTutor。
4. AutoTutor 自动读取画像、错题本、根因诊断，生成教学计划。
5. 学生答错一道题。
6. Agent 触发 reflect / re_plan，降低难度或换例子。
7. 学生答对后，系统更新错题本、记忆和复习计划。
8. 打开 TraceTimeline，展示每个 node、tool、latency、metadata。
9. 打开 Eval / AgentOps，展示该能力被自动评测和监控。
10. 打开教师端，看班级薄弱点或闭环报告。

### 6.3 验收标准

- README 中有明确的 5 分钟 Demo 路线。
- Demo 不依赖临时手工数据库状态。
- `scripts/seed_demo_student.py` 能稳定生成演示数据。
- 每个演示步骤都有对应页面和可见结果。
- 失败时有降级文案，不出现空白页面或无法解释的报错。

---

## 7. P1：MCP / 标准工具协议适配

### 7.1 目标

在已有自研 Tool Registry 之上补充标准协议展示，增强市场关键词和工程兼容性。

### 7.2 推荐范围

第一版只做轻量 MCP Server，不重构现有工具层。

暴露工具：

- `search_history_knowledge`
- `get_textbook_lesson`
- `suggest_review_plan`
- `generate_quiz`

### 7.3 设计原则

- MCP 层只做适配，不复制业务逻辑。
- 继续复用 `backend/tools/registry.py` 的 `run_tool()`。
- MCP tool schema 从现有 Pydantic schema 派生。
- 权限、确认、审计仍由 Tool Registry 统一处理。

### 7.4 验收标准

- 本地能启动 MCP server。
- MCP client 能 list tools。
- MCP client 能调用至少 2 个 read-only tools。
- high-risk tool 不绕过现有 confirmation 机制。
- README / docs 中有 MCP 使用说明。

---

## 8. P1：RAG Inspector 与数据质量治理

### 8.1 目标

让 RAG 不只是“能检索”，而是“能解释、能调试、能评测、能持续改进”。

### 8.2 推荐范围

优先覆盖：

- 历史人物对话。
- 教材问答。
- 学习助手 history_search / textbook_qa。

展示字段：

- 原始 query。
- rewritten query / multi-query。
- top-k chunks。
- vector score。
- keyword score。
- rerank score。
- final score。
- source metadata。
- 是否进入最终回答上下文。
- citation 映射。

### 8.3 验收标准

- 前端能看到一次回答使用了哪些 chunk。
- 每个 chunk 有来源、分数和命中模式。
- Eval case 能关联到检索结果。
- RAG 失败时能判断是召回失败、排序失败还是生成阶段没有引用。

---

## 9. P1：生产化可靠性与成本治理

### 9.1 目标

补齐 AI 全栈工程师对线上系统的要求：稳定、可控、可预算、可恢复。

### 9.2 推荐范围

- 每次请求记录模型调用次数。
- 每次 Agent session 记录 token / cost 估算。
- 增加 p95 latency 统计。
- 增加 LLM timeout 与 fallback 统计。
- 对长任务引入后台任务或可恢复 session。
- 生产 readiness 区分 shallow / deep / external dependency。

### 9.3 验收标准

- AgentOps 中能看到成本和延迟。
- release gate 能输出 readiness summary。
- 外部 LLM 或 embedding 不可用时，系统返回可解释降级，不是静默失败。
- 生产 RAG health smoke 有明确 pass/fail 原因。

---

## 10. P2：多模态与端侧体验增强

### 10.1 目标

在 P0 / P1 稳定后，再增强多模态和移动端体验。

### 10.2 可选方向

- 作业图片 OCR 质量提升。
- PDF / 图片材料结构化解析。
- 移动端拍照批改体验优化。
- 教师材料上传后的自动知识点抽取。
- 多模态输入在 Agent Trace 中展示来源与处理步骤。

### 10.3 暂缓原因

这些能力对作品集有帮助，但如果质量评测和主线演示还不稳定，继续扩展多模态会放大维护成本。

---

## 11. 推荐实施顺序

### Iteration 1：Eval / RAG 稳定化

**优先级：** P0  
**目标：** 让质量报告变成 PASS。  
**核心文件：**

- `eval/run_core_evals.py`
- `eval/reports/latest.md`
- `eval/datasets/`
- `backend/agents/history_character.py`
- `backend/textbook_learning/service.py`
- `backend/rag/knowledge_base.py`
- `backend/structured_output.py`
- `backend/llm_config.py`

### Iteration 2：AgentOps 作品集化

**优先级：** P0  
**目标：** 让运行质量、失败归因、成本和延迟可展示。  
**核心文件：**

- `backend/agent_ops.py`
- `backend/trace_store.py`
- `backend/tracing.py`
- `backend/utils/cost_estimator.py`
- `frontend/app/eval/page.tsx`
- `frontend/components/TraceTimeline.tsx`

### Iteration 3：主线 Demo 收敛

**优先级：** P0  
**目标：** 形成一个可复现、可讲解、可录屏的端到端闭环。  
**核心文件：**

- `README.md`
- `scripts/seed_demo_student.py`
- `backend/agents/auto_tutor.py`
- `frontend/app/(student)/student/auto-tutor/page.tsx`
- `frontend/app/(teacher)/teacher/quality-dashboard/page.tsx`

### Iteration 4：MCP Server 适配

**优先级：** P1  
**目标：** 补齐标准 Agent 工具协议展示。  
**核心文件：**

- `backend/tools/registry.py`
- `backend/tools/base.py`
- `backend/tools/*`
- 新增 `backend/mcp_server.py` 或 `mcp/` 目录。
- `README.md`

### Iteration 5：RAG Inspector

**优先级：** P1  
**目标：** 把 RAG 调试和引用质量显性化。  
**核心文件：**

- `backend/rag/knowledge_base.py`
- `backend/rag/rerank.py`
- `backend/agents/history_character.py`
- `backend/agents/learning_assistant.py`
- `frontend/components/TraceTimeline.tsx`
- 相关问答页面。

---

## 12. 最终验收口径

当以下条件满足时，可以认为 EduAgent 达到“AI Agent 工程师作品集强展示版”：

- 核心 eval Overall PASS。
- RAG 指标稳定达到 0.8+。
- AutoTutor 主线 Demo 可稳定复现。
- Agent Trace 能展示 plan / tool / observe / judge / reflect / re_plan。
- Tool Governance 有 schema、role、risk、confirmation、audit 的完整证据。
- AgentOps 能展示 success、latency、cost、failure reason、trace coverage。
- 至少一个 MCP server 或标准工具协议适配可以运行。
- README 能在 5 分钟内讲清楚项目价值、架构、演示路线和工程亮点。

---

## 13. 一句话方向确认

下一阶段的 EduAgent 不再以“新增更多教育功能”为目标，而是以“把现有教育 Agent 闭环打磨成可靠、可观测、可评测、可治理、可协议化的 AI Agent 工程作品集”为目标。
