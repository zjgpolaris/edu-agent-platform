# 教材在线阅读·划线提问·笔记摘要 开发文档

> 模块：textbook-reader | 学科：历史 | 版本：v0.1 | 日期：2026-06-08

---

## 1. 功能概述

### 1.1 教材在线阅读
用户选择年级（七/八/九年级）和册次（上/下册），系统从 `textbooks/structured/*.yaml` 解析章节目录，渲染正文内容。支持章节导航与滚动展示，是划线和笔记功能的载体页面。

### 1.2 划线提问
用户在正文中选中任意文字，弹出气泡菜单，点击"划线提问"后，选中文本作为上下文传入后端，调用 `llm_quality`（Claude Opus）+ ChromaDB RAG 检索，SSE 流式输出解答。复用现有 `/api/history/character/chat` 的流式响应模式。

### 1.3 笔记摘要
用户可在任意段落旁添加手动笔记，笔记存储于 `localStorage`（MVP，key 格式：`notes:{grade}:{sectionId}`）。另提供"AI 生成章节摘要"按钮，调用 `llm_fast`（Claude Sonnet）对当前章节全文生成结构化摘要，SSE 流式输出。

---

## 2. 数据流与架构图

```
用户操作                 前端 (Next.js 15)            后端 (FastAPI)              AI 层
──────────────────────────────────────────────────────────────────────────────────────
选择年级/册次  ──GET──▶  /api/textbook/toc            yaml.load() + 返回目录 JSON
选择章节      ──GET──▶  /api/textbook/section/{id}    yaml.load() + 返回段落列表
                         TextbookViewer 渲染正文
选中文字      ──────▶   SelectionPopup 弹出
点击"划线提问" ──POST──▶  /api/textbook/ask            RAG 检索 ChromaDB
                                                  ──▶  llm_quality.stream()
                         SSE 流 ◀────────────────────  逐 token 推送
点击"AI摘要"  ──POST──▶  /api/textbook/summary         整合章节文本
                                                  ──▶  llm_fast.stream()
                         SSE 流 ◀────────────────────  逐 token 推送
添加手动笔记  ──────▶   localStorage 直接读写
```

---

## 3. YAML 教材数据结构

现有 `textbooks/structured/*.yaml` 的实际顶层字段为 `grade`、`book`，其余内容条目由 `scripts/generate_textbook_yaml.py` 生成（169 entries）。本模块依赖的完整结构：

```yaml
grade: 七年级上
book: 中国历史七年级上册（人教版）
chapters:
  - id: "1"
    title: "第一单元 史前时期"
    sections:
      - id: "1-1"
        title: "第1课 远古时期的人类活动"
        content: |
          距今约170万年前，元谋人生活在云南元谋...
        key_points:
          - 元谋人是我国境内已知最早的古人类
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `grade` | string | 年级标识，如 `七年级上`，与 YAML 文件名一致 |
| `chapters[].id` | string | 单元 ID |
| `chapters[].sections[].id` | string | 课节 ID，格式 `{单元}-{课}` |
| `sections[].content` | string | 正文，用于渲染和 AI 输入 |
| `sections[].key_points` | list[string] | 可选，重难点提示 |

> ���现有 YAML 缺少 `chapters` 层级，需先确认 `scripts/generate_textbook_yaml.py` 输出格式，必要时补充解析逻辑。

---

## 4. 新增 API 接口

挂载在 `backend/api/main.py`，遵循现有 FastAPI 风格。

### 4.1 获取目录

```
GET /api/textbook/toc?grade=七年级上

Response 200:
{
  "grade": "七年级上",
  "book": "中国历史七年级上册（人教版）",
  "chapters": [
    {
      "id": "1",
      "title": "第一单元 史前时期",
      "sections": [{ "id": "1-1", "title": "第1课 远古时期的人类活动" }]
    }
  ]
}
```

### 4.2 获取章节正文

```
GET /api/textbook/section/{section_id}?grade=七年级上

Response 200:
{
  "id": "1-1",
  "title": "第1课 远古时期的人类活动",
  "paragraphs": [
    { "id": "p1", "text": "距今约170万年前，元谋人生活在云南元谋..." }
  ]
}
```

### 4.3 划线提问（SSE 流式）

```
POST /api/textbook/ask

Request:
{
  "selection": "元谋人生活在云南元谋，距今约170万年",
  "question": "为什么元谋人被称为最早的人类？",   // 可选追问
  "section_id": "1-1",
  "grade": "七年级上",
  "session_id": "uuid"                           // 可选，保持多轮上下文
}

Response: text/event-stream
event: delta
data: {"text": "元谋人之所以..."}

event: sources
data: {"sources": [{"topic": "...", "content": "..."}]}

event: done
data: {"finish_reason": "stop"}
```

### 4.4 章节 AI 摘要（SSE 流式）

```
POST /api/textbook/summary

Request:
{
  "section_id": "1-1",
  "grade": "七年级上"
}

Response: text/event-stream
event: delta
data: {"text": "本课核心内容：..."}

event: done
data: {"finish_reason": "stop"}
```

---

## 5. 前端页面路由

```
frontend/app/
└── textbook-reader/
    ├── page.tsx                    # 年级/册次选择入口
    ├── layout.tsx                  # 共享布局（侧边目录 + 笔记抽屉）
    └── [grade]/
        ├── page.tsx                # 章节目录页（TOC）
        └── [sectionId]/
            └── page.tsx            # 正文阅读页（含划线/笔记面板）
```

路由示例：
- `/textbook-reader` — 选择年级册次
- `/textbook-reader/七年级上` — 章节目录
- `/textbook-reader/七年级上/1-1` — 第1课正文阅读

---

## 6. 关键组件清单

| 组件 | 路径 | 职责 |
|------|------|------|
| `TextbookViewer` | `components/textbook/TextbookViewer.tsx` | 渲染段落列表，监听 `mouseup` 触发划线检测 |
| `SelectionPopup` | `components/textbook/SelectionPopup.tsx` | 浮动气泡菜单，定位于选区坐标，提供"划线提问"/"添加笔记"入口 |
| `NotePanel` | `components/textbook/NotePanel.tsx` | 右侧抽屉，展示/编辑当前章节笔记，读写 `localStorage` |
| `SummaryPanel` | `components/textbook/SummaryPanel.tsx` | 展示 AI 摘要流式输出 |
| `TocSidebar` | `components/textbook/TocSidebar.tsx` | 左侧章节导航，高亮当前节 |

---

## 7. 实现分阶段计划

### P0 — MVP（约 3 天）

目标：选教材、读正文、划线提问。

- [ ] 后端：`/api/textbook/toc` + `/api/textbook/section/{id}`，基于 `PyYAML` 解析现有 YAML
- [ ] 后端：`/api/textbook/ask`，复用 `rag/knowledge_base.py` + `llm_quality.stream()`，套用现有 `sse_frame()` 格式
- [ ] 前端：路由 `textbook-reader/[grade]/[sectionId]`，`TextbookViewer` + `SelectionPopup`
- [ ] 前端：提取 `history-character/page.tsx` 中 SSE fetch 逻辑为 `hooks/useSSEStream.ts` 共享

### P1 — 笔记与摘要（约 2 天）

- [ ] 后端：`/api/textbook/summary`，传入章节 content，调 `llm_fast.stream()`
- [ ] 前端：`NotePanel` + `localStorage` 读写
- [ ] 前端：`SummaryPanel` 流式展示

### P2 — 体验优化

- [ ] 划线高亮持久化（序列化 selection range 存 `localStorage`）
- [ ] 笔记与原文段落关联显示（侧边批注样式）
- [ ] 教材封面入口页（年级卡片）
- [ ] 笔记导出为 Markdown
- [ ] 首页 `page.tsx` 新增 `textbook-reader` 入口卡片

---

## 8. 与现有系统的集成点

| 现有模块 | 路径 | 复用方式 |
|----------|------|----------|
| SSE 流式输出框架 | `backend/api/main.py` → `sse_frame()` + `StreamingResponse` | `/ask` 和 `/summary` 直接复用相同响应格式 |
| RAG 检索器 | `backend/rag/knowledge_base.py` | `/ask` 用划线文本作 query，检索历史知识库 |
| LLM 配置 | `backend/llm_config.py` → `llm_quality` / `llm_fast` | `ask` 用 `llm_quality`，`summary` 用 `llm_fast` |
| 对话历史持久化 | `backend/session_store.py` | `/ask` 可选 `session_id`，支持划线追问多轮上下文 |
| SSE fetch hook | `frontend/app/history-character/page.tsx` | 提取为 `hooks/useSSEStream.ts`，供两个面板共享 |
