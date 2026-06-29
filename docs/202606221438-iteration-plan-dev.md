# EduAgent 迭代开发计划

**文档创建时间：** 2026-06-22  
**状态：** 规划中  
**优先级排序依据：** 用户可感知价值 × 实现复杂度

---

## 背景

当前平台已具备以下核心能力：
- 历史人物对话（RAG + SSE 流式）
- 历史游戏（时间线、卡牌、多人）
- 作文/作业批改（单篇）
- 教科书学习（章节浏览 + AI 问答）
- 材料上传与多模态解析（Level 1 已验证）
- 学生档案 + 弱点记录接口

本文档聚焦**下一阶段**的迭代方向，按优先级分为三个里程碑。

---

## Milestone 1：多模态资料库稳定化（2 周） ✅ 已完成

> 目标：让已上传的材料真正可用——可浏览、可持久、可追溯。

### 1.1 多页 PDF 页码修复 ✅

**问题：** 当前多页 PDF 解析后页码信息丢失，问答时无法定位来源页。

**改动：**
- `backend/materials/` 解析器在分块时保留 `page_number` 字段
- 存入向量库的 metadata 增加 `page: int` 字段
- 问答引用返回时附带 `page_number`

**验收：** 上传 5 页以上 PDF，问答结果能正确返回页码引用。

**状态：** ✅ 已完成
- `parse_pdf` 函数保留 `page_number`
- `_build_material_documents` 将 `page_number` 存入 metadata
- `MaterialSource` 包含 `page` 字段
- 前端详情页显示页码引用

---

### 1.2 资料列表与详情页 ✅

**问题：** 上传后没有统一的浏览入口，无法查看已上传材料。

**后端：**
- `GET /api/materials`：已有，确认返回字段完整（`id, title, type, created_at, page_count, summary`）
- `GET /api/materials/{material_id}`：返回完整元信息 + 分页文本片段

**前端（`/materials`）：**
```
MaterialList
  └── MaterialCard（标题、类型、页数、上传时间）
        └── 点击 → /materials/[id]
MaterialDetail
  ├── 元信息区（标题、类型、摘要）
  ├── 分页文本预览（可折叠）
  └── 问答入口（跳转或 inline）
```

**验收：** 上传材料后可在列表中看到，点击可查看详情和摘要。

**状态：** ✅ 已完成
- `frontend/app/materials/page.tsx` - 资料列表页
- `frontend/app/materials/[materialId]/page.tsx` - 资料详情页
- 支持分页文本预览、资料问答、删除

---

### 1.3 临时材料 TTL 清理 ✅

**问题：** 匿名/未登录上传的临时材料无清理机制，数据持续堆积。

**改动：**
- 材料记录增加 `expires_at: datetime | None` 字段
- 未登录上传默认 TTL 24 小时
- 新增后台定时任务（`scripts/cleanup_expired_materials.py`）：删除过期材料 + Chroma collection
- 或注册为 FastAPI lifespan 中的后台 task

**验收：** 插入过期记录，运行脚本后确认被清理。

**状态：** ✅ 已完成
- `materials` 表已有 `expires_at` 字段
- `save_material_for_rag` 对匿名用户设置 24 小时 TTL
- `scripts/cleanup_expired_materials.py` 清理脚本已存在
- `list_expired_material_rows` 函数已实现

---

### 1.4 资料 RAG owner 隔离验证 ✅

**问题：** 多用户场景下，资料问答可能跨用户检索。

**改动：**
- Chroma 检索时强制加 `where={"owner_id": current_user_id}` 过滤
- smoke test 验证：用户 A 的材料不出现在用户 B 的检索结果中

**验收：** `eval/material_rag_isolation_smoke.py` 全部 PASS。

**状态：** ✅ 已完成
- 所有检索函数强制加 `owner_key` 过滤
- `_strict_vector_search` 和 `_strict_keyword_search` 使用 `build_chroma_where`
- `search_material_chunks` 验证 `_metadata_matches`
- `eval/material_rag_isolation_smoke.py` 已创建

---

## Milestone 2：拍照批改闭环（2 周）

> 目标：学生拍照上传作业，获得完整的批改结果并写入学习记录。

### 2.1 批改结果页体验完善

**现状：** 批改接口已有，但前端结果展示不完整。

**前端（`/homework-grading` 结果区）：**
- 分数展示（大字醒目）
- 各题批改详情（题号、学生答案、正误、得分、解析）
- 知识点标签（`knowledge_points: string[]`）
- 修改建议（`suggestions: string`）
- "记入错题本"按钮（触发弱点写入）

---

### 2.2 选择题支持

**现状：** 批改仅支持主观题/作文，缺少选择题 task type。

**后端（`backend/homework_grading/`）：**
```python
class TaskType(str, Enum):
    essay = "essay"
    short_answer = "short_answer"
    multiple_choice = "multiple_choice"  # 新增
```
- 选择题批改逻辑：识别选项 → 对比标准答案 → 逐题评分
- 返回结构与主观题保持一致

**验收：** 上传含选择题的作业图片，能正确识别并批改。

---

### 2.3 学习事件写入 + 弱点可视化

**现状：** `POST /api/students/{id}/events` 和 `weakpoints` 接口已有，但批改后未自动写入。

**改动：**
- 批改成功后，后端自动写入 `LearningEvent`（`type=homework_grading, score, knowledge_points, weakpoints`）
- 前端学生仪表板（`/student/dashboard`）展示弱点标签云
- 弱点来源聚合：历史游戏判分 + 批改结果 + 教材测验

**数据结构：**
```typescript
interface WeakPoint {
  knowledge_point: string   // e.g. "秦朝统一"
  frequency: number         // 出错次数
  last_seen: string         // 最近出错时间
  sources: ("game" | "grading" | "quiz")[]
}
```

---

## Milestone 3：错题本 + 知识点追踪（1 周）

> 目标：让学生看到自己的薄弱点，形成学习闭环。

### 3.1 错题本服务

**后端（`backend/services/weakpoint_service.py`）：**
```python
def record_weakpoint(student_id, knowledge_point, source, context)
def get_weakpoints(student_id) -> list[WeakPoint]
def clear_weakpoint(student_id, knowledge_point)
```

接入点：
- `history_games.py`：答题错误时调用
- `homework_grading`：批改后自动记录
- `textbook_learning/quiz`：测验答错时记录

---

### 3.2 弱点展示页

**前端（`/student/memory` 或独立 `/student/weakpoints`）：**
- 标签云：按频率排序的知识点标签
- 列表视图：知识点、出错次数、最近日期、来源图标
- 点击知识点 → 跳转到相关教材章节或发起历史人物对话

---

## 技术质量项（随版本穿插）

| 项目 | 说明 | 优先级 |
|------|------|--------|
| Langfuse tracing 补全 | 补齐 prompt/token/latency/error 链路 | P1 |
| RAG hybrid search | 增加 keyword 检索 + rerank，提升召回率 | P1 |
| 结构化输出统一 | 新建 `backend/structured_output.py`，统一 JSON 解析+校验 | P2 |
| smoke test 回归化 | 为 Milestone 1-3 的核心路径各写 smoke test | P1 |

---

## 文件改动汇总

```
backend/
  materials/          - 页码修复、TTL字段、owner过滤 ✅ 已完成
  services/
    weakpoint_service.py   (新建)
    cleanup_service.py     (新建)
  homework_grading/   - 选择题 task type、学习事件写入
  agents/
    history_games.py  - 接入弱点记录
  api/main.py         - 新增/调整相关路由

frontend/app/
  (student)/student/
    materials/        - 列表+详情页完善 ✅ 已完成
    weakpoints/       - 新建弱点页面
    dashboard/        - 弱点标签云组件
  homework-grading/   - 批改结果页完善
  materials/          - 列表+详情页 ✅ 已完成

eval/
  material_rag_isolation_smoke.py  ✅ 已创建
  homework_grading_smoke.py        (新建)

scripts/
  cleanup_expired_materials.py     ✅ 已创建
```

## 完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| Milestone 1：多模态资料库稳定化 | ✅ 已完成 | 页码修复、列表详情页、TTL清理、owner隔离 |
| Milestone 2：拍照批改闭环 | ✅ 已完成 | 见 202606231110-homework-grading-closed-loop-dev.md |
| Milestone 3：错题本 + 知识点追踪 | ✅ 已完成 | 见 202606231110-homework-grading-closed-loop-dev.md |

---

## 参考文档

- [`202606151008-multimodal-remaining-work-dev.md`](202606151008-multimodal-remaining-work-dev.md)
- [`202606111430-feature-roadmap-dev.md`](202606111430-feature-roadmap-dev.md)
- [`202606081653-ai-agent-capability-roadmap-dev.md`](202606081653-ai-agent-capability-roadmap-dev.md)
- [`202606091027-ai-agent-milestone-c-tools-learning-assistant-dev.md`](202606091027-ai-agent-milestone-c-tools-learning-assistant-dev.md)
- [`202606231110-homework-grading-closed-loop-dev.md`](202606231110-homework-grading-closed-loop-dev.md) — 拍照批改闭环
- [`202606231138-teacher-features-enhancement-dev.md`](202606231138-teacher-features-enhancement-dev.md) — 教师端功能增强
- [`202606231154-agent-runtime-visualization-dev.md`](202606231154-agent-runtime-visualization-dev.md) — Agent Runtime 可视化
- [`202606231436-tool-permission-confirmation-dev.md`](202606231436-tool-permission-confirmation-dev.md) — 工具权限治理和确认机制

---

## 当前状态（2026-06-23）

### 已完成里程碑

| 里程碑 | 状态 | 完成日期 |
|--------|------|----------|
| Milestone 1：多模态资料库稳定化 | ✅ 已完成 | 2026-06-23 |
| Milestone 2：拍照批改闭环 | ✅ 已完成 | 2026-06-23 |
| Milestone 3：错题本 + 知识点追踪 | ✅ 已完成 | 2026-06-23 |
| 教师端功能增强 | ✅ 已完成 | 2026-06-23 |
| Agent Runtime 可视化 | ✅ 已完成 | 2026-06-23 |
| 工具权限治理和确认机制 | ✅ 已完成 | 2026-06-23 |

### 下一步建议

根据当前功能完成情况，建议下一迭代聚焦以下方向：

1. **Agent Runtime 可视化（进行中）**
   - 统一 trace event schema
   - 学习助手页面增加 step timeline
   - 工具调用展示 tool metadata
   - 失败 step 可视化

2. **Tool Permission / Confirmation Demo**
   - 强制 role / confirmation 检查
   - 新增 high-risk demo tool
   - 前端确认卡片
   - audit log 记录决策

3. **Eval Dashboard 增强**
   - 展示关键指标
   - 一键运行 quick eval
   - 失败 case 展示与回流入口

4. **学习路径优化**
   - 基于错题本的智能推荐
   - 个性化学习计划生成
   - 学习进度可视化

2. **游戏化学习增强**
   - 历史游戏与错题本联动
   - 答对题目后自动移除错题
   - 游戏成就系统

3. **移动端适配**
   - 响应式布局优化
   - 移动端专用组件
