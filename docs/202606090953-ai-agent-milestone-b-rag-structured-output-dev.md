# EduAgent AI Agent Milestone B：RAG 全链路与结构化稳定性开发文档

## 1. 背景

项目已完成 Milestone A 的主要实现：统一 eval runner、Langfuse request trace、RAG span、structured output span。当前系统已经具备基础回归与观测闭环，但原路线图中 Phase 1 和 Phase 4 的关键能力仍未完全落到业务链路中。

Milestone B 的目标是补齐两类能力：

1. 将已增强的 hybrid RAG、metadata hints、scored sources 更完整地接入历史人物对话、人物推荐和历史游戏生成链路。
2. 在现有 structured output 观测基础上，引入一次性 JSON repair 和 Pydantic 校验封装，提升 LLM JSON 输出稳定性，同时保持原有 fallback 行为。

## 2. 当前项目状态

### 2.1 已具备能力

- `backend/rag/knowledge_base.py` 已支持：
  - vector / keyword / hybrid search。
  - `metadata_filter`。
  - `metadata_hints`。
  - `search_with_scores(...)` 返回 score 和 source_mode。
  - `rag.search` Langfuse span。
- `backend/structured_output.py` 已支持：
  - JSON code fence 清理。
  - 从混合文本中提取 object/list。
  - object/list parse。
  - Pydantic model validation。
  - fallback 返回。
  - structured output tracing span。
- `eval/run_core_evals.py` 已支持统一运行核心 eval。

### 2.2 仍需补齐

- 历史人物对话仍未充分利用 grade、topic/entity hints、score/source_mode。
- 人物推荐仍需接入更强 RAG 召回，而不是只依赖有限规则或简单检索。
- 游戏生成可继续接入 RAG 上下文，但必须保证后端可信事件 ID/year 不被 LLM 改写。
- structured output 目前只观测失败，不会尝试 repair。
- 业务模块中仍有一些 JSON 解析逻辑可逐步统一到 structured output 工具层。

## 3. Milestone B 目标

### 3.1 功能目标

1. 历史人物对话 RAG 增强：
   - 根据 grade、character、message 构造 metadata hints。
   - 使用 hybrid retrieval。
   - 将 scored sources 暴露给 answer generation / SSE sources。
   - 保留 fallback 全库检索。

2. 历史人物推荐 RAG 增强：
   - 使用 hybrid retrieval 查找相关人物、事件、主题。
   - recommendation reason 中体现教材/史料匹配依据。
   - 保留现有 rule/fallback recommender。

3. 历史游戏生成 RAG 增强：
   - timeline/card/multiplayer 生成时引入 RAG context。
   - RAG context 只作为背景材料，不允许覆盖后端选定的事件 ID、年份、顺序答案。
   - 输出 source metadata，方便后续 UI 或 eval 追踪。

4. structured output repair：
   - 新增统一 `invoke_structured(...)`。
   - 支持 Pydantic schema 校验。
   - 首次解析失败后最多调用一次 repair LLM。
   - repair 只修 JSON 格式，不改变可信事实。
   - repair 失败后保持原有 fallback 或抛错行为。

### 3.2 非目标

本阶段不做：

- 完整 tools 层和 learning assistant。
- student profile 长期记忆。
- 权限认证、rate limit、生产安全网关。
- 大规模前端 UI 改版。
- 替换现有 RAG vector index 构建流程。

这些内容进入 Milestone C/D。

## 4. 开发范围

## 4.1 历史人物对话 RAG 增强

### 涉及文件

- `backend/api/main.py`
- `backend/agents/history_character.py`
- `backend/rag/knowledge_base.py`
- `eval/history_character_eval.py`
- `eval/history_character_smoke.py`

### 实现设计

#### 4.1.1 Character state 增加上下文

在 `build_character_state(req)` 中补充：

- `grade`
- `session_id`
- `retrieval_query`
- 可选 `metadata_hints`

建议 state 结构增加：

```python
{
    "character": req.character,
    "grade": req.grade,
    "messages": messages,
    "retrieved_facts": [],
    "retrieved_sources": [],
    "response_draft": "",
    "verified": False,
    "mode": mode,
}
```

#### 4.1.2 构造历史人物检索 hints

在 `history_character.py` 中增加内部 helper：

```python
def build_character_metadata_hints(state: CharacterState) -> MetadataHints:
    ...
```

建议 hints：

- `topic`: character / message 中识别出的主题。
- `entities`: character。
- `grade`: req.grade。
- `lesson`: message 中的教材章节关键词。

注意：`metadata_hints` 只参与 keyword/rerank 加权，不作为硬过滤，避免因为年级或 metadata 不完整导致无结果。

#### 4.1.3 使用 search_with_scores

现有 retriever 可继续保留，但人物对话节点建议直接使用：

```python
search_with_scores(
    "history",
    query,
    k=5,
    mode="hybrid",
    metadata_hints=hints,
    fetch_k=30,
)
```

如果没有结果，再 fallback：

```python
search_with_scores("history", query, k=5, mode="hybrid", fetch_k=30)
```

#### 4.1.4 sources 输出增加观测字段

`retrieved_sources` 建议增加：

- `topic`
- `source`
- `grade`
- `unit`
- `lesson`
- `page`
- `type`
- `score`
- `source_mode`
- `snippet`

`snippet` 需要截断，避免 SSE payload 过大。

#### 4.1.5 Prompt 约束

生成 prompt 中增加：

- RAG 材料为参考资料，不可编造超出材料和常识的具体事实。
- 如果材料不足，应明确说明“史料中没有直接依据”。
- 反事实模式仍需区分史实与假设。

## 4.2 人物推荐 RAG 增强

### 涉及文件

- `backend/agents/character_recommender.py`
- `backend/api/main.py`
- `eval/history_character_eval.py` 或新增 recommendation eval dataset

### 实现设计

#### 4.2.1 检索入口

在 `recommend_characters(message, grade, limit)` 中接入 hybrid search：

```python
search_with_scores(
    "history",
    message,
    k=max(limit * 2, 6),
    mode="hybrid",
    metadata_hints={"grade": grade} if grade else None,
    fetch_k=40,
)
```

#### 4.2.2 推荐候选提取

候选来源：

1. RAG docs metadata 中的 `entities` / `topic` / `event`。
2. 现有内置人物目录。
3. LLM 对 query 的结构化推荐。

排序策略：

- RAG score/source_mode 加权。
- 与用户问题关键词重合度。
- 是否在人物目录中。
- grade 匹配加权。

#### 4.2.3 fallback

如果 RAG 或 LLM 推荐失败，保持现有 recommender fallback，不让接口失败。

## 4.3 游戏生成 RAG 增强

### 涉及文件

- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `backend/agents/multiplayer_card_generator.py`
- `backend/agents/history_games.py`
- `eval/game_generation_eval.py`

### 实现设计

#### 4.3.1 RAG context 作为背景材料

在生成题目或卡牌解释前，根据 topic/grade/difficulty 检索：

```python
search_with_scores(
    "history",
    query,
    k=4,
    mode="hybrid",
    metadata_hints={"grade": grade, "topic": topic},
    fetch_k=30,
)
```

#### 4.3.2 可信事实边界

游戏链路必须区分：

- 后端可信字段：event_id、year、correct_order、card_id。
- LLM 可生成字段：description、hint、explanation、feedback。
- RAG 背景字段：source/topic/page/snippet。

Prompt 必须明确：

```text
以下史料只作为解释参考。不得修改后端提供的事件 ID、年份、正确顺序和卡牌 ID。
如果史料与后端事件不一致，以后端事件字段为准。
```

#### 4.3.3 eval 保护

`game_generation_eval.py` 需要继续验证：

- 年份是整数。
- 事件 ID 不重复。
- 正确顺序存在。
- explanation 不为空。
- LLM 输出无法覆盖后端 canonical answer。

## 4.4 Structured Output Repair

### 涉及文件

- `backend/structured_output.py`
- `backend/textbook_learning/service.py`
- `backend/agents/history_character.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `backend/agents/character_recommender.py`

### 新增接口

建议新增：

```python
def validate_with_pydantic(payload: Any, model: type[T]) -> T:
    ...


def repair_json_with_llm(
    llm,
    raw: str,
    *,
    expect: Literal["object", "list"] = "object",
    schema_name: str | None = None,
    error: str | None = None,
) -> str:
    ...


def invoke_structured(
    llm,
    messages: list[dict[str, str]],
    *,
    expect: Literal["object", "list"] = "object",
    model: type[T] | None = None,
    fallback: Any = _FALLBACK_UNSET,
    repair: bool = True,
) -> Any:
    ...
```

### Repair prompt 要求

Repair LLM prompt 必须强调：

- 只输出 JSON。
- 不新增事实。
- 不删除原文中已有的有效字段，除非 schema 不允许。
- 不改写年份、事件 ID、人物名等事实字段。
- 只修复引号、逗号、括号、根类型、字段类型等格式问题。

### Repair 次数限制

每次 invoke 最多 repair 一次：

1. 原始 parse。
2. 失败后 repair。
3. repair 后再次 parse。
4. 仍失败则 fallback 或 raise。

### Tracing metadata

structured output span 增加：

- `repair_attempted`
- `repair_success`
- `repair_error_type`
- `schema`
- `expect`
- `fallback_used`

## 5. 验证方案

### 5.1 语法检查

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m py_compile \
  backend/structured_output.py \
  backend/rag/knowledge_base.py \
  backend/agents/history_character.py \
  backend/agents/character_recommender.py \
  backend/agents/timeline_question_generator.py \
  backend/agents/card_game.py \
  backend/agents/multiplayer_card_generator.py \
  backend/api/main.py
```

### 5.2 Quick eval

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 eval/run_core_evals.py --quick
```

### 5.3 Core eval

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 eval/run_core_evals.py
```

### 5.4 重点手测

启动后端：

```bash
npm run dev:backend
```

建议测试：

1. 历史人物对话：
   - 问人物生平。
   - 问教材相关问题。
   - 问反事实问题。
   - 检查 SSE sources 是否包含 score/source_mode。

2. 人物推荐：
   - 输入“我想了解秦统一六国”。
   - 输入“八年级上册近代化探索”。
   - 检查推荐理由是否有史料/教材依据。

3. 游戏生成：
   - timeline start。
   - card-game start。
   - multiplayer start。
   - 检查事件 ID/year/order 没有被 LLM 改写。

4. structured repair：
   - 构造带 code fence 的 JSON。
   - 构造前后混有解释文本的 JSON。
   - 构造缺逗号/单引号等轻微错误，确认 repair 最多一次。

## 6. 风险与控制

### 6.1 RAG 相关风险

风险：metadata filter 过严导致召回为空。

控制：Milestone B 中 grade/topic 主要作为 metadata_hints，不默认作为硬过滤。

风险：RAG source 正文过长导致 SSE payload 或 Langfuse payload 过大。

控制：source snippet、span preview 统一截断。

风险：RAG 材料误导游戏 canonical answer。

控制：后端事件 ID/year/order 是可信源，prompt 和代码都不允许 LLM 覆盖。

### 6.2 Structured output repair 风险

风险：repair LLM 改写事实内容。

控制：repair prompt 明确只修 JSON，不改事实；对事件 ID/year 等字段仍以后端字段为准。

风险：repair 引入额外 LLM 成本和延迟。

控制：只在首次 parse 失败后触发，最多一次。

风险：repair 改变现有业务 fallback 行为。

控制：保留原 fallback 语义；repair 失败后按原逻辑 fallback 或 raise。

## 7. 推荐实施顺序

1. 修改 `backend/structured_output.py`，先实现 repair 基础能力和单元式手测。
2. 接入 `textbook_learning/service.py` 中已有 JSON 输出链路。
3. 增强 `history_character.py` 的 RAG 检索与 sources。
4. 增强 `character_recommender.py` 的 RAG 候选与 fallback。
5. 增强 timeline/card/multiplayer 游戏生成 prompt 和 RAG context。
6. 跑 `py_compile`。
7. 跑 `eval/run_core_evals.py --quick`。
8. 跑完整 core eval。
9. 如果 UI sources 字段变化，手测历史人物对话页面和游戏页面。

## 8. 交付标准

Milestone B 完成后应满足：

- 历史人物对话 sources 包含可观测 score/source_mode。
- 人物推荐能利用 RAG 材料生成更贴近教材/史料的问题推荐。
- 游戏生成接入 RAG context，但 canonical answer 不被 LLM 改写。
- structured output parse 失败时可最多 repair 一次。
- repair 失败后仍保持原 fallback 行为。
- `eval/run_core_evals.py --quick` 通过。
- 完整 core eval 不出现已有关键指标下降。
- Langfuse 中可观察到 request trace 下的 RAG span、structured output span、LLM generation。
