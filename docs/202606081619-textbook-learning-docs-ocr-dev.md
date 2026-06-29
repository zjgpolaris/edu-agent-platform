# 教材同步在线学习文档与 OCR 原文层开发文档

> 模块：textbook-learning | 学科：初中历史 | 版本：v0.1 | 日期：2026-06-08

---

## 1. 背景与目标

当前项目已具备历史学习平台基础能力：前端使用 Next.js App Router，后端使用 FastAPI，已有 SSE 流式 Agent 接口、ChromaDB RAG 检索、Claude/通义模型配置，以及多种历史学习模块。教材数据目前分为两类：

- `textbooks/raw/`：6 本人教版初中历史 PDF。
- `textbooks/structured/`：已生成部分知识库 YAML，例如七上、八上、八下、九上。

已验证 PDF 正文文字层不完整：正文页只能提取少量标题或页码，不能直接用 `pdf.js` 文字层实现原版 PDF 精准划线。因此，本功能不应直接定位为“PDF 电子教材阅读器”，而应采用分阶段路线：

1. **短期**：基于 YAML 做“教材同步在线学习文档”。
2. **中期**：引入 OCR + 版面分析，补充 PDF 原文层。
3. **长期**：形成“PDF 原文阅读 + YAML 知识增强 + AI 导学”的混合学习应用。

目标是为初中学生提供可在线学习、可提问、可记笔记、可复习检测的教材同步学习体验。

---

## 2. 当前项目实际情况

### 2.1 技术栈

| 层级 | 当前实现 |
|------|----------|
| 前端 | `frontend/app/`，Next.js + TypeScript |
| 后端 | `backend/api/main.py`，FastAPI |
| AI 接口 | `backend/llm_config.py`，支持 fast / quality / fallback 模型 |
| RAG | `backend/rag/knowledge_base.py`，ChromaDB 检索 |
| 流式输出 | `sse_frame()` + `StreamingResponse` |
| 会话记忆 | `backend/session_store.py` |
| 教材 PDF | `textbooks/raw/*.pdf` |
| 结构化知识库 | `textbooks/structured/*.yaml` |
| PDF 工具 | `scripts/ocr_pdf.py`、`scripts/parse_pdf_corpus.py`、`scripts/generate_textbook_yaml.py` |

### 2.2 已生成 YAML 文件

当前 `textbooks/structured/` 下已有：

```text
中国历史七年级上册知识库.yaml
中国历史八年级上册知识库.yaml
中国历史八年级下册知识库.yaml
世界历史九年级上册知识库.yaml
```

结构示例：

```yaml
grade: 七年级上
book: 中国历史七年级上册（人教版）
units:
  - title: 第一单元 史前时期：原始社会与中华文明的起源
    lessons:
      - title: 第1课 远古时期的人类活动
        items:
          - text: "元谋人距今约170万年，是我国境内目前已确认的最早的古人类，发现于云南元谋县，能够制作工具并使用火。"
            topic: 元谋人
            type: textbook
            page: 2
```

YAML 数据不是教材原文，而是教材同步知识点摘要，适合用于：

- 知识卡片展示
- 本课摘要
- 易错点讲解
- 点击/划线提问
- 自动出题
- 复习笔记

### 2.3 PDF 文字层限制

已抽样验证 `义务教育教科书·历史七年级上册.pdf`：

```text
第3页：39个词
第4页：42个词
第5页：45个词
第6页：15个词
第11页：38个词
```

正文页实际应有数百词，说明 PDF 主要是扫描图片，文字层只包含少量标题或页码。因此：

- 不适合直接做 `pdf.js + 内置文字层` 精准划线。
- 若要实现原版 PDF 图文阅读与划线，需要 OCR + 坐标层重建。

---

## 3. 产品定位

### 3.1 不建议定位

不建议第一版叫：

```text
电子课本
PDF 阅读器
原版教材在线阅读器
```

原因：当前 YAML 不是课本原文，PDF 也无法直接提供完整可选文字层。

### 3.2 推荐定位

推荐定位为：

```text
教材同步 AI 在线学习文档
```

核心体验：

```text
按教材目录学习
→ 阅读本课知识文档
→ 点击知识点提问
→ 添加笔记
→ 生成摘要和易错点
→ 完成本课小测
```

它既保留“按课本同步学习”的路径，又利用 YAML 的结构化优势提供 AI 导学能力。

---

## 4. 总体架构

```text
┌────────────────────────────────────────────────────────┐
│                    Frontend / Next.js                  │
│                                                        │
│  /textbook-learning                                    │
│  ├─ 教材选择                                           │
│  ├─ 单元/课目录                                        │
│  ├─ 在线学习文档                                       │
│  ├─ AI 学习助手                                        │
│  ├─ 笔记面板                                           │
│  └─ 小测验                                             │
└──────────────────────────┬─────────────────────────────┘
                           │ REST / SSE
┌──────────────────────────▼─────────────────────────────┐
│                    Backend / FastAPI                    │
│                                                        │
│  /api/textbooks                                        │
│  /api/textbooks/{book_id}/toc                           │
│  /api/textbooks/{book_id}/lessons/{lesson_id}           │
│  /api/textbook-learning/ask                             │
│  /api/textbook-learning/summary                         │
│  /api/textbook-learning/quiz                            │
└──────────────┬─────────────────────────┬───────────────┘
               │                         │
┌──────────────▼──────────────┐ ┌────────▼───────────────┐
│ YAML 教材知识库              │ │ RAG + LLM               │
│ textbooks/structured/*.yaml │ │ ChromaDB + llm_fast /   │
│                              │ │ llm_quality             │
└─────────────────────────────┘ └────────────────────────┘

中长期补充：

┌─────────────────────────────┐
│ OCR 原文层                   │
│ PDF → page image → OCR       │
│ → blocks/lines/words + bbox  │
└─────────────────────────────┘
```

---

## 5. 第一阶段：YAML 在线学习文档

### 5.1 页面形态

推荐三栏布局：

```text
┌──────────────────────────────────────────────────────┐
│ 顶部：七年级上册 / 第一单元 / 第1课                   │
├──────────────┬─────────────────────┬─────────────────┤
│ 左侧目录      │ 中间学习文档          │ 右侧 AI 学习助手 │
│              │                     │                 │
│ 第一单元      │ 本课导学              │ 划线/点击解释    │
│  第1课        │ 核心知识点            │ 我的笔记         │
│  第2课        │ 重要概念              │ 本课摘要         │
│ 第二单元      │ 史料阅读              │ 易错点           │
│              │ 自测练习              │                 │
└──────────────┴─────────────────────┴─────────────────┘
```

### 5.2 文档内容生成规则

每个 `lesson` 渲染为一篇在线学习文档：

```text
第1课 远古时期的人类活动

一、本课导学
根据本课 items 自动生成 2-3 个学习问题。

二、核心知识点
展示 type=textbook 的 items。

三、重要概念
展示 type=concept 的 items。

四、史料阅读
展示 type=primary 的 items。

五、本课小结
由 AI 或规则生成。

六、自测练习
由 AI 根据 items 生成。
```

### 5.3 知识点交互

每个知识点卡片提供：

```text
解释一下
为什么重要
容易怎么考
生成一道题
加入笔记
```

用户也可以选中文本，弹出操作菜单：

```text
划线提问
添加笔记
生成例题
```

---

## 6. 第二阶段：OCR 原文层

### 6.1 目标

补充 PDF 原文阅读体验，让学生可以对照真实教材页面学习。

### 6.2 推荐 OCR 管线

```text
PDF 页面
→ PyMuPDF 渲染 page image
→ PaddleOCR / PP-Structure 识别文字和版面
→ 输出 page/block/line/word 坐标
→ 保存为 JSON
→ 前端渲染 PDF 页面图片 + 透明文字层
```

### 6.3 OCR 输出结构

建议新增目录：

```text
textbooks/ocr/
  中国历史七年级上册/
    pages/
      001.png
      002.png
    layout.json
```

`layout.json` 示例：

```json
{
  "book": "中国历史七年级上册（人教版）",
  "pages": [
    {
      "page": 5,
      "width": 595,
      "height": 842,
      "blocks": [
        {
          "id": "p5-b1",
          "type": "paragraph",
          "text": "北京人已经学会使用火，并会长时间保存火种。",
          "bbox": [80, 120, 500, 180],
          "lines": [
            {
              "text": "北京人已经学会使用火，并会长时间保存火种。",
              "bbox": [80, 120, 500, 140]
            }
          ]
        }
      ]
    }
  ]
}
```

### 6.4 与 YAML 的关系

OCR 层负责：

```text
原文、页码、图片、版面、可视化划线
```

YAML 层负责：

```text
知识点、摘要、易错点、考点、小测、AI 问答上下文
```

二者通过 `page`、`lesson title`、`topic` 做弱关联：

```text
OCR 段落 text
→ embedding / keyword match
→ YAML item.topic / item.text
```

---

## 7. API 设计

### 7.1 获取教材列表

```http
GET /api/textbooks
```

响应：

```json
{
  "books": [
    {
      "id": "history-grade-7a",
      "grade": "七年级上",
      "book": "中国历史七年级上册（人教版）",
      "source": "textbooks/structured/中国历史七年级上册知识库.yaml",
      "status": "ready"
    }
  ]
}
```

### 7.2 获取目录

```http
GET /api/textbooks/{book_id}/toc
```

响应：

```json
{
  "grade": "七年级上",
  "book": "中国历史七年级上册（人教版）",
  "units": [
    {
      "title": "第一单元 史前时期：原始社会与中华文明的起源",
      "lessons": [
        { "id": "lesson-1", "title": "第1课 远古时期的人类活动" }
      ]
    }
  ]
}
```

### 7.3 获取课文学习文档

```http
GET /api/textbooks/{book_id}/lessons/{lesson_id}
```

响应：

```json
{
  "book": "中国历史七年级上册（人教版）",
  "grade": "七年级上",
  "unit_title": "第一单元 史前时期：原始社会与中华文明的起源",
  "lesson": {
    "id": "lesson-1",
    "title": "第1课 远古时期的人类活动",
    "items": [
      {
        "id": "lesson-1-item-1",
        "text": "元谋人距今约170万年...",
        "topic": "元谋人",
        "type": "textbook",
        "page": 2
      }
    ]
  }
}
```

### 7.4 知识点提问（SSE）

```http
POST /api/textbook-learning/ask
```

请求：

```json
{
  "book_id": "history-grade-7a",
  "lesson_id": "lesson-1",
  "selected_text": "北京人能够使用火并长时间保存火种。",
  "question": "这句话为什么重要？",
  "item_id": "lesson-1-item-2",
  "session_id": "optional-session-id"
}
```

响应：`text/event-stream`

```text
event: sources
data: {"sources": [...]}

event: delta
data: {"text": "这句话的重要性在于..."}

event: final
data: {"response": "..."}
```

### 7.5 生成本课摘要（SSE）

```http
POST /api/textbook-learning/summary
```

请求：

```json
{
  "book_id": "history-grade-7a",
  "lesson_id": "lesson-1",
  "mode": "overview" // overview | exam_points | mistakes | compare
}
```

### 7.6 生成小测

```http
POST /api/textbook-learning/quiz
```

请求：

```json
{
  "book_id": "history-grade-7a",
  "lesson_id": "lesson-1",
  "question_types": ["choice", "judge", "material"],
  "count": 5
}
```

---

## 8. 前端路由规划

```text
frontend/app/textbook-learning/
  page.tsx                         # 教材选择页
  [bookId]/
    page.tsx                       # 单元/课目录页
    [lessonId]/
      page.tsx                     # 学习文档页
```

可选组件目录：

```text
frontend/components/textbook-learning/
  BookGrid.tsx
  TextbookToc.tsx
  LessonDocument.tsx
  KnowledgeItemCard.tsx
  SelectionToolbar.tsx
  LearningAssistantPanel.tsx
  NotePanel.tsx
  SummaryPanel.tsx
  QuizPanel.tsx
```

---

## 9. 后端模块规划

建议新增教材学习专用模块，避免继续把逻辑堆在 `backend/api/main.py`。

```text
backend/textbook_learning/
  __init__.py
  loader.py          # 读取 YAML，建立 book_id 映射
  schema.py          # Pydantic models
  service.py         # toc / lesson / ask / summary / quiz 业务逻辑
  prompts.py         # 提问、摘要、小测 prompt
```

`backend/api/main.py` 中只保留路由接入。

需要复用：

| 现有能力 | 路径 | 用途 |
|----------|------|------|
| SSE frame | `backend/api/main.py:sse_frame()` | 流式问答与摘要 |
| LLM 配置 | `backend/llm_config.py` | `llm_fast` 用摘要/小测，`llm_quality` 用深度解释 |
| RAG 检索 | `backend/rag/knowledge_base.py:get_retriever()` | 结合知识库补充上下文 |
| 会话存储 | `backend/session_store.py` | 保存学生对某课的连续追问 |

---

## 10. 数据校验与完整性检查

YAML 生成后必须做结构校验，避免空文件或截断文件进入应用。

### 10.1 校验规则

每本书需满足：

```text
grade 非空
book 非空
units 数量 > 0
每个 unit 有 title 和 lessons
每个 lesson 有 title 和 items
每个 item 有 text/topic/type/page
item.type 只能是 textbook / primary / concept
每课 items 数量建议 4-6
```

### 10.2 建议新增脚本

```text
scripts/validate_textbook_yaml.py
```

输出示例：

```text
中国历史七年级上册知识库.yaml
- units: 4
- lessons: 20
- items: 112
- invalid_items: 0
- status: OK
```

如检测到文件只有 `grade/book` 或 items 为 0，应标记为 `EMPTY`。

---

## 11. 实施计划

### P0：YAML 在线学习文档 MVP

目标：学生可以选择教材、按课学习、点击知识点提问、做笔记。

- 新增 YAML loader，读取 `textbooks/structured/*.yaml`。
- 新增 `/api/textbooks`、`/api/textbooks/{book_id}/toc`、`/api/textbooks/{book_id}/lessons/{lesson_id}`。
- 前端新增 `/textbook-learning` 路由。
- 实现 `LessonDocument` 和 `KnowledgeItemCard`。
- 实现本地笔记 `localStorage`。
- 首页新增“教材同步学习”入口。

### P1：AI 导学增强

目标：把知识点学习变成可交互学习。

- 新增 `/api/textbook-learning/ask` SSE 问答。
- 新增 `/api/textbook-learning/summary`，支持本课速览、考点摘要、易错点。
- 新增 `/api/textbook-learning/quiz`，基于当前课 items 生成小测。
- 复用现有流式输出 UI 逻辑。

### P2：OCR 原文试点

目标：只对七上做 OCR 原文层试点。

- 使用 `PyMuPDF` 将 PDF 页面渲染为图片。
- 使用 PaddleOCR / PP-Structure 识别正文、标题、表格、图片说明。
- 产出 `textbooks/ocr/中国历史七年级上册/layout.json`。
- 前端增加“原文页模式”，展示页面图片和透明文字层。
- 将 OCR 段落与 YAML topic 做弱关联。

### P3：混合学习模式

目标：形成“原文 + 知识增强”的完整学习应用。

- 左侧显示 PDF 原文页或文档视图切换。
- 右侧显示对应知识点、AI 解释、笔记、摘要。
- 支持原文划线提问，并带入 YAML item 作为增强上下文。
- 建立学习进度、错题本和薄弱知识点推荐。

---

## 12. 验证方案

### 12.1 后端验证

- 运行 FastAPI 服务。
- 请求 `/api/textbooks`，确认列出已生成 YAML。
- 请求某本书 TOC，确认单元和课数量正确。
- 请求某课详情，确认 items 正确分组。
- 请求 `/api/textbook-learning/ask`，确认 SSE 正常输出。
- 请求 `/api/textbook-learning/summary`，确认不同 mode 有不同摘要结果。

### 12.2 前端验证

- 启动 Next.js 前端。
- 进入 `/textbook-learning`。
- 选择“七年级上册”。
- 进入“第1课 远古时期的人类活动”。
- 检查核心知识点、概念、史料卡片是否正确展示。
- 选中文本或点击知识点提问，确认右侧流式回答。
- 添加笔记，刷新页面后确认本地笔记仍存在。
- 生成本课摘要和小测。

### 12.3 数据验证

- 对所有 `textbooks/structured/*.yaml` 运行结构校验。
- 随机抽查每本书 3 课，确认课次没有明显缺失。
- 对 `primary` 类型内容进行人工抽查，避免史料引用不准确。
- `page` 字段前端统一显示为“约第 X 页”。

---

## 13. 风险与处理

| 风险 | 影响 | 处理 |
|------|------|------|
| YAML 是 AI 生成，不是课本原文 | 不能冒充电子教材 | 产品命名为“教材同步学习文档” |
| page 页码不精确 | 误导学生 | 前端显示“约第 X 页” |
| primary 史料可能不准确 | 学习内容风险 | 加入人工抽查或降低展示权重 |
| PDF 文字层缺失 | 无法直接精准划线 | P2 使用 OCR + 坐标层重建 |
| OCR 错字与版面错序 | 影响原文阅读 | 先七上试点，评估准确率后再扩展 |
| API 逻辑堆积在 main.py | 可维护性下降 | 新增 `backend/textbook_learning/` 模块 |

---

## 14. 推荐结论

当前最合适的开发路线是：

```text
先做 YAML 在线学习文档 MVP
→ 加 AI 提问、笔记、摘要、小测
→ 再对七上试点 OCR 原文层
→ 最终融合成原文阅读 + 知识增强的混合学习应用
```

第一版不要追求 PDF 原版还原，而应重点验证：学生是否愿意按课查看知识文档、是否会点击知识点提问、笔记和小测是否能帮助复习。OCR 原文层作为第二阶段增强，不应阻塞当前功能上线。
