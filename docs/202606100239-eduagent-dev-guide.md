# EduAgent 开发文档

> 版本：2026-06-10 | 适用范围：本地开发、功能扩展、新成员上手

---

## 1. 项目概览

EduAgent 是一个 K-12 历史/语文 AI 教学平台，核心能力为：

| 功能模块 | 描述 |
|---|---|
| 历史人物对话 | RAG 检索 + 角色扮演 + 验证防幻觉 |
| 历史游戏 | 时间轴排序、卡牌配对、多人对战 |
| 作文批改 | LangGraph 图式批改-反思-终稿循环 |
| 辩论督导 | 多 Agent 协作辩论流程 |
| 教材学习 | 教材问答、章节总结、测验生成 |
| 历史地图 | 地图交互 Agent |

---

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12, FastAPI, LangGraph |
| 前端 | Next.js 14 App Router, TypeScript strict |
| 向量库 | Chroma + BGE-large-zh-v1.5 (CPU) |
| 会话存储 | Redis（降级为内存，TTL 1h） |
| LLM 调用 | `zode_client.js` Node 中间层（多 Provider） |

---

## 3. 目录结构

```
edu-agent-platform/
├── backend/
│   ├── api/main.py          # FastAPI 入口，路由定义，SSE 帧
│   ├── agents/              # 15 个 Agent 模块
│   ├── rag/knowledge_base.py
│   ├── session_store.py
│   ├── llm_config.py        # LLM 路由与 Provider 抽象
│   ├── tracing.py           # span 追踪
│   ├── security/            # auth, audit_log, rate_limit
│   ├── student_profile.py
│   └── textbook_learning/
├── frontend/app/
│   ├── page.tsx             # 学习中心首页
│   ├── history-character/   # 历史人物对话页
│   ├── history-games/       # 游戏大厅 + 各游戏页
│   ├── learning-assistant/
│   └── textbook-learning/
├── knowledge_base/history/corpus.json
├── textbooks/structured/*.yaml
├── eval/                    # smoke tests
├── scripts/                 # 数据ingestion工具
├── build_index.py           # RAG 索引重建
└── docs/                    # 开发文档（本文件所在目录）
```

---

## 4. 本地开发环境

### 4.1 依赖安装

```bash
pip install -r backend/requirements.txt
npm install --prefix frontend
```

### 4.2 环境变量

在项目根目录创建 `.env.local`：

```bash
# LLM Provider（选其一）
LLM_PROVIDER=anthropic          # 或 bailian / dashscope
ANTHROPIC_AUTH_TOKEN=sk-ant-xxx
# BAILIAN_API_KEY=xxx
# DASHSCOPE_API_KEY=xxx

# 可选：覆盖模型
LLM_MODEL_FAST=claude-haiku-4-5-20251001
LLM_MODEL_QUALITY=claude-opus-4-6
LLM_MODEL_FALLBACK=claude-sonnet-4-6
```

### 4.3 启动服务

```bash
npm run dev                  # 同时启动 backend:8000 + frontend:3000
npm run dev:backend          # 仅后端
npm run dev:frontend         # 仅前端
```

自定义 Python 路径：
```bash
PYTHON_BIN=/usr/bin/python3 npm run dev
```

---

## 5. API 路由

### 历史人物

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/history/character/recommend` | 推荐历史人物 |
| POST | `/api/history/character/chat` | 非流式对话 |
| POST | `/api/history/character/stream` | SSE 流式对话 |

流式对话 SSE 事件序列：
```
sources   → 检索到的知识来源
delta     → 逐字生成的回答片段
status    → 验证中/已验证
final     → 完整回答
fact_card → 知识卡片 JSON
```

请求体（`/stream`）：
```json
{
  "character": "诸葛亮",
  "message": "你为什么选择辅佐刘备？",
  "session_id": "uuid",
  "student_id": "s001",
  "grade": "7",
  "stream": true,
  "mode": null
}
```
`mode` 为 `null` 时自动检测：包含"如果/假如/要是"等词触发 `counterfactual` 模式。

### 游戏

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/history/games` | 游戏列表 |
| POST | `/api/history/games/timeline/start` | 开始时间轴游戏 |
| POST | `/api/history/games/timeline/submit` | 提交时间轴答案 |
| POST | `/api/history/card-game/start` | 开始卡牌游戏 |
| POST | `/api/history/card-game/submit` | 提交卡牌答案 |
| POST | `/api/history/multiplayer/start` | 开始多人游戏回合 |
| POST | `/api/history/multiplayer/human-turn` | 人类回合 |
| POST | `/api/history/multiplayer/ai-turn` | AI 回合 |

### 其他

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chinese/essay/grade` | 作文批改 |
| POST | `/api/history/debate/start` | 辩论启动 |
| GET | `/api/debug/llm/health` | LLM 连通性检查 |

---

## 6. Agent 架构

### 6.1 历史人物对话（`history_character.py`）

```
用户消息
  └─ detect_mode()        # 判断事实/反事实模式
  └─ retrieve_facts()     # Hybrid RAG 检索（k=5, fetch_k=30）
  └─ generate_response()  # 角色扮演生成（llm_fast）
  └─ verify_response()    # 质量验证（llm_quality）
  └─ emit_fact_card()     # 生成知识卡片
```

`CharacterState` 字段：`character`, `grade`, `session_id`, `messages`, `retrieved_facts`, `retrieved_sources`, `response_draft`, `verified`, `mode`

### 6.2 作文批改（`essay_grader.py`）

LangGraph StateGraph，最多 2 次反思循环：`grade → critique → (revise →) finalize`

### 6.3 多人游戏（`multiplayer_game.py`）

协调 `multiplayer_card_generator.py`（卡片生成）、`multiplayer_ai_commentary.py`（AI 解说）、`multiplayer_coach.py`（AI 陪练）。

---

## 7. RAG 系统

### 7.1 索引构建

```bash
# 完整重建
python3 build_index.py

# 从教材 YAML 重建
python3 scripts/parse_textbook.py
python3 build_index.py
```

索引存储在 `.chroma/`，来源文件 `knowledge_base/history/corpus.json`。

### 7.2 检索参数

```python
search_with_scores(
    collection="history",
    query=query,
    k=5,           # 返回条数
    mode="hybrid", # vector | keyword | hybrid
    metadata_hints={"topic": [...], "grade": "7"},
    fetch_k=30     # 初步召回数
)
```

Embedding 模型：`BAAI/bge-large-zh-v1.5`，查询前缀：`为这个句子生成表示以用于检索相关文章：`

### 7.3 教材数据

```
textbooks/structured/*.yaml  →  scripts/parse_textbook.py  →  corpus.json  →  build_index.py
```

YAML 格式参考 `textbooks/structured/README.md`。

---

## 8. LLM 配置

`backend/llm_config.py` 通过 `zode_client.js` 调用 LLM，支持自动 fallback：

```
主 Provider (LLM_PROVIDER)
  └─ MODEL_FAST    → 意图识别、简单分类
  └─ MODEL_QUALITY → 验证、最终生成
  └─ MODEL_FALLBACK
  └─ 若主 Provider 失败 → 自动切换到 Anthropic fallback
```

`ZodeChatModel` 使用 `_provider_model_chain()` 构建尝试链，按顺序逐个调用直到成功。

---

## 9. 会话存储

`backend/session_store.py`：

- 优先 Redis：`redis.Redis(host="localhost", port=6379)`，key 格式 `session:{session_id}`，TTL 3600s
- Redis 不可用时降级为内存字典，同样 TTL 1h

```python
from session_store import load_messages, save_messages

messages = load_messages(session_id)
save_messages(session_id, messages)
```

---

## 10. 安全与追踪

| 模块 | 路径 | 功能 |
|---|---|---|
| 审计日志 | `security/audit_log.py` | `record_audit_event()` |
| 认证 | `security/auth.py` | `get_actor_from_request()`, `assert_student_access()` |
| 限流 | `security/rate_limit.py` | `check_rate_limit()` |
| 追踪 | `tracing.py` | `start_span()`, `end_span()`, `truncate_text()` |

---

## 11. 前端开发

前端通过 `fetch` 直接调用后端，基础 URL 来自环境变量：

```ts
const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
```

SSE 流式接收示例：

```ts
const res = await fetch(`${API}/api/history/character/stream`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
})
const reader = res.body!.getReader()
// 按行解析 "data: {...}" 格式
```

页面路由：

| 路由 | 文件 | 说明 |
|---|---|---|
| `/` | `app/page.tsx` | 学习中心首页 |
| `/history-character` | `app/history-character/page.tsx` | 历史人物对话 |
| `/history-games` | `app/history-games/page.tsx` | 游戏大厅 |
| `/history-games/timeline` | `timeline/` | 时间轴游戏 |
| `/history-games/card-game` | `card-game/` | 卡牌游戏 |
| `/history-games/multiplayer` | `multiplayer/` | 多人游戏 |
| `/textbook-learning` | `textbook-learning/` | 教材学习 |

---

## 12. 验证与测试

```bash
# Agent smoke test
python3 eval/history_character_smoke.py

# Milestone 验证脚本
npm run verify:milestone-b         # 快速
npm run verify:milestone-b:full    # 完整
npm run verify:milestone-c
npm run verify:milestone-d

# 前端类型检查 + 构建
npm run build --prefix frontend
npm run lint --prefix frontend
```

当前无 pytest/Jest 配置，测试依赖 smoke scripts 和构建验证。

---

## 13. 新功能开发流程

1. **新增 Agent**：在 `backend/agents/` 新建模块，继承 `StateGraph` 模式，在 `api/main.py` 注册路由
2. **扩展 RAG 语料**：编辑 `knowledge_base/history/corpus.json` 或新增 `textbooks/structured/*.yaml`，执行 `python3 build_index.py` 重建索引
3. **新增前端页面**：在 `frontend/app/` 新建路由目录，SSE 消费参考 `history-character/page.tsx`
4. **新增文档**：文件名格式 `YYYYMMDDHHmm-kebab-case-name.md`，放在 `docs/`

---

## 14. 已知限制与待优化项

| 问题 | 影响 | 建议方案 |
|---|---|---|
| Embedding 路径硬编码 | 换机器部署失败 | 改为环境变量 |
| 无 Query Rewrite | RAG 口语问题命中率低 | 加 fast model 改写步骤 |
| 无 Rerank | 噪声片段混入 top-k | 集成 bge-reranker |
| 对话历史无摘要压缩 | 长对话 token 暴增 | session_store 加 summarize hook |
| 无 golden dataset 评测 | 无法量化质量 | eval/ 补充标注数据集 |
| LLM 调用无重试上限 | 偶发错误破坏 SSE 流 | invoke 加 max_retries=2 |
| 索引全量重建 | 新增少量文档耗时长 | 记录文件 hash，增量更新 |
