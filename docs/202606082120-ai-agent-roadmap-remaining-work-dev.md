# EduAgent AI Agent 路线图未完成项补齐开发文档

## 1. 背景

`docs/202606081653-ai-agent-capability-roadmap-dev.md` 对 EduAgent 下一阶段 AI Agent 能力补强进行了规划，目标是从“多个教育 AI 功能集合”升级为“具备持续学习辅导能力的教育 Agent 平台”。

截至当前项目状态，部分能力已经落地或已有雏形：

- RAG 增强检索底层能力已经在 `backend/rag/knowledge_base.py` 中实现。
- Eval 数据集和多类评测脚本已经在 `eval/` 下建立。
- Langfuse 第一阶段 LLM tracing MVP 已接入，相关设计文档见 `docs/202606082106-langfuse-tracing-dev.md`。
- 结构化输出已有统一解析模块 `backend/structured_output.py`。
- session 级短期记忆已由 `backend/session_store.py` 支持。

但从路线图目标看，仍有多个生产级 Agent 能力未完成或只完成了局部能力。本开发文档用于整理后续补齐范围、优先级、涉及文件和验收标准。

## 2. 当前完成度概览

| Phase | 能力 | 当前状态 | 主要缺口 |
|---|---|---|---|
| Phase 1 | RAG 检索增强 | 部分完成 | 底层增强检索已有，但未全面接入历史人物、推荐、游戏生成等链路 |
| Phase 2 | Agent / RAG eval | 基本完成 | 缺统一 eval runner、CI 化、更多稳定 case |
| Phase 3 | Langfuse 观测 | 部分完成 | 已有 LLM generation tracing，缺 request trace、RAG span、结构化输出 span |
| Phase 4 | 结构化输出治理 | 部分完成 | 缺统一 schema validate、JSON repair、invoke_structured 闭环 |
| Phase 5 | Tool Calling 与学习助手 | 未完成 | tools 层基本未实现，learning assistant 未实现 |
| Phase 6 | 长期学习记忆 | 未完成/少量雏形 | 缺 student profile、长期画像存储、学习事件聚合 |
| Phase 7 | 权限与安全 | 部分完成 | 缺认证鉴权、session/student 数据隔离、rate limit、审计、统一 prompt injection 防护 |

## 3. 开发目标

后续开发目标按“可回归、可观测、可组合、可个性化、可安全上线”的顺序推进。

短期目标：

1. 建立统一 eval 入口，保证后续改动可回归。
2. 完善 Langfuse 观测，从单次 LLM 调用扩展到完整学习交互链路。
3. 将增强检索能力接入主要 Agent 场景。
4. 完善结构化输出 schema 校验和 repair 闭环。

中期目标：

1. 建立 tools 层，将现有教育能力封装为可组合工具。
2. 实现统一学习助手 Agent。
3. 初步建立长期学习画像和学习事件记录。

长期目标：

1. 建立用户身份、角色、数据隔离和审计体系。
2. 统一 RAG prompt injection 防护模板。
3. 支持个性化推荐、自适应练习和学习路径闭环。

## 4. 未完成项一：RAG 增强全链路接入

### 4.1 当前状态

`backend/rag/knowledge_base.py` 已具备：

- `vector_search`
- `keyword_search`
- `hybrid_search`
- `rerank_documents`
- `search_with_scores`
- metadata filter
- metadata hints

教材问答链路已经较好接入增强检索：

- `backend/textbook_learning/service.py`

但其他主要业务仍未全面使用增强检索。

### 4.2 待补齐内容

优先接入以下模块：

- `backend/agents/history_character.py`
- `backend/agents/character_recommender.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `backend/agents/multiplayer_card_generator.py`

建议策略：

1. 历史人物对话使用 hybrid search，并结合 `character`、`grade`、`mode` 构造 metadata hints。
2. 人物推荐使用 hybrid search，提高主题匹配和人物覆盖准确性。
3. 时间线和卡牌游戏生成优先使用带 score 的检索结果，减少不相关史料干扰。
4. 多人卡牌生成记录 source metadata，便于后续 Langfuse RAG span 观测。

### 4.3 验收标准

- `eval/rag_retrieval_eval.py` 通过率不下降。
- `eval/history_character_eval.py` 通过率不下降。
- 教材问答仍能优先命中当前章节。
- 游戏生成引用材料主题相关性提升。
- 检索结果 sources 中包含稳定 metadata。

## 5. 未完成项二：统一 Eval Runner

### 5.1 当前状态

当前已有多个 eval 脚本：

- `eval/history_character_smoke.py`
- `eval/history_character_eval.py`
- `eval/rag_retrieval_eval.py`
- `eval/textbook_qa_eval.py`
- `eval/game_generation_eval.py`

也已有数据集目录：

- `eval/datasets/`

但缺少一条命令运行核心评测的统一入口。

### 5.2 待补齐内容

新增：

```text
eval/run_core_evals.py
```

建议功能：

1. 顺序运行核心 eval。
2. 捕获每个 eval 的退出码。
3. 汇总通过率、失败 case 数、总耗时。
4. 以统一格式输出结果。
5. 支持 `--quick`、`--json` 等可选参数。

核心 eval 范围：

- history character eval
- RAG retrieval eval
- textbook QA eval
- game generation eval

### 5.3 输出示例

```text
[PASS] history_character_eval  18/20
[PASS] rag_retrieval_eval      24/25
[FAIL] textbook_qa_eval        13/16
[PASS] game_generation_eval    10/10

Total: 65/71 passed
Failed suites: textbook_qa_eval
```

### 5.4 验收标准

- 可通过一条命令运行核心 eval：

```bash
python3 eval/run_core_evals.py
```

- 任一 eval 失败时总命令返回非 0。
- 输出能定位失败 suite。
- 后续 RAG、prompt、模型变更可使用该入口回归。

## 6. 未完成项三：Langfuse 观测补强

### 6.1 当前状态

已完成第一阶段 LLM tracing MVP：

- `backend/tracing.py`
- `backend/llm_config.py`
- `.env.example`
- `backend/api/main.py` shutdown flush

已覆盖：

- `llm.invoke`
- `llm.stream`
- provider/model/fallback attempt
- output chars
- chunk count
- tracing disabled no-op

### 6.2 待补齐内容

#### 6.2.1 Request-level trace

在核心 API 中创建 request trace：

- `/api/history/character/chat`
- `/api/textbook-learning/ask`
- `/api/textbook-learning/summary`
- `/api/textbook-learning/quiz`
- `/api/history/games/timeline/start`
- `/api/history/card-game/start`
- `/api/history/multiplayer/start`

建议 metadata：

- `feature`
- `route`
- `session_id`
- `student_id`
- `round_id`
- `grade`
- `topic`
- `difficulty`
- `mode`
- `stream`

#### 6.2.2 RAG span

在检索入口记录 span：

- `backend/rag/knowledge_base.py`
- `backend/textbook_learning/service.py`
- `backend/agents/history_character.py`

建议字段：

- query
- collection
- k
- mode
- metadata_filter
- metadata_hints
- source_count
- source metadata preview

#### 6.2.3 Structured output span

在 `backend/structured_output.py` 中记录：

- JSON parse success/fail
- schema validation success/fail
- repair 是否发生
- fallback 是否发生

### 6.3 验收标准

- 一次历史人物对话在 Langfuse 中可看到完整 trace。
- 一次教材问答可看到 request trace、RAG span、LLM generation。
- LLM 失败或 fallback 时可在 trace 中定位 provider/model attempt。
- 可按 `session_id` 或 `student_id` 查询学习交互。

## 7. 未完成项四：结构化输出强约束治理

### 7.1 当前状态

已有：

- `backend/structured_output.py`
- 多个业务模块已使用统一 JSON parse 方法

但仍存在：

- prompt 要求 JSON 仍是主要约束方式。
- Pydantic schema 分散。
- JSON repair 没有统一封装。
- 字段缺失、类型错误、模型多余文本处理策略不统一。

### 7.2 待补齐内容

增强 `backend/structured_output.py`：

- `validate_with_pydantic(...)`
- `repair_json_with_llm(...)`
- `invoke_structured(...)`
- `StructuredOutputError`
- 标准 parse / validate / repair / fallback 流程

优先覆盖：

- `backend/agents/history_character.py` 的 fact card
- `backend/agents/character_recommender.py` 的人物推荐
- `backend/textbook_learning/service.py` 的 quiz
- `backend/agents/timeline_question_generator.py` 的时间线题目
- `backend/agents/card_game.py` 的卡牌题目
- `backend/agents/multiplayer_card_generator.py` 的多人卡牌池
- `backend/agents/multiplayer_ai_commentary.py` 的 AI 解说

### 7.3 验收标准

- 核心结构化输出都有显式 schema。
- JSON parse 失败时走统一 repair 策略。
- repair 后仍失败时返回清晰错误或明确 fallback。
- `json_parse_success_rate` 和 schema validation 指标可纳入 eval。

## 8. 未完成项五：Tools 层

### 8.1 当前状态

`backend/tools/` 目录存在，但核心工具尚未实现。

### 8.2 待补齐内容

新增工具模块：

```text
backend/tools/
  history_search.py
  textbook_tools.py
  quiz_tools.py
  character_tools.py
  game_tools.py
  essay_tools.py
```

候选工具：

- `search_history_knowledge`
- `get_textbook_lesson`
- `summarize_lesson`
- `generate_quiz`
- `recommend_character`
- `chat_with_character`
- `start_timeline_game`
- `start_card_game`
- `grade_essay`

工具设计要求：

- 每个工具有明确输入 schema。
- 每个工具有明确输出结构。
- 工具内部复用现有 service/agent，不重复实现业务逻辑。
- 工具错误返回结构统一。
- 工具调用可被 Langfuse 或本地日志记录。

### 8.3 验收标准

- 现有教材、问答、游戏、推荐能力可以通过 tools 层调用。
- 工具参数有后端校验。
- 工具失败时返回结构化错误。
- 不影响现有 API。

## 9. 未完成项六：统一学习助手 Agent

### 9.1 当前状态

尚未实现：

```text
backend/agents/learning_assistant.py
```

尚未实现 API：

```text
POST /api/learning/assistant/chat
```

### 9.2 待补齐内容

新增统一学习助手流程：

```text
classify_intent
  -> select_tool
  -> execute_tool
  -> synthesize_response
  -> suggest_next_step
```

支持意图：

- 教材讲解
- 教材问答
- 生成测验
- 推荐历史人物
- 开始时间线游戏
- 开始卡牌游戏
- 作文批改
- 学习复习建议

SSE 事件：

- `intent`
- `tool_start`
- `tool_result`
- `delta`
- `final`
- `suggestions`

### 9.3 验收标准

- 学生可以用自然语言触发至少 3 类学习能力。
- Agent 能展示调用了哪个工具。
- 工具失败时能给出清晰解释。
- 输出包含下一步学习建议。

## 10. 未完成项七：长期学习记忆与学生画像

### 10.1 当前状态

已有：

- `backend/session_store.py` 短期 session memory
- 游戏侧少量 `student_id` 记录

但没有统一长期学生画像。

### 10.2 待补齐内容

新增：

```text
backend/student_profile.py
```

第一版存储可使用 SQLite 或 JSON 文件，后续再迁移 PostgreSQL。

建议画像结构：

```json
{
  "student_id": "string",
  "grade": "string",
  "recent_lessons": [],
  "weak_topics": [],
  "strong_topics": [],
  "wrong_question_patterns": [],
  "preferred_learning_style": "string",
  "character_chat_history_summary": [],
  "game_performance": {},
  "updated_at": "datetime"
}
```

学习事件类型：

- textbook_ask
- quiz_answer
- timeline_game_result
- card_game_result
- character_chat
- essay_grade

### 10.3 验收标准

- 能记录学生最近学习章节。
- 能记录 quiz / 游戏薄弱点。
- 能读取画像生成复习建议。
- 不同 `student_id` 数据隔离。
- 画像内容有过期或修正机制。

## 11. 未完成项八：权限、安全与 Prompt Injection 防护

### 11.1 当前状态

已有：

- CORS
- Pydantic 参数校验
- 部分 prompt injection 防护意识

但缺少完整用户级安全体系。

### 11.2 待补齐内容

安全基础：

- 用户身份认证
- 学生/教师/管理员角色
- session_id 归属校验
- student_id 数据隔离
- API rate limit
- 操作审计日志
- 工具调用参数校验

Prompt injection 防护：

- 统一 RAG context 模板
- 明确检索材料是不可信输入
- 检索材料不能覆盖 system prompt
- 检索材料中的命令、指令、要求不能被执行
- 回答只能使用材料中的事实内容

建议新增：

```text
backend/security/
  auth.py
  rate_limit.py
  audit_log.py
  prompt_injection.py
```

也可以先不建完整目录，只从 `prompt_injection.py` 和 RAG prompt 模板开始。

### 11.3 验收标准

- session_id 不能跨用户读取。
- student_id 数据不能跨用户访问。
- RAG prompt 统一包含不可信材料隔离说明。
- 工具调用参数有 schema 校验。
- 高风险操作有审计日志。

## 12. 推荐实施顺序

### Milestone A：回归与观测闭环

优先做：

1. `eval/run_core_evals.py`
2. Langfuse request-level trace
3. Langfuse RAG span
4. Langfuse structured output span

目标：后续所有 RAG、prompt、模型变更都可被评测和观测。

### Milestone B：RAG 与结构化稳定性

优先做：

1. 增强检索接入历史人物对话。
2. 增强检索接入人物推荐。
3. 增强检索接入游戏生成。
4. 统一结构化输出 schema。
5. 统一 JSON repair。

目标：提升准确性和稳定性。

### Milestone C：可组合学习助手

优先做：

1. tools 层。
2. learning assistant agent。
3. `/api/learning/assistant/chat`。
4. 前端统一学习助手入口。

目标：让学生可以自然语言组合教材讲解、问答、测验、游戏和推荐能力。

### Milestone D：个性化与安全

优先做：

1. student profile。
2. learning events。
3. 个性化复习建议。
4. session/student 数据隔离。
5. rate limit 和 audit log。
6. prompt injection 统一模板。

目标：从单次学习交互升级为持续辅导闭环。

## 13. 下一步建议

最建议的下一个开发任务是：

```text
新增 eval/run_core_evals.py，建立统一核心评测入口。
```

原因：

- 工程量小。
- 不影响业务逻辑。
- 能立刻支撑后续 RAG、Langfuse、结构化输出改动回归。
- 适合作为后续 Milestone A 的第一步。

第二优先任务是：

```text
为 Langfuse 增加 request-level trace 和 RAG span。
```

原因：

- 当前已有 LLM generation tracing。
- 再补 request/RAG 后，就能看到完整学习交互链路。
- 对排查 RAG 命中、模型幻觉、fallback 和延迟问题价值最高。
