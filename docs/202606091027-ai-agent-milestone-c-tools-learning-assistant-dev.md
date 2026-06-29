# EduAgent AI Agent Milestone C：Tools 层与统一学习助手开发文档

## 1. 背景

EduAgent 当前已经完成多个独立教育 AI 能力：历史人物对话、教材问答、课文摘要、测验生成、时间线游戏、卡牌游戏、多人时间巨轮、作文批改和辩论原型。Milestone A/B 已补齐回归验证、Langfuse tracing、RAG 全链路增强和 structured output repair。

但系统仍然是“多个功能入口的集合”，还没有形成统一 Agent 能力：

- 现有业务能力没有统一 tools 抽象。
- 新增 Agent 时容易重复调用 service/agent 逻辑。
- 前端缺少一个统一学习助手入口来自动选择教材问答、测验生成、人物推荐、游戏等能力。
- Langfuse 里虽然能看到 request/RAG/LLM span，但缺少 tool-level 观测。

Milestone C 的目标是建立可组合 tools 层，并实现统一学习助手 MVP，让用户可以通过一个对话入口触发已有教育能力。

## 2. 当前项目状态

### 2.1 已具备能力

#### 后端能力

- `backend/textbook_learning/service.py`
  - 教材问答 streaming。
  - 课文摘要 streaming。
  - 题目生成。
- `backend/agents/history_character.py`
  - 历史人物对话。
  - RAG sources。
  - fact card。
- `backend/agents/character_recommender.py`
  - 历史人物推荐。
- `backend/agents/history_games.py`
  - timeline/card/multiplayer 游戏入口。
- `backend/agents/timeline_question_generator.py`
  - timeline LLM 生成。
- `backend/agents/card_game.py`
  - card game LLM 生成。
- `backend/structured_output.py`
  - JSON parse / repair / Pydantic validate。
- `backend/tracing.py`
  - request trace、span、generation。
- `eval/run_core_evals.py`
  - quick/core eval runner。

#### 前端能力

- `frontend/app/page.tsx`
  - 学习中心入口。
- `frontend/app/history-character/page.tsx`
  - 历史人物对话 UI。
- `frontend/app/history-games/`
  - 历史游戏入口和具体游戏页。

### 2.2 仍需补齐

- 缺 `backend/tools/` 工具层。
- 缺统一 `ToolResult`、tool input schema、tool registry。
- 缺 tool execution span。
- 缺 `backend/agents/learning_assistant.py`。
- 缺统一学习助手 API。
- 缺学习助手前端页面。
- 缺 learning assistant eval/smoke。

## 3. Milestone C 目标

### 3.1 功能目标

1. 建立 tools 层：
   - 将已有教育能力薄封装为可组合工具。
   - 每个工具有 Pydantic input schema。
   - 每个工具返回统一 `ToolResult`。
   - 工具异常转结构化错误，不向上泄露内部异常栈。

2. 实现 learning assistant MVP：
   - 支持识别用户意图。
   - 能调用工具完成教材问答、生成测验、推荐历史人物、启动时间线游戏。
   - 支持 SSE 输出 tool_start/tool_result/final/suggestions。

3. 补充 observability：
   - 每次 tool 调用记录 Langfuse span。
   - 记录 tool name、success、error_type、duration、输入输出摘要。

4. 补充验证入口：
   - 新增 learning assistant smoke eval。
   - 接入 `eval/run_core_evals.py` 或新增 npm verify 命令。

### 3.2 非目标

Milestone C 不做：

- 长期 student profile 和个性化学习画像。
- 生产级认证鉴权。
- rate limit。
- 多轮复杂 planner。
- 复杂自主 Agent loop。
- 完整前端重设计。
- 替换现有专用页面。

这些进入 Milestone D 或后续阶段。

## 4. 总体架构

### 4.1 分层设计

```text
frontend/app/learning-assistant/page.tsx
        |
        v
POST /api/learning/assistant/chat
        |
        v
backend/agents/learning_assistant.py
        |
        v
backend/tools/registry.py
        |
        +-- textbook_tools.py
        +-- quiz_tools.py
        +-- character_tools.py
        +-- game_tools.py
        +-- history_search.py
```

### 4.2 关键原则

1. tools 只薄封装已有 service/agent，不复制业务逻辑。
2. learning assistant 只做意图识别、工具选择、结果组织。
3. 第一版不做复杂多步 planner，优先可控、可验证。
4. 工具输入必须 Pydantic 校验。
5. 工具输出必须结构化。
6. 工具失败必须可降级为可理解的 assistant 回复。
7. 所有工具调用都应可观测。

## 5. 后端开发范围

## 5.1 新增 tools 基础层

### 新增文件

```text
backend/tools/__init__.py
backend/tools/base.py
backend/tools/registry.py
backend/tools/history_search.py
backend/tools/textbook_tools.py
backend/tools/quiz_tools.py
backend/tools/character_tools.py
backend/tools/game_tools.py
```

### 5.1.1 ToolResult

`backend/tools/base.py`

建议结构：

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolResult(BaseModel):
    tool_name: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 5.1.2 Base Tool 定义

```python
class ToolDefinition(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
```

也可以先不用抽象类，第一版采用函数式 registry：

```python
ToolHandler = Callable[[BaseModel], ToolResult]
```

### 5.1.3 Tool execution wrapper

新增：

```python
def run_tool(tool_name: str, payload: dict[str, Any]) -> ToolResult:
    ...
```

职责：

- 根据 registry 查找工具。
- Pydantic validate input。
- 创建 `tool.execute` span。
- 捕获异常并转换为 `ToolResult(ok=False)`。
- 返回统一结构。

Span metadata：

- `tool_name`
- `success`
- `error_type`
- `input_schema`
- `duration_ms`

## 5.2 第一批工具

### 5.2.1 search_history_knowledge

文件：`backend/tools/history_search.py`

Input：

```python
class SearchHistoryKnowledgeInput(BaseModel):
    query: str
    grade: str | None = None
    topic: str | None = None
    k: int = Field(default=4, ge=1, le=8)
```

调用：

```python
search_with_scores("history", query, k=k, mode="hybrid", metadata_hints=...)
```

Output data：

```python
{
  "sources": [
    {
      "topic": "...",
      "source": "...",
      "grade": "...",
      "unit": "...",
      "lesson": "...",
      "page": "...",
      "score": 1.23,
      "source_mode": "hybrid",
      "snippet": "..."
    }
  ]
}
```

### 5.2.2 get_textbook_lesson

文件：`backend/tools/textbook_tools.py`

Input：

```python
class GetTextbookLessonInput(BaseModel):
    book_id: str
    lesson_id: str
```

调用：

```python
get_lesson(book_id, lesson_id)
```

Output data：

```python
{
  "lesson": lesson.model_dump()
}
```

### 5.2.3 generate_quiz

文件：`backend/tools/quiz_tools.py`

Input：

```python
class GenerateQuizInput(BaseModel):
    book_id: str
    lesson_id: str
    question_types: list[str] = Field(default_factory=lambda: ["single_choice", "short_answer"])
    count: int = Field(default=3, ge=1, le=10)
    focus_item_id: str | None = None
```

调用：

```python
generate_quiz(TextbookQuizRequest(...))
```

Output data：

```python
{
  "quiz": response.model_dump()
}
```

### 5.2.4 recommend_character

文件：`backend/tools/character_tools.py`

Input：

```python
class RecommendCharacterInput(BaseModel):
    message: str
    grade: str | None = None
    limit: int = Field(default=3, ge=2, le=4)
```

调用：

```python
recommend_characters(message, grade, limit)
```

Output data：

```python
{
  "recommendations": [...]
}
```

### 5.2.5 start_timeline_game

文件：`backend/tools/game_tools.py`

Input：

```python
class StartTimelineGameInput(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None
    student_id: str | None = None
    mode: str = "llm"
```

调用：

```python
start_timeline_round(grade, difficulty, topic, student_id, mode)
```

Output data：

```python
{
  "game": round_payload
}
```

## 5.3 Tool Registry

文件：`backend/tools/registry.py`

建议结构：

```python
TOOLS = {
    "search_history_knowledge": ToolSpec(...),
    "get_textbook_lesson": ToolSpec(...),
    "generate_quiz": ToolSpec(...),
    "recommend_character": ToolSpec(...),
    "start_timeline_game": ToolSpec(...),
}
```

暴露函数：

```python
def list_tools() -> list[dict]:
    ...


def run_tool(name: str, payload: dict[str, Any]) -> ToolResult:
    ...
```

## 6. Learning Assistant MVP

### 6.1 新增文件

```text
backend/agents/learning_assistant.py
```

### 6.2 请求/响应模型

可放在 `backend/api/main.py` 或单独 schema 文件。

```python
class LearningAssistantRequest(BaseModel):
    message: str
    session_id: str | None = None
    student_id: str | None = None
    grade: str | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    stream: bool = True
```

### 6.3 意图类型

第一版支持：

```text
textbook_qa
quiz_generation
character_recommendation
timeline_game
history_search
chat
```

### 6.4 意图识别策略

第一版建议使用规则优先，LLM 兜底。

规则示例：

- 包含“出题 / 练习 / 测验 / 考考我” → `quiz_generation`
- 包含“推荐人物 / 和谁聊 / 历史人物” → `character_recommendation`
- 包含“游戏 / 时间线 / 排序 / 时间巨轮” → `timeline_game`
- 有 `book_id + lesson_id` → `textbook_qa`
- 其他历史问题 → `history_search`
- 其他 → `chat`

后续可再用 `invoke_structured(...)` 加 LLM intent classifier。

### 6.5 SSE 事件协议

API：

```text
POST /api/learning/assistant/chat
```

SSE events：

```text
intent
工具选择结果

tool_start
工具开始执行

tool_result
工具执行结果摘要

delta
助手自然语言回复流

final
最终响应

suggestions
后续建议动作

error
错误信息
```

示例：

```text
event: intent
data: {"intent":"quiz_generation","confidence":0.9}

event: tool_start
data: {"tool_name":"generate_quiz"}

event: tool_result
data: {"tool_name":"generate_quiz","ok":true}

event: final
data: {"response":"我已为你生成 3 道练习题。", "tool_results":[...]}
```

### 6.6 Assistant 输出组织

不同 intent 的 final response：

#### quiz_generation

- 简短说明已生成题目。
- 返回 quiz data。
- suggestions：
  - “再来 3 道选择题”
  - “解释第 1 题”
  - “换成简答题”

#### character_recommendation

- 简短说明推荐人物。
- 返回 recommendations。
- suggestions：
  - “开始和第一位人物对话”
  - “换一个角度推荐”
  - “只推荐教材覆盖高的人物”

#### timeline_game

- 简短说明已创建游戏。
- 返回 game round。
- suggestions：
  - “开始游戏”
  - “换难度”
  - “围绕同一专题再来一局”

#### textbook_qa / history_search

- 用 LLM 组织自然语言回答。
- 引用 sources。
- suggestions：
  - “生成练习题”
  - “总结本课”
  - “推荐相关历史人物”

## 7. API 接入

### 7.1 修改文件

```text
backend/api/main.py
```

新增：

```python
@app.post("/api/learning/assistant/chat")
async def learning_assistant_chat(req: LearningAssistantRequest):
    ...
```

### 7.2 Streaming 实现

和现有 SSE endpoint 保持一致：

- 使用 `StreamingResponse`。
- `media_type="text/event-stream"`。
- `headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}`。
- trace_context 必须包在 generator 内部。

### 7.3 Non-stream fallback

可以先不实现非流式，或者返回聚合后的 final payload。建议第一版只支持 stream，因为前端对 Agent 状态更友好。

## 8. 前端开发范围

### 8.1 新增页面

```text
frontend/app/learning-assistant/page.tsx
```

### 8.2 UI MVP

布局：

- 顶部：学习助手标题与说明。
- 左侧/主体：对话流。
- 底部：输入框。
- 右侧或消息卡片：tool result cards。

消息类型：

- user message。
- assistant streaming message。
- intent badge。
- tool running card。
- quiz result card。
- character recommendation card。
- game launch card。
- source list。

### 8.3 前端 SSE 状态机

状态：

```typescript
type AssistantEvent =
  | { type: "intent"; data: IntentPayload }
  | { type: "tool_start"; data: ToolStartPayload }
  | { type: "tool_result"; data: ToolResultPayload }
  | { type: "delta"; data: { text: string } }
  | { type: "final"; data: FinalPayload }
  | { type: "suggestions"; data: SuggestionsPayload }
  | { type: "error"; data: { message: string } };
```

### 8.4 导航入口

修改：

```text
frontend/app/page.tsx
```

新增学习助手卡片入口：

```text
统一学习助手
```

## 9. Eval 与验证

### 9.1 新增 smoke eval

新增：

```text
eval/learning_assistant_smoke.py
```

覆盖 case：

1. “帮我出 3 道本课练习题” → intent = quiz_generation。
2. “我想了解秦始皇，推荐一个历史人物” → intent = character_recommendation。
3. “来一局中国近代史时间线游戏” → intent = timeline_game。
4. “鸦片战争为什么重要？” → intent = history_search 或 textbook_qa。

验证：

- intent 非空。
- 至少一个 tool_result ok。
- final response 非空。
- 没有未捕获异常。

### 9.2 Eval runner 接入

修改：

```text
eval/run_core_evals.py
```

建议加入 quick 或 core：

- quick：可暂不加入，避免 LLM 成本上升。
- core：加入 `learning_assistant_smoke`。

也可以新增：

```bash
npm run verify:milestone-c
npm run verify:milestone-c:syntax
```

### 9.3 验证命令

语法检查：

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m py_compile \
  backend/tools/base.py \
  backend/tools/registry.py \
  backend/tools/history_search.py \
  backend/tools/textbook_tools.py \
  backend/tools/quiz_tools.py \
  backend/tools/character_tools.py \
  backend/tools/game_tools.py \
  backend/agents/learning_assistant.py \
  backend/api/main.py \
  eval/learning_assistant_smoke.py
```

后端 smoke：

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 eval/learning_assistant_smoke.py
```

前端检查：

```bash
npm run lint --prefix frontend
npm run build --prefix frontend
```

完整回归：

```bash
npm run verify:milestone-b
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 eval/run_core_evals.py
```

UI 手测：

```bash
npm run dev
```

访问：

```text
http://localhost:3000/learning-assistant
```

测试：

- 教材问答。
- 生成测验。
- 推荐人物。
- 启动时间线游戏。
- 普通历史问答。

## 10. 风险与控制

### 10.1 工具层重复业务逻辑

风险：tools 复制 service/agent 逻辑，导致后续维护分叉。

控制：tools 只做输入校验、调用现有函数、统一输出。

### 10.2 Assistant 误选工具

风险：规则意图识别误判。

控制：第一版优先高置信关键词；低置信时走 history_search/chat，并在 suggestions 提供可选动作。

### 10.3 工具输出过大

风险：quiz/game/source payload 过大影响 SSE 和 Langfuse。

控制：tool_result SSE 先发摘要，final 中返回必要结构；source snippet 截断。

### 10.4 LLM 成本上升

风险：assistant 每次请求多次调用 LLM。

控制：第一版规则 intent，只有 history_search/textbook_qa 需要总结型 LLM；工具优先复用已有逻辑。

### 10.5 前端状态复杂

风险：SSE event 多，UI 状态不稳定。

控制：先做单轮对话 MVP，不做复杂多轮 planner；每次请求独立处理。

## 11. 推荐实施顺序

1. 新增 `backend/tools/base.py` 和 `registry.py`。
2. 实现第一批 tools：
   - `search_history_knowledge`
   - `get_textbook_lesson`
   - `generate_quiz`
   - `recommend_character`
   - `start_timeline_game`
3. 给 `run_tool(...)` 加 tracing span。
4. 新增 `backend/agents/learning_assistant.py`：
   - intent 识别。
   - tool 选择。
   - SSE event generator。
   - final/suggestions 组织。
5. 在 `backend/api/main.py` 新增 `/api/learning/assistant/chat`。
6. 新增 `eval/learning_assistant_smoke.py`。
7. 新增 `scripts/verify_milestone_c.py` 和 npm verify 命令。
8. 新增 `frontend/app/learning-assistant/page.tsx`。
9. 在首页增加入口。
10. 运行语法、smoke、quick/core eval、前端 build/lint。
11. 启动 dev server 手测 UI。

## 12. 交付标准

Milestone C 完成后应满足：

- `backend/tools/` 下存在稳定 tools 层。
- `run_tool(...)` 能统一执行工具并返回 `ToolResult`。
- 每个 tool 有 Pydantic input schema。
- 工具失败不会导致未捕获异常泄露到 API。
- `/api/learning/assistant/chat` 可通过 SSE 返回：
  - `intent`
  - `tool_start`
  - `tool_result`
  - `delta` 或 `final`
  - `suggestions`
  - `error`
- learning assistant 至少支持：
  - 教材/历史问答。
  - 生成测验。
  - 推荐历史人物。
  - 启动时间线游戏。
- `eval/learning_assistant_smoke.py` 通过。
- 现有 `npm run verify:milestone-b` 仍通过。
- 前端 learning assistant 页面可手测主要路径。
- Langfuse 中可观察到 request trace 下的 tool span、RAG span、LLM generation。
