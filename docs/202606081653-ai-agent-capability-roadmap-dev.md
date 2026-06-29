# EduAgent AI Agent 能力补强开发文档

## 1. 背景

当前项目 EduAgent 是面向 K-12 中文/历史学习场景的 AI 教学平台，已经具备历史人物对话、教材问答、作文批改、辩论、历史时间线游戏、时间巨轮卡牌游戏和多人 AI 游戏等能力。

结合 `docs/ai-agent-engineer-skills.md` 中整理的 AI Agent 工程师技能点，以及当前项目代码实现，项目已经覆盖了 LLM 调用、模型路由、LangGraph 工作流、RAG、SSE 流式输出、短期会话记忆、结构化输出和教育垂直 Agent 场景。

下一阶段的目标不是重做现有功能，而是在现有架构上补齐生产级 Agent 应用更关键的能力：更可靠的检索、更系统的评测、更完整的观测、更稳定的结构化输出、更清晰的工具抽象、长期学习记忆和权限安全体系。

## 2. 当前项目已具备能力

### 2.1 LLM API、模型路由与 Streaming

当前项目通过 `backend/llm_config.py` 统一封装 LLM 调用。

已具备：

- Anthropic 兼容调用。
- Bailian / DashScope OpenAI 兼容调用。
- `llm_fast`、`llm_quality`、`llm_reasoning` 分层。
- fallback model chain。
- 普通 invoke 调用。
- streaming 调用。
- 基础日志与 API key mask。

相关文件：

- `backend/llm_config.py`
- `backend/zode_client.js`

### 2.2 LangGraph / Agent Workflow

历史人物对话已经使用 LangGraph 构建检索、生成、校验流程。

现有流程：

```text
retrieve -> generate -> verify -> END
```

已具备：

- RAG 检索节点。
- 教学模拟生成节点。
- 质量模型校验节点。
- 反事实问题模式识别。
- 史实卡片生成。

相关文件：

- `backend/agents/history_character.py`
- `backend/agents/essay_grader.py`
- `backend/agents/debate_supervisor.py`

### 2.3 RAG 知识库

当前项目使用 Chroma + BGE embedding 构建历史知识库。

已具备：

- 本地 BGE embedding。
- Chroma vector store。
- 文档 chunking。
- BGE query prefix。
- 历史语料构建。
- 教材 YAML / PDF / OCR 到知识库的处理链路。

相关文件：

- `backend/rag/knowledge_base.py`
- `build_index.py`
- `scripts/parse_textbook.py`
- `scripts/ocr_pdf.py`
- `scripts/pdf_to_yaml.py`

### 2.4 SSE 流式交互

历史人物对话和教材学习已经支持 SSE 流式响应。

已具备事件：

- `sources`
- `delta`
- `status`
- `final`
- `fact_card`

相关文件：

- `backend/api/main.py`
- `backend/agents/history_character.py`
- `backend/textbook_learning/service.py`
- `frontend/app/history-character/page.tsx`

### 2.5 短期会话记忆

当前项目有 session 级短期记忆。

已具备：

- Redis 优先。
- 内存兜底。
- 1 小时 TTL。
- 最近 16 条消息上下文。

相关文件：

- `backend/session_store.py`
- `backend/api/main.py`
- `backend/textbook_learning/service.py`

### 2.6 结构化输出雏形

多个模块已经通过 prompt 要求模型输出 JSON，并在后端进行解析。

覆盖场景：

- 历史人物推荐。
- 史实卡片。
- 教材 quiz。
- 时间线题目。
- 卡牌游戏。
- 多人游戏 AI 卡牌生成。
- AI 玩家讲解。

相关文件：

- `backend/agents/history_character.py`
- `backend/agents/character_recommender.py`
- `backend/textbook_learning/service.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `backend/agents/multiplayer_card_generator.py`
- `backend/agents/multiplayer_ai_commentary.py`

### 2.7 评测雏形

当前项目已有历史人物对话 smoke test。

已具备：

- 基础 case 列表。
- Agent graph 调用。
- 回答结构断言。
- sources 存在性断言。
- 检索命中关键词断言。

相关文件：

- `eval/history_character_smoke.py`

项目依赖里已有但尚未完整接入：

- `ragas`
- `langfuse`

### 2.8 教育垂直 Agent 场景

当前项目已经具备较完整的教育垂直场景。

包括：

- 历史人物对话。
- 人物推荐。
- 教材问答。
- 教材摘要。
- 教材 quiz。
- 作文批改。
- 辩论。
- 历史时间线游戏。
- 时间巨轮卡牌游戏。
- 多人 AI 游戏。

## 3. 当前主要不足

### 3.1 RAG 检索仍偏基础

当前检索主要依赖 `similarity_search`，缺少：

- Hybrid Search。
- Rerank。
- metadata filter。
- 检索质量评测。
- 引用准确性评测。

在历史教育场景中，事实准确性是核心体验。检索质量直接影响回答可信度、游戏题目质量和教材问答准确性。

### 3.2 缺少系统化 Agent 评测

目前只有 smoke test，不能覆盖：

- 多章节教材问答。
- 反事实问题。
- 人物推荐准确率。
- 时间线题目合法性。
- 卡牌题目合法性。
- 史料引用准确性。
- 模型幻觉。
- 多轮对话一致性。

### 3.3 缺少 LLM 调用观测链路

虽然项目依赖中已有 `langfuse`，但当前未形成完整 tracing。

缺少：

- prompt 记录。
- model 记录。
- token/cost 记录。
- latency 记录。
- retrieval sources 记录。
- final answer 记录。
- error 记录。
- session 维度追踪。

### 3.4 结构化输出不够强约束

当前大量模块依赖 prompt 要求 JSON，再手动解析。

问题包括：

- JSON 格式不稳定。
- 字段缺失时处理分散。
- 校验逻辑重复。
- 模型修复策略不统一。
- 不同模块 schema 不够显式。

### 3.5 还没有统一 Tool Calling 抽象

当前项目有很多功能函数，但没有形成统一的 Agent tools。

例如：

- 搜索历史知识库。
- 获取教材章节。
- 生成测验。
- 推荐历史人物。
- 开始时间线游戏。
- 开始卡牌游戏。
- 批改作文。

这些能力目前由 API 或业务模块直接调用，还没有被统一学习助手 Agent 作为工具组合使用。

### 3.6 只有短期记忆，没有长期学习画像

当前 session memory 只能服务一次会话。教育产品更需要长期学习画像。

缺少：

- 学生年级。
- 最近学习章节。
- 薄弱知识点。
- 常错题型。
- 游戏表现。
- 作文问题。
- 历史人物对话偏好。
- 个性化推荐依据。

### 3.7 权限与安全体系较基础

当前项目主要有 CORS 配置和 API key 环境变量管理，缺少用户级权限体系。

后续如接入用户数据、学习记录、教师端管理和更多工具调用，需要补充：

- 用户身份。
- 学生/教师/管理员角色。
- session 归属校验。
- API rate limit。
- 数据隔离。
- 操作审计。
- Prompt injection 防护。

## 4. 开发目标

### 4.1 短期目标

短期目标是提升当前 Agent 的准确性、稳定性和可观测性。

包括：

1. 增强 RAG 检索质量。
2. 建立基础 eval 数据集。
3. 接入 Langfuse tracing。
4. 统一结构化输出校验。

### 4.2 中期目标

中期目标是把当前多个分散教育 Agent 能力整合成可组合的学习助手能力。

包括：

1. 封装 Agent tools。
2. 设计统一学习助手 Agent。
3. 增加学生长期学习记忆。
4. 加强安全与权限控制。

### 4.3 长期目标

长期目标是形成完整的个性化学习闭环。

包括：

1. 学情诊断。
2. 个性化讲解。
3. 自适应练习。
4. 自动批改。
5. 错题回顾。
6. 学习路径推荐。
7. 多模态作业和教材理解。

## 5. 推荐实施路线

## Phase 1：RAG 检索增强

### 5.1 目标

提升历史问答、教材问答、游戏生成和人物推荐的史料命中率与引用准确性。

### 5.2 设计方案

在 `backend/rag/knowledge_base.py` 增加增强检索能力。

建议新增：

- `keyword_search`
- `vector_search`
- `hybrid_search`
- `rerank_documents`
- `search_with_scores`
- metadata filter 参数

目标流程：

```text
query
  -> query normalization
  -> metadata filter
  -> vector search
  -> keyword search
  -> merge/deduplicate
  -> rerank
  -> top_k documents
```

### 5.3 可选技术方案

优先级建议：

1. 先加 metadata filter 和更合理的 query 拼接。
2. 再加 lightweight keyword search。
3. 最后接入中文 reranker。

Rerank 可选：

- BGE reranker。
- DashScope rerank。
- Cohere Rerank。
- 本地 cross-encoder reranker。

### 5.4 涉及文件

- `backend/rag/knowledge_base.py`
- `backend/agents/history_character.py`
- `backend/textbook_learning/service.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `build_index.py`

### 5.5 验收标准

- 历史人物对话 sources 命中率提升。
- 教材问答能优先命中当前章节内容。
- 游戏题目生成引用材料更稳定。
- `eval/history_character_smoke.py` 通过。
- 新增 RAG eval case 通过。

## Phase 2：Agent / RAG 评测体系

### 5.6 目标

从 smoke test 升级为可持续回归的评测体系。

### 5.7 设计方案

在 `eval/` 下新增评测数据和脚本。

建议目录：

```text
eval/
  datasets/
    history_character_cases.json
    textbook_qa_cases.json
    timeline_game_cases.json
  history_character_eval.py
  textbook_qa_eval.py
  rag_retrieval_eval.py
  game_generation_eval.py
```

### 5.8 评测指标

建议先实现以下指标：

- `retrieval_hit_rate`
- `source_presence_rate`
- `answer_structure_pass_rate`
- `verified_pass_rate`
- `citation_keyword_hit_rate`
- `json_parse_success_rate`
- `game_rule_valid_rate`

后续再加入：

- RAGAS faithfulness。
- LLM-as-a-judge。
- 人工标注集。

### 5.9 涉及文件

- `eval/history_character_smoke.py`
- `eval/history_character_eval.py`
- `eval/rag_retrieval_eval.py`
- `eval/datasets/*.json`
- `backend/requirements.txt`

### 5.10 验收标准

- 可以一条命令运行核心 eval。
- eval 输出通过率和失败 case。
- 至少覆盖历史人物对话、教材问答和 RAG 检索。
- eval 能用于后续 RAG、prompt 和模型变更回归。

## Phase 3：Langfuse 观测接入

### 5.11 目标

为 LLM 调用、RAG 检索和 Agent 工作流建立可追踪链路。

### 5.12 设计方案

在 LLM 调用层和关键 Agent 流程中加入 tracing。

建议记录：

- session_id。
- route / feature。
- model。
- provider。
- prompt input。
- response output。
- latency。
- error。
- retrieval query。
- retrieved sources。
- verified 状态。
- final answer。

### 5.13 涉及文件

- `backend/llm_config.py`
- `backend/api/main.py`
- `backend/agents/history_character.py`
- `backend/textbook_learning/service.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`

### 5.14 环境变量

建议新增：

```bash
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
LANGFUSE_ENABLED=true
```

### 5.15 验收标准

- 每次历史人物对话能看到完整 trace。
- 每次教材问答能看到检索 query 和 sources。
- LLM 调用失败时能在 trace 中定位。
- 可以按 session_id 查询一次完整学习交互。

## Phase 4：结构化输出统一治理

### 5.16 目标

减少 JSON 输出失败，提高题目、卡牌、推荐和史实卡片生成稳定性。

### 5.17 设计方案

新增统一结构化输出工具模块。

建议新增文件：

```text
backend/structured_output.py
```

提供能力：

- `extract_json_object`
- `parse_with_model`
- `validate_with_pydantic`
- `repair_json_with_llm`
- `invoke_json`

### 5.18 Schema 覆盖范围

优先覆盖：

- Character recommendation。
- Fact card。
- Textbook quiz。
- Timeline game round。
- Card game round。
- Multiplayer card pool。
- AI commentary。

### 5.19 涉及文件

- `backend/structured_output.py`
- `backend/agents/history_character.py`
- `backend/agents/character_recommender.py`
- `backend/textbook_learning/service.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `backend/agents/multiplayer_card_generator.py`
- `backend/agents/multiplayer_ai_commentary.py`

### 5.20 验收标准

- 结构化输出解析逻辑集中管理。
- JSON parse 失败率下降。
- 各模块 schema 明确。
- 输出字段缺失时有统一错误提示或修复机制。
- 游戏和题目生成 eval 通过。

## Phase 5：Tool Calling 与统一学习助手 Agent

### 5.21 目标

把当前分散的教育能力封装成工具，构建一个能理解学生意图并组合能力的统一学习助手 Agent。

### 5.22 工具设计

建议新增 tools 层：

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

### 5.23 统一学习助手流程

建议新增：

```text
backend/agents/learning_assistant.py
```

目标流程：

```text
classify_intent
  -> select_tool
  -> execute_tool
  -> synthesize_response
  -> suggest_next_step
```

示例：

```text
学生：我想复习秦汉历史，再做几道题。
Agent：
1. 获取相关教材章节
2. 总结重点
3. 生成 quiz
4. 根据答题结果推荐复习方向
```

### 5.24 API 设计

建议新增：

```text
POST /api/learning/assistant/chat
```

SSE 事件建议：

- `intent`
- `tool_start`
- `tool_result`
- `delta`
- `final`
- `suggestions`

### 5.25 涉及文件

- `backend/tools/*`
- `backend/agents/learning_assistant.py`
- `backend/api/main.py`
- `frontend/app/*`

### 5.26 验收标准

- 学生可以用自然语言触发教材讲解、出题、人物推荐或游戏。
- Agent 能展示调用了什么工具。
- 工具失败时能返回清晰错误。
- 高风险或耗时操作有状态提示。

## Phase 6：长期学习记忆与学生画像

### 5.27 目标

从 session 记忆升级为长期学习画像，为个性化推荐和自适应学习做准备。

### 5.28 数据设计

建议新增学生画像结构：

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

### 5.29 能力设计

新增：

- 学习记录写入。
- 学习画像读取。
- 错题与薄弱点聚合。
- 个性化推荐。
- 画像过期和修正机制。

### 5.30 涉及文件

- `backend/session_store.py`
- `backend/student_profile.py`
- `backend/api/main.py`
- `backend/agents/history_games.py`
- `backend/textbook_learning/service.py`
- `backend/agents/learning_assistant.py`

### 5.31 存储方案

短期可以使用 JSON 文件或 SQLite。

中长期建议：

- PostgreSQL 存结构化学习记录。
- Redis 存短期会话。
- 向量库保存可检索的长期学习摘要。

### 5.32 验收标准

- 能记录学生最近学习章节。
- 能记录 quiz 和游戏薄弱点。
- 能根据画像推荐复习内容。
- 不同 student_id 数据隔离。

## Phase 7：权限、安全与 Prompt Injection 防护

### 5.33 目标

为后续真实用户、教师端和工具调用能力打安全基础。

### 5.34 安全增强项

建议补充：

- 用户身份认证。
- 学生/教师/管理员角色。
- session_id 归属校验。
- API rate limit。
- 操作审计日志。
- 敏感配置检查。
- Prompt injection 防护模板。
- RAG 材料和用户指令隔离。
- 工具参数校验。

### 5.35 Prompt Injection 防护原则

所有 RAG 场景应明确：

- 检索材料是不可信输入。
- 检索材料不能覆盖 system prompt。
- 检索材料中的命令、指令、要求都不能被执行。
- 回答只能使用材料中的事实内容。

建议统一封装 RAG context 模板，避免每个 prompt 分散处理。

### 5.36 涉及文件

- `backend/api/main.py`
- `backend/agents/history_character.py`
- `backend/textbook_learning/prompts.py`
- `backend/agents/timeline_question_generator.py`
- `backend/agents/card_game.py`
- `backend/agents/multiplayer_card_generator.py`

### 5.37 验收标准

- session_id 不能跨用户读取。
- RAG prompt 中统一包含不可信材料隔离说明。
- 工具调用参数有后端校验。
- 高风险操作有审计日志。

## 6. 优先级排序

### P0：优先做

1. RAG 检索增强。
2. Agent / RAG eval。
3. Langfuse tracing。
4. 结构化输出统一治理。

### P1：中期做

1. Tool Calling 抽象。
2. 统一学习助手 Agent。
3. 长期学习记忆。
4. 权限和数据隔离。

### P2：后续做

1. 多 Agent 协作学习闭环。
2. 多模态实时学习。
3. 成本控制和 prompt caching。
4. 教师端学情分析。

## 7. 建议里程碑

### Milestone 1：检索与评测基础

目标：让历史问答和教材问答更准，并且可回归。

包含：

- RAG metadata filter。
- 初版 hybrid search。
- RAG eval dataset。
- history character eval。
- textbook QA eval。

### Milestone 2：观测与结构化稳定性

目标：让 Agent 行为可追踪，结构化输出更稳定。

包含：

- Langfuse tracing。
- 统一 JSON parser。
- Pydantic schema。
- JSON 修复策略。
- 游戏生成 eval。

### Milestone 3：统一学习助手

目标：让学生可以用自然语言触发多个学习能力。

包含：

- tools 层。
- learning assistant agent。
- SSE 工具调用状态。
- 前端统一学习助手入口。

### Milestone 4：个性化学习闭环

目标：从一次性问答升级为持续辅导。

包含：

- student profile。
- 学习记录。
- 薄弱点分析。
- 个性化推荐。
- 错题复习。

## 8. 风险与注意事项

### 8.1 不要过早做通用 Agent

当前项目优势是 K-12 历史教育垂直场景，不应过早做成泛化助手。统一学习助手也应该围绕教材、问答、测验、游戏和学习路径服务。

### 8.2 RAG 优化要以 eval 为准

检索策略不能只凭主观体验调整，应配套评测集。否则 chunk、embedding、rerank、prompt 的改动容易互相影响，无法判断收益。

### 8.3 Tool Calling 必须有权限边界

即使当前工具大多是学习类操作，也要从一开始设计工具 schema、参数校验和调用日志，避免后续接入真实用户数据时返工。

### 8.4 长期记忆要避免污染

学生画像应记录稳定、可验证、对学习有帮助的信息。不要无差别保存完整对话，也不要让过期画像长期影响推荐。

### 8.5 结构化输出不要只依赖 prompt

对于题目、卡牌、时间线和推荐等核心功能，应使用 schema 校验和失败修复策略，不能只靠“请返回 JSON”。

## 9. 总结

当前 EduAgent 已经具备 AI Agent 产品的核心雏形：LLM 路由、LangGraph 工作流、RAG、SSE、短期记忆、结构化输出和教育场景落地。

下一阶段建议围绕“准确、稳定、可观测、可组合、个性化、安全”六个关键词推进：

1. 用 RAG 增强和 eval 提升准确性。
2. 用 Langfuse 和日志提升可观测性。
3. 用 schema 治理提升结构化输出稳定性。
4. 用 tools 和统一学习助手提升能力组合。
5. 用学生画像提升个性化。
6. 用权限和 prompt injection 防护提升安全边界。

按照该路线推进后，项目可以从“多个教育 AI 功能集合”升级为“具备持续学习辅导能力的教育 Agent 平台”。
