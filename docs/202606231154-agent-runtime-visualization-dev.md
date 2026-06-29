# Agent Runtime 可视化开发文档

**创建时间：** 2026-06-23
**迭代目标：** 实现 Agent 执行过程可视化，让 Agent runtime 可观察
**预计工期：** 1-2 周

---

## 一、功能概述

### 1.1 背景

当前 EduAgent 已有多个 Agent（历史人物对话、学习助手、作文批改等），但 Agent 执行过程对用户和开发者来说是黑盒。无法看到：
- Agent 当前在做什么
- 工具调用的入参和出参
- 检索到了哪些资料
- 每个步骤的耗时和状态

### 1.2 目标

为学习助手、历史角色对话等核心 Agent 增加可视化执行轨迹，让用户能看到一次 Agent 请求背后的完整过程。

### 1.3 展示内容

每次请求生成一个 `trace_id`，前端展示：
- 用户输入
- Agent 名称
- 当前 step
- 意图识别结果
- 检索到的资料
- 工具选择
- 工具入参
- 工具返回
- LLM 模型名称
- 是否写入 memory / student profile
- 最终回答
- 总耗时
- 成功 / 失败状态

---

## 二、技术方案

### 2.1 统一 Trace Event Schema

**文件：** `backend/tracing.py`（扩展）

```python
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

@dataclass
class TraceEvent:
    trace_id: str
    agent_name: str
    step_name: str
    event_type: str  # "start", "intent", "retrieval", "tool_start", "tool_result", "llm", "memory", "end", "error"
    status: str  # "success", "pending", "error"
    latency_ms: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_sse(self) -> str:
        """转换为 SSE 事件格式"""
        data = asdict(self)
        return f"event: trace\ndata: {json.dumps(data)}\n\n"
```

### 2.2 Trace Store

**文件：** `backend/trace_store.py`（新建）

```python
from typing import Dict, List, Optional
from collections import defaultdict
import threading

class TraceStore:
    """内存中的 trace 存储，用于前端查询"""
    def __init__(self):
        self._traces: Dict[str, List[dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def add_event(self, trace_id: str, event: dict):
        with self._lock:
            self._traces[trace_id].append(event)

    def get_trace(self, trace_id: str) -> List[dict]:
        with self._lock:
            return self._traces.get(trace_id, [])

    def cleanup_old(self, ttl_seconds: int = 3600):
        """清理过期 trace"""
        # 实现清理逻辑
        pass

_trace_store = TraceStore()

def get_trace_store() -> TraceStore:
    return _trace_store
```

### 2.3 API 接口

**文件：** `backend/api/main.py`（新增）

```python
from pydantic import BaseModel
from trace_store import get_trace_store

class TraceResponse(BaseModel):
    trace_id: str
    events: list[dict]

@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """获取指定 trace 的完整事件序列"""
    store = get_trace_store()
    events = store.get_trace(trace_id)
    return TraceResponse(trace_id=trace_id, events=events)
```

---

## 三、后端改动

### 3.1 学习助手 Agent 集成

**文件：** `backend/agents/learning_assistant.py`

```python
from tracing import TraceEvent, emit_trace_event
from trace_store import get_trace_store

async def learning_assistant_chat(request: LearningAssistantRequest):
    trace_id = str(uuid.uuid4())

    # Step 1: Start
    emit_trace_event(TraceEvent(
        trace_id=trace_id,
        agent_name="learning_assistant",
        step_name="receive_query",
        event_type="start",
        status="success",
        metadata={"query": request.query}
    ))

    # Step 2: Intent Detection
    start = time.time()
    intent = detect_intent(request.query)
    emit_trace_event(TraceEvent(
        trace_id=trace_id,
        agent_name="learning_assistant",
        step_name="intent_detection",
        event_type="intent",
        status="success",
        latency_ms=int((time.time() - start) * 1000),
        metadata={"intent": intent, "confidence": 0.86}
    ))

    # Step 3: Tool Execution (如果有工具调用)
    if intent == "material_qa":
        emit_trace_event(TraceEvent(
            trace_id=trace_id,
            agent_name="learning_assistant",
            step_name="tool_selection",
            event_type="tool_start",
            status="pending",
            metadata={"tool_name": "search_material", "risk_level": "low"}
        ))

        # 执行工具
        result = await execute_tool(...)
        emit_trace_event(TraceEvent(
            trace_id=trace_id,
            agent_name="learning_assistant",
            step_name="tool_execution",
            event_type="tool_result",
            status="success",
            latency_ms=tool_latency,
            metadata={"tool_name": "search_material", "result_summary": "..."}
        ))

    # ... 其他步骤

    # 返回 trace_id 给前端
    return {"answer": "...", "trace_id": trace_id}
```

### 3.2 历史人物对话 Agent 集成

**文件：** `backend/agents/history_character.py`

类似地，在历史人物对话 Agent 中集成 trace 事件。

---

## 四、前端改动

### 4.1 Trace Timeline 组件

**文件：** `frontend/components/TraceTimeline.tsx`（新建）

```tsx
"use client"

import { useState, useEffect } from "react"

interface TraceEvent {
  trace_id: string
  agent_name: string
  step_name: string
  event_type: string
  status: string
  latency_ms?: number
  metadata?: Record<string, any>
  timestamp: string
}

interface TraceTimelineProps {
  traceId: string | null
}

export function TraceTimeline({ traceId }: TraceTimelineProps) {
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!traceId) return

    setLoading(true)
    fetch(`/api/traces/${traceId}`)
      .then(res => res.json())
      .then(data => setEvents(data.events))
      .finally(() => setLoading(false))
  }, [traceId])

  if (!traceId) return null

  return (
    <div className="trace-timeline">
      <h3>Agent 执行轨迹</h3>
      {loading ? (
        <p>加载中...</p>
      ) : (
        <div className="timeline">
          {events.map((event, i) => (
            <div key={i} className={`timeline-item status-${event.status}`}>
              <div className="step-name">{event.step_name}</div>
              <div className="event-type">{event.event_type}</div>
              {event.latency_ms && (
                <div className="latency">{event.latency_ms}ms</div>
              )}
              {event.metadata && (
                <div className="metadata">
                  {Object.entries(event.metadata).map(([k, v]) => (
                    <div key={k} className="metadata-item">
                      <span className="key">{k}:</span>
                      <span className="value">{String(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

### 4.2 学习助手页面集成

**文件：** `frontend/app/learning-assistant/page.tsx`

```tsx
import { TraceTimeline } from "@/components/TraceTimeline"

export default function LearningAssistantPage() {
  const [traceId, setTraceId] = useState<string | null>(null)

  // 发送消息后获取 trace_id
  const handleSendMessage = async (message: string) => {
    const response = await fetch("/api/learning/assistant/chat", {
      method: "POST",
      body: JSON.stringify({ query: message })
    })
    const data = await response.json()
    setTraceId(data.trace_id)
  }

  return (
    <div>
      {/* ... 现有 UI ... */}
      {traceId && <TraceTimeline traceId={traceId} />}
    </div>
  )
}
```

---

## 五、样式

**文件：** `frontend/app/globals.css`（添加）

```css
.trace-timeline {
  margin-top: 20px;
  padding: 16px;
  background: #f5f5f5;
  border-radius: 8px;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-item {
  padding: 12px;
  background: white;
  border-radius: 4px;
  border-left: 4px solid #ccc;
}

.timeline-item.status-success {
  border-left-color: #10b981;
}

.timeline-item.status-error {
  border-left-color: #ef4444;
}

.timeline-item.status-pending {
  border-left-color: #f59e0b;
}

.step-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.event-type {
  font-size: 0.875rem;
  color: #666;
}

.latency {
  font-size: 0.75rem;
  color: #999;
  margin-top: 4px;
}

.metadata {
  margin-top: 8px;
  padding: 8px;
  background: #f9f9f9;
  border-radius: 4px;
  font-size: 0.875rem;
}

.metadata-item {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.metadata-item .key {
  color: #666;
}

.metadata-item .value {
  color: #333;
}
```

---

## 六、测试计划

### 6.1 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| Trace Event 序列化 | `eval/trace_event_smoke.py` | 确认 trace event 能正确序列化为 SSE |
| Trace Store 基本操作 | `eval/trace_store_smoke.py` | 确认 trace store 能正确存储和检索 |

### 6.2 集成测试

1. **学习助手流程**
   - 发送消息 → 获取 trace_id → 查询 trace → 验证事件序列正确

2. **历史人物对话流程**
   - 发送消息 → 获取 trace_id → 查询 trace → 验证事件序列正确

---

## 七、验收标准

- [x] TraceEvent 数据结构定义完成
- [ ] TraceStore 实现完成
- [ ] GET /api/traces/{trace_id} 接口实现
- [ ] 学习助手 Agent 集成 trace 事件
- [ ] 历史人物对话 Agent 集成 trace 事件
- [ ] TraceTimeline 组件实现
- [ ] 学习助手页面集成 timeline
- [ ] 历史人物对话页面集成 timeline
- [ ] 样式完成
- [ ] smoke tests 通过

---

## 八、相关文档

- [`202606231148-next-product-direction-analysis.md`](202606231148-next-product-direction-analysis.md) — 下一步产品方向分析
- [`202606221438-iteration-plan-dev.md`](202606221438-iteration-plan-dev.md) — 迭代计划

---

## 九、文件改动汇总

```
backend/
  tracing.py                      - 扩展 TraceEvent 数据结构
  trace_store.py                  - 新建 trace 存储
  agents/
    learning_assistant.py         - 集成 trace 事件
    history_character.py          - 集成 trace 事件
  api/main.py                     - 新增 GET /api/traces/{trace_id}

frontend/
  components/
    TraceTimeline.tsx             - 新建 trace timeline 组件
  app/
    learning-assistant/page.tsx   - 集成 timeline
    history-character/page.tsx    - 集成 timeline
  app/globals.css                 - 添加 timeline 样式

eval/
  trace_event_smoke.py           - 新建 trace event 测试
  trace_store_smoke.py           - 新建 trace store 测试
```

---

## 十、完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| TraceEvent 数据结构 | ✅ 已完成 | backend/trace_store.py |
| TraceStore 实现 | ✅ 已完成 | backend/trace_store.py |
| API 接口 | ✅ 已完成 | GET /api/traces/{trace_id} |
| 学习助手集成 | ✅ 已完成 | learning_assistant.py emit_trace_event |
| 历史人物对话集成 | ⏳ 待开始 | |
| TraceTimeline 组件 | ✅ 已完成 | frontend/components/TraceTimeline.tsx |
| 页面集成 | ✅ 已完成 | learning-assistant/page.tsx |
| 样式 | ✅ 已完成 | globals.css |
| smoke tests | ✅ 已完成 | eval/trace_smoke.py |
