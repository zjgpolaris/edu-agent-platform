# EduAgent 功能路线图开发文档

**日期**：2026-06-11  
**优先级顺序**：教材章节导读 Agent → 作文批量批改仪表板 → 错题本追踪

---

## 功能一：教材章节导读 Agent

### 目标

用户选定教材章节，Agent 自动提炼核心考点并生成思考题，辅助课前预习和课后复习。

### 现有基础

- `textbooks/structured/*.yaml`：结构化教材数据
- `backend/rag/knowledge_base.py`：Chroma 向量检索
- `backend/agents/history_character.py`：RAG + LLM 生成范式可复用
- `backend/api/main.py`：SSE 流式框架已就绪

### 新增文件

```
backend/agents/textbook_guide.py
backend/services/textbook_service.py
frontend/app/textbook-guide/page.tsx
```

### 接口定义

```python
class TextbookGuideRequest(BaseModel):
    chapter_id: str
    grade: str
    student_id: str | None

class TextbookGuideResponse(BaseModel):
    chapter_title: str
    key_points: list[str]       # 3-5 条核心考点
    questions: list[str]        # 3-5 道思考题
    related_characters: list[str]
```

**路由**

```
GET  /api/history/textbook/chapters
POST /api/history/textbook/guide
```

### Agent 流程

```
load_chapter → retrieve_rag_context → generate_guide → verify_quality
```

- `load_chapter`：读取 YAML，模块级 dict 缓存，避免重复 IO
- `retrieve_rag_context`：章节标题 + 关键词做 RAG 检索
- `generate_guide`：调用 `llm_quality` 生成考点和思考题
- `verify_quality`：正则校验格式，非 LLM

### 前端

左侧章节树（册 / 单元 / 章节三级），右侧展示考点和思考题，底部"和相关历史人物对话"跳转按钮。

`related_characters` 须与 `history_character.py` 中的人物名保持一致。

---

## 功能二：作文批量批改仪表板

### 目标

教师上传多篇作文，批量调用已有批改 Agent，展示评分分布和逐篇详情。

### 现有基础

- `backend/agents/essay_grader.py`：`build_grader_graph()` + `EssayState` 完整实现
- `POST /api/chinese/essay/grade`：单篇接口就绪
- 无需修改 Agent 本身，只需服务层并发调用

### 新增文件

```
backend/services/batch_essay_service.py
frontend/app/essay-dashboard/page.tsx
```

### 接口

```
POST /api/chinese/essay/grade/batch
```

```python
class BatchEssayRequest(BaseModel):
    essays: list[dict]    # [{student_name: str, essay: str}]
    class_id: str | None

class BatchEssayResponse(BaseModel):
    results: list[dict]
    summary: dict         # {avg_score, score_distribution, needs_review_count}
```

**并发实现**

```python
async def batch_grade(essays: list[dict]) -> list[dict]:
    return await asyncio.gather(*[grade_single(e) for e in essays])
```

单次上限 50 篇。

### 前端仪表板三区

1. 上传区：粘贴（`\n---\n` 分隔）或 CSV（`student_name,essay` 两列），解析在前端做
2. 统计卡片：平均分、分数段分布、需人工复核数
3. 详情列表：可展开批改意见，`needs_human_review: true` 条目高亮

---

## 功能三：错题本 + 知识点追踪

### 目标

记录答题错误，识别薄弱知识点，历史人物对话时自动推送补强内容。

### 新增文件

```
backend/services/weakpoint_service.py   # record / get / clear
```

### 数据结构（key: `weakpoints:{student_id}`）

```python
{
    "knowledge_tag": str,   # "商鞅变法"
    "wrong_count": int,
    "last_wrong_at": str,   # ISO 时间戳
    "source": str           # "timeline_game" | "card_game" | "textbook_guide"
}
```

### 集成点

| 位置 | 改动 |
|------|------|
| `history_games.py` 判分后 | 答错调用 `record_weakpoint(student_id, tag)` |
| `textbook_guide.py` 思考题回答后 | 同上 |
| `history_character.py` `retrieve_facts` | 将弱点 tag 追加到 RAG 查询词 |

**路由**

```
GET /api/student/{student_id}/weakpoints
```

**前端**：`app/page.tsx` 个人卡片增加薄弱知识点标签云，点击跳转对话并预填问题。

**注意**：当前无 DB，弱点随 session 过期（1 小时），上线前需接 DB。`student_id` 建议前端用 localStorage UUID 保证跨页一致。

---

## 开发顺序

```
Week 1-2: 功能一（后端 + 前端）
Week 3-4: 功能二（后端 + 仪表板）
Week 5:   功能三（weakpoint_service + 各处集成）
```

功能三依赖功能一的 `textbook_guide.py`，其余可并行推进。
