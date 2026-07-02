# 语义质检自改进闭环开发文档

**创建时间：** 2026-07-02
**迭代目标：** 让教师人工判定的 `bad_question` 反哺 LLM 语义质检，作为 few-shot 反例，使质检随复核越用越准——把质量反馈链从"人工闭环"升级为"自改进闭环"
**类型：** 后端（服务 + 质检 + 端点）+ 测试

---

## 一、背景

前几轮已构成完整的人工质量反馈链：
AI 出题质检 → 持久化 `quality` → 真实作答比对（`quality_blind_spots`）→ 徽标提醒 → 教师复核（`question_review_flags`，verdict `bad_question`/`not_mastered`）。

但教师的复核结论此前只用于调整徽标，没有回流去改进 AI 本身。本轮闭合最后一环：把教师判为 `bad_question` 的题作为 few-shot 反例注入语义质检 prompt。

范围：**仅本教师**自己的样本（隐私干净、符合 teacher 隔离惯例；新教师冷启动无样本时行为同现状）。

## 二、实现

### 后端
- **`get_bad_question_examples(teacher_id, *, limit=5)`**（`assignment_service.py`）：
  join `question_review_flags`(verdict=bad_question) 与 `assignments.questions_json`，取对应题干 + flag 备注，按复核时间倒序、题干去重，teacher 隔离；无数据返回 `[]`。只读确定性。
- **`check_question_semantic(q, *, llm=None, bad_examples=None)`**（`question_quality.py`）：
  新增 `bad_examples` 可选参数（默认 None → 完全向后兼容）。有值时在 system prompt 末尾追加「该教师此前判定为『题目有问题』的样例…（只借鉴问题类型，勿照搬）」段，前 3 条、每条截断防膨胀。schema / fallback / 返回契约不变。
- **端点**（`main.py teacher_generate_questions`）：`semantic_check=true` 时 `run_in_threadpool(get_bad_question_examples, actor.actor_id)` 取一次（非每题），传入 `_with_quality → check_question_semantic`。取样失败降级为空，不阻断出题。

### 测试
- `question_quality_smoke.py`（离线）：`_RecordingStubLLM` 记录 messages →
  - `semantic_injects_bad_examples_into_prompt`：断言 system prompt 含反例题干与「题目有问题」。
  - `semantic_without_bad_examples_unchanged`：不传时 prompt 不含 few-shot 段（回归）。
  - 15 → 17 例。
- `assignment_smoke.py`（真实 DB）：`bad_question_examples_fetch_and_isolation`——标 1 题 bad_question + 1 题 not_mastered → 仅取到 bad_question 那道（题干+备注）；别的教师取不到。16 → 17 例。

## 三、验证

1. `python3 eval/question_quality_smoke.py` → 17/17
2. `python3 eval/assignment_smoke.py` → 17/17
3. `python3 eval/run_core_evals.py` → 相关套件全绿
4. `npm run build --prefix frontend` → 53/53（前端无改动，回归）
5. `ast.parse` 三个后端文件

## 四、闭环全貌（至此完整）

```
AI 出题 → 结构+语义质检(quality) → 随作业持久化
   ↑                                    ↓
few-shot 反例 ← 教师复核(bad_question) ← 徽标提醒 ← 真实作答比对(盲区)
```
教师每标一道 bad_question，语义质检下次就多一个本地反例——闭环自我强化。
