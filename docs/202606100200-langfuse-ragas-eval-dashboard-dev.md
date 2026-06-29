# Langfuse 链路串联 + Ragas 评估补齐开发文档

## 1. 现状差距

| 项目 | 状态 | 问题 |
|------|------|------|
| Langfuse 基础设施 (`backend/tracing.py`) | 完成 | — |
| LLM generation 记录 (`backend/llm_config.py`) | 完成 | — |
| RAG span (`backend/rag/knowledge_base.py`) | 完成 | — |
| **Request-level trace context** | **未完成** | `_current_trace` ContextVar 永远是 `None`，span/generation 不挂在同一条 trace 下 |
| **Ragas 评估** | **未完成** | `ragas>=0.2.0` 已声明，但无任何代码使用；`eval/` 下全为自定义 keyword 指标 |
| **Eval 可视化界面** | **未完成** | 无 UI 查看 eval 结果 |

---

## 2. Langfuse 链路串联补齐

### 2.1 已有 `trace_context` 调用

`backend/api/main.py` 已在全部核心路由中调用 `trace_context`，包括：
- `GET /api/debug/llm/health`
- `POST /api/history/games/timeline/start`
- `POST /api/history/card-game/start`
- `POST /api/history/multiplayer/start`
- `POST /api/textbook-learning/ask`
- `POST /api/textbook-learning/summary`
- `POST /api/textbook-learning/quiz`
- `POST /api/learning/assistant/chat`
- `POST /api/history/character/recommend`
- `POST /api/history/character/chat`

**实际链路串联已完成**，每个请求会设置 `_current_trace` ContextVar，后续 LLM generation 和 RAG span 会自动挂在该 trace 下。

### 2.2 验证方法

```bash
# 1. 启动服务（需配置 .env.local）
set -a; . ./.env.local; set +a
LANGFUSE_ENABLED=true npm run dev:backend

# 2. 发一条历史人物对话请求
curl -N -X POST http://localhost:8000/api/history/character/chat \
  -H "Content-Type: application/json" \
  -d '{"character":"秦始皇","message":"你为什么要修长城？","session_id":"test-001"}'

# 3. 在 Langfuse UI 中确认
# - 出现一条 trace: "POST /api/history/character/chat"
# - trace 下挂有 generation: "llm.stream" 和 span: "rag.search"
```

### 2.3 缺失覆盖：`/api/history/character/chat` 内部 SSE 流

`stream_character_response` 是异步生成器，`trace_context` 是同步 contextmanager，需要确保 `_current_trace` ContextVar 在生成器帧内可见。当前实现用 `with trace_context(...)` 包裹整个 SSE 生成器函数体，**已正确传递**，无需修改。

### 2.4 环境变量（`.env.local`）

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com   # 或自托管地址
LANGFUSE_ENVIRONMENT=local
LANGFUSE_RELEASE=edu-agent-local
LANGFUSE_CAPTURE_INPUT=true
LANGFUSE_CAPTURE_OUTPUT=true
```

---

## 3. Ragas 评估接入

### 3.1 适用场景

Ragas 评估 RAG pipeline 质量，适合以下两类评估：

| 场景 | 对应 eval 文件 | Ragas 指标 |
|------|--------------|-----------|
| 历史人物对话（历史知识问答） | `eval/history_character_eval.py` | `faithfulness`, `answer_relevancy`, `context_recall` |
| 教材 QA (`/textbook-learning/ask`) | `eval/textbook_qa_eval.py` | `faithfulness`, `answer_relevancy` |
| RAG 检索质量 | `eval/rag_retrieval_eval.py` | `context_precision`, `context_recall` |

### 3.2 新增文件

**`eval/ragas_eval.py`** — 独立 Ragas 评估脚本：

```
eval/
  ragas_eval.py          ← 新增：运行 Ragas 指标评估
  datasets/
    ragas_cases.json     ← 新增：包含 question/answer/contexts/ground_truth 的测试集
```

### 3.3 `eval/datasets/ragas_cases.json` 格式

```json
[
  {
    "name": "秦始皇修长城动机",
    "question": "秦始皇为什么修长城？",
    "ground_truth": "为了抵御北方匈奴的入侵，保护中原农业文明。",
    "contexts": [],        // 留空时由脚本自动从 RAG 检索填充
    "answer": ""           // 留空时由脚本自动通过 LLM 生成填充
  }
]
```

### 3.4 `eval/ragas_eval.py` 实现要点

```python
# 核心流程：
# 1. 对每个 case，如果 contexts 为空 → 调用 search_with_scores("history", question, k=5)
# 2. 如果 answer 为空 → 调用 llm_quality.invoke([...]) 生成回答
# 3. 构建 ragas Dataset
# 4. 运行 evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_recall])
# 5. 打印每条 case 的指标分数 + 汇总均值
# 6. 可选：通过 langfuse_client.score() 将指标上报到 Langfuse
```

### 3.5 Langfuse 指标上报（可选）

```python
from langfuse import Langfuse
lf = Langfuse(...)
lf.score(
    trace_id=trace_id,          # 需与 eval 时的 trace 关联
    name="ragas/faithfulness",
    value=score,
    comment="auto eval",
)
```

### 3.6 运行方式

```bash
# 需配置 LLM 环境变量（同正常后端启动）
PYTHONPATH=backend python3 eval/ragas_eval.py

# 也可通过统一 eval runner 运行（需在 run_core_evals.py 中注册）
python3 eval/run_core_evals.py --suite ragas_eval
```

---

## 4. Eval 可视化界面

### 4.1 方案

在 `backend/api/main.py` 增加 `POST /api/eval/run` 接口，在 `frontend/app/eval/` 新增查看页面。

**接口职责：**
- 接收 suite 名称（或 `quick` / `all`）
- 后台调用 `eval/run_core_evals.py` 的 `run_suite()`
- 返回 JSON 格式的 suite 结果（复用 `SuiteResult.to_dict()`）

**前端页面职责：**
- 列出所有可用 suite
- 一键运行选定 suite（或 quick / all）
- 展示每个 case 的 OK/FAIL 状态
- 展示各项指标通过率

### 4.2 新增/修改文件

| 文件 | 操作 |
|------|------|
| `backend/api/main.py` | 新增 `POST /api/eval/run` |
| `frontend/app/eval/page.tsx` | 新增 eval 查看页 |

---

## 5. 实施顺序

1. **立即可用**：Langfuse 链路串联已完成，配置 `.env.local` 即可观测。
2. **Eval 界面**（本次已实现）：`/eval` 页面可运行 eval suite 并查看结果。
3. **Ragas 接入**（后续）：补充 `eval/datasets/ragas_cases.json` + `eval/ragas_eval.py`。

---

## 6. 注意事项

- Ragas 的 `LLMasJudge` 指标（`faithfulness`、`answer_relevancy`）会消耗真实 LLM tokens，不要在 CI 中高频运行。
- Langfuse 的 `score()` 上报需要关联 `trace_id`，eval 脚本运行时需开启 `LANGFUSE_ENABLED=true` 并在 eval 流程中读取 trace 对象。
- 不要把 Ragas 指标当作绝对标准，结合当前 keyword hit rate 指标一起看，防止 LLM 自我循环打高分。
