# 「随问 · 学习助手」对话优先体验优化 Spec

**日期：** 2026-08-13
**状态：** P0 / P0.5 / P1 已实现
**目标版本：** v1.28
**优先级：** P0
**适用范围：** 学生端 `/student/assistant`、复用页面 `/learning-assistant`、AutoTutor 与教材学习入口
**关联文档：** `docs/20260813-learning-assistant-free-question-spec.md`

## 1. 决策摘要

“随问”应采用**对话优先、上下文自动进入、手动上下文按需添加**的交互，而不是要求学生在提问前先选择教材和课文。

本轮核心调整：

1. 学生进入“随问”后可以直接输入问题，教材和课文不再是前置条件。
2. 移除常驻的左侧“学习上下文”栏，将教材选择收进输入框的“添加上下文”入口。
3. 从教材、AutoTutor 等能够提供明确来源上下文的业务页面进入时，由系统自动携带可信上下文，并在输入框上方以标签透明展示；学情报告等入口继续通过预填问题和学生画像衔接。
4. 普通入口未携带业务上下文时，系统继续使用当前会话、学生画像、意图识别和按需 RAG，不展示“未选择教材”的阻塞提示。
5. 右侧 Timeline、RAG Inspector、Tools、Memory 从学生主界面移出，收敛为默认折叠的“查看回答依据”；开发调试模式保留完整观察面板。
6. 保留 EduAgent 的教育闭环能力：回答反馈、追问建议、生成练习、史料来源、工具确认和返回 AutoTutor。

这不是把 EduAgent 做成通用 ChatGPT，而是借鉴其“先表达问题，再由系统组织上下文”的低门槛交互。

## 2. 背景

### 2.1 当前能力基线

项目目前已经具备：

- 持久化随问会话和最近会话恢复；
- 最多 12 条最近消息的多轮上下文；
- “它、这个、刚才、换个说法、仍没懂”等自然追问；
- AutoTutor 到随问的可信上下文交接和返回路径；
- 教材问答、史料检索、测验生成、人物推荐、时间线游戏等工具；
- “解决了 / 仍没懂”反馈闭环；
- Tool Governance、TraceTimeline、RAG Inspector 和 Memory 可观察能力；
- 会话所有权、权限、限流、审计和输入 guardrail。

当前 eval 报告为 `49/49 suites passed`，其中学习助手工具 Smoke 为 `10/10`。因此本轮不应重写学习助手 Agent 或会话模型，应在保持现有主链路稳定的前提下优化学生交互。

### 2.2 当前页面问题

现有 `/learning-assistant` 使用三栏布局：

```text
学习上下文       对话区             Agent Observability
教材选择         消息               Timeline / RAG / Tools / Memory
课文选择         输入框
示例问题
```

主要问题：

1. **上下文被表现成前置配置。** 学生容易认为“不选教材就不能问”。
2. **主任务不突出。** 页面同时强调上下文、Agent 状态和运行时观察，输入框反而不是视觉中心。
3. **产品心智冲突。** “随问”表达的是随时提问，但页面更像需要配置参数的工具控制台。
4. **学生信息过载。** Timeline、Tools 风险级别、Trace ID 等更适合开发者和演示场景，不适合作为普通学生的常驻信息。
5. **业务上下文入口不统一。** AutoTutor 已能携带上下文，但教材学习和学情报告主要通过问题文本或独立问答接口进入，学生无法统一感知“助手正在参考什么”。
6. **小屏体验冗长。** 当前三栏在窄屏变成纵向堆叠，学生需要先经过上下文区域才能到达对话输入。

### 2.3 已验证的技术事实

`POST /api/learning/assistant/chat` 中的 `grade`、`book_id`、`lesson_id` 均为可选字段。没有教材上下文时，Agent 仍可通过：

- `conversation_history`；
- `source_context`；
- 学生画像和 typed memory；
- `search_history_knowledge`；
- 普通 `chat` 回答路径；

完成回答。因此，教材/课文选择不应成为页面一级结构或发送前置条件。

## 3. 产品目标

### 3.1 核心目标

1. 学生打开“随问”后 3 秒内理解“可以直接输入问题”。
2. 未选择教材时，发送按钮仍然可用。
3. 当系统使用教材、AutoTutor 或其他来源上下文时，学生能够看见、理解并在允许时移除。
4. 保持现有多轮、工具、权限、安全、反馈和 AutoTutor 状态中立性不变。
5. 将学生主界面从“Agent 控制台”收敛为“学习对话界面”。

### 3.2 非目标

- 不重写 `backend/agents/learning_assistant.py` 的意图路由和工具编排。
- 不合并 AutoTutor 与随问的状态机。
- 不开放非学习领域的通用聊天定位。
- 不默认把普通对话写入长期 memory。
- 不在 P0 实现文件上传、图片问答或网页搜索。
- 不在 P0 实现完整会话列表、重命名和归档管理。
- 不删除 Trace、RAG、Tools、Memory 能力，只调整普通学生界面的展示层级。

## 4. 产品原则

### 4.1 先问，再补上下文

学生的首要动作是表达问题。仅当回答确实缺少必要范围时，助手才追问“你指的是哪一课/哪个知识点”。

### 4.2 自动上下文优先，手动选择兜底

系统优先从进入来源和会话状态获得上下文；“添加教材”用于学生主动限定范围，而不是必填配置。

### 4.3 上下文透明但不暴露内部实现

学生看到“八上历史 · 洋务运动”“自主辅导 · 洋务运动”等业务标签，不直接看到 `book_id`、`trace_id`、token、检索分数或内部 prompt。

### 4.4 当前问题的明确选择优先

学生本轮明确添加的教材上下文优先于历史推断。系统不能因为学生曾问过某课，就永久把后续新话题绑定到旧教材。

### 4.5 教学闭环高于通用聊天外观

界面可以借鉴 ChatGPT 的对话优先结构，但必须保留：

- 史料或教材来源；
- “解决了 / 仍没懂”；
- 分层解释与继续追问；
- 生成练习等学习动作；
- AutoTutor 返回入口；
- 高风险工具确认。

## 5. 信息架构

### 5.1 学生默认页面

桌面端：

```text
┌────────────────────────────────────────────────────────────┐
│ 随问                                      [新对话]          │
│ 有问题直接问，我会结合对话和学习进度帮助你。                │
├────────────────────────────────────────────────────────────┤
│                                                            │
│                       对话消息流                            │
│                                                            │
│  [教材 · 八上历史 · 洋务运动  ×]                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ＋  问任何学习问题……                           发送 │  │
│  └──────────────────────────────────────────────────────┘  │
│  AI 可能会出错，重要史实请结合教材与来源核对。              │
└────────────────────────────────────────────────────────────┘
```

移动端：

- 顶部仅保留“随问”和“新对话”图标；
- 消息区占满剩余高度；
- 输入框固定在安全区上方；
- “添加上下文”使用底部抽屉；
- 不先展示 hero、上下文卡或 Agent 观察面板。

### 5.2 空会话状态

新会话没有真实消息时，在对话区中央展示：

```text
今天想弄懂什么？

[解释一个知识点] [帮我复习] [给我出题]
[比较两个事件]   [我还是没懂]
```

示例按钮只负责填入或直接提交自然语言，不预设教材为必选项。

### 5.3 有消息状态

首条用户消息发送后：

- 空状态建议消失；
- 对话消息自然向下增长；
- 输入框保持在页面底部；
- 当前回答的建议动作展示在回答下方；
- 历史回答不重复展示完整运行时 Timeline。

## 6. 上下文模型

### 6.1 上下文类型

| 类型 | 来源 | 是否自动添加 | 学生能否移除 | P0 展示文案 |
| --- | --- | --- | --- | --- |
| AutoTutor 课程上下文 | `autotutor_session_id`，后端加载 | 是 | 否，可返回辅导 | `自主辅导 · {knowledge_point}` |
| 教材课文上下文 | 教材页面深链或手动选择 | 是/手动 | 是 | `{grade} · {book} · {lesson}` |
| 会话上下文 | 最近最多 12 条消息 | 是 | 通过“新对话”清空 | 不单独占用标签 |
| 学生画像 | typed memory / review plan | 是，按策略读取 | P0 不在输入框移除 | 回答依据中显示“结合近期学习情况” |
| RAG 史料 | Agent 按意图检索 | 是，单次请求 | 不适用 | 回答来源中展示史料标题 |
| 问题文本预填 | `q` / `prompt` | 是 | 可编辑 | 输入框文本，不算上下文标签 |

### 6.2 上下文优先级

按以下顺序决定当前请求的约束：

1. AutoTutor 可信来源上下文；
2. 当前输入框明确附加的教材/课文；
3. 当前会话最近消息；
4. 学生画像中与当前问题相关的 typed memory；
5. Agent 根据当前问题按需检索的史料；
6. 无足够信息时由助手追问，不静默猜测具体课文。

AutoTutor 上下文和手动教材上下文同时存在时，P0 不允许再添加教材，避免两个课程来源冲突。学生先返回辅导或开始新对话，再选择其他教材。

### 6.3 上下文生命周期

- 普通新对话：默认无显式教材上下文。
- 手动添加教材：对当前会话后续问题生效，直到移除或新建对话。
- 教材页进入：自动附加对应课文，允许移除。
- AutoTutor 进入：绑定当前辅导来源，当前随问会话内不可移除。
- “新对话”：清空短期消息和手动教材上下文，不清空学生画像、错题本或学习事件。
- 页面刷新：P0 至少恢复会话消息和 AutoTutor 来源；手动教材上下文的持久化列为 P1，详见第 12 节。

## 7. 关键交互

### 7.1 普通入口直接提问

1. 学生打开 `/student/assistant`。
2. 页面恢复最近 active 会话；没有则保持空会话 UI。
3. 输入框立即可编辑，不等待教材列表和目录请求完成。
4. 学生输入问题并发送。
5. 前端仅在真正提交时懒创建会话。
6. 后端加载会话历史，识别意图并按需调用工具。
7. 回答流式出现，完成后展示反馈和建议动作。

### 7.2 手动添加教材

1. 学生点击输入框左侧 `＋`。
2. 弹层展示：`添加教材上下文`、`不使用教材`。
3. 选择教材后再选择课文；课文确定前不改变当前上下文。
4. 确认后在输入框上方显示一个上下文标签。
5. 发送请求时复用现有 `grade`、`book_id`、`lesson_id` 字段。
6. 点击标签 `×` 仅移除显式教材约束，不清空会话消息。

约束：

- 不把教材列表和目录请求放在页面首屏阻塞链路中；
- 打开“添加上下文”后再加载教材数据；
- 加载失败时显示“教材暂时无法加载，你仍可以直接提问”；
- 只允许同时附加一个课文上下文。

### 7.3 从教材学习进入

教材页新增“在随问中继续”入口：

```text
/student/assistant
  ?book_id={book_id}
  &lesson_id={lesson_id}
  &q={optional_question}
```

进入后：

- 前端根据 `book_id`、`lesson_id` 加载可读标题；
- 输入框上方显示教材标签；
- `q` 只用于预填问题，不自动发送；
- 学生可以移除教材标签并改为开放提问。

教材页原有本课问答、摘要和自测继续保留；“在随问中继续”用于需要多轮追问、跨工具组合或离开教材页继续对话的场景，不强行替代原有轻量功能。

### 7.4 从 AutoTutor 进入

继续复用：

```text
/student/assistant?autotutor_session_id={session_id}&prompt={optional_prompt}
```

进入后：

- 后端按 `autotutor_session_id` 加载并校验可信上下文；
- 显示不可删除标签 `自主辅导 · {knowledge_point}`；
- 页面顶部或输入框附近持续显示“返回自主辅导”；
- 随问不得修改 AutoTutor 的 `revision`、`attempts`、当前题目或掌握度；
- 刷新页面不能因为同一来源重复创建无意义会话，后续实现应优先恢复同一 active handoff 会话。

### 7.5 “仍没懂”

当前行为保持：

1. 学生点击“仍没懂”。
2. 记录一次不可重复覆盖的反馈。
3. 系统自动提交更简单解释的 follow-up prompt。
4. 新回答继续继承当前会话和显式上下文。

UI 文案改为更面向学生：

- `解决了`；
- `换种方式讲`，替代页面上的“仍没懂”操作文案；
- 反馈记录后可显示“已换一种方式解释”。

事件值仍可保持 `resolved / unresolved`，避免破坏现有指标。

### 7.6 新对话

点击“新对话”后：

- 创建新的 standalone 会话；
- 清空消息、当前 intent、trace、RAG 结果、工具状态和手动教材上下文；
- 保留学生画像和长期 memory；
- 如果当前会话来自 AutoTutor，需二次轻提示：“新对话不会影响辅导进度，仍可返回自主辅导”；
- 不归档旧会话，P0 保持现有 active 会话模型兼容。

## 8. 回答展示

### 8.1 消息命名

移除偏系统化的“学习任务 / 助手回执”，改为：

- 用户消息不显示角色标题；
- 助手消息只显示助手标识和必要状态；
- intent 不作为每条回答的醒目标签，可放入“回答依据”。

### 8.2 工具结果

工具执行结果转为学生能理解的学习卡片：

| Tool | 学生展示 |
| --- | --- |
| `search_history_knowledge` | `参考史料`，展示来源和摘要 |
| `get_textbook_lesson` | `本课内容`，展示课文与知识点 |
| `generate_quiz` | 直接展示可作答练习 |
| `recommend_character` | `可以继续对话的人物` |
| `start_timeline_game` | `时间线挑战` + 进入按钮 |
| `suggest_review_plan` | `下一步复习建议` |

默认不向学生显示 tool name、risk level、required role 或原始 JSON。

### 8.3 回答依据

每条完成的助手回答可展示折叠入口：

```text
[查看回答依据]
```

展开后最多包含：

- 使用了哪一课或哪个 AutoTutor 知识点；
- 使用了多少条最近对话；
- 使用了哪些史料来源；
- 是否结合近期学习情况；
- 回答是否走了降级模式。

以下内容只在 `debug=1`、开发环境或有权限的内部角色显示：

- 完整 Timeline；
- Trace ID；
- RAG score；
- Tool Registry；
- 工具风险和权限 metadata；
- Memory 原始条目。

### 8.4 错误和降级

- 教材加载失败：`教材暂时无法加载，你仍可以直接提问。`
- 流式回答失败但已有部分文本：保留部分文本，并显示 `回答中断，重新生成`。
- 完全失败：在当前助手消息内显示重试，不把错误只放在输入框下方。
- RAG 无结果：允许基于可信课程上下文或通用解释降级，并提示 `没有找到匹配史料，以下为基础解释`。
- guardrail 拒绝：使用适合学生理解的安全提示，不显示内部 error code。

## 9. 页面状态

| 状态 | 对话区 | 输入框 | 上下文操作 |
| --- | --- | --- | --- |
| 初始化会话 | 骨架或空状态 | 可输入，发送时等待 session ready | 可用 |
| 空会话 | 示例建议 | 可发送 | 可添加教材 |
| 恢复会话 | 历史消息 | 可发送 | 恢复来源标签 |
| 生成中 | 最后一条助手消息流式增长 | 禁止重复发送，允许后续增加“停止生成” | 不可切换上下文 |
| 等待工具确认 | 回答内确认卡 | 暂停当前请求 | 不可切换上下文 |
| 失败 | 当前消息内错误与重试 | 可继续编辑 | 可用 |
| AutoTutor 来源 | 顶部显示返回入口 | 可发送 | 来源标签锁定 |

## 10. 前端实现要求

### 10.1 主要文件

- `frontend/app/learning-assistant/page.tsx`
- `frontend/app/globals.css`
- `frontend/app/(student)/student/assistant/page.tsx`（继续复用）
- `frontend/app/(student)/student/auto-tutor/page.tsx`
- `frontend/app/textbook-learning/[bookId]/[lessonId]/LessonLearningClient.tsx`

建议从大页面中拆出：

```text
frontend/app/learning-assistant/
  page.tsx
  AssistantConversation.tsx
  AssistantComposer.tsx
  ContextPicker.tsx
  ContextChip.tsx
  AnswerEvidence.tsx
  DebugInspector.tsx
```

是否拆文件不作为 P0 验收条件，但 `page.tsx` 不应继续无限累积所有 UI 状态。

### 10.2 前端状态建议

```ts
type ExplicitContext =
  | { type: "textbook_lesson"; bookId: string; lessonId: string; grade: string; bookLabel: string; lessonLabel: string }
  | { type: "auto_tutor"; sessionId: string; knowledgePoint: string; locked: true }
  | null;
```

发送请求映射：

```ts
{
  session_id,
  message,
  student_id,
  grade: explicitContext?.type === "textbook_lesson" ? explicitContext.grade : null,
  book_id: explicitContext?.type === "textbook_lesson" ? explicitContext.bookId : null,
  lesson_id: explicitContext?.type === "textbook_lesson" ? explicitContext.lessonId : null,
  stream: true
}
```

### 10.3 布局调整

将当前：

```css
grid-template-columns: 300px minmax(0, 1fr) 320px;
```

调整为对话主列，推荐最大宽度 `880px–960px`。学生默认页面不保留左右 sticky panel。

要求：

- 桌面端输入框始终在主列视觉中心；
- 移动端输入区使用 `position: sticky` 或页面 shell 的底部布局，并处理 safe-area；
- 消息区不能固定为仅 `650px` 高后在页面中形成双滚动；
- textarea 默认 1–3 行自动增长，达到上限后内部滚动；
- `Enter` 发送，`Shift+Enter` 换行；中文输入法 composing 状态不得误发送；
- 发送按钮必须有可访问名称和键盘焦点样式。

## 11. 后端与数据契约

### 11.1 P0：保持现有接口兼容

P0 复用现有接口：

- `POST /api/learning/assistant/sessions`
- `GET /api/learning/assistant/students/{student_id}/latest-session`
- `POST /api/learning/assistant/chat`
- `POST /api/learning/assistant/sessions/{session_id}/messages/{message_id}/feedback`
- `POST /api/learning/assistant/sessions/{session_id}/return-to-source`

不修改 `LearningAssistantRequest` 的必填规则；`grade`、`book_id`、`lesson_id` 继续保持 nullable。

P0 必须保证：

- 未选择教材时仍能完成 chat/history_search；
- 选择教材后 textbook_qa/quiz_generation 能收到正确 ID；
- AutoTutor 来源只信任后端通过 `source_session_id` 加载的上下文；
- query string 中的知识点或 prompt 不能替代后端可信来源；
- 新 UI 不绕过现有权限、确认、审计、trace 和 guardrail。

### 11.2 P1：显式上下文持久化

为保证刷新后恢复手动教材标签，P1 增加会话上下文更新能力，优先复用 `assistant_sessions.context_json`，不新增表：

```http
PATCH /api/learning/assistant/sessions/{session_id}/context
Content-Type: application/json

{
  "textbook": {
    "book_id": "...",
    "lesson_id": "..."
  }
}
```

移除：

```json
{ "textbook": null }
```

后端要求：

1. 校验 session 所有权；
2. 使用 `textbook_learning.loader.get_lesson()` 校验并获取可信标题；
3. 只持久化必要字段：`book_id`、`lesson_id`、`grade`、`book`、`lesson_title`；
4. 保留 AutoTutor 顶层可信上下文，不允许该接口覆盖 `knowledge_point`、`teaching`、`question`、`return_path`；
5. AutoTutor 来源会话拒绝附加第二教材上下文并返回 409；
6. 更新 `updated_at`，记录 audit 和 `assistant_context_attached/detached` learning event；
7. `GET session/latest-session` 返回更新后的 context。

建议逐步把 `context_json` 规范成：

```json
{
  "source": {
    "type": "auto_tutor",
    "knowledge_point": "洋务运动"
  },
  "textbook": {
    "book_id": "history-8-1",
    "lesson_id": "lesson-4",
    "grade": "八年级上册",
    "book": "中国历史",
    "lesson_title": "洋务运动"
  }
}
```

迁移时需兼容当前 AutoTutor context 的扁平结构，不能直接切换导致 `_source_context_text()` 失效。

## 12. 埋点与指标

### 12.1 复用现有指标

- 随问解决率；
- 随问追问率；
- 上下文解决率；
- 回答降级率；
- AutoTutor 返回率；
- 会话恢复率。

### 12.2 新增事件

| event_type | 触发时机 | metadata |
| --- | --- | --- |
| `assistant_composer_focused` | 首次聚焦输入框 | `entry_source` |
| `assistant_context_picker_opened` | 打开上下文选择 | `session_id` |
| `assistant_context_attached` | 添加教材 | `book_id`, `lesson_id`, `source` |
| `assistant_context_detached` | 移除教材 | `book_id`, `lesson_id` |
| `assistant_evidence_opened` | 展开回答依据 | `message_id`, `has_rag`, `has_memory` |
| `assistant_retry_requested` | 回答失败后重试 | `failure_stage` |

输入框 focus 属于高频 UI 事件，若 learning_events 只承载学习行为，可仅在前端产品分析通道记录，不写学习证据表。

### 12.3 上线观察目标

P0 上线后以同等流量窗口对比旧版：

- 打开页面到首次发送的中位时长下降；
- 未选择教材的首次发送占比不再异常偏低；
- 首次问题发送率提高；
- 随问解决率不下降超过 3 个百分点；
- 上下文问题解决率不下降；
- AutoTutor 返回率不下降；
- 工具调用准确率和现有 eval 保持通过。

不在没有真实基线时写死绝对转化率，先收集一周基线再设置正式门槛。

## 13. 测试与质量门

### 13.1 前端单元测试

至少覆盖：

1. 无教材上下文时发送请求，三个教材字段为 `null`；
2. 添加课文后请求携带正确 `grade/book_id/lesson_id`；
3. 移除标签后下一次请求不再携带教材字段；
4. AutoTutor context chip 锁定且不能移除；
5. `q` / `prompt` 仅预填，不自动发送；
6. Enter 发送、Shift+Enter 换行、IME composing 不误发送；
7. “换种方式讲”继续继承当前上下文；
8. 教材接口失败不禁用输入框。

### 13.2 Playwright E2E

学生路径：

```text
登录 → 打开随问 → 不选择教材 → 提问 → 收到流式回答
     → 追问“它有什么影响” → 收到带上下文回答
     → 点击“换种方式讲” → 收到更简单解释
```

教材路径：

```text
打开教材课文 → 在随问中继续 → 看见教材标签
             → 提问 → 回答使用本课工具
             → 移除标签 → 继续普通提问
```

AutoTutor 路径：

```text
开始自主辅导 → 我有疑问 → 看见锁定知识点标签
             → 提问 → 返回自主辅导
             → revision / attempts / current question 不变
```

### 13.3 后端回归

必须通过：

```bash
npm run test:assistant-multiturn
npm run test:autotutor-handoff
PYTHONPATH=backend python3 eval/learning_assistant_smoke.py
```

前端必须通过：

```bash
cd frontend
npm run lint
npm run test:unit
npm run build
```

合并前再运行与当前项目一致的快速 release gate，确保 UI 调整没有破坏主路径。

## 14. 分阶段实施

### Phase 0：对话优先 UI（P0）

- 移除左侧常驻学习上下文面板；
- 将页面收敛为单主列对话；
- 将示例问题放入空状态；
- 新增输入框 `＋` 和教材上下文选择弹层；
- 新增 context chip；
- 支持教材深链 query params；
- AutoTutor 显示锁定来源 chip 和返回入口；
- 右侧观察面板改为默认折叠的回答依据/调试入口；
- 保持现有 API 请求字段和 SSE 事件处理。

### Phase 1：稳定性与可恢复（P0.5）

- 增加输入框键盘与 IME 行为；
- 回答内重试；
- 避免同一 AutoTutor handoff 刷新时重复创建会话；
- 增加 frontend unit 与 Playwright 覆盖；
- 增加新 UI 事件。

### Phase 2：上下文与会话管理（P1，已实现）

- 显式教材上下文持久化；
- 会话列表、重命名、归档；
- 停止生成、重新生成；
- 每条回答独立“回答依据”；
- 根据真实数据决定是否增加图片/文件上下文。

## 15. 验收标准

### 15.1 必须满足

- [ ] 页面首屏不再出现常驻“教材 / 课文”选择栏。
- [ ] 未添加任何教材时，学生可以直接发送问题并获得回答。
- [ ] 输入框是桌面和移动端的主要视觉与操作焦点。
- [ ] 学生可以通过 `＋` 可选添加一个教材课文。
- [ ] 已添加上下文以可读标签展示，不显示内部 ID。
- [ ] 普通教材标签可以移除，AutoTutor 来源标签不可伪造或覆盖。
- [ ] 从 AutoTutor 返回后，辅导状态保持不变。
- [ ] 多轮追问、会话恢复、回答反馈和工具确认继续工作。
- [ ] 普通学生默认看不到完整 Tool Registry、Trace ID 和原始 Memory。
- [ ] 教材列表加载失败不会阻止普通提问。
- [ ] `q` / `prompt` 不会未经学生确认自动发送。
- [ ] 移动端不出现“上下文面板 → 对话 → 观察面板”的长页面堆叠。
- [ ] 现有学习助手和 AutoTutor smoke 全部通过。

### 15.2 明确不验收为 P0 缺陷

- 刷新后手动添加的教材标签未恢复，但会话消息仍可恢复；
- 暂无完整历史会话侧栏；
- 暂无文件、图片、语音输入；
- 默认学生界面没有完整 Agent Timeline。

## 16. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 隐藏教材选择后用户不知道可限定课文 | 教材工具使用率下降 | 空状态提示“可添加教材”，教材页提供深链 |
| 自动上下文让用户误以为系统读取所有学习记录 | 隐私和信任问题 | 回答依据只说明实际使用的来源，不宣称读取全部数据 |
| 历史话题污染新问题 | 回答指代错误 | 新对话入口突出；显式当前上下文优先；不确定时追问 |
| 调试面板隐藏后不利于项目演示 | Agent 工程能力不明显 | 保留 `debug=1` 或内部角色的完整 Inspector |
| AutoTutor 与教材上下文冲突 | 回答引用错误课程 | AutoTutor handoff 会话禁止附加第二教材 |
| P0 仅前端保存教材选择 | 刷新丢失标签 | P0 明示边界，P1 增加 session context PATCH |
| 页面组件继续膨胀 | 维护困难 | 拆分 Composer、ContextPicker、Evidence、DebugInspector |

## 17. 最终产品定义

优化后的“随问”应让学生形成以下心智：

> 我可以先把问题说出来。助手会结合当前对话和学习进度回答；如果我要限定某一课，可以随时把教材加进来。

它与 ChatGPT 的相似点是“对话优先”，与通用 ChatGPT 的不同点是“上下文可解释、能力围绕学习、回答能够回到练习和辅导闭环”。
