# AutoTutor 退出票与学习证据闭环开发记录

**日期：** 2026-07-13  
**版本：** v1.26  
**目标：** 将 AutoTutor 从“教学步骤完成即结束”升级为“退出票检验后写入学习证据”，形成可演示、可评测、可解释的作品集主线闭环。

## 背景

当前 EduAgent 已具备 AutoTutor 自主规划、答错反思重规划、错题本、SM-2 复习、TraceTimeline、Eval 与 AgentOps。下一步不再横向扩展功能，而是补齐“AI 辅导是否真正生效”的证据链。

核心闭环：

> 薄弱点 → AutoTutor 定向辅导 → 反思重规划 → 退出票检验 → learning_events / 错题掌握度 / 复习 / memory → 教师端辅导效果证据。

## 状态机变化

原流程：

```text
plan -> act -> observe -> judge -> next_step/reflect -> finalize
```

v1.26 流程：

```text
plan -> act -> observe -> judge -> next_step/reflect -> exit_ticket -> evidence -> finalize
```

设计约束：

- 不新增 API 端点，继续复用 `POST /api/autotutor/answer`。
- `status` 保持 `awaiting_answer | completed`，新增 `phase` 区分 `lesson | exit_ticket | completed`。
- 退出票不混入 `lesson_plan`，单独保存在 `exit_ticket` / `exit_ticket_result`，避免过程题和学习证据指标混淆。

## API 契约

AutoTutor response 新增字段：

- `phase`: `lesson | exit_ticket | completed`
- `current_question.kind`: `lesson | exit_ticket`
- `exit_ticket_result`: 退出票作答结果
- `evidence`: 学习证据写入摘要

最后一个教学步骤答完后，接口返回：

```json
{
  "status": "awaiting_answer",
  "phase": "exit_ticket",
  "current_question": {
    "kind": "exit_ticket",
    "knowledge_point": "鸦片战争",
    "strategy": "课后退出票检验"
  }
}
```

退出票答完后才返回：

```json
{
  "status": "completed",
  "phase": "completed",
  "exit_ticket_result": {
    "is_correct": true,
    "mastery_signal": "exit_ticket_passed"
  },
  "evidence": {
    "exit_ticket_recorded": true,
    "learning_event_types": ["auto_tutor_step", "auto_tutor_exit_ticket"],
    "weakpoint_action": "correct_evidence_recorded",
    "tutor_effectiveness_ready": true
  }
}
```

## 数据与证据

`learning_events` 新增语义：

- `auto_tutor_step`：教学过程步骤，用于过程掌握率。
- `auto_tutor_exit_ticket`：退出票学习证据，用于辅导后通过率和教师端班级证据。

退出票结果写回：

- 通过：`record_correct_evidence(student_id, tag)`。
- 未通过：`record_weakpoint(student_id, tag, source="auto_tutor_exit_ticket")`。
- 始终写入 `review_goal` memory 和 `auto_tutor_exit_ticket` learning event。

## 前端呈现

学生端 `/student/auto-tutor`：

- 题卡识别 `current_question.kind === "exit_ticket"` 时显示“退出票检验”。
- 完成态展示学习证据卡，包括退出票结果、答案、错题/掌握度动作、教师端可见状态。
- Trace/runtime steps 对 `event_type="exit_ticket"` 使用独立视觉语义。

教师端 `/teacher/class-analytics`：

- 在“AI 辅导效果”区展示退出票数、退出票通过率、有证据学生数。
- 知识点 chip tooltip 展示过程掌握率与退出票通过率。

## Eval 覆盖

扩展：

- `eval/auto_tutor_trajectory_eval.py`
  - 退出票在 finalize 前出现。
  - 退出票作答后才 completed。
  - 写入 `auto_tutor_exit_ticket` learning event。
  - 答错退出票会强化错题本。
- `eval/tutor_effectiveness_smoke.py`
  - 学生/班级视角统计退出票数和通过率。
  - 老的 step-only 数据保持兼容。
- `eval/pilot_path_smoke.py`
  - pilot seed 后教师端有退出票学习证据。

## Demo 路线

1. 运行 `PYTHONPATH=backend python3 scripts/seed_demo_student.py`。
2. 学生登录 `demo-student / demo123`。
3. 打开 `/student/auto-tutor?focus=鸦片战争`。
4. 故意答错一次，观察 reflect / re_plan。
5. 完成教学步骤后进入退出票检验。
6. 完成退出票，查看学习证据卡。
7. 教师登录后打开 `/teacher/class-analytics`，查看退出票通过率与知识点证据。

## 验收命令

```bash
PYTHONPATH=backend python3 eval/auto_tutor_trajectory_eval.py
PYTHONPATH=backend python3 eval/tutor_effectiveness_smoke.py
PYTHONPATH=backend python3 eval/pilot_path_smoke.py
npm run test
npm run release:gate:fast
npm run lint --prefix frontend
npm run build --prefix frontend
```
