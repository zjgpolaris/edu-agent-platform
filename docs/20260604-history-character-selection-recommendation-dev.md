# 历史人物对话馆人物选择与智能推荐机制开发文档

> 模块：模块1 虚拟历史人物对话 | 日期：2026-06-04 | 状态：待开发

---

## 一、背景

当前“历史人物对话馆”已经具备基础对话能力：前端提交历史人物与学生问题，后端通过 RAG 检索教材与史料，再由角色扮演 Agent 生成教学模拟回答，并进行史实一致性检查。

但从产品体验看，当前人物入口偏固定：前端只展示 5 个预设人物，容易让用户误以为系统只能与这几位人物对话。实际上，后端并没有人物白名单限制，`CharacterRequest.character` 会直接进入检索与生成链路，理论上可以支持任意历史人物。

因此，本阶段需要把人物选择机制从“固定人物按钮”升级为“用户自主选择 + 系统智能推荐 + 资料覆盖提示”的混合模式。

---

## 二、当前项目现状

### 2.1 前端现状

位置：

- `frontend/app/page.tsx`
- `frontend/app/history-character.html`
- `frontend/app/globals.css`

当前 `page.tsx` 中写死了 5 个推荐人物：

- 商鞅
- 秦始皇
- 唐太宗
- 林则徐
- 孙中山

当前能力：

- 支持点击预设人物卡片。
- 支持手动输入历史人物。
- 支持输入问题并调用后端对话接口。
- 支持展示回答、史料来源、史实校验状态和史实速览卡片。

当前不足：

- 推荐人物数量过少，和“历史人物对话馆”的产品定位不匹配。
- 页面视觉重点集中在 5 个卡片上，弱化了自由输入能力。
- 用户如果只输入历史问题，系统无法推荐应该和谁对话。
- 对资料不足的人物没有明确提示，用户难以判断回答可信度。
- 推荐问题与人物强绑定，缺少“围绕一个历史问题推荐多个人物视角”的能力。

### 2.2 后端现状

位置：

- `backend/api/main.py`
- `backend/agents/history_character.py`
- `backend/rag/knowledge_base.py`

当前对话接口：

```http
POST /api/history/character/chat
```

请求体：

```json
{
  "character": "商鞅",
  "message": "你为什么要变法？",
  "session_id": null,
  "grade": null,
  "stream": true,
  "mode": null
}
```

当前后端特征：

- 后端没有历史人物白名单。
- `retrieve_facts` 使用 `character + message` 作为 RAG 查询。
- 已支持 `factual` / `counterfactual` 模式检测。
- 已支持 `session_id` 多轮消息存储。
- 已支持 `fact_card` 史实速览事件。

当前后端不足：

- 没有人物目录或人物画像数据结构。
- 没有“根据问题推荐人物”的接口。
- 没有对人物资料覆盖度进行评估。
- 对资料不足的情况只依赖生成 Prompt 提醒，缺少结构化字段供前端展示。

---

## 三、产品决策

### 3.1 采用混合人物选择模式

本项目不应采用“系统自动决定唯一人物”的模式，也不应只保留“用户手动选择人物”的模式。

推荐方案：

```text
用户自主选择为主，系统智能推荐为辅。
```

原因：

1. 历史学习问题通常存在多个视角，系统直接决定唯一人物会过度简化历史。
2. 课堂任务和考试复习经常要求学生围绕指定人物学习，必须保留用户自主选择。
3. 初中学生常常只知道问题，不知道该问谁，因此需要系统推荐入口。
4. 推荐人物可以展示推荐理由，帮助学生建立“人物—事件—观点”的历史关联。

### 3.2 目标交互流程

```text
用户进入历史人物对话馆
  ↓
选择入口：
  A. 我想和某位历史人物对话
  B. 我有一个历史问题，不知道该问谁
  ↓
如果选择 A：
  展示推荐人物 + 分类人物库 + 自由输入框
  用户选定人物后进入对话
  ↓
如果选择 B：
  用户先输入历史问题
  系统推荐 2–4 个相关人物，并给出推荐理由
  用户选择一个人物后进入对话
  ↓
后端基于人物 + 问题检索史料
  ↓
生成教学模拟回答、史实校验、史实速览卡片
```

### 3.3 不建议的设计

不建议：

```text
用户输入问题 → 系统直接指定一个人物 → 自动开始对话
```

原因：

- 容易误判用户意图。
- 历史问题通常有多个合理视角。
- 会降低学生主动选择和比较历史观点的机会。
- 不利于教师课堂控制。

---

## 四、功能范围

### 4.1 本阶段实现

1. 扩展前端人物选择体验。
2. 新增“根据问题推荐人物”入口。
3. 新增后端人物推荐接口。
4. 建立首版历史人物目录 `CharacterProfile`。
5. 对推荐人物返回推荐理由和资料覆盖等级。
6. 对资料不足的人物展示清晰提示。

### 4.2 本阶段不实现

- 不实现完整教材人物自动抽取系统。
- 不实现教师后台配置人物库。
- 不实现学生画像个性化推荐。
- 不实现复杂图谱数据库。
- 不强制限制只能对话人物库内人物。

---

## 五、前端设计

### 5.1 页面入口调整

在现有页面人物区增加两个模式切换：

```text
[选择历史人物] [根据问题推荐]
```

#### 模式一：选择历史人物

保留现有人物卡片，但扩展为分组展示：

```text
推荐人物
- 商鞅
- 秦始皇
- 唐太宗
- 林则徐
- 孙中山

中国古代史
- 孔子
- 汉武帝
- 张骞
- 司马迁
- 北魏孝文帝
- 隋文帝
- 武则天
- 岳飞
- 郑和
- 康熙

中国近现代史
- 洪秀全
- 李鸿章
- 康有为
- 梁启超
- 陈独秀
- 李大钊
- 毛泽东
- 周恩来
- 邓小平

世界史
- 伯里克利
- 亚历山大
- 凯撒
- 哥伦布
- 华盛顿
- 拿破仑
- 马克思
- 列宁
```

自由输入框仍然保留：

```text
没有找到想问的人物？直接输入人物姓名
[              ]
```

#### 模式二：根据问题推荐

用户先输入问题：

```text
我想了解：为什么秦国能够统一六国？
[帮我推荐可以对话的人物]
```

系统返回推荐卡片：

```text
推荐你可以问：

1. 商鞅
   推荐理由：商鞅变法增强了秦国实力，是秦统一的重要基础。
   资料覆盖：较充分
   推荐问题：变法为什么能让秦国强大？

2. 秦始皇
   推荐理由：秦始皇完成统一，并推行巩固统一的制度措施。
   资料覆盖：充分
   推荐问题：统一六国后采取了哪些措施？

3. 李斯
   推荐理由：李斯参与秦朝制度建设，与统一文字、中央集权相关。
   资料覆盖：有限
   推荐问题：统一文字有什么意义？
```

用户点击其中一个人物后，再进入当前已有的对话流程。

### 5.2 前端状态设计

建议在 `frontend/app/page.tsx` 中增加状态：

```ts
type SelectionMode = "character" | "question";

type CoverageLevel = "high" | "medium" | "low" | "unknown";

type RecommendedCharacter = {
  name: string;
  dynastyOrPeriod: string;
  reason: string;
  suggestedQuestion: string;
  coverageLevel: CoverageLevel;
  matchedTopics: string[];
};
```

新增 state：

```ts
const [selectionMode, setSelectionMode] = useState<SelectionMode>("character");
const [recommendQuestion, setRecommendQuestion] = useState("");
const [recommendedCharacters, setRecommendedCharacters] = useState<RecommendedCharacter[]>([]);
const [recommendLoading, setRecommendLoading] = useState(false);
const [recommendError, setRecommendError] = useState("");
```

### 5.3 资料覆盖提示

根据 `coverageLevel` 展示不同提示：

| coverageLevel | 前端文案 |
|---|---|
| `high` | 资料较充分，适合进行人物对话。 |
| `medium` | 有一定资料，可围绕教材重点提问。 |
| `low` | 资料较少，建议提出更具体的问题。 |
| `unknown` | 当前知识库覆盖不明确，回答需结合史料依据判断。 |

当用户自由输入非推荐人物时，不阻止对话，但在输入区下方提示：

```text
如果知识库中该人物资料较少，系统会基于已检索到的史料有限回答，请重点查看右侧史料依据。
```

---

## 六、后端设计

### 6.1 新增人物推荐接口

新增接口：

```http
POST /api/history/character/recommend
```

请求体：

```json
{
  "message": "为什么秦国能够统一六国？",
  "grade": "七年级上",
  "limit": 4
}
```

响应体：

```json
{
  "recommendations": [
    {
      "name": "商鞅",
      "dynasty_or_period": "战国 · 秦国",
      "reason": "商鞅变法增强了秦国实力，是秦统一的重要基础。",
      "suggested_question": "变法为什么能让秦国强大？",
      "coverage_level": "high",
      "matched_topics": ["商鞅变法", "秦国富国强兵"]
    }
  ]
}
```

### 6.2 请求模型

在 `backend/api/main.py` 增加：

```python
class CharacterRecommendRequest(BaseModel):
    message: str
    grade: str | None = None
    limit: int = 4
```

### 6.3 响应模型

```python
class CharacterRecommendation(BaseModel):
    name: str
    dynasty_or_period: str
    reason: str
    suggested_question: str
    coverage_level: str
    matched_topics: list[str]
```

### 6.4 新增人物目录

建议新增文件：

```text
backend/agents/character_catalog.py
```

首版使用静态配置，不引入数据库：

```python
CHARACTER_CATALOG = [
    {
        "name": "商鞅",
        "dynasty_or_period": "战国 · 秦国",
        "period_group": "中国古代史",
        "keywords": ["商鞅变法", "秦国", "变法", "富国强兵", "军功爵制"],
        "default_question": "你为什么要变法？",
    },
    {
        "name": "秦始皇",
        "dynasty_or_period": "秦朝",
        "period_group": "中国古代史",
        "keywords": ["统一六国", "秦朝", "中央集权", "郡县制", "统一文字"],
        "default_question": "统一文字为什么重要？",
    },
]
```

后续可以把该目录迁移到 JSON 文件或数据库。

### 6.5 推荐逻辑

首版推荐不需要复杂模型，采用“关键词匹配 + RAG 覆盖度评估”的稳定方案。

流程：

```text
用户问题
  ↓
对人物目录做关键词匹配
  ↓
取 Top N 候选人物
  ↓
对每个人物执行一次轻量 RAG 查询：人物名 + 用户问题
  ↓
根据召回资料数量和来源质量计算 coverage_level
  ↓
生成推荐理由和推荐问题
  ↓
返回 2–4 个推荐人物
```

### 6.6 覆盖度计算规则

首版规则：

```python
def estimate_coverage(sources: list[dict]) -> str:
    if len(sources) >= 3:
        return "high"
    if len(sources) >= 1:
        return "medium"
    return "low"
```

后续可以加入来源类型权重：

| 来源类型 | 权重 |
|---|---:|
| `textbook` | 3 |
| `primary` | 3 |
| `timeline` | 2 |
| `concept` | 1 |

### 6.7 推荐理由生成

首版可以先用模板生成，避免额外 LLM 调用：

```text
推荐理由 = 该人物与「命中的 topic」相关，适合从「人物所属事件/制度/思想」角度理解这个问题。
```

如果需要更自然的文案，可在第二阶段增加 LLM 生成，但必须要求：

- 只基于命中的人物关键词和 RAG 来源生成。
- 不编造人物参与过的事件。
- 推荐理由不超过 60 字。

---

## 七、前后端集成方案

### 7.1 推荐接口调用

前端新增函数：

```ts
async function recommendCharacters() {
  const response = await fetch(`${apiBaseUrl}/api/history/character/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: recommendQuestion, grade: null, limit: 4 }),
  });

  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  setRecommendedCharacters(data.recommendations || []);
}
```

### 7.2 点击推荐人物后的行为

用户点击推荐人物卡片：

```ts
function selectRecommendedCharacter(item: RecommendedCharacter) {
  setSelectedCharacter(item.name);
  setCharacter(item.name);
  setMessage(item.suggestedQuestion || recommendQuestion);
  setStatus(`已选择${item.name}，可以直接开始对话，也可以修改问题。`);
}
```

### 7.3 与现有对话接口关系

新增推荐接口只负责“帮用户选人”，不替代现有对话接口。

```text
/api/history/character/recommend  → 推荐人物
/api/history/character/chat       → 与选定人物对话
```

这样可以避免推荐逻辑影响现有 RAG 对话稳定性。

---

## 八、人物库首版范围建议

首版建议从初中历史高频人物中选 30–50 个，不追求一次覆盖全部历史人物。

### 8.1 中国古代史

- 孔子
- 孟子
- 商鞅
- 秦始皇
- 陈胜
- 吴广
- 汉武帝
- 张骞
- 司马迁
- 北魏孝文帝
- 隋文帝
- 唐太宗
- 武则天
- 玄奘
- 鉴真
- 岳飞
- 成吉思汗
- 忽必烈
- 朱元璋
- 郑和
- 康熙
- 乾隆

### 8.2 中国近现代史

- 林则徐
- 洪秀全
- 曾国藩
- 李鸿章
- 康有为
- 梁启超
- 孙中山
- 袁世凯
- 陈独秀
- 李大钊
- 鲁迅
- 毛泽东
- 周恩来
- 邓小平

### 8.3 世界史

- 伯里克利
- 亚历山大
- 凯撒
- 屋大维
- 查理曼
- 哥伦布
- 华盛顿
- 拿破仑
- 林肯
- 马克思
- 恩格斯
- 列宁

---

## 九、教学体验要求

### 9.1 保持学生主动性

系统推荐人物时必须让用户选择，不能自动进入某个人物对话。

推荐卡片应该强调：

```text
你可以从这些人物视角理解这个问题。
```

而不是：

```text
你应该问这个人物。
```

### 9.2 保持史实边界

对资料覆盖不足的人物，前端和后端都要提示：

```text
当前知识库中关于该人物的资料较少，回答会基于已检索到的史料进行有限解释。
```

### 9.3 鼓励多视角学习

对于同一个历史问题，推荐多个相关人物视角，例如：

问题：

```text
为什么秦国能统一六国？
```

推荐：

- 商鞅：从变法强国角度理解。
- 秦始皇：从统一过程和制度建设角度理解。
- 李斯：从中央集权和文字制度角度理解。

---

## 十、开发任务拆分

### Task 1：扩展前端人物选择模式

文件：

- `frontend/app/page.tsx`
- `frontend/app/globals.css`

任务：

- 增加 `selectionMode`。
- 增加“选择历史人物 / 根据问题推荐”切换。
- 保留现有人物卡片。
- 增加推荐结果卡片区域。
- 增加资料覆盖提示样式。

### Task 2：新增人物目录

文件：

- `backend/agents/character_catalog.py`

任务：

- 定义 `CHARACTER_CATALOG`。
- 覆盖首批 30–50 个教材常见人物。
- 每个人物包含姓名、时代、分类、关键词、默认问题。

### Task 3：新增推荐服务逻辑

文件：

- `backend/agents/character_recommender.py`

任务：

- 实现关键词匹配。
- 调用历史知识库 retriever 评估覆盖度。
- 生成推荐理由和推荐问题。
- 返回排序后的推荐结果。

### Task 4：新增推荐 API

文件：

- `backend/api/main.py`

任务：

- 增加 `CharacterRecommendRequest`。
- 增加 `POST /api/history/character/recommend`。
- 返回 `recommendations`。

### Task 5：前端接入推荐 API

文件：

- `frontend/app/page.tsx`

任务：

- 实现 `recommendCharacters`。
- 处理 loading、error、empty 三种状态。
- 点击推荐人物后填充 `character` 和 `message`。
- 保持原有 `/chat` 对话流程不变。

### Task 6：补充测试与验证

建议验证问题：

- 为什么秦国能够统一六国？
- 辛亥革命为什么会爆发？
- 鸦片战争为什么会发生？
- 唐朝前期为什么会出现盛世？
- 新文化运动有什么影响？

验证点：

- 是否返回 2–4 个合理人物。
- 推荐理由是否符合史实。
- 资料覆盖等级是否能正确展示。
- 点击推荐人物后是否能正常进入对话。
- 自由输入非推荐人物时是否仍可对话。

---

## 十一、验收标准

### 11.1 功能验收

- 用户可以继续手动选择或输入历史人物。
- 用户可以只输入历史问题并获得人物推荐。
- 推荐结果包含人物、时代、推荐理由、推荐问题、资料覆盖等级。
- 用户点击推荐人物后，可以继续编辑问题并发起对话。
- 原有历史人物对话、史料依据、史实校验、史实速览不受影响。

### 11.2 体验验收

- 页面不再让用户感觉只能和 5 个固定人物对话。
- 推荐人物不是唯一结论，而是多个可选视角。
- 对资料不足的人物有明确提示。
- 推荐文案适合初中生理解。

### 11.3 技术验收

- 新增推荐接口不破坏现有 `/api/history/character/chat`。
- 推荐接口失败时，前端不影响手动对话功能。
- 推荐逻辑首版不依赖额外数据库。
- 推荐结果排序稳定，可调试。

---

## 十二、后续演进方向

### 12.1 基于教材知识库自动扩展人物

当人教版初中历史全册知识库补齐后，可以从 `corpus.json` 中自动抽取人物、事件、朝代和关键词，生成更完整的人物目录。

### 12.2 支持多人物视角对比

后续可以增加：

```text
用多个历史人物视角回答同一个问题
```

例如：

```text
问题：如何看待商鞅变法？
视角：商鞅 / 旧贵族 / 秦孝公 / 普通农民
```

### 12.3 与历史辩论模拟器联动

推荐人物机制可以复用于历史辩论模拟器，为正反方自动推荐代表性历史人物或观点来源。

### 12.4 教师可配置人物库

正式教学版本可以允许教师按课程进度配置本周推荐人物，例如：

```text
七年级上册 第6课：动荡的春秋时期
推荐人物：齐桓公、管仲、晋文公、孔子
```

---

## 十三、结论

历史人物对话馆不应被设计成只有少数固定人物的封闭入口，也不应完全交给系统自动决定人物。

最适合当前项目阶段的方案是：

```text
保留用户自主选择，增加问题驱动的人物推荐，并用资料覆盖提示控制史实边界。
```

该方案可以在不重构现有 Agent 的前提下，显著提升产品完整度和教学可用性，同时为后续教材知识库扩展、多视角学习和教师配置能力预留空间。
