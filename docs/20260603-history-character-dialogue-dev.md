# 虚拟历史人物对话开发文档

## 1. 功能定位

虚拟历史人物对话是面向广东初中历史学习场景的教学型 Agent。学生输入一个历史人物和问题，系统通过历史史料知识库检索相关材料，再由 LLM 基于史料生成第一人称教学模拟回答，并通过二次校验降低史实幻觉。

该功能不是娱乐化角色扮演，而是“课堂教学模拟助手”：

- 帮助学生理解历史人物、历史事件和制度背景。
- 回答必须基于已检索史料或明确标注“基于史料的合理推断”。
- 输出语言面向初中生，表达清晰、适合教学。
- 回答末尾必须给出“史料依据”。

## 2. 当前项目基础

当前项目已经具备以下能力：

### 2.1 历史史料知识库

位置：

- `knowledge_base/history/corpus.json`
- `backend/rag/knowledge_base.py`
- `.chroma/`

当前知识库覆盖广东初中历史核心内容，包括：

- 中国古代史：商鞅变法、秦朝统一、汉武帝、张骞通西域、贞观之治等。
- 中国近现代史：鸦片战争、太平天国、洋务运动、戊戌变法、辛亥革命、五四运动、新中国成立等。
- 世界史：文艺复兴、新航路开辟、英国资产阶级革命、美国独立战争、工业革命等。

向量检索使用：

- Embedding 模型：本地 ModelScope 下载的 `BAAI/bge-large-zh-v1.5`
- 向量库：Chroma
- 查询前缀：`为这个句子生成表示以用于检索相关文章：`
- 文档构建策略：将 `topic` 前置到 `page_content`，提升中文主题召回质量。

### 2.2 LLM 接入

位置：

- `backend/llm_config.py`
- `backend/zode_client.js`

当前不默认使用 Claude，统一通过 Zode 调用非 Claude 模型。

模型路由：

```python
MODEL_FAST = "kimi-k2.5"        # 1点：日常问答、历史人物对话、RAG生成
MODEL_QUALITY = "kimi-k2.6"     # 3点：史实校验、作文批改、辩论裁判
MODEL_FALLBACK = "GLM-5.1"      # 1点：Kimi 异常时兜底
MODEL_REASONING = "gpt-5.4"     # 4点：复杂推理备用，默认不使用

llm_fast = ZodeChatModel(MODEL_FAST, max_tokens=1024, fallback_models=[MODEL_FALLBACK])
llm_quality = ZodeChatModel(MODEL_QUALITY, max_tokens=2048, fallback_models=[MODEL_FAST, MODEL_FALLBACK])
llm_reasoning = ZodeChatModel(MODEL_REASONING, max_tokens=2048, fallback_models=[MODEL_QUALITY, MODEL_FAST])
```

虚拟历史人物对话建议：

- 生成回答：`llm_fast`
- 史实校验：`llm_quality`
- 复杂综合追问：后续可按需引入 `llm_reasoning`

### 2.3 Agent 编排

位置：

- `backend/agents/history_character.py`

当前已经实现 LangGraph 三阶段流程：

```text
retrieve -> generate -> verify -> END
```

节点职责：

1. `retrieve`：根据人物名和学生问题检索史料。
2. `generate`：基于史料生成教学模拟回答。
3. `verify`：检查回答是否明显违背史料，如有问题做最小修正。

### 2.4 API 接口

位置：

- `backend/api/main.py`

当前接口：

```http
POST /api/history/character/chat
```

请求体：

```json
{
  "character": "商鞅",
  "message": "你为什么要变法？"
}
```

响应为 `application/x-ndjson` 流式响应，目前返回：

```json
{"response":"..."}
```

## 3. 目标用户与典型场景

### 3.1 目标用户

- 广东初中学生。
- 历史教师。
- 想通过对话方式理解历史事件的学习者。

### 3.2 典型使用场景

#### 场景 A：人物动机理解

学生输入：

```json
{
  "character": "商鞅",
  "message": "你为什么要进行变法？"
}
```

系统应回答：

- 用第一人称模拟商鞅解释变法动机。
- 说明战国时期诸侯竞争、秦国富国强兵需求。
- 引用商鞅变法相关史料。
- 明确哪些内容是史料支持，哪些是合理推断。

#### 场景 B：事件影响解释

学生输入：

```json
{
  "character": "林则徐",
  "message": "虎门销烟有什么历史意义？"
}
```

系统应回答：

- 解释禁烟背景。
- 说明虎门销烟与鸦片战争前后关系。
- 避免把后世评价伪装成林则徐本人确定知道的内容。

#### 场景 C：课堂追问

学生输入：

```json
{
  "character": "秦始皇",
  "message": "统一文字为什么重要？"
}
```

系统应回答：

- 面向初中生解释统一文字对政令推行、文化交流、国家统一的意义。
- 使用史料依据说明，不空泛扩写。

## 4. 功能需求

### 4.1 基础对话能力

系统必须支持：

- 输入历史人物名称。
- 输入学生问题。
- 检索相关史料。
- 生成第一人称模拟回答。
- 输出史料依据。
- 对明显史实错误进行校验修正。

### 4.2 回答格式

推荐输出结构：

```text
同学你好，我将用“历史教学模拟”的方式，以【人物名】的视角回答。

【回答】
...

【史料依据】
1. ...
2. ...

【学习提示】
...
```

约束：

- 不直接声称“我就是真正的历史人物”。
- 不编造史料来源。
- 史料不足时必须提示：`这是基于史料的合理推断`。
- 不回答超出历史学习范围的危险、违法或成人内容。
- 对现代政治敏感内容、仇恨内容、暴力煽动内容应转为教育性解释或拒答。

### 4.3 史料引用

第一阶段可只列出史料内容摘要。

后续建议增强为：

```json
{
  "response": "...",
  "sources": [
    {
      "topic": "春秋战国·商鞅变法",
      "source": "《战国策·秦策一》",
      "grade": "七年级上",
      "text": "商君治秦，法令至行..."
    }
  ]
}
```

### 4.4 多轮对话

当前接口每次只接收单条 `message`。

建议后续扩展为：

```json
{
  "character": "商鞅",
  "messages": [
    {"role": "user", "content": "你为什么要变法？"},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "那为什么要奖励军功？"}
  ]
}
```

多轮对话策略：

- 仍以最新问题作为检索核心。
- 检索 query 可以合并人物名、最近一轮问题和必要上下文。
- 不把长历史对话全部塞给检索，避免噪声。

## 5. 技术设计

### 5.1 后端模块结构

当前相关模块：

```text
backend/
  agents/
    history_character.py
  api/
    main.py
  rag/
    knowledge_base.py
  llm_config.py
  zode_client.js
knowledge_base/
  history/
    corpus.json
.chroma/
build_index.py
```

建议下一步保持现有结构，优先增强而非重构。

### 5.2 Agent 状态定义

当前状态：

```python
class CharacterState(TypedDict):
    character: str
    messages: Annotated[list, operator.add]
    retrieved_facts: list[str]
    response_draft: str
    verified: bool
```

建议后续扩展为：

```python
class CharacterState(TypedDict):
    character: str
    messages: Annotated[list, operator.add]
    retrieved_facts: list[str]
    retrieved_sources: list[dict]
    response_draft: str
    verified: bool
    safety_result: str
```

扩展原因：

- `retrieved_sources` 用于 API 返回结构化史料来源。
- `safety_result` 用于记录问题是否适合历史教学对话。

### 5.3 推荐 Agent 流程

短期使用当前流程：

```text
retrieve -> generate -> verify -> END
```

中期推荐升级为：

```text
safety_check -> retrieve -> generate -> verify -> format -> END
```

节点说明：

1. `safety_check`
   - 判断问题是否适合历史教学。
   - 对不适合问题返回教学边界提示。

2. `retrieve`
   - 使用 `get_retriever("history")` 获取史料。
   - Query：`人物名 + 学生最新问题`。

3. `generate`
   - 使用 `llm_fast`。
   - 基于史料生成回答。

4. `verify`
   - 使用 `llm_quality`。
   - 只做史实校验和最小修正。

5. `format`
   - 统一输出字段。
   - 附带 sources。

### 5.4 检索策略

当前策略：

```python
query = f"{state['character']} {state['messages'][-1]['content']}"
facts = rag_retriever.invoke(query)
```

建议保持该策略作为第一版。

后续可优化：

- `k=5` 默认。
- 如果检索结果与人物或问题明显无关，可增加一次改写 query。
- 对“人物名不存在于语料库”的情况，提示知识库暂未覆盖。

### 5.5 Prompt 设计

当前生成 Prompt：

```python
system = (
    "你是一个广东初中历史课堂的教学模拟助手。"
    f"请基于史料，用第一人称模拟{state['character']}回答学生问题。"
    "不要声称自己真的就是历史人物；如果史料不足，要明确说'这是基于史料的合理推断'。"
    "语言要适合初中生，回答后用'史料依据'列出对应依据。\n\n"
    f"可用史料：\n{facts_text}"
)
```

建议增强为：

```text
你是一个广东初中历史课堂的教学模拟助手。
请基于下方史料，用第一人称模拟【人物名】回答学生问题。

要求：
1. 不要声称自己真的就是历史人物。
2. 不能编造史料中没有的信息。
3. 如果需要补充推断，必须写明“这是基于史料的合理推断”。
4. 语言适合初中生，避免过长句子。
5. 回答末尾必须包含“史料依据”。
6. 如果史料不足以回答，请先说明史料不足，再给出有限解释。

可用史料：
...
```

校验 Prompt 保持“最小修正”原则，避免二次模型重写导致风格漂移。

## 6. API 设计

### 6.1 第一版接口

```http
POST /api/history/character/chat
Content-Type: application/json
```

请求：

```json
{
  "character": "商鞅",
  "message": "你为什么要变法？"
}
```

响应：

```json
{
  "response": "同学你好..."
}
```

### 6.2 推荐增强版接口

```http
POST /api/history/character/chat
Content-Type: application/json
```

请求：

```json
{
  "character": "商鞅",
  "message": "你为什么要变法？",
  "grade": "七年级上",
  "stream": true
}
```

响应：

```json
{
  "response": "...",
  "character": "商鞅",
  "sources": [
    {
      "topic": "春秋战国·商鞅变法",
      "source": "《战国策·秦策一》",
      "grade": "七年级上",
      "type": "primary",
      "content": "商君治秦，法令至行..."
    }
  ],
  "verified": true
}
```

## 7. 前端页面建议

当前 `frontend/` 还未实现完整 UI。建议页面结构：

```text
历史人物对话页
├── 人物选择区
│   ├── 推荐人物：商鞅、秦始皇、汉武帝、唐太宗、林则徐、孙中山、毛泽东
│   └── 自定义输入
├── 对话区
│   ├── 学生消息
│   └── 历史人物教学模拟回答
├── 史料依据区
│   ├── 来源
│   ├── 年级/单元/主题
│   └── 原文片段
└── 学习提示区
    ├── 相关知识点
    └── 可继续追问的问题
```

推荐交互：

- 首屏提供示例问题。
- 回答时显示“正在检索史料 / 正在生成回答 / 正在校验史实”。
- 史料依据可折叠展开。
- 对史料不足的问题给出明确提示，而不是硬答。

## 8. 安全与教学边界

### 8.1 必须避免

- 编造不存在的史料。
- 声称模型是真实历史人物。
- 将演义、影视、野史当作正史。
- 对历史人物进行过度现代化揣测。
- 输出仇恨、暴力煽动、歧视性内容。
- 回答与学习无关的敏感请求。

### 8.2 推荐拒答模板

```text
这个问题不太适合作为历史课堂中的人物模拟对话。我可以从历史学习角度，帮你分析这个人物所处时代、主要事件和历史影响。
```

### 8.3 史料不足模板

```text
目前知识库中的史料不足以直接回答这个问题。下面内容是基于已有史料和教材知识的合理推断：...
```

## 9. 验收标准

### 9.1 功能验收

至少完成以下测试用例：

1. 商鞅：`你为什么要变法？`
   - 能检索商鞅变法史料。
   - 回答包含富国强兵、法令推行、奖励军功等要点。

2. 秦始皇：`统一文字有什么意义？`
   - 能解释统一文字与国家治理、文化交流的关系。

3. 林则徐：`虎门销烟为什么重要？`
   - 能关联禁烟、鸦片输入、民族危机。

4. 唐太宗：`什么是贞观之治？`
   - 能解释政治清明、经济恢复、纳谏等。

5. 史料不足：`商鞅怎么看手机？`
   - 不应编造历史人物知道手机。
   - 应说明这是现代事物，只能做类比解释。

### 9.2 质量验收

回答应满足：

- 面向初中生，易懂。
- 有明确史料依据。
- 无明显史实错误。
- 不过度扩写。
- 不把推断伪装成史实。

### 9.3 技术验收

- `build_index.py` 可重新构建历史向量库。
- `backend/rag/knowledge_base.py` 可正常检索。
- `backend/agents/history_character.py` 可完成 LangGraph 调用。
- `POST /api/history/character/chat` 可返回回答。
- Zode 环境变量存在时，`llm_fast` 和 `llm_quality` 可用。

## 10. 开发步骤

### 第一阶段：完善当前后端能力

1. 保持现有 `retrieve -> generate -> verify` 流程。
2. 增强 prompt，固定输出格式。
3. 在 `retrieve_facts` 中保留 metadata，支持返回 sources。
4. 修改 API 响应，增加 `sources` 和 `verified` 字段。
5. 加入 5 个 smoke test 用例。

### 第二阶段：增加前端页面

1. 创建历史人物对话页。
2. 接入 `/api/history/character/chat`。
3. 展示对话气泡。
4. 展示史料依据。
5. 增加推荐人物和示例问题。

### 第三阶段：增强 Agent 能力

1. 增加安全分类节点。
2. 增加 query rewrite 节点，处理检索不准问题。
3. 增加史料不足判断。
4. 增加学习提示生成。
5. 增加多轮对话上下文管理。

## 11. 推荐下一步实现范围

为了尽快做出可演示版本，下一步建议只做以下内容：

1. 修改 `backend/agents/history_character.py`：
   - 返回 `retrieved_sources`。
   - 固定回答格式。

2. 修改 `backend/api/main.py`：
   - 响应增加 `sources` 和 `verified`。

3. 新增一个后端 smoke test：
   - 测试商鞅、秦始皇、林则徐三个问题。

4. 再做前端页面。

这样可以先完成一个“可演示、可讲清楚 Agent 技术点”的闭环：

```text
学生问题 -> RAG 检索 -> LLM 生成 -> Reflection 校验 -> API 返回 -> 前端展示史料依据
```

该闭环能体现当前 AI Agent 应用开发工程师常见能力：RAG、Agent 编排、模型路由、提示词工程、史实校验、API 服务化和教学产品设计。
