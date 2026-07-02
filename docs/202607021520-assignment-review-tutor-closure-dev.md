# 作业错题-复习-辅导数据闭环开发文档

**创建日期：** 2026-07-02 15:20
**目标：** 把已有的三个独立系统（作业批改 / 自适应复习 / AutoTutor）通过共享的薄弱点数据真正联动起来，形成「作业错题 → 薄弱点 → 复习 / 辅导」的完整学习循环。

---

## 一、背景与三处断点

此前作业错题已经写入 `weakpoints` 表，AutoTutor 与 SM-2 复习也都读同一张表，数据层是通的。但用户体验层存在三处断点：

| # | 断点 | 位置 |
|---|------|------|
| 1 | 提交结果不返回答错知识点，学生不知道该复习什么 | `assignment_service.submit_assignment` |
| 2 | 今日复习 session 已存在时，新作业错题当天进不去（`ON CONFLICT DO NOTHING`） | `review_service` |
| 3 | 结果页无法直接跳转到复习 / AutoTutor | `student/assignments/page.tsx` |

---

## 二、后端改动

### 1. `submit_assignment` 返回 `wrong_tags`

提交结果新增 `wrong_tags` / `correct_tags` 字段（答错 / 答对的知识点标签），供前端引导复习。

### 2. `review_service.merge_new_weakpoints_to_today`

新增函数：作业提交后把新增错误知识点追加到**已存在**的今日复习 session。

- 今日 session 不存在 → 跳过（学生主动打开复习页时按原逻辑创建）
- 已存在 → 仅追加不在 session 中的 tag，去重
- 不调用 LLM，追加的任务标 `pending_generate`，题目在打开复习页时按需生成

`submit_assignment` 在错题回流后调用它（用 `date.today()`，失败不阻塞提交）。

### 3. AutoTutor `focus_tags`

`start_session` 新增 `focus_tags` 参数；`AutoTutorStartRequest` 新增同名字段并透传。

传入 `focus_tags` 时，把这些知识点提到 `weakpoints` 列表最前（不在错题本里的补一个占位项），使教学计划优先讲解作业错题。

---

## 三、前端改动

### 学生作业结果页 `(student)/student/assignments/page.tsx`

`SubmitResult` 增加 `wrong_tags` / `correct_tags`。结果区块在有答错知识点时展示：

- 答错知识点 chips
- 「这些知识点已加入今日复习」提示
- 两个 CTA：`今日复习 →`（跳 `/student/review`）、`AutoTutor 辅导`（跳 `/student/auto-tutor?focus=<第一个错题知识点>`）

### AutoTutor 页 `(student)/student/auto-tutor/page.tsx`

- 用 `useSearchParams` 读取 `?focus=`，启动时作为 `focus_tags` 传给后端
- 开始按钮上方提示「将优先讲解你作业中答错的「X」」
- `useSearchParams` 需 Suspense 边界：组件改名 `AutoTutorInner`，默认导出用 `<Suspense>` 包裹

---

## 四、测试

新增 `eval/assignment_review_loop_smoke.py`（5 例，已接入 `run_core_evals.py`）：

1. `submit_returns_wrong_tags` — 提交答错两题，返回正确的 `wrong_tags`
2. `wrong_tags_written_to_weakpoints` — 错题写入错题本
3. `merge_appends_to_existing_session` — 新弱点追加进已存在的今日 session
4. `merge_dedups_and_skips_missing_session` — 重复 tag 去重、无 session 的日期跳过不报错
5. `autotutor_prioritizes_focus_tags` — `focus_tags` 指定的知识点排在教学计划首位

回归：`assignment_smoke` 12/12、`learning_closure_smoke` 4/4、`review_system_smoke` 4/4、前端 build 52/52。

---

## 五、后续计划

1. 复习页消费 `pending_generate` 占位任务，打开时按需生成题目。
2. `wrong_tags` 去重（同一 tag 多题答错目前会重复出现在 chips）。
3. weakpoint 从「答对即删」升级为掌握度模型（证据计数）。
4. 学生 dashboard 增加「作业产生 N 个新薄弱点」提示卡。
