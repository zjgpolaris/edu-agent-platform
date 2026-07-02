# 作业讲评闭环洞察开发文档

**创建日期：** 2026-07-01 17:31  
**目标：** 在教师已完成 AI 出题、发放、学生提交、人工评阅的基础上，把作业数据聚合成可直接用于下一节课讲评的洞察。

---

## 一、背景

当前教师作业工作流已经具备：

```text
AI 出题 → 教师修改确认 → 发放学生 → 学生提交 → 自动批改 / 人工评阅 → 错题回流 AutoTutor
```

但教师仍需要手动判断：

- 哪些知识点错得最多？
- 哪道题正确率最低？
- 哪些学生需要重点关注？
- 还有多少主观题没评阅？
- 下一节课该讲什么？

本迭代新增 **Assignment Closure Insights**，将提交明细聚合为讲评洞察。

---

## 二、数据来源

### assignments.questions_json

每道题包含：

- `type`
- `prompt`
- `options`
- `answer`
- `knowledge_tag`
- `reference_answer`（简答题参考答案要点，仅教师端使用）

### assignment_submissions.answers_json

每位学生每题提交包含：

- `question_index`
- `student_answer`
- `is_correct`
- `correct_answer`

### assignment_submissions 主字段

- `score`
- `status`
- `teacher_feedback`
- `reviewed_at`

---

## 三、后端聚合

核心函数：

```python
def compute_assignment_insights(assignment, submissions, threshold=60.0) -> dict:
    ...
```

返回结构：

```json
{
  "submission_rate": {
    "submitted": 2,
    "assignee_count": 3,
    "percent": 67,
    "missing_student_ids": ["student_003"]
  },
  "average_score": 72.5,
  "graded_average_score": 80.0,
  "pending_review_count": 1,
  "lowest_accuracy_questions": [],
  "top_weak_tags": [],
  "below_threshold_students": [],
  "suggested_reteach_focus": []
}
```

### 聚合规则

1. **提交率**：`submitted / assignee_count`。
2. **均分**：所有非空 `score` 的平均。
3. **已评阅均分**：仅 `status == graded` 的平均。
4. **待评阅数**：`status == partial` 的提交数。
5. **低正确率题**：只统计客观题；按正确率升序、错误数降序排序。
6. **薄弱知识点**：
   - 客观题答错：`objective_wrong`
   - 低分主观题涉及的知识点：`review_score`
7. **低分学生**：`score < 60`。
8. **讲评重点**：基于 top weak tags deterministic 生成，不调用 LLM。

---

## 四、API 行为

### 教师作业列表

```http
GET /api/teacher/assignments
```

每个作业 summary 增加：

- `pending_review_count`
- `top_weak_tags`
- `lowest_accuracy_question`
- `below_threshold_count`

### 作业提交详情

```http
GET /api/teacher/assignments/{assignment_id}/submissions
```

返回增加：

```json
{
  "assignment": {},
  "submissions": [],
  "insights": {}
}
```

---

## 五、前端体验

文件：`frontend/app/(teacher)/teacher/assignments/page.tsx`

### 作业列表

每份作业卡片显示：

- 完成率
- 已交人数
- 均分
- 待评阅数
- Top 薄弱知识点 chip
- 最低正确率题
- 低分学生数

### 作业详情

详情顶部新增「讲评洞察」区域：

- 提交率 / 均分 / 待评阅 / 低分学生四个指标
- 讲评优先级
- 低正确率题
- 需关注学生
- 复制讲评提纲按钮

---

## 六、验收方式

1. 教师创建含单选、判断、简答题的作业。
2. 两个学生提交，其中一个学生故意答错客观题。
3. 教师打开作业列表，看到薄弱点与低正确率题摘要。
4. 打开详情，看到讲评洞察面板。
5. 教师评阅简答题后，待评阅数刷新。
6. 点击「复制讲评提纲」，文本可读且包含讲评重点。

---

## 七、后续计划

1. 学生端已完成作业复盘页：展示教师评语、每题错因、参考答案与复习入口。
2. weakpoint 删除策略从“答对即删除”升级为证据计数或掌握度模型。
3. 作业提交 learning event 语义细化，避免 `partial` 被误判为失败。
4. 讲评建议可选接入 LLM，但需要基于当前 deterministic insights 做输入。
