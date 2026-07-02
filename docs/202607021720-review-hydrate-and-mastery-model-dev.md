# 复习占位补齐 + 错题本掌握度模型开发文档

**创建日期：** 2026-07-02 17:20
**目标：** (D) 补齐 P1 遗留——复习页按需生成作业错题追加的占位题；(C) 把错题本"答对即删"升级为证据计数的掌握度模型。

---

## D：复习占位题按需生成

### 背景
P1 中 `merge_new_weakpoints_to_today` 把作业错题追加进今日复习 session 时，标了 `pending_generate` 占位（题干为"关于「X」的复习题"、无选项），题目留待打开复习页时生成。此前一直没消费这个占位。

### 实现（`services/review_service.py`）
- `get_today_session(student_id, today, *, hydrate=True)`：新增 `hydrate` 参数。
  - `hydrate=True`（复习页默认）：调 `_hydrate_pending_tasks` 把未作答的 `pending_generate` 占位题用 `_generate_question` 生成真题（题干/选项/答案/解析）、清除标记并落库；已生成过的不重复调用 LLM。
  - `hydrate=False`：只读不生成——供徽标轮询等只需计数的场景（`api/main.py` 学生徽标端点用 `hydrate=False`，避免每 60s 触发 LLM）。
- 前端复习页无需改动（本就渲染 `task.question`/`task.options`）。

---

## C：错题本掌握度模型

### 背景
`weakpoints` 移除逻辑此前是"答对即删"（`delete_weakpoint`）：任一处答对一次立即删除薄弱点。答对一次≠掌握，导致薄弱点频繁进出、复习池不稳、掌握度失真。

### 实现（`services/weakpoint_service.py`）
- 表加列 `correct_streak INTEGER DEFAULT 0`（`inspect` 检测后 `ALTER TABLE` 补列，兼容旧库）。
- `record_weakpoint`（答错）：`wrong_count+1` 且 `correct_streak=0`（答错即未掌握）。
- 新增 `record_correct_evidence(student_id, tag, *, mastery_threshold=2)`：
  - 未跟踪的 tag → no-op `{"removed": False, "reason": "not_tracked"}`。
  - 已跟踪 → `correct_streak+1`；达阈值删除并返回 `{"removed": True}`，否则更新 streak。
- `get_weakpoints` 返回带 `correct_streak`。

### 迁移的四处"答对"调用（`delete_weakpoint` → `record_correct_evidence`）
- `agents/auto_tutor.py`（答对某步）
- `textbook_learning/service.py`（教材练习答对）
- `services/assignment_service.py`：教师评阅≥60、学生客观题答对
- **保留** `api/main.py` 错题本页 `DELETE`（用户显式删除）与 `clear_weakpoints`。

### 复习作答回写（新增闭环）
`review_service.submit_answer` 此前不回写错题本。现在：答对→`record_correct_evidence`，答错→`record_weakpoint(source="review")`，让复习真正影响掌握度。

### 掌握度视图
`get_mastery_overview` 的 strength 纳入 `correct_streak` 加成（`+streak*0.2`，钳制 0.1–1.0），近期连续答对体现为强度上升；返回带 `correct_streak`。

---

## 测试

`eval/weakpoints_smoke.py` 由 5 例扩到 8 例，新增：
- `mastery_requires_consecutive_correct`：答对一次不删（streak=1），连续两次才删。
- `wrong_resets_streak`：答对后答错，streak 归零。
- `correct_evidence_on_untracked_is_noop`：未跟踪 tag 答对 no-op。

`eval/assignment_review_loop_smoke.py` 由 5 例扩到 6 例，新增 `hydrate_generates_pending_tasks`（stub LLM，验证占位题生成并落库）；其余断言改用 `hydrate=False` 保持离线确定性。

回归：assignment_smoke 12/12、learning_closure、build 52/52。

---

## 后续
1. mastery_threshold 可按知识点难度/题型动态调整。
2. 掌握度视图可展示 correct_streak 进度条（"再答对 1 次即掌握"）。
3. review 占位题生成可批量/异步，减少首屏等待。
