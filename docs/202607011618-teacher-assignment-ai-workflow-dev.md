# 教师 AI 布置作业工作流开发文档

**创建日期：** 2026-07-01 16:18  
**相关提交：** `daed49c`、`207a2c4`、`9e00797`  
**目标：** 将「教师布置作业」从手工录题升级为 AI 出题、教师确认、学生作答、错题回流 AutoTutor 的闭环。

---

## 一、背景

原有教师作业工作流已经支持：

1. 教师手工创建作业；
2. 指定学生；
3. 学生提交；
4. 客观题自动判分。

但缺少三个关键环节：

- 教师需要手工录入题目，效率低；
- 教师只能看到完成率/均分，看不到学生每题答题情况；
- 作业中暴露的薄弱点没有回流到错题本和 AutoTutor。

本轮迭代补齐为完整链路：

```text
教师输入知识点 → AI RAG 出题 → 教师修改确认 → 发放学生
                                            ↓
学生作答提交 → 自动批改 → 错题写入 weakpoints → AutoTutor 后续规划使用
                                            ↓
教师查看提交详情：分数 / 每题答对错 / 学生答案 / 正确答案
```

---

## 二、实现内容

### 2.1 P0：作业错题回流薄弱点

文件：`backend/services/assignment_service.py`

在 `submit_assignment()` 中增加知识点标签回流逻辑：

- 客观题答错：`record_weakpoint(student_id, knowledge_tag, source="assignment")`
- 客观题答对：`delete_weakpoint(student_id, knowledge_tag)`
- 回流失败不影响作业提交结果，避免弱依赖阻塞核心流程。

价值：学生在教师布置作业中暴露的薄弱点，会自动进入错题本，成为 AutoTutor 规划下一节课的输入。

---

### 2.2 P1：教师提交详情下钻

文件：`frontend/app/(teacher)/teacher/assignments/page.tsx`

后端已有接口：

```http
GET /api/teacher/assignments/{assignment_id}/submissions
```

前端新增：

- 作业列表行可点击；
- 点击后加载提交详情；
- 展示每个学生：
  - 分数；
  - 提交状态；
  - 每题答对/错；
  - 学生答案与正确答案；
  - 题目知识点标签。

价值：教师不再只能看统计值，可以定位具体错题，用于课堂讲评和个别辅导。

---

### 2.3 P2：AI 出题支持多题型

文件：

- `backend/api/main.py`
- `frontend/app/(teacher)/teacher/assignments/page.tsx`

新增接口：

```http
POST /api/teacher/assignments/generate-questions
```

请求核心字段：

```json
{
  "knowledge_points": ["鸦片战争", "洋务运动"],
  "difficulty": "medium",
  "question_type": "single_choice",
  "subject": "历史"
}
```

支持题型：

| 题型 | `question_type` | 自动批改 |
|------|------------------|----------|
| 单选题 | `single_choice` | 是 |
| 判断题 | `true_false` | 是 |
| 简答题 | `subjective` | 否，待人工评阅 |

生成策略：

- 单选题：复用 `agents.auto_tutor._generate_question()`；
- 判断题：RAG 取材后结构化生成 `statement / answer / explanation`；
- 简答题：RAG 取材后结构化生成 `question / reference_answer`；
- 生成失败时提供 fallback，保证教师端流程可继续。

前端新增：

- AI 出题区的「题型」选择器；
- 生成后自动映射到可编辑题目卡片；
- 教师仍可修改题干、选项、答案、知识标签后再发布。

---

## 三、数据流

```text
teacher/assignments page
  └── POST /api/teacher/assignments/generate-questions
        ├── search_history_knowledge(RAG)
        ├── LLM structured output
        └── generated draft questions

teacher edits and confirms
  └── POST /api/teacher/assignments
        └── assignments.questions_json

student/assignments page
  └── POST /api/student/{student_id}/assignments/{assignment_id}/submit
        ├── objective auto grading
        ├── assignment_submissions.answers_json
        └── weakpoints update
              ├── wrong → record_weakpoint(..., source="assignment")
              └── correct → delete_weakpoint(...)
```

---

## 四、验收方式

### 4.1 教师端

1. 登录 `teacher_zhang / teacher123`；
2. 进入 `/teacher/assignments`；
3. 新建作业；
4. 在 AI 出题区输入知识点；
5. 分别测试单选题、判断题、简答题；
6. 修改题目内容；
7. 勾选学生并发布；
8. 回到作业列表，确认作业出现；
9. 点击作业行，查看提交详情。

### 4.2 学生端

1. 登录 `demo-student / demo123` 或 `student_001`；
2. 进入 `/student/assignments`；
3. 打开待完成作业；
4. 提交客观题；
5. 查看即时批改结果。

### 4.3 闭环验证

1. 对带 `knowledge_tag` 的题故意答错；
2. 提交后检查错题本/薄弱点；
3. 再进入 AutoTutor，确认规划会纳入新的薄弱点。

---

## 五、注意事项

- 简答题当前不自动判分，提交后状态为 `partial`，需要教师人工评阅能力后续补齐。
- 错题回流只处理客观题，因为主观题没有自动判定 `is_correct`。
- 生成题目使用 RAG 史料作为上下文，但仍保留教师修改确认环节，避免 AI 题目未经审核直接发放。
- 认证禁用的本地开发模式下，`require_auth()` fallback 为 `dev-teacher`，避免 `teacher_id=null` 写库失败。

---

## 六、后续建议

1. 增加教师人工评阅主观题入口；
2. 将提交详情中的高频错题聚合成「本次作业讲评建议」；
3. AI 出题支持混合题型：同一批知识点按比例生成单选/判断/简答；
4. 把作业错题回流事件写入学习事件表，供成长报告展示来源。
