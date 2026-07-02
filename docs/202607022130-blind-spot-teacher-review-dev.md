# 质检盲区教师复核开发文档

**创建时间：** 2026-07-02
**迭代目标：** 让质检盲区从只读提示升级为可处置——教师给判定（题目有问题 / 学生没掌握），记录结论并据此调整徽标
**类型：** 后端（新表 + API）+ 前端 + 测试

---

## 一、背景

上一轮「质检有效性回路」让 `compute_assignment_insights` 能算出 `quality_blind_spots`（AI 判合格但真实正确率 <40%、样本 ≥3 的客观题），教师端「⚠ 质检盲区」徽标提示。

但盲区是只读的，两种情况混在一起无法区分：
1. **题目确实有问题**（歧义 / 答案争议 / 干扰项过强）→ AI 质检漏检，应记录且不再反复提示。
2. **学生只是没掌握**（题目没问题）→ 误报，徽标应能消掉。

本轮加教师复核，把人放进闭环。范围：只做复核（不含 few-shot 回流，留待后续）。

## 二、实现

### 后端
- **新表 `question_review_flags`**（`_ensure_tables`）：`(assignment_id, question_index)` 唯一，字段 verdict / note / created_at。
- **`record_question_review_flag(teacher_id, assignment_id, question_index, verdict, note=None)`**：
  - verdict 仅 `bad_question` / `not_mastered`，否则 `ValueError`。
  - 校验作业存在且归属（`PermissionError`）、index 越界（`LookupError`）。
  - UPSERT = 先 DELETE 同 (assignment, index) 再 INSERT，避免方言差异。
- **`get_question_review_flags(assignment_id)`**：按 question_index 索引。
- **`get_assignment_submissions`** 返回加 `review_flags`（`{str(index): {verdict, note, created_at}}`）与 `open_blind_spot_count`（盲区中未复核数）。
- **API** `POST /api/teacher/assignments/{id}/questions/{index}/review-flag`，`require_teacher_actor` + `run_in_threadpool`，异常映射 400/404/403。

### 前端（`teacher/assignments/page.tsx`）
- `AssignmentDetail` 加 `review_flags` / `open_blind_spot_count`；新增 `flagQuestion(index, verdict)` + `flagging` 状态。
- 盲区题（未复核）：徽标旁「题目有问题」「学生没掌握」按钮 → POST → `loadDetail` 刷新。
- 复核后：`bad_question` → 徽标变「已标记题目问题」（暗色）；`not_mastered` → 盲区徽标消失，改极淡「学生未掌握」。

### 测试（`eval/assignment_smoke.py`，真实 DB）
- `record_review_flag_bad_question`：记录后 `review_flags["0"].verdict == "bad_question"`、note 保留。
- `record_review_flag_upsert_and_validate`：not_mastered 覆盖 bad_question；非法 verdict→ValueError；越界→LookupError；非归属→PermissionError。
- 14 → 16 例。

## 三、验证

1. `python3 eval/assignment_smoke.py` → 16/16
2. `python3 eval/run_core_evals.py` → 回归全绿
3. `npm run build --prefix frontend` → 53/53
4. `python3 -c "import ast; ast.parse(open('backend/services/assignment_service.py').read()); ast.parse(open('backend/api/main.py').read())"`
5. 手动：盲区题「题目有问题」→ 徽标变「已标记题目问题」且刷新保留；「学生没掌握」→ 盲区徽标消失

## 四、后续可延伸

- `bad_question` 样本作为 `check_question_semantic` 的 few-shot 反例，让语义质检越用越准。
- `open_blind_spot_count` 接入教师通知徽标，未复核盲区提醒。
