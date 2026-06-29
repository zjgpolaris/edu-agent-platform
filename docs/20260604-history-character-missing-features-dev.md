# 虚拟历史人物对话——缺失功能开发文档

> 模块：模块1 虚拟历史人物对话 | 日期：2026-06-04 | 状态：待开发

---

## 背景

当前 `history_character.py` 已实现 RAG + Role-playing + Reflection 核心骨架，但以下三项 PRD 需求尚未落地。

---

## 待实现功能

### 1. History Counterfactual 模式

**PRD 要求**：支持学生追问"如果你知道结局会怎样？"，以推演模式回答并明确标注。

**实现方案**

在 `CharacterState` 增加 `mode` 字段，由前端请求传入或由 Agent 自动识别：

```python
# history_character.py

COUNTERFACTUAL_TRIGGERS = ["如果", "假如", "要是", "若是", "倘若", "知道结局"]

def detect_mode(message: str) -> str:
    return "counterfactual" if any(t in message for t in COUNTERFACTUAL_TRIGGERS) else "factual"
```

在 `build_generation_messages` 中按 mode 切换 system prompt：

```python
if state.get("mode") == "counterfactual":
    mode_instruction = (
        "本次问题属于【历史推演模式】。\n"
        "你可以基于史料做合理推断，但必须：\n"
        "1. 在回答开头标注：⚠️ 以下为历史推演，非史实。\n"
        "2. 每处推断标注（推演）字样。\n"
        "3. 回答结尾保留【史料依据】说明推演的历史基础。\n"
    )
else:
    mode_instruction = "本次问题属于【史实问答模式】，只能基于史料回答。\n"
```

`CharacterRequest` 增加可选字段，也支持后端自动检测：

```python
class CharacterRequest(BaseModel):
    ...
    mode: str | None = None  # "factual" | "counterfactual" | None（自动检测）
```

`build_character_state` 中自动检测并写入 state：

```python
def build_character_state(req: CharacterRequest) -> dict:
    mode = req.mode or detect_mode(req.message)
    return {
        ...
        "mode": mode,
    }
```

API 响应带上 mode 字段，前端据此渲染推演标识：

```python
yield {"event": "final", "data": {..., "mode": state.get("mode", "factual")}}
```

---

### 2. 对话结束自动生成"史实速览"卡片

**PRD 要求**：每次对话结束后自动生成结构化史实卡片。

**卡片结构**

```json
{
  "character": "商鞅",
  "question_summary": "商鞅变法的主要内容",
  "key_facts": ["废井田、开阡陌", "军功爵制", "县制推行"],
  "sources": ["人教版七年级上册第6课", "史记·商君列传"],
  "mode": "factual",
  "generated_at": "2026-06-04T10:00:00Z"
}
```

**实现方案**

在 `stream_character_response` 的 final 事件后新增 `generate_fact_card` 步骤：

```python
CARD_PROMPT = (
    "根据以下历史教学对话，提取关键史实，生成JSON格式的史实速览卡片。\n"
    "字段：key_facts（列表，≤5条，每条≤20字）、question_summary（≤30字）。\n"
    "只输出JSON，不要其他内容。\n\n"
    "问题：{question}\n史料依据：{facts}\n模拟回答：{response}"
)

def generate_fact_card(state: CharacterState) -> dict:
    import json as _json
    from datetime import datetime, timezone
    prompt = CARD_PROMPT.format(
        question=state["messages"][-1]["content"],
        facts="\n".join(state["retrieved_facts"][:3]),
        response=state["response_draft"][:500],
    )
    raw = llm.invoke([{"role": "user", "content": prompt}]).content
    try:
        card_data = _json.loads(raw)
    except Exception:
        card_data = {"key_facts": [], "question_summary": ""}
    return {
        "character": state["character"],
        "question_summary": card_data.get("question_summary", ""),
        "key_facts": card_data.get("key_facts", []),
        "sources": [s["source"] for s in state.get("retrieved_sources", []) if s.get("source")],
        "mode": state.get("mode", "factual"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
```

在 `stream_character_response` 末尾 final 事件后追加：

```python
fact_card = generate_fact_card(state)
yield {"event": "fact_card", "data": {"card": fact_card}}
```

API 层透传该事件：

```python
elif event == "fact_card":
    yield sse_frame("fact_card", data)
```

---

### 3. 多轮对话记忆（session_id 落地）

**PRD 要求**：支持持续对话，角色保持上下文一致性。当前 `session_id` 已在请求中接收但未使用。

**实现方案**

用 Redis 存储每个 session 的消息历史（复用 PRD 选型中的 Redis）：

```python
# session_store.py
import json
import redis

_r = redis.Redis(host="localhost", port=6379, decode_responses=True)
SESSION_TTL = 3600  # 1小时

def load_messages(session_id: str) -> list[dict]:
    raw = _r.get(f"session:{session_id}")
    return json.loads(raw) if raw else []

def save_messages(session_id: str, messages: list[dict]):
    _r.setex(f"session:{session_id}", SESSION_TTL, json.dumps(messages, ensure_ascii=False))
```

`build_character_state` 中合并历史消息：

```python
from session_store import load_messages, save_messages

def build_character_state(req: CharacterRequest) -> dict:
    mode = req.mode or detect_mode(req.message)
    history = load_messages(req.session_id) if req.session_id else []
    # 截取最近8轮防止 token 超限
    messages = history[-16:] + [{"role": "user", "content": req.message}]
    return {
        "character": req.character,
        "messages": messages,
        "retrieved_facts": [],
        "retrieved_sources": [],
        "response_draft": "",
        "verified": False,
        "mode": mode,
    }
```

对话结束后保存 assistant 回复：

```python
# character_chat 路由，final 事件处理后
if req.session_id and final_response:
    history = load_messages(req.session_id)
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": final_response})
    save_messages(req.session_id, history)
```

流式场景下在 `event_stream` 中捕获 final 事件并回写：

```python
async def event_stream():
    final_response = None
    for item in stream_character_response(state, retriever):
        ...
        if event == "final":
            final_response = data.get("response", "")
            yield sse_frame("final", data)
    if req.session_id and final_response:
        history = load_messages(req.session_id)
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": final_response})
        save_messages(req.session_id, history)
```

---

## 修改文件清单

| 文件 | 改动内容 |
|------|---------|
| `backend/agents/history_character.py` | 增加 mode 字段、counterfactual prompt、`generate_fact_card`、fact_card 事件 |
| `backend/api/main.py` | `build_character_state` 集成 mode 检测和 session 历史；透传 fact_card 事件；写回 session |
| `backend/session_store.py` | 新文件，Redis session 管理 |

---

## 开发顺序建议

1. **session 记忆**（独立，不依赖其他两项，影响所有后续对话质量）
2. **Counterfactual 模式**（依赖 state.mode，建立后 card 也能带上 mode 标注）
3. **史实速览卡片**（依赖 final response，最后接入）
