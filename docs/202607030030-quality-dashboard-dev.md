# 命题质量看板开发文档

**创建时间：** 2026-07-02
**迭代目标：** 把前几轮攒下的质检数据（每题 quality、盲区、复核 flag、few-shot 反例）从"散落在单份作业详情"升维成**跨作业的教师命题质量画像**，让教师一眼看清 AI 质检准不准、自己最常踩哪类坑——数据有了，补上"数据→洞察"的出口视图。
**类型：** 后端（聚合服务 + 端点）+ 前端（看板页 + 侧边栏入口）+ 测试

---

## 一、背景

质量反馈链已闭环：AI 出题质检 → 持久化 `quality` → 真实作答比对（`quality_blind_spots`）→ 徽标提醒 → 教师复核（`question_review_flags`）→ few-shot 反哺。

但这些数据只在**单份作业**的详情里出现。教师看不到"我出的题整体质量如何、AI 质检的命中/误报趋势"。本轮补上聚合视图，收口当前赛道。

## 二、实现

### 后端
- **`services/quality_dashboard.py`（新模块）· `get_teacher_quality_dashboard(teacher_id)`**：
  跨该教师全部作业聚合，只读确定性，复用 `compute_assignment_insights` / `get_bad_question_examples` 等。返回：
  - `totals`：作业 / 题目 / 客观题 / 已质检 / 含语义质检 计数
  - `quality_distribution`：`{error, warn, ok, unchecked}`（来自每题持久化的 `quality.level`）
  - `effectiveness`（核心差异化）：
    - `proactive_flagged` 主动预警（level ∈ error/warn）
    - `suspected_false_alarm` 疑似误报（预警但真实正确率 ≥ `FALSE_ALARM_ACCURACY`=80）
    - `blind_spots_total / open / confirmed_bad / not_mastered`（盲区总数 / 待复核 / 复核确认 AI 漏检 / 其实是学生没掌握）
  - `review_verdicts`：教师复核结论分布
  - `top_issue_types`：高频问题类型（对 `quality.issues` 去「语义：」前缀后计数，Top 6）
  - `hardest_questions`：跨作业真实正确率最低的题（attempts ≥ 3，附所属作业，升序，Top 8）
  - `recent_bad_examples`：近期回流的 few-shot 反例
  > 独立成模块而非并入 677 行的 `assignment_service.py`：它是纯只读分析层，模块边界合理；开发当时写工具受限也促成此选择。
- **端点**（`main.py`）：`GET /api/teacher/quality-dashboard`，`require_teacher_actor` + `run_in_threadpool`。

### 前端
- **`(teacher)/teacher/quality-dashboard/page.tsx`（新页，组内自带侧边栏 shell）**：
  命题概览四宫格 → AI 质检有效性四宫格（主动预警 / 疑似误报 / 待复核盲区 / 已确认漏检，附一句自然语言解读 + 去复核 CTA）→ 质检分布条 + 图例 → 高频问题类型 → 最难题 Top（正确率色阶 + AI 预警/盲区标签，点击回作业页）→ 复核结论 + 近期反例。`qd-` 前缀内联 `<style>`，沿用朱砂/青金/纸色设计语言。
- **侧边栏**：`AppSidebar` teacherNav「系统运维」分组新增「命题质量」入口。

### 测试
- **`eval/quality_dashboard_smoke.py`（新，真实 DB 离线，7 例）**：构造 3 题（Q0 判 ok 但正确率 20%→盲区、Q1 判 warn 但 100%→疑似误报、Q2 判 error 40%）+ 5 份提交 + 标 Q0 为 bad_question，断言 totals/分布/有效性/复核结论/高频问题/最难题排序/反例，以及 teacher 隔离。已接入 `run_core_evals.py`（SMOKE）。

## 三、验证

1. `python3 eval/quality_dashboard_smoke.py` → **7/7**
2. `python3 eval/assignment_smoke.py` → **17/17**（回归）
3. `ast.parse` `quality_dashboard.py` / `main.py` / `run_core_evals.py` → OK
4. `npm run build --prefix frontend` → **53/53**，新增 `/teacher/quality-dashboard` 已编译

## 四、闭环全貌（数据 → 洞察）

```
AI 出题质检 → 持久化 quality ┐
真实作答比对（盲区）        ├─→ get_teacher_quality_dashboard → 命题质量看板
教师复核（bad/not_mastered）┘        （分布 · 有效性漏检误报 · 高频问题 · 最难题 · 反例）
```
单份作业的质检数据被升维成教师可决策的命题质量画像，质量反馈链自此既能自我强化（few-shot），又能被教师俯瞰复盘。
