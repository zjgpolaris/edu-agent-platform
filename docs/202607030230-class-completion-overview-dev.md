# 教师班级作业完成情况（催办）开发文档

**创建时间：** 2026-07-02
**迭代目标：** 教师此前只能看到"每份作业的完成率"，看不到"跨多份作业，哪个学生欠交最多、有几份逾期"。补一个**学生维度**的完成情况聚合，帮教师一眼识别掉队学生、精准催办。
**类型：** 后端（聚合服务 + 端点）+ 前端（教师首页催办卡）+ 测试

---

## 一、背景

`list_teacher_assignments` 给的是每份作业的 `completion_rate`（作业维度）。但教师真正需要的运营视角是**学生维度**：张三跨 5 份作业欠交 3 份、其中 2 份逾期。这个视图此前完全没有，教师无法快速定位掉队学生。

本轮做学生维度的跨作业聚合，与学生侧「今日计划」（1.16.7）形成师生对称：学生看自己今天该做什么，教师看谁落下了。

## 二、实现

### 后端
- **`services/completion_overview.py`（新模块）**：
  - `compute_class_completion(records, today)` —— **纯函数**。`records=[{id,title,due_date,assignee_ids,submitted_ids}]`，按学生聚合 `assigned/submitted/pending/overdue/overdue_titles`；逾期定义＝作业 `due_date < today` 且该生未交。学生按"逾期多 > 欠交多 > 学号"排序（掉队优先）。`summary` 给班级维度：学生数、有逾期学生数、已全交学生数、总体提交率。
  - `get_class_completion_overview(teacher_id, today)` —— 装配层：拉该教师全部作业 + 每份的提交学生集，喂给纯函数。teacher 隔离。
- **端点**（`main.py`）：`GET /api/teacher/completion-overview`，`require_teacher_actor` + `run_in_threadpool`。

### 前端
- **`(teacher)/teacher/ClassCompletionCard.tsx`（新组件，自包含取数）**：班级四指标（总体提交率 / 有逾期学生 / 已全交 / 作业数）+ 掉队学生列表（逾期红标、欠交黄标、逾期作业名，点击进个人学情页）；全交时显示"都已交齐"。教师首页 `page.tsx` 仅新增 2 行（import + 在班级概览后渲染）。

### 测试
- **`eval/completion_overview_smoke.py`（新，6 例，离线）**：空班级、逐生计数、逾期需 due 在过去（今天/无 due 不算）、掉队排序、班级摘要指标，外加真实 DB 集成（建逾期作业 + 一生提交 → 另一生逾期 + teacher 隔离）。接入 `run_core_evals.py`（SMOKE，category=teacher）。

## 三、验证

1. `python3 eval/completion_overview_smoke.py` → **6/6**
2. `ast.parse` `completion_overview.py` / `main.py` → OK
3. `npm run build --prefix frontend` → 全绿（教师首页组件编译）

## 四、师生对称

```
学生：GET /api/students/{id}/today          → 我今天该做什么（作业到期/复习/薄弱点）
教师：GET /api/teacher/completion-overview   → 谁落下了（跨作业欠交/逾期，掉队优先）
```
两者都是确定性聚合、复用既有作业数据、纯函数核心可离线测。
