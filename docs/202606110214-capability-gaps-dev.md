# EduAgent 能力补齐开发文档

创建时间：2026-06-11

本文档根据 AI Agent 工程师技能对标分析，列出项目当前待补齐项及实现方案。按优先级排序。

---

## P0 安全与权限

**现状**：无权限层，无审计日志，无 Prompt Injection 防护。

### 1. API 权限中间件

在 `backend/api/main.py` 增加 Bearer Token 验证：

```python
# backend/auth.py
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

def require_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    token = (creds.token if creds else None) or ""
    if token != os.getenv("API_SECRET", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
```

在 `main.py` 各路由加 `dependencies=[Depends(require_auth)]`。

### 2. Prompt Injection 防护

在 `history_character.py` 的 `retrieve_facts` 入口处过滤用户输入：

```python
_INJECTION_PATTERNS = [
    r"ignore (previous|above|all) instructions?",
    r"system\s*prompt",
    r"你现在是",
    r"forget your",
]

def sanitize_input(text: str) -> str:
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            raise ValueError("Invalid input detected")
    return text[:2000]  # 硬截断防超长注入
```

### 3. 操作审计日志

```python
# backend/audit.py
import json, time, logging

_audit = logging.getLogger("audit")

def log_tool_call(user_id: str, tool: str, params: dict, result: str):
    _audit.info(json.dumps({
        "ts": time.time(), "user": user_id,
        "tool": tool, "params": params, "result": result[:200]
    }, ensure_ascii=False))
```

在每个 agent 工具调用前后调用 `log_tool_call`。

---

## P0 评测体系自动化

**现状**：`eval/` 目录有框架，缺 golden dataset 和 CI 集成。

### 1. Golden Dataset 建立

创建 `eval/datasets/history_character_golden.json`：

```json
[
  {
    "id": "hc_001",
    "character": "孔子",
    "question": "您为什么周游列国？",
    "must_contain": ["仁政", "礼"],
    "must_not_contain": ["不知道", "无法回答"],
    "source_required": true
  }
]
```

每个人物最少 5 条，覆盖：事实问答、反事实问答、来源追溯三类。

### 2. 自动评测脚本

扩展 `eval/history_character_eval.py`，使用 LLM-as-a-judge：

```python
# eval/run_core_evals.py 补充
JUDGE_PROMPT = """评估以下回答是否满足要求（返回 JSON）：
问题：{question}
回答：{answer}
要求：必须包含 {must_contain}，不得出现 {must_not_contain}
返回：{{"pass": bool, "reason": str}}"""

def judge_answer(case: dict, answer: str) -> dict:
    resp = llm_fast.invoke(JUDGE_PROMPT.format(**case, answer=answer))
    return json.loads(resp.content)
```

### 3. Makefile 集成

```makefile
# 在项目根添加 Makefile
eval:
	PYTHONPATH=backend python3 eval/run_core_evals.py

eval-rag:
	PYTHONPATH=backend python3 eval/rag_retrieval_eval.py
```

---

## P1 RAG 能力增强

**现状**：基础向量检索 + 关键词混合，缺 rerank 和 multi-query。

### 1. Rerank 阶段

在 `backend/rag/knowledge_base.py` 的 `search_with_scores` 后增加：

```python
# backend/rag/rerank.py
from langchain_community.cross_encoders import HuggingFaceCrossEncoder

_reranker = None

def get_reranker():
    global _reranker
    if _reranker is None:
        model_path = os.getenv("RERANK_MODEL_PATH", "")
        if model_path:
            _reranker = HuggingFaceCrossEncoder(model_name=model_path)
    return _reranker

def rerank(query: str, docs: list[ScoredDocument], top_k: int = 5) -> list[ScoredDocument]:
    reranker = get_reranker()
    if not reranker:
        return docs[:top_k]
    pairs = [(query, d["document"].page_content) for d in docs]
    scores = reranker.score(pairs)
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    return [d for _, d in ranked[:top_k]]
```

在 `search_with_scores` 末尾调用 `rerank(query, results)`。

### 2. Multi-Query Retrieval

在 `history_character.py` 的 `retrieve_facts` 中：

```python
def _expand_queries(character: str, question: str) -> list[str]:
    prompt = (f"为以下问题生成3个不同角度的检索查询，每行一个，只输出查询：\n"
              f"人物：{character} 问题：{question}")
    resp = llm.invoke([{"role": "user", "content": prompt}])
    queries = [q.strip() for q in resp.content.strip().split("\n") if q.strip()]
    return queries[:3] or [question]
```

对每个查询执行检索后去重合并，按 score 取 top-8。

### 3. 增量索引

在 `build_index.py` 增加 `--incremental` 模式，对比 corpus 文件 mtime 和 Chroma collection 最后更新时间，只重建变化的 collection。

---

## P1 Human-in-the-loop UI 接入

**现状**：`essay_grader.py` 标记了 `needs_human_review`，但 API 和前端未处理。

### 后端：新增 API 路由

```python
# 在 main.py 补充
@app.post("/api/chinese/essay/review-result")
async def submit_review(session_id: str, approved: bool, teacher_comments: str = ""):
    # 写入 session store，供后续 Agent 节点读取
    msgs = load_messages(session_id)
    msgs.append({"role": "system", "content": f"[教师复核] approved={approved} {teacher_comments}"})
    save_messages(session_id, msgs)
    return {"status": "ok"}
```

### 前端：教师复核组件

在作文批改页面，当响应包含 `needs_human_review: true` 时展示：

```tsx
// frontend/app/essay/ReviewBanner.tsx
export function ReviewBanner({ reason, sessionId }: { reason: string; sessionId: string }) {
  const [submitted, setSubmitted] = useState(false);
  const submit = async (approved: boolean) => {
    await fetch(`${API_BASE}/api/chinese/essay/review-result`, {
      method: "POST",
      body: new URLSearchParams({ session_id: sessionId, approved: String(approved) }),
    });
    setSubmitted(true);
  };
  if (submitted) return <p>已提交复核结果</p>;
  return (
    <div className="review-banner">
      <p>建议教师复核：{reason}</p>
      <button onClick={() => submit(true)}>确认通过</button>
      <button onClick={() => submit(false)}>需修改</button>
    </div>
  );
}
```

---

## P2 长期记忆系统完善

**现状**：`user_memory.py` 有 `enrich_hints_with_memory`，结构不明确。

### 设计目标

```
user_memory 存储：
- 学生偏好人物、偏好话题
- 历史互动记录摘要（按人物）
- 薄弱知识点标记
```

### 实现方案

```python
# backend/user_memory.py 补充
class UserMemory(TypedDict):
    student_id: str
    favorite_characters: list[str]
    weak_topics: list[str]
    interaction_summary: dict[str, str]  # character -> summary
    updated_at: float

def update_memory_after_chat(student_id: str, character: str, messages: list[dict]):
    mem = load_memory(student_id)
    if character not in (mem.get("favorite_characters") or []):
        mem.setdefault("favorite_characters", []).append(character)
    # 超过 5 轮更新该人物摘要
    if len(messages) >= 10:
        summary = _summarize_for_memory(character, messages)
        mem.setdefault("interaction_summary", {})[character] = summary
    mem["updated_at"] = time.time()
    save_memory(student_id, mem)
```

记忆过期：`updated_at` 超过 30 天的条目在读取时自动清理。

---

## P2 Docker 化与部署

**现状**：无 Dockerfile，本地路径硬编码（embedding 模型路径已改为环境变量，其余需核查）。

### Dockerfile（后端）

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
ENV PYTHONPATH=/app
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml（根目录）

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  backend:
    build: { context: ., dockerfile: backend/Dockerfile }
    ports: ["8000:8000"]
    env_file: .env.local
    volumes:
      - ./.chroma:/app/.chroma
      - ${EMBED_MODEL_PATH}:${EMBED_MODEL_PATH}:ro
    depends_on: [redis]

  frontend:
    build: { context: frontend }
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_BASE_URL: http://backend:8000
    depends_on: [backend]
```

---

## P3 前端 Agent 执行步骤可视化

**现状**：SSE 有 `status`、`sources`、`delta`、`final`、`fact_card` 事件，但 `status` 事件未在 UI 中可视化展示。

### 方案

在 `frontend/app/history-character/page.tsx` 中，接收到 `status` 事件时追加到步骤列表：

```tsx
const [steps, setSteps] = useState<string[]>([]);

// 在 SSE 处理器中
if (event === "status") {
  setSteps(prev => [...prev, data.message]);
}

// 渲染
<div className="agent-steps">
  {steps.map((s, i) => <div key={i} className="step-item">⋯ {s}</div>)}
</div>
```

---

## 实施顺序建议

| 周次 | 任务 |
|------|------|
| Week 1 | P0：API 权限中间件 + Prompt Injection 防护 |
| Week 1 | P0：Golden dataset 建立 + 评测脚本自动化 |
| Week 2 | P1：RAG Rerank + Multi-query |
| Week 2 | P1：Human-in-the-loop API + 前端组件 |
| Week 3 | P2：长期记忆完善 + Docker 化 |
| Week 3 | P3：Agent 步骤可视化 |
