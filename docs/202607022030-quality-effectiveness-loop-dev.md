# 质检有效性回路开发文档

**创建时间：** 2026-07-02
**迭代目标：** 让 AI 出题质检结论随作业持久化，并在讲评洞察中交叉比对真实作答，标记「质检盲区」题，形成质检的自我改进回路
**类型：** 后端 + 前端 + 测试（存储层零改动）

---

## 一、背景

AI 出题会做结构质检（`question_quality.check_question`）+ 可选 LLM 语义质检（`check_question_semantic`），结论放进每题 `quality` 字段（`{level, issues}`），教师出题草稿区用徽标展示。

排查发现：这个结论在**建作业时被静默丢弃**——

- 后端 `AssignmentQuestion`（`backend/api/main.py`）无 `quality` 字段 → Pydantic 丢弃。
- 前端 `save()` 的 `payloadQuestions`（`assignments/page.tsx`）未带 `quality`。

结果："AI 预判质量"与"学生真实作答表现"这条回路无法建立。

## 二、核心思路

**质检盲区**：AI 判为合格（`level` 为 `ok` 或未做语义检查即 `None`）、但学生真实正确率异常低的客观题。这类题是质检规则 / 语义检查没覆盖到的真问题（如题干歧义、答案争议、干扰项过强），最值得教师复核，也是评估质检有效性的直接信号。

判定阈值（`assignment_service.py` 常量）：
- `BLIND_SPOT_ACCURACY = 40`：正确率 <40% 视为异常低
- `BLIND_SPOT_MIN_ATTEMPTS = 3`：作答样本 ≥3 才有统计意义

被质检**预警过**（`warn`/`error`）的低正确率题**不算盲区**——那是质检起了作用，非盲区。

## 三、实现

### 1. 持久化 quality（存储零改动）
- `AssignmentQuestion` 加 `quality: dict | None = None`。`create_assignment` 本就 `json.dumps(questions)` 全量存储，自动持久化。
- 前端 `save()` payload 每题加 `quality: q.quality ?? null`。

### 2. insights 计算盲区（`compute_assignment_insights`）
- `lowest_accuracy_questions` 每题附 `predicted_level`（读 `q["quality"]["level"]`）。
- 新增 `quality_blind_spots`：按上述阈值筛选，按 accuracy 升序取前 5，元素 `{question_index, prompt, accuracy, attempts, predicted_level}`。
- `_compact_insights` 加 `quality_blind_spot_count`（作业列表摘要用）。

### 3. 前端展示（`teacher/assignments/page.tsx`）
- 类型加 `QualityBlindSpot` / `AssignmentInsights.quality_blind_spots` / `LowAccuracyQuestion.predicted_level`。
- 「低正确率题」卡片：命中盲区的题追加「⚠ 质检盲区」徽标（`.tasg-blindspot`），tooltip 说明「AI 质检判为合格，但真实正确率异常低，建议复核题目本身」。

### 4. 测试（`eval/assignment_smoke.py`，纯函数）
- `insights_flags_quality_blind_spot`：quality=ok + 20% 正确率 + 5 人作答 → 命中。
- `insights_excludes_prewarned_and_underanswered`：quality=error → 不计入；样本仅 2 人 → 不计入。
- 12 → 14 例。

## 四、验证

1. `python3 eval/assignment_smoke.py` → 14/14
2. `python3 eval/run_core_evals.py` → 回归全绿
3. `npm run build --prefix frontend` → 53/53
4. `python3 -c "import ast; ast.parse(open('backend/services/assignment_service.py').read())"` → 语法 OK

## 五、后续可延伸

- 盲区题反哺 `question_quality`：把真实高错误率作为语义质检 few-shot 反例。
- 教师复核后标记「题目有问题 / 学生确实没掌握」，区分"题差"与"知识点难"。
