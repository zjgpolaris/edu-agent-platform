# 作业-错题-复习-学情闭环增强开发记录

## 背景

本轮迭代延续“班级作业 + AI 批改 + 错题归因 + 个性化复习 + 教师学情”的下一阶段方向，但只读探索后发现项目已经具备较完整的底座：

- 作业批改：`backend/homework_grading/` 已支持拍照/文本批改、结构化结果、教师审核队列。
- 学生画像：`backend/student_profile.py` 已有 `learning_events`、`student_profiles`、`memory_entries`。
- 错题本：`backend/services/weakpoint_service.py` 已有 `weakpoints` 持久化与 API。
- 教师端：已有班级学情、教师资料库、作业审核和教学建议接口/页面。
- 评估：已有 `eval/run_core_evals.py` 统一评估 runner。

因此本轮没有新建独立的作业/错题/复习数据模型，而是补齐现有能力之间的闭环断点。

## 目标

让已有链路形成可见、可验证的闭环：

```text
作业/练习/游戏产生薄弱点
→ weakpoints + student_profiles 聚合
→ 学生首页 / 错题本 / 学习路径 / 学情中心展示优先复习
→ 教师首页 / 班级学情展示本轮讲评重点
→ 教学建议基于高频薄弱点生成讲评步骤和分层作业
```

## 后端改动

### 1. 修复教师班级学情真实 schema 读取

文件：`backend/api/main.py`

`/api/teacher/class-analytics` 原先读取已不存在的字段：

- `quiz_avg_score`
- `game_avg_score`
- `weak_topics`
- `strong_topics`

本轮改为读取真实 SQLite schema：

- `quiz_stats_json`
- `game_stats_json`
- `weak_topics_json`
- `strong_topics_json`

并保持 API 输出字段兼容：

- `average_quiz_score`
- `average_game_score`
- `weak_topics_distribution`
- `strong_topics_distribution`
- `top_weak_topics`
- `activity_by_day`

### 2. 增强复习计划和学习路径

文件：`backend/api/main.py`

`GET /api/students/{student_id}/review-plan` 保留原有 `review_plan` 响应，同时新增：

- `weakpoints`
- `priority_topics`

`GET /api/students/{student_id}/learning-path` 修复 `profile.created_at` 不存在的问题，并新增：

- `weakpoints`
- `priority_topics`

学习路径的 `progress` 会基于错题次数调整：

- `wrong_count >= 5`：`0.25`
- `wrong_count >= 3`：`0.4`
- 其他错题：`0.5`
- 优势点：`0.8`

### 3. 强化教学建议 prompt

文件：`backend/api/main.py`

`POST /api/teacher/teaching-suggestions` 的 prompt 现在会传入高频薄弱点的人数和占比，例如：

```text
- 洋务运动: 3 名学生，约 60%
```

并要求模型输出更具体的教师动作：

- 讲评课步骤
- 典型错因讲评
- 同类题即时练习
- 重点知识点
- 基础巩固 + 提高拓展的分层作业

响应 schema 保持不变：

```json
{
  "suggestions": [],
  "activities": [],
  "key_topics": [],
  "homework_suggestions": []
}
```

### 4. 教师审核结果反向同步学习信号

文件：`backend/api/main.py`、`backend/homework_grading/review_store.py`

`POST /api/teacher/homework-reviews/{review_id}/decision` 在保存教师决策后，会重新读取审核记录并写入学习事件：

- `accepted` → `teacher_review_accepted`
- `edited` → `teacher_review_edited`
- `rejected` → `teacher_review_rejected`

当教师决策为 `accepted` 或 `edited` 时，会把批改结果中的 `weak_points` 和题目级 `knowledge_tags` 写入 `weakpoints`，来源标记为 `homework_teacher_review`。`rejected` 只记录审核学习事件，不新增错题本薄弱点，避免 AI 误判污染学生画像。

接口响应保持兼容并额外返回：

```json
{
  "ok": true,
  "event_id": "..."
}
```

## 前端改动

### 1. 学生首页闭环入口

文件：`frontend/app/(student)/student/page.tsx`

学生首页现在同时读取：

- `/api/students/{student_id}/profile`
- `/api/students/{student_id}/review-plan`

并展示：

- 今日优先复习知识点
- 错题本重点数量
- 复习路径入口
- 错题本入口

### 2. 错题本页面串联复习路径

文件：`frontend/app/(student)/student/weakpoints/page.tsx`

页面顶部新增“查看复习路径”入口，保持每个知识点跳转学习助手复习。

### 3. 学习路径展示错题优先级

文件：`frontend/app/student/learning-path/page.tsx`

学习路径页面支持后端新增字段：

- `weakpoints`
- `priority_topics`

薄弱知识点区域优先展示错题本数据，包括出错次数、来源、进度和复习链接。

### 4. 学生学情中心接入闭环

文件：`frontend/app/student-dashboard/page.tsx`

学生学情中心现在优先使用 `review-plan` 中的 `weakpoints` 和 `priority_topics`：

- 全览页显示“优先复习”
- 薄弱点面板显示出错次数并可跳转学习助手
- 复习方案面板显示错题本优先级
- 错题本面板使用统一优先级数据

### 5. 教师班级学情页增强

文件：`frontend/app/teacher/class-analytics/page.tsx`

新增“本轮讲评重点”卡片，基于 `top_weak_topics[0]` 显示：

- 重点知识点
- 影响学生人数
- 班级占比
- 生成讲评建议按钮

薄弱点分布新增比例条，帮助教师判断讲评优先级。

### 6. 教师首页前置讲评重点

文件：`frontend/app/teacher/dashboard/page.tsx`

教师首页现在同时读取：

- `/api/teacher/students`
- `/api/teacher/class-analytics`

并在首页展示“本轮讲评重点”卡片，点击进入班级学情分析。

## 评估与测试改动

### 1. 新增学习闭环 smoke

文件：`eval/learning_closure_smoke.py`

覆盖：

- 作业类学习事件更新学生画像
- weakpoints 进入 review-plan 优先级
- learning-path 包含 weakpoints、priority_topics、milestones、progress
- teacher class analytics 能读取真实 JSON schema

已接入：

- `CORE_SUITES`
- `QUICK_SUITES`
- `SMOKE_SUITES`
- `SUITE_FILES`
- `SUITE_METADATA`

### 2. 标准化教师功能 smoke

文件：`eval/teacher_features_smoke.py`

改为标准 `OK/FAIL/metric` 输出，并使用临时 SQLite 与 LLM stub。

覆盖：

- 班级学情 API schema
- 教师资料库 API schema
- 教学建议 API schema
- 教师 `accepted` 审核决策反向写入 learning event 与 weakpoints
- 教师 `edited` 审核决策反向写入 learning event 与 weakpoints
- 教师 `rejected` 审核决策只记录 learning event，不写入 weakpoints

已接入 `eval/run_core_evals.py`。

### 3. 统一 npm test

文件：`package.json`

`npm test` 从 legacy runner 切换为：

```bash
PYTHONPATH=backend python3 eval/run_core_evals.py --smoke
```

### 4. 标记 legacy runner

文件：`eval/run_smoke_tests.py`

补充说明该文件是 legacy/simple runner，主入口为 `eval/run_core_evals.py`。

## 文档改动

文件：`SCHEMA.md`

同步更新：

- 学生学习路径 API
- 真实 `student_profiles` / `learning_events` / `memory_entries` / `weakpoints` schema
- 学习闭环 smoke
- 教师端闭环能力说明
- teacher_features_smoke 接入统一 runner
- `npm test` 指向新版 runner

## 已验证项

用户本地已执行并通过：

```bash
python3 eval/run_core_evals.py --suite learning_closure_smoke
# learning_closure_smoke 4/4

python3 eval/weakpoints_smoke.py
# weakpoints_smoke 5/5

python3 eval/homework_grading_smoke.py
# homework_grading_smoke 3/3

python3 eval/teacher_features_smoke.py
# teacher_features_smoke 3/3（旧版本执行结果；当前版本已扩展到 6 个 case，待重跑）

python3 eval/student_profile_smoke.py
# student_profile_smoke 6/6
```

其中 `student_profile_smoke.py` 运行前曾因缺少 `backend` 路径导入失败，已修复。

## 待验证项

前端验证按当前开发节奏暂缓：

```bash
npm run lint --prefix frontend
npm run build --prefix frontend
```

统一 smoke runner 后建议补跑：

```bash
npm test
python3 eval/run_core_evals.py --suite teacher_features_smoke
```

本轮已尝试在当前环境直接运行 `python3 eval/teacher_features_smoke.py`，但 Bash 安全分类器暂时不可用，未能执行；需用户本地或稍后环境恢复后重跑。

## 后续建议

1. 运行前端 lint/build，修复可能的 TypeScript/React hook 问题。
2. 重跑当前版本 `teacher_features_smoke.py` 和 `npm test`，确认新增教师审核同步 case 通过。
3. 为教师端讲评建议增加前端展示优化，例如一键复制讲评大纲。
4. 后续如需题目级错题本，再基于现有 weakpoints 增量扩展，不建议直接替换现有模型。
