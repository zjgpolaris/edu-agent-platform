# EduAgent 下一步产品方向分析

**分析日期：** 2026-06-23
**分析依据：** 当前已完成功能、能力完成度分析、作品集路线图

---

## 一、当前项目状态总结

### 1.1 已完成里程碑

| 里程碑 | 状态 | 完成日期 |
|--------|------|----------|
| Milestone 1：多模态资料库稳定化 | ✅ 已完成 | 2026-06-23 |
| Milestone 2：拍照批改闭环 | ✅ 已完成 | 2026-06-23 |
| Milestone 3：错题本 + 知识点追踪 | ✅ 已完成 | 2026-06-23 |
| 教师端功能增强 | ✅ 已完成 | 2026-06-23 |

### 1.2 当前能力完成度

| 评估视角 | 完成度 | 判断 |
|----------|--------|------|
| AI Agent 工程作品集展示 | 75% - 85% | 已能展示 LangGraph、RAG、流式交互、多模态、评测和 tracing 等核心能力 |
| 生产级线上 Agent 平台 | 55% - 65% | 基础架构具备，但 eval、AgentOps、权限治理、CI/CD 和生产监控仍需加强 |
| 教育垂直场景完整度 | 80% - 90% | 历史角色、材料学习、作文批改、辩论和游戏化学习场景较完整 |

### 1.3 核心结论

> EduAgent 已经具备"AI Agent 工程作品集"的主体能力；下一阶段应少堆新功能，优先补齐 eval、AgentOps、schema-first tool calling、guardrails 和 CI/CD，把项目从"功能完整"升级为"工程成熟"。

---

## 二、下一步产品方向建议

### 方向一：工程成熟度提升（推荐优先）

**目标：** 将项目从"功能完整的教育 AI 应用"升级为"可评测、可观测、可治理的教育 Agent 工程作品集"。

#### P0：Agent Runtime 可视化

**价值：** 让 Agent 执行过程可见，展示 Agent 不是黑盒聊天。

**内容：**
- 统一 trace event schema（trace_id、agent_name、step_name、status、latency）
- 学习助手页面增加 step timeline
- 工具调用展示 tool metadata（name、risk_level、input、result）
- 失败 step 可视化

**验收标准：**
- 至少学习助手页面能展示完整 step timeline
- 每个 step 有 status、latency、metadata
- 工具调用 step 能展示 tool_name、risk_level
- 失败时能显示 error_code 和失败 step

#### P0：Tool Permission / Confirmation Demo

**价值：** 展示工具治理、安全边界、human confirmation。

**内容：**
- 强制 role / confirmation 检查
- 新增 high-risk demo tool（如 delete_student_memory）
- 前端确认卡片
- audit log 记录决策
- tool permission eval cases

**验收标准：**
- `run_tool()` 强制检查 role
- `requires_confirmation=true` 时不直接执行工具
- 前端能展示确认弹窗
- audit log 记录 allow / deny / confirmation_required

#### P0：Eval Dashboard 增强

**价值：** 展示 Evaluation Engineering 和 regression 能力。

**内容：**
- Core suites 总览
- 每个 suite 的 pass / fail / skipped
- 关键指标：task_success_rate、retrieval_hit_rate、source_correctness、tool_schema_validity
- 一键运行 quick eval
- 下载 `latest.json` 和 `latest.md`

**验收标准：**
- eval 页面能展示最新报告
- 后端 API 能触发 quick eval 或读取报告
- 至少展示 tools / rag / safety 三类指标
- 失败 suite 有明确 failed cases

---

### 方向二：产品体验深化

#### P1：RAG 可解释检索面板

**价值：** 展示 retrieval debugging、grounding、citation。

**内容：**
- 原始 query、query rewrite 结果
- top-k retrieved chunks（vector score、rerank score）
- chunk title / source / page / section
- 哪些 chunk 被用于最终回答
- 答案中的 citation 对应来源

**验收标准：**
- 至少材料问答或历史角色问答支持 inspector
- 每个 source 有 score 和 metadata
- 最终答案能展示来源引用
- eval 中有 retrieval hit rate 指标

#### P1：Agent Memory 管理页面

**价值：** 展示长期记忆策略、用户控制、隐私意识。

**内容：**
- Student Profile（strong topics、weak topics、recent activities）
- Memory Entries（content、type、source、created_at、last_used_at）
- Used in Current Answer（memory id、reason）
- actions: delete / disable

**验收标准：**
- 用户能查看学生画像和学习事件
- 用户能删除或禁用一条 memory
- Agent 回答能显示使用了哪些 memory
- audit log 记录 memory 删除行为

#### P1：学习路径优化

**价值：** 基于错题本的智能推荐，形成个性化学习闭环。

**内容：**
- 基于错题本的智能推荐
- 个性化学习计划生成
- 学习进度可视化
- 答对题目后自动移除错题

**验收标准：**
- 学生能看到个性化学习路径
- 推荐内容与错题本联动
- 学习进度可追踪

---

### 方向三：游戏化学习增强

#### P1：历史游戏与错题本联动

**价值：** 增强游戏化学习效果，形成学习闭环。

**内容：**
- 历史游戏与错题本联动
- 答对题目后自动移除错题
- 游戏成就系统

**验收标准：**
- 游戏题目基于错题本生成
- 答对后错题本自动更新
- 成就系统可展示

---

### 方向四：移动端适配

#### P2：响应式布局优化

**价值：** 扩大用户覆盖面，支持移动端学习。

**内容：**
- 响应式布局优化
- 移动端专用组件
- 拍照批改移动端优化

**验收标准：**
- 核心页面在移动端可用
- 拍照批改在移动端体验良好

---

## 三、不建议优先投入的方向

当前阶段不建议继续优先做：

- 更多学科页面
- 更多游戏类型
- 更多普通聊天入口
- 更复杂的学校 / 班级 / 组织管理
- 复杂商业化权限套餐
- 大量静态 dashboard

**原因：** 这些更偏教育 SaaS 产品扩展，对 AI Agent 工程师作品集的边际加分不如 runtime、eval、tool governance、RAG inspector 和 AgentOps。

---

## 四、推荐实施顺序

### Iteration 1：Agent Runtime 可视化（1-2 周）

- 统一 trace event schema
- 学习助手页面增加 step timeline
- 工具调用展示 tool metadata
- 失败 step 可视化

### Iteration 2：Tool Governance（1-2 周）

- 强制 role / confirmation 检查
- 新增 high-risk demo tool
- 前端确认卡片
- audit log 记录决策
- tool permission eval cases

### Iteration 3：Eval & AgentOps 展示（1-2 周）

- 稳定生成 eval reports
- eval dashboard 展示指标
- AgentOps summary 增强 latency / tool failure / trace coverage
- 失败 case 展示与回流入口

### Iteration 4：产品体验深化（2-3 周）

- RAG 可解释检索面板
- Agent Memory 管理页面
- 学习路径优化

---

## 五、作品集展示话术

完成上述 feature 后，可以这样介绍 EduAgent：

> EduAgent 是一个面向 K-12 历史与语文学习的垂直教育 Agent 平台。它不仅支持角色对话、材料学习、作文批改和游戏化学习，还重点实现了生产级 Agent 工程能力：LangGraph 工作流、RAG grounding、schema-first tool calling、工具权限治理、human confirmation、Agent trace 可视化、Eval dashboard、AgentOps summary 和学生长期记忆管理。

面试展示时建议按以下顺序演示：

1. 打开学习助手，提出一个需要工具调用的问题
2. 展示 Agent step timeline
3. 点开某个 tool call，看 input schema、risk level、result 和 latency
4. 触发一个 high-risk tool，展示 confirmation
5. 打开 RAG inspector，看 retrieved chunks 和 citations
6. 打开 eval dashboard，看 pass rate 和 failed cases
7. 打开 AgentOps summary，看 trace coverage、audit events 和 tool failures
8. 打开 memory 页面，看学生画像和本次回答使用的记忆

---

## 六、相关文档

- [`202606221438-iteration-plan-dev.md`](202606221438-iteration-plan-dev.md) — 迭代计划
- [`202606151423-eduagent-ai-agent-capability-completion-analysis.md`](202606151423-eduagent-ai-agent-capability-completion-analysis.md) — 能力完成度分析
- [`202606161343-ai-agent-portfolio-feature-roadmap-dev.md`](202606161343-ai-agent-portfolio-feature-roadmap-dev.md) — 作品集路线图
