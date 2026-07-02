# AI 出题质量治理开发文档

**创建日期：** 2026-07-02 16:05
**目标：** 给 AI 生成的作业题目加确定性结构质检，把可机检的问题在教师审阅前显式标注，让 AI 出题质量可控。

---

## 一、背景

`POST /api/teacher/assignments/generate-questions` 此前把 LLM 生成的题目直接返回给教师，无任何结构校验。单选题可能选项不足 4 个、正确答案字母越界、选项重复、题干为空、判断题 answer 非法——教师只能肉眼发现。

本轮加一层**确定性（不额外调用 LLM）质检**，成本近零、可测、给教师明确信号。语义质检（歧义、答案是否真的正确）与教师改题 diff 记录留待后续。

---

## 二、后端

### `backend/services/question_quality.py`（新建）

- `check_question(q: dict) -> {"level": ok|warn|error, "issues": [...]}`，纯函数。
  - 通用：题干为空 → error；题干 <6 字 → warn。
  - single_choice：非空选项 ≠ 4 → error；选项重复 → warn；答案字母不在 A–D 或超出选项范围 → error。
  - true_false：answer 非「正确/错误」→ error。
  - subjective：`reference_answer`/`explanation` 皆空 → warn。
  - level 取最高级别。
- `summarize_quality(questions) -> {"error_count","warn_count"}`。

### `backend/api/main.py`

- `GeneratedQuestion` 新增 `quality: dict | None`。
- `teacher_generate_questions` 内 `_with_quality()` 包裹三种题型的构造，用 `check_question(gq.model_dump())` 回填。simple 题的参考答案存于 `explanation`，`check_question` 对 subjective 会读 `explanation`，兼容。

---

## 三、前端 `(teacher)/teacher/assignments/page.tsx`

- `DraftQuestion` 加 `quality?: { level; issues }`；AI 生成映射带上后端返回的 `quality`。
- 题卡题干下方渲染质量徽标：`error` 红色「⚠ 需修正」、`warn` 黄色「可优化」，附 issues；`ok` 不显示。
- 新增 CSS：`.tasg-quality` / `-error` / `-warn` / `-tag` / `-issues`。
- 徽标仅反映 AI 生成那一刻的检查结果，教师手动编辑后不实时重算（保持简单）。

---

## 四、测试

`eval/question_quality_smoke.py`（新建，10 例，纯离线）：合法单选 ok、3 选项 error、答案 E error、重复选项 warn、空题干 error、判断题「对」error、判断题「正确」ok、简答缺参考答案 warn、简答有参考答案 ok、summarize 统计。已注册 `run_core_evals.py`（p1/teacher）。

回归：`assignment_smoke` 12/12、前端 build 52/52。

---

## 五、后续

1. LLM 语义质检：题干歧义、判断题陈述与 answer 是否自洽、单选干扰项是否合理（基于当前 deterministic 结果做输入）。
2. 教师改题 diff 记录，作为出题模型微调数据。
3. 质检不通过的题在保存时可选阻断或二次确认。
