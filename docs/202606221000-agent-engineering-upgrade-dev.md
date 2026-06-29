# EduAgent 工程能力升级开发文档

**创建时间：** 2026-06-22  
**背景：** 基于 AI Agent 工程师技能文档（`docs/ai-agent-engineer-skills.md`）与当前 2026 年线上岗位要求，项目已具备垂直教育场景、LangGraph 工作流、RAG、流式 UX 和 Langfuse tracing 等核心基础。本文档规划把项目从「功能完整」升级为「可评测、可观测、可治理」的下一阶段开发路线。

---

## 整体目标

```
现状：有功能 → 目标：有功能 + 可量化 + 可观测 + 可治理
```

---

## 第一优先级：Evaluation Engineering（1-2 周）

**目标：** 把现有 smoke test 升级为输出量化指标的标准 eval harness，这是区分「Demo 开发者」和「AI Agent 工程师」的最直接能力证明。

### 1.1 建立统一 eval runner

**文件：** `eval/run_eval.py`

输出标准化 JSON 指标：

```json
{
  "suite": "history_character",
  "timestamp": "2026-06-22T10:00:00Z",
  "summary": {
    "task_success_rate": 0.88,
    "retrieval_hit_rate": 0.82,
    "source_correctness": 0.79,
    "hallucination_rate": 0.05,
    "avg_latency_ms": 1240,
    "avg_cost_usd": 0.0032,
    "format_valid_rate": 1.0
  },
  "cases": [...]
}
```

**需要新增的指标维度：**

| 指标 | 说明 | 采集方式 |
|------|------|---------|
| task_success_rate | 最终回答是否完成目标任务 | LLM-as-judge 或规则 |
| retrieval_hit_rate | 检索到的文档是否包含正确答案 | 与 golden chunk 对比 |
| source_correctness | 输出引用是否来自检索结果 | 规则校验 |
| hallucination_rate | 输出是否包含检索结果之外的事实 | LLM-as-judge |
| avg_latency_ms | 端到端响应时间 | 时间戳差 |
| avg_cost_usd | 模型调用费用 | token 数 × 单价 |
| format_valid_rate | 结构化输出格式是否合法 | Pydantic 校验 |

### 1.2 为核心场景建立 golden dataset

**文件位置：** `eval/datasets/`

需要建立的数据集：

- `eval/datasets/history_character_golden.json` — 历史角色问答，含预期引用文档、预期格式
- `eval/datasets/material_rag_golden.json` — 材料问答，含预期检索命中
- `eval/datasets/learning_assistant_tools_golden.json` — 工具调用，含预期工具名称和参数

每条 case 格式：

```json
{
  "id": "hc_001",
  "input": "唐太宗为什么推行均田制？",
  "expected_tool_calls": [],
  "expected_sources": ["唐朝土地制度", "贞观之治"],
  "expected_contains": ["均田", "府兵"],
  "judge_criteria": "回答需基于检索内容，说明均田制的经济背景"
}
```

### 1.3 Trajectory eval — 工具调用准确率

针对 `learning_assistant` 的工具调用场景：

- 工具选择是否正确（是否调用了预期工具）
- 参数是否正确（关键字段有无缺失或错误）
- 是否有多调/漏调
- 工具失败后是否正确处理

**文件：** `eval/trajectory_eval.py`

---

## 第二优先级：Schema-first Tool Calling（1 周）

**目标：** 把 `tools/registry.py` 从「应用侧模拟工具调用」升级为「provider-native、schema 约束、标准化返回」的生产级工具编排。

### 2.1 为每个工具定义 Pydantic schema

**文件：** `backend/tools/schemas.py`

```python
from pydantic import BaseModel, Field

class SearchKnowledgeBaseInput(BaseModel):
    query: str = Field(..., description="检索查询词，中文")
    top_k: int = Field(5, ge=1, le=20)
    collection: str = Field("history", description="知识库名称")

class ToolOutput(BaseModel):
    ok: bool
    data: dict | list | None = None
    error_code: str | None = None   # PARAM_ERROR | PERMISSION_DENIED | TIMEOUT | SERVICE_ERROR
    message: str | None = None
    trace_id: str | None = None
```

### 2.2 工具风险等级标注

在 `tools/registry.py` 中为每个工具增加 `risk_level` 字段：

| 风险等级 | 示例工具 | 处理策略 |
|---------|---------|---------|
| `read` | 知识库检索、学情查询 | 直接执行 |
| `write` | 保存笔记、更新学情 | 记录审计日志 |
| `external` | 搜索引擎、外部 API | 限流 + 日志 |
| `destructive` | 删除数据 | 后端强制确认，不依赖 prompt |

### 2.3 工具执行拦截层

```python
# backend/tools/executor.py
async def execute_tool(tool_name, args, context):
    tool = registry[tool_name]
    validated = tool.input_schema(**args)           # Pydantic 校验

    if tool.risk_level != "read":
        await audit_log.record(tool_name, validated, context)

    if tool.risk_level == "destructive":
        if not context.confirmed:
            return ToolOutput(ok=False, error_code="CONFIRMATION_REQUIRED")

    return await tool.execute(validated)
```

---

## 第三优先级：AgentOps 闭环可视化（3-5 天）

**目标：** 让 Langfuse trace 数据变成可展示的成本/延迟/质量数字。

### 3.1 统一 trace 字段规范

在 `backend/tracing.py` 确保每次 trace 包含：

```python
{
    "session_id": str,
    "user_id": str,
    "agent_name": str,       # "history_character" | "learning_assistant" | ...
    "tool_calls": list,      # [{tool_name, input, output, latency_ms, ok}]
    "retrieval_docs": list,  # [{source, score}]
    "model": str,
    "input_tokens": int,
    "output_tokens": int,
    "latency_ms": int,
    "cost_usd": float,
    "success": bool,
    "error": str | None
}
```

### 3.2 成本估算工具

**文件：** `backend/utils/cost_estimator.py`

```python
PRICE_TABLE = {
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.0},   # per 1M tokens USD
    "claude-sonnet-4-6":         {"input": 3.0,   "output": 15.0},
    "claude-opus-4-8":           {"input": 15.0,  "output": 75.0},
}

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICE_TABLE.get(model, {"input": 3.0, "output": 15.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
```

### 3.3 metrics 导出脚本

**文件：** `eval/export_metrics.py`

从 Langfuse 拉取最近 N 天 trace，输出：
- 按 agent 分组的 avg_latency / avg_cost / success_rate
- 失败 trace 列表（可转为 eval case）
- token 消耗趋势

---

## 第四优先级：Runtime Guardrails 加强（3-5 天）

**目标：** 安全控制从「prompt 层提醒」升级为「后端强制执行」。

### 4.1 Prompt Injection 测试集

**文件：** `eval/security/prompt_injection_cases.json`

覆盖场景：
- RAG 检索内容中嵌入指令（indirect prompt injection）
- 用户输入包含角色切换指令
- 工具返回值包含恶意指令

### 4.2 RAG 输出引用校验

生成回答时验证：模型引用的内容是否确实存在于检索结果中，不在则标记 `unverified`。

---

## 第五优先级：CI/CD 基础（1 周）

**文件：** `.github/workflows/ci.yml`

触发：push main / PR

```yaml
steps:
  - npm run lint --prefix frontend
  - npm run build --prefix frontend
  - python3 -m py_compile backend/api/main.py
  - python3 eval/run_eval.py --suite smoke --fail-threshold 0.8
  - docker build backend/ -t eduagent-backend
```

补充 `.env.example` 每个变量的用途和必填/可选标注。

---

## 开发排期

```
Week 1：
  Day 1-2  golden dataset（history_character + material_rag）
  Day 3-4  eval runner + 量化指标 JSON 输出
  Day 5    trajectory eval（工具调用准确率）

Week 2：
  Day 1-2  tools Pydantic schema + 标准化返回
  Day 3    工具风险等级 + 执行拦截层
  Day 4-5  Langfuse 字段规范 + cost_estimator

Week 3：
  Day 1-2  metrics 导出脚本
  Day 3    prompt injection 测试集
  Day 4-5  GitHub Actions CI
```

---

## 完成后求职展示矩阵

| 展示点 | 对应岗位能力 | 量化证据 |
|--------|------------|---------|
| LangGraph 状态图 Agent | Agent workflow、状态机 | 代码结构 |
| Chroma + BGE + sources | RAG、引用可追溯 | retrieval_hit_rate 数字 |
| Pydantic schema tool calling | Schema-first 工具编排 | 工具定义文件 |
| Langfuse trace + cost_estimator | Observability、AgentOps | cost/latency 导出数据 |
| eval golden dataset + runner | Evaluation engineering | task_success_rate 数字 |
| trajectory eval | 工具调用准确率评测 | tool_call_accuracy 数字 |
| prompt injection 测试集 | Runtime safety | 安全评测通过率 |
| GitHub Actions CI | 生产交付能力 | 流水线截图 |
