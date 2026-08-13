# 「随问 · 学习助手」与 AutoTutor 协同 Spec

**日期：** 2026-08-13
**状态：** P0 已实现 / P1 增强项保留
**目标版本：** v1.27
**适用范围：** EduAgent 学生端自由提问、多轮学习助手、AutoTutor 课中提问协同

## 1. 背景与问题

EduAgent 当前有两个容易被学生混淆的入口：

- `AutoTutor 自主辅导`：读取学生画像和错题本，自主规划课程，执行讲解、检验、反思、重教、退出票和学习证据写回。
- `统一学习助手`：接收自然语言任务，识别意图并调用史料检索、教材读取、测验生成、人物推荐、时间线游戏等工具。

AutoTutor 已形成明确的系统主导教学闭环，但不适合承载不受限的自由聊天。学习助手具备自由文本 UI，却仍是单轮任务路由器：前端没有稳定提交 `session_id`，后端没有加载历史消息，`chat` 意图只返回能力说明，不能可靠处理“它有什么影响”“换个说法”“我还是没懂”等自然追问。

本轮目标不是合并两个 Agent，而是建立清晰分工，并让学生始终有一个可以随时提问的入口。

## 2. 产品决策

### 2.1 一句话定位

- **AutoTutor：** 系统带着学生完成一节课。
- **随问 · 学习助手：** 学生随时提出学习问题，系统结合当前上下文回答或调用工具。

### 2.2 产品关系

```text
不知道该学什么
      ↓
AutoTutor 读取学情并组织课程
      ↓
Teach → Check → Diagnose → Re-teach
      ↓ 课中产生疑问
随问 · 学习助手（携带当前课程上下文）
      ↓ 回答完成
返回 AutoTutor，继续当前题目
      ↓
Exit Ticket → Evidence → Review
```

### 2.3 核心原则

1. 自由提问只有一个实现：`随问 · 学习助手`。
2. AutoTutor 不内建第二套聊天状态和消息存储。
3. 随问不修改 AutoTutor 的 `revision`、`attempts`、步骤状态或掌握度。
4. 从 AutoTutor 发起的提问必须携带最小必要课程上下文，但不能包含正确答案。
5. 多轮短期对话与长期学生记忆分离；普通聊天内容不自动写入长期 memory。

## 3. 当前实现基线

| 能力 | 当前实现 | 本 Spec 处理方式 |
| --- | --- | --- |
| AutoTutor 状态机 | `backend/agents/auto_tutor.py` | 保持课程主状态机不变 |
| AutoTutor API | `/api/autotutor/start`、`/answer`、`/session/*` | 不新增自由聊天逻辑 |
| 学习助手编排 | `backend/agents/learning_assistant.py` | 增加多轮上下文和真实 chat 回答 |
| 学习助手 API | `POST /api/learning/assistant/chat` | 扩展请求/响应契约 |
| 学习助手页面 | `frontend/app/learning-assistant/page.tsx`，学生路由复用该页面 | 改为“随问 · 学习助手”主入口 |
| 工具治理 | `tools.registry.run_tool()` | 继续复用权限、确认、审计、trace |
| 学习事件 | `learning_events` | 记录提问与完成事件，不等同于掌握证据 |
| 长期记忆 | `memory_entries` / `user_memory.py` | 只在显式或高置信条件下写入 |
| 数据库 | SQLite / PostgreSQL + Alembic | 新表加入 `db/schema.py` 和 Alembic migration |
| Eval | `eval/run_core_evals.py` | 新增多轮与 AutoTutor 协同质量门 |

## 4. 用户故事

### 4.1 全局自由提问

作为学生，我可以从一级导航打开“随问”，输入任意学习相关问题，例如：

- “鸦片战争为什么爆发？”
- “这和洋务运动有什么关系？”
- “刚才那段我没懂，换个简单例子。”
- “根据这课给我出两道题。”

系统应结合当前会话历史、教材选择和学生年级回答。

### 4.2 AutoTutor 课中提问

作为正在接受 AutoTutor 辅导的学生，我可以点击“我有疑问”，提出：

- “为什么会产生这个影响？”
- “换个例子。”
- “这个概念和上一课有什么区别？”

随问应知道当前知识点和当前讲解；回答后回到原题，课程进度不发生变化。

### 4.3 恢复会话

作为学生，我重新打开随问页面后，可以继续最近一段未归档对话，而不需要重新解释上下文。

### 4.4 新建话题

作为学生，我可以点击“新对话”，清空短期对话上下文；这不会删除长期学习画像、错题本或历史学习事件。

## 5. 功能边界

### 5.1 P0 / MVP

1. 学习助手持久化会话与消息。
2. 前端生成并持续提交 `session_id`。
3. 后端加载最近多轮对话，支持代词和自然追问。
4. `chat` 意图生成真实回答，不再返回固定能力介绍。
5. 页面更名为“随问 · 学习助手”，导航提升为一级入口。
6. AutoTutor 增加“我有疑问”入口，跳转到随问并携带当前课程上下文。
7. 提问不会推进或修改 AutoTutor 状态。
8. 增加权限、上下文隔离、多轮追问和课程不变性测试。

### 5.2 P1

1. AutoTutor 页面内使用抽屉展示随问，而不是整页跳转。
2. 会话列表、重命名、归档。
3. 回答中展示所使用的课程上下文与史料来源。
4. 学生可以对回答选择“解决了 / 仍没懂”。
5. “仍没懂”可生成更简单解释，但不直接改变 AutoTutor 掌握度。

### 5.3 非目标

- 不将 AutoTutor 改成开放式聊天 Agent。
- 不允许随问直接判定知识点已掌握或完成退出票。
- 不在 MVP 支持所有学科；范围保持项目当前的历史学习、教材和学习任务能力。
- 不默认把每一句对话写入长期 memory。
- 不在本轮重做现有 Tool Registry、RAG 或 TraceTimeline。

## 6. 信息架构与命名

### 6.1 导航

桌面端学生一级导航建议：

```text
今日学习
随问
自主辅导
复习
作业
学习资源
历史探索
```

移动端底栏建议：

```text
首页 | 随问 | 辅导 | 复习 | 更多
```

“作业”移动入口移入“更多”，未完成作业数量继续通过 badge 提示。

### 6.2 页面文案

- 页面标题：`随问 · 学习助手`
- 页面说明：`有问题就问。可以追问刚才的内容，也可以让我查史料、解释教材、生成练习或规划下一步。`
- 输入框 placeholder：`问任何学习问题，例如：刚才为什么说辛亥革命没有改变社会性质？`
- 主按钮：`发送`
- 新会话按钮：`新对话`

## 7. 交互设计

### 7.1 独立进入随问

1. 页面加载最近未归档会话；不存在则在前端创建临时会话标识。
2. 学生输入问题。
3. 后端校验会话所有权，写入用户消息。
4. 加载最近上下文，完成意图识别和工具调用。
5. 流式返回回答、工具结果、来源和建议。
6. 写入助手消息与 learning event。

### 7.2 从 AutoTutor 进入

AutoTutor 讲解卡增加操作：

```text
[我有疑问] [换个例子] [讲简单一点]
```

MVP 使用路由跳转：

```text
/student/assistant?source=autotutor
  &autotutor_session_id=at_xxx
  &knowledge_point=洋务运动
  &prompt=为什么要提出自强和求富？
```

实现要求：

- `knowledge_point` 和 `prompt` 只是 UI 预填信息。
- 后端必须通过 `autotutor_session_id` 加载会话并校验所有权。
- 后端从 AutoTutor 会话构建可信上下文，不能信任客户端传入的讲解文本。
- 上下文只包含当前知识点、难度、教学策略、教学讲解和题干；不得包含 `answer`、`correct_answer` 或未公开的内部字段。
- 随问完成后显示 `返回自主辅导`。

### 7.3 提问期间的 AutoTutor 状态

进入和使用随问期间：

- `AutoTutorState.revision` 不变。
- 当前 `attempts` 不变。
- 当前 question 不变。
- 不生成 `judge`、`reflect`、`re_plan` 或 `exit_ticket` 事件。
- 可以生成独立的 `learning_assistant` trace 和 `autotutor_question_asked` learning event。

## 8. 数据模型

新增两张表，必须同时更新 `backend/db/schema.py` 和 Alembic migration。

### 8.1 `assistant_sessions`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `session_id` | TEXT | PK | `la_<uuid>` |
| `student_id` | TEXT | NOT NULL | 会话所有者 |
| `title` | TEXT | NULL | 默认取首条问题摘要 |
| `status` | TEXT | NOT NULL | `active / archived` |
| `source_feature` | TEXT | NOT NULL | `standalone / auto_tutor / textbook` |
| `source_session_id` | TEXT | NULL | AutoTutor 或其他来源 session |
| `context_json` | TEXT | NOT NULL | 最小可信来源上下文 |
| `created_at` | TEXT | NOT NULL | ISO 时间 |
| `updated_at` | TEXT | NOT NULL | ISO 时间 |

索引：

- `idx_assistant_sessions_student_updated(student_id, updated_at)`
- `idx_assistant_sessions_source(source_feature, source_session_id)`

### 8.2 `assistant_messages`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `message_id` | TEXT | PK | 消息 ID |
| `session_id` | TEXT | NOT NULL | 所属会话 |
| `role` | TEXT | NOT NULL | `user / assistant / system_context` |
| `content` | TEXT | NOT NULL | 消息正文 |
| `intent` | TEXT | NULL | 本轮识别意图 |
| `trace_id` | TEXT | NULL | Agent trace |
| `tool_results_json` | TEXT | NOT NULL | 工具摘要，不保存敏感参数 |
| `metadata_json` | TEXT | NOT NULL | 来源、模型、反馈等元数据 |
| `created_at` | TEXT | NOT NULL | ISO 时间 |

索引：

- `idx_assistant_messages_session_created(session_id, created_at)`

### 8.3 保留策略

- MVP 每个请求只加载最近 12 条消息，避免上下文无限增长。
- 单条消息最大 2,000 字；API 当前 `message` 的 500 字限制可先保持。
- 会话归档不删除消息。
- 真正删除会话属于后续高风险操作，需要确认和 audit。

## 9. API 契约

### 9.1 创建会话

`POST /api/learning/assistant/sessions`

请求：

```json
{
  "student_id": "student-001",
  "source_feature": "auto_tutor",
  "source_session_id": "at_abc123"
}
```

响应：

```json
{
  "session_id": "la_def456",
  "student_id": "student-001",
  "status": "active",
  "source_feature": "auto_tutor",
  "source_session_id": "at_abc123",
  "context": {
    "knowledge_point": "洋务运动",
    "difficulty": "easy",
    "return_path": "/student/auto-tutor"
  }
}
```

权限要求：

- 必须对 `student_id` 执行 `assert_student_access()`。
- `source_feature=auto_tutor` 时必须加载来源会话，并再次按来源会话中的 `student_id` 校验。

### 9.2 发送消息

继续使用 `POST /api/learning/assistant/chat`，扩展请求：

```json
{
  "session_id": "la_def456",
  "message": "为什么要提出自强和求富？",
  "student_id": "student-001",
  "grade": "八年级上册",
  "stream": true
}
```

行为：

1. 根据 `session_id` 加载会话。
2. 使用数据库中的 `student_id` 校验所有权，不能信任请求体中的学生 ID。
3. 写入用户消息。
4. 加载最近 12 条消息与可信来源上下文。
5. 意图识别、工具调用和回答生成。
6. 写入助手消息。
7. SSE `final` 返回同一个 `session_id`。

`final` 事件新增：

```json
{
  "session_id": "la_def456",
  "response": "……",
  "intent": "history_search",
  "tool_results": [],
  "context_usage": {
    "history_messages": 4,
    "source_feature": "auto_tutor",
    "source_session_id": "at_abc123"
  },
  "trace_id": "trace_xxx"
}
```

### 9.3 查询最近会话

`GET /api/learning/assistant/students/{student_id}/latest-session`

- 返回最近一个 `active` 会话及最近消息。
- 必须执行学生访问校验。
- 没有会话时返回 404，前端进入空状态。

### 9.4 查询指定会话

`GET /api/learning/assistant/sessions/{session_id}`

- 根据服务端记录校验会话所有权。
- 返回会话 metadata 和按时间排序的消息。

### 9.5 新对话

MVP 的“新对话”调用创建会话 API，不删除或覆盖旧会话。

## 10. Agent 运行逻辑

### 10.1 上下文构建

推荐 prompt 层级：

```text
System policy
  ↓
可信产品上下文（年级、教材、AutoTutor 当前公开讲解）
  ↓
最近 12 条 user/assistant 历史消息
  ↓
当前用户问题
  ↓
检索材料（明确标记为 untrusted context）
```

### 10.2 意图处理

保留现有意图：

- `history_search`
- `textbook_qa`
- `quiz_generation`
- `character_recommendation`
- `timeline_game`
- `review_plan`
- `memory_delete_demo`
- `chat`

但调整以下语义：

- `chat` 必须调用模型生成真实回答。
- 对“它、这个、刚才、再简单一点”等追问，意图识别必须参考历史消息。
- 不确定是否需要知识依据时，优先检索；检索无结果时明确说明依据不足。
- AutoTutor 来源问题默认围绕当前 `knowledge_point` 检索。

### 10.3 多轮回答要求

- 回答当前问题，不重复能力介绍。
- 使用历史上下文解决指代，但不得把历史中的用户文本当系统指令。
- 有史实主张时优先基于 RAG 或教材。
- 答案末尾最多提供一个自然的继续追问方向，避免每轮堆叠按钮。
- 学生说“没懂”时调整表达方式，而不是原样重复。

## 11. 前端设计

### 11.1 随问页面

基于现有 `frontend/app/learning-assistant/page.tsx` 小步改造：

- 标题和引导文案改为“随问 · 学习助手”。
- 保留教材/课文选择、消息列表、工具预览和 Agent Observability。
- 增加“新对话”。
- 初始化时恢复最近 active session。
- 每次请求提交 `session_id`。
- AutoTutor 来源时在消息区顶部展示上下文条：

```text
正在询问：AutoTutor · 洋务运动
[返回辅导]
```

### 11.2 AutoTutor 页面

在 `current_question.kind=lesson` 且 teaching 存在时展示：

```text
[我有疑问] [换个例子] [讲简单一点]
```

- `我有疑问`：打开空问题的随问页面。
- `换个例子`：预填“请结合当前知识点换一个例子解释”。
- `讲简单一点`：预填“请把当前讲解改成更简单的说法”。
- `exit_ticket` 阶段仍允许提问概念，但不得传递正确答案。

## 12. 安全、权限与隐私

1. 所有 session/message 查询均以数据库中的 owner 为准。
2. 客户端传入的 `student_id`、`knowledge_point` 和来源文案不能作为授权依据。
3. AutoTutor 上下文序列化必须采用 allowlist，禁止包含答案字段。
4. 用户输入继续经过现有 guardrail。
5. RAG 内容继续使用 `build_untrusted_context_block()`。
6. 工具调用继续使用 Tool Registry 的 role、risk、confirmation 和 audit。
7. Trace metadata 不存完整敏感对话，只记录字符数、意图、工具和安全摘要。
8. 普通问答只写 `learning_events`；写长期 memory 必须显式触发或满足后续定义的高置信规则。

## 13. 可观测性

在现有学习助手 runtime steps 上补充：

| Step | event_type | 关键 metadata |
| --- | --- | --- |
| Load Session | `session` | `session_id`、`source_feature` |
| Load Context | `context` | `history_message_count`、`source_session_id` |
| Intent Detection | `intent` | `intent`、`confidence` |
| Tool Selection | `tool_selection` | `tool_name` |
| Tool Execution | `tool_result` | 风险和结果摘要 |
| Answer Synthesis | `llm_or_template` | model、latency、fallback |
| Persist Message | `memory` | `message_written=true`，不表示长期记忆 |

AgentOps 新增建议指标：

- `assistant_session_resume_rate`
- `assistant_followup_rate`
- `assistant_context_resolution_rate`
- `assistant_answer_fallback_rate`
- `autotutor_question_return_rate`

## 14. Learning Event 语义

新增或规范事件：

| feature | event_type | 含义 |
| --- | --- | --- |
| `learning_assistant` | `question_asked` | 学生提出问题 |
| `learning_assistant` | `answer_completed` | 回答完成 |
| `learning_assistant` | `followup_asked` | 同一会话中的追问 |
| `learning_assistant` | `answer_feedback` | 解决了 / 仍没懂（P1） |
| `auto_tutor` | `autotutor_question_asked` | 从课程跳转随问 |

这些事件不能直接计为 `mastered`。只有 AutoTutor 判题、退出票或现有掌握度规则可以改变掌握证据。

## 15. Eval 与测试

### 15.1 新增 `learning_assistant_multiturn_smoke.py`

至少覆盖：

1. 第一轮问“鸦片战争为什么爆发”，第二轮问“它有什么影响”，能解析指代。
2. “再简单一点”生成不同表达，不返回能力介绍。
3. 不同学生不能读取或继续对方 session。
4. 新对话不继承旧会话短期上下文。
5. 服务重启后能恢复最近 active session。
6. 最近消息窗口有明确上限。

### 15.2 新增 `autotutor_question_handoff_smoke.py`

至少覆盖：

1. 从 AutoTutor 创建随问会话时带入当前知识点。
2. 上下文中不包含正确答案。
3. 提问前后 AutoTutor `revision`、`attempts`、phase 和 question 保持不变。
4. 其他学生不能通过来源 session 创建或访问随问。
5. 回答后能够返回原 AutoTutor session。

### 15.3 扩展 `learning_assistant_smoke.py`

- `chat` 意图必须返回真实回答。
- 追问场景能加载历史上下文。
- 原有工具意图、确认和 guardrail 不回退。

### 15.4 Eval 注册

新 suite 接入：

- `eval/run_core_evals.py` 的 `CORE_SUITES`
- `QUICK_SUITES`
- `SUITE_FILES`
- `SUITE_METADATA`
- `package.json` 中增加单独执行命令

## 16. 验收标准

### 16.1 产品验收

- 学生在一级导航和移动底栏能直接找到“随问”。
- 学生可连续进行至少 3 轮自然追问。
- “它、这个、刚才”等指代在标准测试集上可正确解析。
- 未命中特定工具意图的问题仍会得到实际回答。
- 从 AutoTutor 发起提问后，可以返回同一课程继续作答。
- 随问期间 AutoTutor 状态完全不变。

### 16.2 工程验收

- 会话和消息在 SQLite、PostgreSQL 均可持久化。
- 数据模型进入 Alembic migration，不只依靠运行时 `CREATE TABLE`。
- 所有会话 API 都有 owner 校验。
- AutoTutor 上下文不泄露答案。
- 新增 trace step、learning event 和 eval suite。
- 现有 AutoTutor trajectory、teaching quality、session recovery 和学习助手工具测试继续通过。

### 16.3 质量门

```bash
PYTHONPATH=backend python3 eval/learning_assistant_multiturn_smoke.py
PYTHONPATH=backend python3 eval/autotutor_question_handoff_smoke.py
PYTHONPATH=backend python3 eval/learning_assistant_smoke.py
PYTHONPATH=backend python3 eval/auto_tutor_trajectory_eval.py
PYTHONPATH=backend python3 eval/autotutor_teaching_quality_eval.py
PYTHONPATH=backend python3 eval/run_core_evals.py --quick --no-report
npm run lint --prefix frontend
npm run build --prefix frontend
```

## 17. 分阶段实施

### Phase 1：持久化多轮随问

- 新增 session/message service、schema 和 migration。
- 扩展 chat API。
- 实现真实 `chat` 回答和历史上下文加载。
- 前端生成、恢复并提交 session。
- 完成多轮 smoke。

### Phase 2：产品入口与命名

- 页面改名为“随问 · 学习助手”。
- 提升桌面和移动导航入口。
- 增加新对话与上下文提示。

### Phase 3：AutoTutor 协同

- AutoTutor 增加三个提问操作。
- 服务端安全构建课程上下文。
- 增加返回课程入口。
- 完成 handoff smoke。

### Phase 4：效果证据

- 增加“解决了 / 仍没懂”。
- 聚合随问追问率、上下文解析率和 AutoTutor 返回率。
- 在 Eval Dashboard / AgentOps 展示指标。

## 18. 代码改动清单

预计新增：

- `backend/services/learning_assistant_session_service.py`
- `backend/alembic/versions/005_learning_assistant_sessions.py`
- `eval/learning_assistant_multiturn_smoke.py`
- `eval/autotutor_question_handoff_smoke.py`

预计修改：

- `backend/db/schema.py`
- `backend/agents/learning_assistant.py`
- `backend/api/routers/learning.py`
- `backend/agents/auto_tutor.py`（只增加公开上下文 helper，不增加聊天状态）
- `frontend/app/learning-assistant/page.tsx`
- `frontend/app/(student)/student/auto-tutor/page.tsx`
- `frontend/app/components/AppSidebar.tsx`
- `eval/learning_assistant_smoke.py`
- `eval/run_core_evals.py`
- `package.json`
- `README.md`

## 19. 最终验收红线

以下任一项未满足，功能不得标记完成：

1. `chat` 意图仍返回固定能力介绍而不回答问题。
2. 前端仍不提交和恢复 `session_id`。
3. 不同学生可以访问同一个随问 session。
4. AutoTutor 来源上下文包含正确答案。
5. 随问导致 AutoTutor attempts、revision 或课程阶段变化。
6. 多轮和 handoff 测试没有进入 QUICK eval。

## 20. 实施结果（2026-08-13）

目标版本 P0 已完成：

- 新增 `assistant_sessions` / `assistant_messages`、SQLAlchemy schema 和 Alembic `005` migration。
- 学习助手支持会话创建、最近会话恢复、指定会话读取和最近 12 条消息上下文。
- `chat` 意图改为真实回答；历史追问会结合最近消息和 AutoTutor 可信上下文。
- 页面与导航更名为“随问 · 学习助手”，支持新对话、会话恢复和一级/移动入口。
- AutoTutor 增加“我有疑问 / 换个例子 / 讲简单一点”，并通过服务端 allowlist handoff。
- 随问不改变 AutoTutor revision、attempts、phase 或 current question。
- 新增多轮、owner 隔离、恢复、handoff、答案防泄露与状态不变性测试，并接入 QUICK / CORE。
- 增加 `question_asked`、`followup_asked`、`answer_completed`、`autotutor_question_asked` learning events。

P1 中的页面内抽屉、会话列表管理和回答反馈属于后续增强项，不属于 v1.27 P0 完成红线。
