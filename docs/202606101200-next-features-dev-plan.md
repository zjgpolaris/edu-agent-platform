# EduAgent 下一阶段功能开发规划

> 版本：2026-06-10 | 基于当前项目状态分析

---

## 1. 当前项目能力总览

| 模块 | 后端 | 前端 | 评测 |
|------|------|------|------|
| 历史人物对话 | 完成（RAG+反射+SSE） | 完成 | smoke + eval |
| 历史游戏大厅 | 完成（时间轴/卡牌/多人） | 完成 | smoke |
| 作文批改 | 完成（LangGraph 5维评分） | 完成 | — |
| 统一学习助手 | 完成（意图路由+工具调用） | 完成 | smoke |
| 教材同步学习 | 完成（问答+总结+出题） | 完成 | eval |
| 历史时空地图 | 完成（地图 Agent） | 完成 | — |
| 学生画像 | 完成（API + 事件记录） | **无前端页面** | smoke |
| 辩论 Agent | 原型（3轮 pro/con/judge） | **无前端页面** | — |
| RAG 评测 | 完成（Ragas + 自定义） | **无可视化** | eval |

---

## 2. 可推进的功能方向

### 2.1 学情分析 Dashboard（高优先级）

**背景**：`student_profile.py` + API 已完整实现，`/api/students/{id}/profile` 和 `/api/students/{id}/review-plan` 已可用，但没有前端页面消费这些数据。

**目标**：让学生（或教师）能看到学习轨迹、薄弱知识点和���习建议。

**需要新建**：`frontend/app/student-dashboard/page.tsx`

**展示内容**：
- 近期学习事件时间线（对话/练习/游戏记录）
- 各知识点掌握度（按 `event_type` 聚合）
- AI 生成的复习建议（调用 `/api/students/{id}/review-plan`）

**涉及文件**：
- `frontend/app/student-dashboard/page.tsx`（新建）
- `frontend/app/page.tsx`（首页加入口卡片）
- 后端无需改动

---

### 2.2 辩论对话页面（中优先级）

**背景**：`debate_supervisor.py` 已实现 Supervisor-Worker 多 Agent 模式（正方/反方/裁判，3轮），`/api/history/debate/start` 已注册，但没有前端页面。

**目标**：让学生输入辩题，观看 AI 双方自动辩论，最终裁判给出结论，适合历史观点类学习。

**现有问题**：
- `debate_supervisor.py` 当前是非流式的，等待全部完成后返回
- 没有 Human-in-the-loop 节点（学生无法参与辩论）

**Phase 1**（只做前端）：
- `frontend/app/history-debate/page.tsx`（新建）
- 输入辩题 → 调用 API → 展示正反双方逐轮论点 + 裁判结论

**Phase 2**（加 Human-in-the-loop）：
- 后端 `debate_supervisor.py` 加 `student_argument` 节点
- 学生可以扮演正方或反方，和 AI 对手辩论

**涉及文件**：
- `frontend/app/history-debate/page.tsx`（新建）
- `backend/agents/debate_supervisor.py`（Phase 2 改造）
- `backend/api/main.py`（Phase 2 加 SSE 路由）

---

### 2.3 智能出题练习页面（高优先级）

**背景**：`quiz_tools.py` + `textbook_learning/service.py` 已实现教材维度的出题，`/api/textbook-learning/quiz` 已可用，但只能在教材学习上下文中触发，没有独立入口。

**目标**：独立的出题练习页，学生选择章节/年级，AI 出题，即时判卷，结果写入学生画像。

**需要新建**：`frontend/app/quiz-practice/page.tsx`

**功能流程**：
1. 选择 `book_id` + `lesson_id` + 题型 + 数量
2. 调用 `/api/textbook-learning/quiz`
3. 前端展示题目，学生作答
4. 提交答案后本地判卷（选择题）或调用 LLM 判卷（简答题）
5. 结果通过 `/api/students/{id}/events` 写入学生画像

**后端需要补充**：
- 简答题判卷 API（当前 quiz API 只生成题，不判卷）
- `POST /api/students/{id}/events` 写入学习事件（当前只在 Agent 内部调用）

**涉及文件**：
- `frontend/app/quiz-practice/page.tsx`（新建）
- `backend/api/main.py`（加 `/api/students/{id}/events` 公开路由）
- `backend/agents/quiz_grader.py`（新建，简答题判卷）

---

### 2.4 Eval 可视化界面（中优先级）

**背景**：`eval/` 下已有完整评测脚本和数据集，`run_core_evals.py` 可以跑全套指标，但结果只输出到控制台/JSON 文件，没有可视化。

**目标**：在前端展示历次 eval 运行结果，直观看到 RAG 命中率、幻觉率、task success rate 的趋势。

**方案选择**：
- 轻量方案：Langfuse 内置 dataset eval UI（已接入 Langfuse，零开发成本）
- 自建方案：`frontend/app/eval/page.tsx` 读取 `eval/results/*.json` 展示

**推荐**：先用 Langfuse 方案，后续有定制需求再自建。

---

## 3. 优先级排序

| 功能 | 优先级 | 开发量 | 需要新建后端 |
|------|--------|--------|-------------|
| 学情分析 Dashboard | 高 | 小（前端为主） | 否 |
| 智能出题练习页面 | 高 | 中（前后端） | 是（判卷+事件写入） |
| 辩论对话页面 Phase 1 | 中 | 小（前端为主） | 否 |
| 辩论 Human-in-the-loop | 低 | 大（后端改造） | 是 |
| Eval 可视化 | 中 | 小（Langfuse 方案） | 否 |

---

## 4. 建议开发顺序

```
1. 学情分析 Dashboard（前端页面 + 调用现有 API）
   └─ 验收：能看到近期学习记录和复习建议

2. 智能出题练习页面
   ├─ 后端：公开 /api/students/{id}/events 路由
   ├─ 后端：quiz_grader.py 简答题判卷
   └─ 前端：quiz-practice 页面完整流程

3. 辩论对话页面（Phase 1，纯前端）
   └─ 验收：能输入辩题观看 AI 自动辩论

4. 辩论 Human-in-the-loop（Phase 2，按需）
```

---

## 5. 技术约束与注意事项

- 前端新页面需要在 `frontend/app/page.tsx` 的 `modules` 数组加入口卡片
- 学生画像数据当前存在内存/文件中（`student_profile.py`），多实例部署需迁移到 Redis 或数据库
- 出题练习的学生答案不能传给 RAG 内容，防止 prompt injection（参考 `security/prompt_injection.py` 的 `build_untrusted_context_block`）
- 辩论 Agent 当前无 SSE，前端等待时间可能较长，Phase 1 上线前需加 loading 状态
