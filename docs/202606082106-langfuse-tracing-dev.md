# Langfuse Tracing 接入开发文档

## 1. 背景

根据 `docs/202606081653-ai-agent-capability-roadmap-dev.md`，EduAgent 下一阶段需要补齐生产级 Agent 应用的观测能力。当前项目虽然已经在 `backend/requirements.txt` 中声明 `langfuse` 依赖，但尚未在 LLM 调用、RAG 检索或 Agent 工作流中接入 trace。

当前后端 LLM 调用主要集中在 `backend/llm_config.py` 的 `ZodeChatModel.invoke()` 和 `ZodeChatModel.stream()`，实际 provider HTTP 请求由 `backend/zode_client.js` 执行。因此第一阶段优先在 Python LLM 封装层接入 Langfuse generation tracing，以最小改动覆盖主要业务链路。

## 2. 开发目标

第一阶段目标：

1. 为所有通过 `llm_fast`、`llm_quality`、`llm_reasoning` 发起的 LLM 调用记录 Langfuse generation。
2. 覆盖非流式 `invoke()` 和流式 `stream()`。
3. 记录 provider、model、fallback attempt、max_tokens、stream 状态、输出字符数、chunk 数等关键字段。
4. Langfuse 未启用、缺少 key、SDK 初始化失败或服务不可用时，业务逻辑必须无侵入降级。
5. 不修改 `backend/zode_client.js`，不引入全局 middleware，不改变现有 Agent/API 调用方式。

## 3. 实施范围

本次修改文件：

- `backend/tracing.py`
- `backend/llm_config.py`
- `backend/api/main.py`
- `.env.example`

本次不做：

- 不改 `backend/zode_client.js`。
- 不做完整 API request trace。
- 不做 RAG span。
- 不估算 token usage。
- 不修改业务 Agent 函数签名。
- 不接入认证、权限、tools 或 learning assistant。

## 4. 设计方案

### 4.1 Langfuse 安全封装

新增 `backend/tracing.py`，集中封装 Langfuse SDK 访问。

提供能力：

- `is_tracing_enabled()`：判断 tracing 是否可用。
- `start_generation(...)`：安全创建 generation。
- `end_generation(...)`：安全结束 generation。
- `safe_flush()` / `safe_shutdown()`：服务退出时安全 flush。
- `sanitize_messages(...)`：对输入 messages 做 role/content 保留和内容截断。
- `sanitize_output(...)`：对输出做截断。
- `safe_error_message(...)`：限制错误信息长度。

降级原则：

- `LANGFUSE_ENABLED=false` 时完全 no-op。
- `LANGFUSE_ENABLED=true` 但缺少 key 时只记录 warning。
- Langfuse SDK import、初始化、generation 创建、generation 结束或 flush 任一阶段失败，都不得影响业务返回。

### 4.2 LLM generation 记录

在 `backend/llm_config.py` 中为 `ZodeChatModel` 增加可选 `name` 字段：

- `llm_fast`
- `llm_quality`
- `llm_reasoning`

每次 `_provider_model_chain()` 中的 provider/model attempt 都记录一条 generation。

非流式 `invoke()` 记录：

- `name`: `llm.invoke`
- `model`: 当前 attempt model
- `input`: 脱敏截断后的 messages
- `output`: 成功时的模型输出
- `model_parameters`:
  - `max_tokens`
  - `stream=false`
- `metadata`:
  - `provider`
  - `llm_name`
  - `configured_model`
  - `attempt_model`
  - `attempt_index`
  - `fallback_models`
  - `transport=zode_client.js`
  - `operation=invoke`
  - `output_chars`

流式 `stream()` 记录：

- `name`: `llm.stream`
- `model`: 当前 attempt model
- `input`: 脱敏截断后的 messages
- `output`: 正常结束后的完整拼接输出，或失败时的 partial output
- `model_parameters`:
  - `max_tokens`
  - `stream=true`
- `metadata`:
  - `provider`
  - `llm_name`
  - `configured_model`
  - `attempt_model`
  - `attempt_index`
  - `fallback_models`
  - `chunk_count`
  - `output_chars`
  - `emitted`
  - `partial_output`

### 4.3 Streaming 行为约束

保持原有 streaming fallback 语义：

- 如果某个 provider/model 在未 emit 任何 chunk 前失败，则记录 error generation，并继续 fallback。
- 如果已经 emit chunk 后失败，则记录 error generation 和 partial output，并继续抛出异常，不 fallback 到下一个模型。
- 这样可以避免前端 SSE 输出中混合两个模型的文本。

### 4.4 服务关闭 flush

在 `backend/api/main.py` 中增加 FastAPI shutdown hook，调用 `safe_shutdown()`，让服务退出时尽量 flush Langfuse 队列。

该 hook 不应影响服务关闭流程，所有异常都在 `backend/tracing.py` 内吞掉并记录 warning。

## 5. 环境变量

`.env.example` 新增：

```bash
# Langfuse tracing
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=local
LANGFUSE_RELEASE=edu-agent-local
LANGFUSE_CAPTURE_INPUT=true
LANGFUSE_CAPTURE_OUTPUT=true
```

说明：

- 默认关闭 Langfuse，避免本地未配置 key 时误报。
- 真实 key 只应写入本地 `.env.local` 或部署环境变量，不应提交到仓库。
- 生产环境可将 `LANGFUSE_CAPTURE_INPUT` / `LANGFUSE_CAPTURE_OUTPUT` 设为 `false`，只保留 metadata。

## 6. 验收方式

### 6.1 语法检查

```bash
PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m py_compile backend/tracing.py backend/llm_config.py backend/api/main.py
```

### 6.2 禁用 Langfuse 验证无侵入

```bash
LANGFUSE_ENABLED=false PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

请求：

```bash
curl -s http://localhost:8000/api/debug/llm/health
```

预期：API 行为与接入前一致，日志无未捕获 tracing 异常。

### 6.3 启用 Langfuse 验证非流式调用

```bash
set -a; . ./.env.local; set +a; LANGFUSE_ENABLED=true PYTHONPATH=backend /Users/cengjiguang/.local/python3.12/bin/python3 -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

请求：

```bash
curl -s http://localhost:8000/api/debug/llm/health
```

预期：Langfuse 中出现 `llm.invoke` generation，metadata 包含 provider、model、attempt、max_tokens 等字段。

### 6.4 启用 Langfuse 验证流式调用

```bash
curl -N -X POST http://localhost:8000/api/textbook-learning/summary \
  -H "Content-Type: application/json" \
  -d '{"book_id":"<book_id>","lesson_id":"<lesson_id>","mode":"overview"}'
```

预期：SSE 正常输出，Langfuse 中出现 `llm.stream` generation，metadata 包含 `chunk_count`、`output_chars`、`emitted=true`。

### 6.5 现有 smoke test

```bash
python3 eval/history_character_smoke.py
```

预期：现有历史人物 smoke test 行为不因 tracing 改变。

## 7. 后续增强方向

### 7.1 API request trace

后续可在 `backend/api/main.py` 的核心 endpoint 中设置 request trace context，让多个 LLM generation 归属于同一个业务请求。

优先覆盖：

- `/api/history/character/chat`
- `/api/textbook-learning/ask`
- `/api/textbook-learning/summary`
- `/api/textbook-learning/quiz`
- `/api/history/games/timeline/start`
- `/api/history/card-game/start`
- `/api/history/multiplayer/start`

建议 trace metadata：

- `feature`
- `route`
- `session_id`
- `student_id`
- `round_id`
- `grade`
- `topic`
- `difficulty`
- `mode`

### 7.2 RAG span

后续可在 `backend/rag/knowledge_base.py` 的 `search(...)` 或 `BGERetriever.invoke(...)` 中增加 `rag.search` span。

建议记录：

- query
- collection
- k
- mode
- metadata_filter
- metadata_hints
- source_count
- source metadata preview

### 7.3 结构化输出 span

后续可在 `backend/structured_output.py` 中记录 JSON parse、schema validate 和 repair 结果，用于分析结构化输出失败率。

## 8. 注意事项

- 不要记录 API key、认证头、完整环境变量。
- 不要把估算 token 当作真实 token usage 上报。
- 不要在全局 middleware 中读取 request body，避免影响 FastAPI/Pydantic 和 SSE。
- 已经 emit chunk 的 streaming 调用失败后不要 fallback 到另一个模型。
- Langfuse 是观测链路，不得影响核心教学功能可用性。
