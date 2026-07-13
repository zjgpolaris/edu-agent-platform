# AutoTutor 自主辅导 Agent 闭环 — 迭代计划

**创建日期：** 2026-06-29
**定位目标：** 求职作品集 / 面试演示（压技术深度 + 一个能讲清楚的 agent 故事）
**前序分析：** [`202606231148-next-product-direction-analysis.md`](202606231148-next-product-direction-analysis.md)

---

## 一、背景与决策

### 1.1 当前状态判断

6-23 方向文档列的 P0/P1 已基本全部落地，原 roadmap 已用完：

| 原规划 | 现状 |
|--------|------|
| Agent Runtime 可视化 | ✅ `trace_store` + `TraceTimeline` |
| Tool 权限/确认治理 | ✅ `confirmation.py` + `ToolConfirmationDialog` |
| Eval Dashboard | ✅ `/eval` 页 + eval API |
| RAG 可解释面板 | ✅ `rag_inspector`（history-character、learning-assistant） |
| Agent Memory 管理页 | ✅ `/memory` + memory-audit |
| 学习路径/自适应复习 | ✅ SM-2 复习引擎 |
| 移动端适配 | ✅ MobileBottomNav 全页 |
| CI/CD | ✅ lint/build + smoke + quick-eval(PR 评论) + docker build |
| Postgres 化 | ✅ Supabase 迁移完成 |

**结论：** "从功能完整 → 可评测可观测可治理"的原定目标已达成。这是一个转折点——不能再照旧 roadmap 抄。

### 1.2 核心问题

- **广度过剩、深度不足。** 20+ 页面、十几个功能，但缺一个能让人记住的"杀手级 agent 闭环"。
- **agent 大多是固定流水线，不是真正 agentic。** 例如 `history_character` 是 检索→生成→质检 三步定死；`learning_assistant` 是单轮工具调用。2026 年人人都有 RAG+工具，真正差异化是 **plan → act → observe → reflect → adapt** 的多步自纠循环。
- **最近迭代在贬值。** 版本 1.7→1.10.2 全部花在时间巨轮桌游视觉打磨上，恰是原文档自列的"不建议优先"项。

### 1.3 决策

- **服务目标：** 求职作品集 / 面试 → 压"技术深度 + 一个能讲清楚的 agent 故事"。
- **Track A（旗舰自主闭环）+ 上线一个能点的 demo**，两者一个迭代内并行完成。
- **明确砍掉：** 游戏 UI 继续打磨、新学科页面、新游戏类型、新聊天入口、班级/组织管理、商业化权限。

---

## 二、AutoTutor 是什么

一句话定义：**给定一个学生，agent 自己决定教什么、怎么教、答错了怎么补，全程可观测、可评测、可干预。**

### 2.1 四个"非流水线"特征（核心差异点）

1. **Plan** —— 读学生画像 + 错题本，自主产出本节课计划（教哪几个知识点、用什么工具、顺序），而非写死的三步。
2. **Act + Observe** —— 按计划调已有工具（RAG 取材、出题、判分），每步结果回灌状态。
3. **Reflect / Re-plan** —— 学生答错 → agent 反思"是我讲得不对，还是题超纲" → 动态改计划（补讲 / 降难度 / 换例子）。**这是和普通 tool-calling 拉开差距的核心。**
4. **Adapt** —— 课后自动写 `memory_entry` + 排 SM-2 复习。此步已有基建，直接接。

### 2.2 为什么这一个功能就够撑场面

它把已建好的所有零件串成一条线，面试一次演示全亮：

| 闭环环节 | 复用的现有基建 |
|----------|----------------|
| 规划 / 反思 / 重规划过程 | **TraceTimeline**（plan step、reflect step、re-plan 都是可见 step） |
| 工具调用 + 高危确认 | **tool governance / confirmation** |
| 取材引用 | **rag_inspector** |
| 课后记忆 | **/memory 页** |
| 质量回归 | **eval dashboard** |

不是加第 21 个功能，是给前 20 个基建找一个**总入口**。

---

## 三、技术设计

### 3.1 后端：自主循环

新增 `backend/agents/auto_tutor.py`，以 LangGraph 风格状态图实现：

```
plan ──> act ──> observe ──> [judge] ──┬── pass ──> next_step ──> ... ──> finalize
                                       └── fail ──> reflect ──> re_plan ──> act
```

**状态对象（AutoTutorState）关键字段：**

| 字段 | 说明 |
|------|------|
| `student_id` / `grade` | 目标学生 |
| `lesson_plan` | 当前课程计划（知识点列表 + 每点的策略/工具/难度） |
| `current_step_index` | 当前执行到第几步 |
| `step_history` | 每步的 act/observe/judge 结果（含 re-plan 记录） |
| `reflect_log` | 反思记录（触发原因、诊断、调整动作） |
| `replans` | 重规划次数（用于防死循环 + eval 指标） |
| `mastery_delta` | 本节课对各知识点掌握度的预估变化 |

**复用的工具（不新增工具，只编排）：**
- RAG 取材：`tools/history_search.py` / 材料检索
- 出题：`tools/quiz_tools.py` / `timeline_question_generator.py`
- 学生画像与错题本：`tools/profile_tools.py` / `services/weakpoint_service.py`
- 课后记忆与复习：`user_memory.py` + 自适应复习引擎

**防护：**
- `replans` 上限（如 ≤3）防死循环。
- 单节课 step 上限（如 ≤6）。
- LLM 调用用现有 `llm_config.py`，规划/反思用 quality 模型，判分可用 fast 模型。

### 3.2 可观测：接入现有 trace

- 每个 node（plan / act / observe / reflect / re_plan / finalize）emit 一个 trace step，复用现有 trace event schema（trace_id、step_name、status、latency、metadata）。
- reflect step 的 metadata 带上"诊断结论 + 调整动作"，让 timeline 能讲出反思故事。

### 3.3 API

新增端点（写进 `backend/api/main.py`，同步 SCHEMA.md）：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/autotutor/start` | 给定 student_id，启动一节课，返回 session_id + 首个计划 |
| POST | `/api/autotutor/answer` | 提交学生对当前题的作答，驱动 observe→judge→(reflect/next) |
| GET | `/api/autotutor/session/{session_id}` | 拉取当前会话状态（计划、已完成步、trace_id） |

（流式可选：复用现有 SSE 框架，emit plan/act/reflect/final 事件。）

### 3.4 前端

- 新增学生端入口页 `frontend/app/auto-tutor/page.tsx`（或归入 `(student)` 组）。
- 左侧：课程计划进度 + 当前题目/讲解；右侧或下方：**接入 TraceTimeline**，把规划/反思过程实时呈现。
- 答错后展示"agent 正在反思并调整计划"的可见反馈。

---

## 四、配套两件必做事

### 4.1 Trajectory eval（面试高频考点）

- 复用 `eval/trajectory_eval.py`，新增 AutoTutor 轨迹用例。
- LLM-as-judge 评测维度：
  - **规划合理性**：计划是否对准学生薄弱点。
  - **反思触发正确性**：该反思时是否反思了、不该反思时是否没乱改。
  - **闭环命中**：最终是否覆盖了目标薄弱点 + 是否正确写了 memory/复习。
- 接进 CI 的 `quick-eval`，回答"agent 改了之后怎么证明没变笨"。

### 4.2 上线可点 demo

- 前端挂 Vercel，后端挂一个 host（Docker 已就绪）。
- 灌一份 demo 学生种子数据（**预置错题本**，让 AutoTutor 一进去就有东西可规划）。
- 写一段 30 秒演示脚本（见第六节）。
- 简历上一个活链接 > 三个新功能。

---

## 五、排期与验收

| 阶段 | 内容 | 验收标准 |
|------|------|----------|
| W1 | 后端 plan→act→observe→reflect→re-plan 循环，复用现有 tools | 学生答错能触发**一次真实 re-plan**；trace 里能看到 reflect step + 诊断结论 |
| W1.5 | 前端入口 + 规划/反思过程接入 TraceTimeline | 一次演示能看到从 plan 到 finalize 的完整 step 流 |
| W2 | trajectory_eval 用例 + 接 CI quick-eval | CI 能跑出轨迹通过率，失败 case 可见 |
| W2.5 | 部署上线 + demo 种子数据 + 演示脚本 | 线上 URL 可点，进去就有可规划的学生 |

**总体约 2-3 周。**

### 验收红线（缺一不可）
1. agent 的计划是**生成的**而非写死的（换个学生，计划不同）。
2. 至少存在一条路径：答错 → 反思 → 计划真实改变 → 后续 step 体现调整。
3. 整个过程在 TraceTimeline 完整可见。
4. 课后自动落 memory + 排复习（接已有基建）。
5. trajectory eval 跑通并进 CI。

---

## 六、面试演示脚本（30 秒）

1. 打开 AutoTutor，选一个预置薄弱点的 demo 学生。
2. agent 现场规划本节课（指出它读了画像/错题本）。
3. 故意答错一题 → 展示 agent 反思 + 重规划（TraceTimeline 上的 reflect step）。
4. 点开某 tool call，看 input schema / risk level / RAG 来源引用。
5. 课程结束，打开 /memory 看本节课写入的记忆 + 复习计划。
6. 打开 /eval，看这个 agent 的 trajectory 通过率。

> 一句话总结："这是一个会自己规划、答错会反思重规划、全程可观测可评测、课后会写记忆排复习的自主辅导 agent。"

---

## 七、明确不做

- ⛔ 时间巨轮 / 任何游戏 UI 继续打磨
- ⛔ 新学科页面、新游戏类型、新聊天入口
- ⛔ 班级 / 组织管理、商业化权限套餐
- ⛔ 再写零散的静态 dashboard

---

## 八、相关文档

- [`202606231148-next-product-direction-analysis.md`](202606231148-next-product-direction-analysis.md) — 上一轮方向分析
- [`202606221438-iteration-plan-dev.md`](202606221438-iteration-plan-dev.md) — 历史迭代计划
- `SCHEMA.md` — 完成后需同步：目录结构、API 接口、核心功能、测试列表

---

## 九、实施进展（2026-06-29）

W1 + W1.5 + W2 已落地，W2.5 留种子脚本待部署：

| 模块 | 落地物 | 状态 |
|------|--------|------|
| 后端自主循环 | `backend/agents/auto_tutor.py`：plan→act→observe→judge→reflect→re_plan→finalize，内存会话存储(TTL 1h)，护栏 `MAX_STEPS=4 / MAX_REPLANS=3 / MAX_ATTEMPTS_PER_STEP=3` | ✅ |
| 计划生成 | quality 模型读画像+错题本生成计划；无 LLM 时按错题权重确定性兜底（换学生计划不同）；LLM 扩写的知识点经 `_match_source_tag` 映射回错题本原标签 | ✅ |
| 取材 / 出题 | 经 `tools.registry.run_tool("search_history_knowledge")` 走治理+审计+RAG；据难度出四选一题 | ✅ |
| 反思 / 重规划 | 答错→quality 模型诊断(reteach/lower_difficulty/change_example)→当前步与后续步真实降难度+重新出题 | ✅ |
| 课后自适应 | 写 `review_goal` memory；按掌握度记 learning event；已掌握移出错题本、仍薄弱进错题本（接 SM-2 今日复习） | ✅ |
| 退出票证据闭环 | v1.26 新增 `phase=exit_ticket`：最后教学步骤后先完成退出票检验，写 `auto_tutor_exit_ticket` learning event，并回流掌握证据/错题本/教师端辅导效果看板 | ✅ |
| 可观测 | 每个 node `emit_trace_event` 写 trace_store，可经 `/api/traces/{trace_id}` 查询 | ✅ |
| API | `POST /api/autotutor/start`、`POST /api/autotutor/answer`、`GET /api/autotutor/session/{id}`（auth + 限流 + 审计 + trace_context） | ✅ |
| 前端 | `frontend/app/(student)/student/auto-tutor/page.tsx`：计划进度 + 当前题/反思 + runtime steps/TraceTimeline；AppSidebar/MobileBottomNav 新增「自主辅导」入口 | ✅ |
| Eval | `eval/auto_tutor_trajectory_eval.py`（规划合理性 / 反思触发正确性正反例 / 闭环命中），离线可跑，已接入 `run_core_evals.py` 的 CORE + QUICK（4/4 通过） | ✅ |
| Demo 种子 | `scripts/seed_demo_student.py`（demo-student/demo123 + 预置错题本） | ✅ |
| 部署上线 | Vercel(前端) + Render(后端 Docker) + Supabase：`render.yaml`、`frontend/vercel.json`、`.dockerignore`×2、前端 standalone 构建、CORS 经 `FRONTEND_ORIGIN`/`*.vercel.app` 放行、部署文档 [`202606291600-autotutor-deploy-dev.md`](202606291600-autotutor-deploy-dev.md) | ✅ 配置就绪，待按文档执行平台部署 |

**验收红线对照：** ① 计划生成且换学生不同 ✅ ② 答错→反思→计划真实改变→后续 step 体现 ✅ ③ 全程 trace 可见 ✅ ④ 课后落 memory + 排复习 ✅ ⑤ trajectory eval 跑通并进 CI ✅ ⑥ v1.26 退出票 evidence closure 接入，辅导结束前必须有出口检验 ✅。

## 十、v1.26 退出票与学习证据闭环（2026-07-13）

本轮把 AutoTutor 从“教学步骤完成即 finalize”升级为“退出票检验后 finalize”：

```text
plan → act → observe → judge → reflect/re_plan → exit_ticket → evidence → finalize
```

关键变化：

- `AutoTutorState` 新增 `phase`、`exit_ticket`、`exit_ticket_result`、`evidence`。
- 保持 `status=awaiting_answer/completed` 不变，前端通过 `phase=exit_ticket` 区分退出票阶段。
- `POST /api/autotutor/answer` 继续作为唯一作答入口：教学题作答推进 lesson，退出票作答触发 finalize。
- `learning_events` 新增 `auto_tutor_exit_ticket` 语义，辅导效果服务统计退出票数和通过率。
- 学生端 AutoTutor 完成态展示学习证据卡；教师班级学情页展示退出票证据聚合。
- 详情记录见 [`202607131430-autotutor-exit-ticket-evidence-dev.md`](202607131430-autotutor-exit-ticket-evidence-dev.md)。

