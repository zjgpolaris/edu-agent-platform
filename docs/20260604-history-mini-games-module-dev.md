# 初中历史小游戏模块开发文档

> 日期：2026-06-04 | 项目：edu-agent-platform | 第一阶段实现：历史时间线闯关

---

## 一、目标

在现有教育 Agent 平台中新增“初中历史小游戏”模块，用游戏化方式承载历史知识点学习、课堂互动和课后复习。

本模块采用“全部游戏保留入口 + 第一阶段只实现一个”的策略：

- 保留多个历史游戏的产品入口、配置结构和扩展位。
- 第一阶段只开发并上线 **历史时间线闯关**。
- 其他游戏以“即将开放 / 规划中”状态展示，不进入实现范围。
- 所有游戏后续都应复用现有历史知识库、历史人物对话、辩论和史料检索能力。

---

## 二、当前项目基础

### 2.1 前端基础

当前前端位于：

- `frontend/app/page.tsx`
- `frontend/app/globals.css`

技术栈：

- Next.js 14
- React 18
- TypeScript
- App Router
- 当前页面已是客户端交互型页面，适合继续扩展游戏交互。

现有视觉风格偏“纸张、史册、岭南历史课堂”，小游戏模块应延续：

- 宣纸/书卷质感背景。
- 朱砂、青绿、金色等历史教学色彩。
- 卡片式学习面板。
- 面向初中生的清晰表达。

### 2.2 后端基础

当前后端位于：

- `backend/api/main.py`
- `backend/agents/history_character.py`
- `backend/agents/debate_supervisor.py`
- `backend/agents/character_recommender.py`
- `backend/rag/knowledge_base.py`
- `backend/llm_config.py`

已有能力：

- FastAPI 接口。
- 历史知识库 RAG 检索。
- 历史人物对话 Agent。
- 历史人物推荐。
- 历史辩论接口。
- 通过 Zode 调用非 Claude 模型。

小游戏模块第一阶段不需要复杂 LangGraph 编排，优先采用确定性规则 + 可选知识库解释。

---

## 三、游戏总览与保留策略

### 3.1 游戏清单

| 游戏 | 玩法概述 | 教学目标 | 第一阶段状态 |
|------|----------|----------|--------------|
| 历史时间线闯关 | 拖拽事件卡片到正确时间顺序 | 时间观念、朝代顺序、事件先后 | 实现 |
| 历史人物身份推理 | 根据线索猜人物、朝代或事件 | 人物识记、史实归纳 | 保留入口 |
| 朝代经营小沙盘 | 扮演统治者进行政策选择 | 制度理解、历史因果 | 保留入口 |
| 历史事件因果链拼图 | 拼接原因、经过、结果、影响 | 历史解释、因果分析 | 保留入口 |
| 穿越历史现场 | 场景探索、NPC 对话、任务收集 | 情境理解、史料阅读 | 保留入口 |
| 历史辩论赛 | 围绕历史评价组织论据 | 材料分析、观点表达 | 保留入口 |

### 3.2 产品展示策略

前端应展示一个“历史小游戏大厅”：

- 已开放游戏：可点击进入。
- 未开放游戏：展示简介、教学目标和“即将开放”。
- 不隐藏未开放游戏，便于教师理解长期规划。
- 未开放游戏不调用后端，不提供半成品交互。

推荐页面名称：

```text
历史修复室
```

第一期开放游戏名称：

```text
时间线修复师
```

---

## 四、第一阶段游戏：历史时间线闯关

### 4.1 游戏定位

学生扮演“历史修复师”，系统将若干历史事件打乱，学生需要把事件拖拽到正确时间顺序。提交后系统给出：

- 正确排序。
- 得分。
- 错误位置提示。
- 每个事件的简短知识点讲解。
- 可选的“继续追问历史人物”入口。

### 4.2 核心学习目标

历史时间线闯关主要训练：

1. 初中历史重要事件的先后顺序。
2. 朝代、时期与事件之间的对应关系。
3. 事件之间的简单因果关系。
4. 学生对“历史时间观念”的掌握程度。

### 4.3 第一阶段范围

第一阶段只做一个完整闭环：

```text
选择关卡 → 开始闯关 → 拖拽排序 → 提交答案 → 查看反馈 → 再来一局
```

第一阶段不做：

- 登录系统。
- 班级排行榜。
- 教师后台配置。
- 复杂成就系统。
- 多人实时对战。
- AI 动态生成全部题目。

---

## 五、关卡设计

### 5.1 关卡维度

第一阶段建议内置 3 类关卡：

| 关卡类型 | 示例 | 难度 |
|----------|------|------|
| 中国古代史基础 | 商鞅变法、秦统一、汉武帝大一统、张骞通西域 | 入门 |
| 中国近代史基础 | 鸦片战争、洋务运动、戊戌变法、辛亥革命、五四运动 | 标准 |
| 世界史基础 | 文艺复兴、新航路开辟、英国资产阶级革命、工业革命 | 标准 |

### 5.2 每局题目规模

第一阶段每局 5 张事件卡片。

原因：

- 适合课堂快速互动。
- 移动端和桌面端都容易拖拽。
- 错误反馈不会过长。
- 初中生认知负担较低。

后续可以扩展：

| 难度 | 卡片数 | 适用场景 |
|------|--------|----------|
| 入门 | 4–5 | 新授课导入 |
| 标准 | 5–7 | 课堂练习 |
| 挑战 | 8–10 | 复习课、竞赛 |

### 5.3 示例题库

第一阶段可以先使用人工校准题库，保证时间准确性。

```json
[
  {
    "id": "ancient-china-basic-01",
    "title": "中国古代史基础线索",
    "grade": "七年级上/下",
    "events": [
      {
        "id": "shang-yang-reform",
        "title": "商鞅变法",
        "year": -356,
        "period": "战国时期",
        "summary": "秦孝公任用商鞅进行变法，推动秦国富国强兵。",
        "topic": "商鞅变法"
      },
      {
        "id": "qin-unification",
        "title": "秦统一六国",
        "year": -221,
        "period": "秦朝",
        "summary": "秦王嬴政完成统一，建立中国历史上第一个统一的多民族封建国家。",
        "topic": "秦朝统一"
      },
      {
        "id": "han-wudi-unification",
        "title": "汉武帝巩固大一统",
        "year": -141,
        "period": "西汉",
        "summary": "汉武帝在政治、思想、经济和军事方面加强中央集权。",
        "topic": "汉武帝大一统"
      },
      {
        "id": "zhang-qian-western-regions",
        "title": "张骞出使西域",
        "year": -138,
        "period": "西汉",
        "summary": "张骞出使西域，促进汉朝与西域的联系。",
        "topic": "张骞通西域"
      },
      {
        "id": "silk-road",
        "title": "丝绸之路形成",
        "year": -130,
        "period": "西汉",
        "summary": "丝绸之路成为东西方经济文化交流的重要通道。",
        "topic": "丝绸之路"
      }
    ]
  }
]
```

说明：

- 公元前年份使用负数，便于排序。
- 对于持续性事件，可使用教材常见起点年份或阶段性标识。
- 如果年份存在争议，题目中应避免要求精确年份，改为“先后顺序”。

---

## 六、数据结构设计

### 6.1 游戏定义

建议新增前后端共享概念：

```ts
type HistoryGameDefinition = {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  teachingGoals: string[];
  status: "available" | "planned";
  estimatedMinutes: number;
};
```

第一阶段游戏配置：

```ts
const historyGames = [
  {
    id: "timeline",
    title: "时间线修复师",
    subtitle: "把被打乱的历史事件放回正确顺序",
    description: "训练历史时间观念，理解事件先后和朝代脉络。",
    teachingGoals: ["时间顺序", "朝代脉络", "事件影响"],
    status: "available",
    estimatedMinutes: 5
  },
  {
    id: "character-deduction",
    title: "历史人物身份推理",
    subtitle: "根据线索猜出历史人物",
    description: "训练人物识记和史实归纳能力。",
    teachingGoals: ["人物识记", "线索归纳", "史实判断"],
    status: "planned",
    estimatedMinutes: 5
  }
]
```

### 6.2 时间线事件

```ts
type TimelineEvent = {
  id: string;
  title: string;
  year: number;
  displayYear: string;
  period: string;
  summary: string;
  topic: string;
};
```

### 6.3 时间线回合

```ts
type TimelineRound = {
  roundId: string;
  title: string;
  grade?: string;
  difficulty: "easy" | "normal" | "hard";
  events: Omit<TimelineEvent, "year">[];
};
```

前端开始游戏时不应直接拿到 `year`，避免学生通过调试信息看到答案。

### 6.4 提交结果

```ts
type TimelineSubmitResult = {
  roundId: string;
  score: number;
  total: number;
  correctOrder: string[];
  submittedOrder: string[];
  items: Array<{
    eventId: string;
    title: string;
    isCorrectPosition: boolean;
    correctIndex: number;
    submittedIndex: number;
    explanation: string;
  }>;
  learningTip: string;
};
```

---

## 七、后端接口设计

### 7.1 获取游戏大厅配置

```http
GET /api/history/games
```

响应：

```json
{
  "games": [
    {
      "id": "timeline",
      "title": "时间线修复师",
      "subtitle": "把被打乱的历史事件放回正确顺序",
      "description": "训练历史时间观念，理解事件先后和朝代脉络。",
      "teaching_goals": ["时间顺序", "朝代脉络", "事件影响"],
      "status": "available",
      "estimated_minutes": 5
    }
  ]
}
```

### 7.2 开始时间线闯关

```http
POST /api/history/games/timeline/start
```

请求：

```json
{
  "grade": "七年级上",
  "difficulty": "easy",
  "topic": "中国古代史"
}
```

响应：

```json
{
  "round_id": "timeline-20260604-abc123",
  "title": "中国古代史基础线索",
  "difficulty": "easy",
  "events": [
    {
      "id": "qin-unification",
      "title": "秦统一六国",
      "display_year": "公元前221年",
      "period": "秦朝",
      "summary": "秦王嬴政完成统一，建立秦朝。",
      "topic": "秦朝统一"
    }
  ]
}
```

### 7.3 提交排序答案

```http
POST /api/history/games/timeline/submit
```

请求：

```json
{
  "round_id": "timeline-20260604-abc123",
  "ordered_event_ids": [
    "shang-yang-reform",
    "qin-unification",
    "han-wudi-unification",
    "zhang-qian-western-regions",
    "silk-road"
  ]
}
```

响应：

```json
{
  "round_id": "timeline-20260604-abc123",
  "score": 5,
  "total": 5,
  "correct_order": [
    "shang-yang-reform",
    "qin-unification",
    "han-wudi-unification",
    "zhang-qian-western-regions",
    "silk-road"
  ],
  "submitted_order": [
    "shang-yang-reform",
    "qin-unification",
    "han-wudi-unification",
    "zhang-qian-western-regions",
    "silk-road"
  ],
  "items": [
    {
      "event_id": "shang-yang-reform",
      "title": "商鞅变法",
      "is_correct_position": true,
      "correct_index": 0,
      "submitted_index": 0,
      "explanation": "商鞅变法发生在战国时期，早于秦统一六国。"
    }
  ],
  "learning_tip": "你已经掌握了战国到西汉前期的重要事件顺序，可以继续关注这些事件之间的因果联系。"
}
```

---

## 八、后端实现建议

### 8.1 新增文件

建议新增：

```text
backend/agents/history_games.py
```

职责：

- 管理游戏定义。
- 管理第一阶段内置时间线题库。
- 生成随机回合。
- 校验学生提交顺序。
- 生成基础反馈。

第一阶段不建议把小游戏逻辑直接写入 `backend/api/main.py`，避免 API 文件继续膨胀。

### 8.2 `backend/api/main.py` 增加接口

在现有 FastAPI 入口中新增：

```python
from agents.history_games import (
    list_history_games,
    start_timeline_round,
    submit_timeline_round,
)
```

新增 Pydantic 请求模型：

```python
class TimelineStartRequest(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None


class TimelineSubmitRequest(BaseModel):
    round_id: str
    ordered_event_ids: list[str]
```

新增接口：

```python
@app.get("/api/history/games")
async def history_games():
    return {"games": list_history_games()}


@app.post("/api/history/games/timeline/start")
async def timeline_start(req: TimelineStartRequest):
    return start_timeline_round(req.grade, req.difficulty, req.topic)


@app.post("/api/history/games/timeline/submit")
async def timeline_submit(req: TimelineSubmitRequest):
    return submit_timeline_round(req.round_id, req.ordered_event_ids)
```

### 8.3 回合状态存储

第一阶段可以使用内存存储：

```python
TIMELINE_ROUNDS: dict[str, TimelineRoundInternal] = {}
```

原因：

- 当前项目尚未接入数据库。
- 小游戏第一阶段主要用于本地教学演示。
- 回合状态短生命周期，不需要持久化。

后续如果要支持课堂排行榜、学生记录和教师分析，应迁移到数据库。

### 8.4 知识库解释策略

第一阶段反馈解释优先使用人工题库内的 `summary` 和固定规则。

可选增强：

- 提交后根据错题 `topic` 调用 `get_retriever("history")` 检索教材内容。
- 将检索结果压缩成 1–2 句“学习提示”。
- 不要求每个题目都调用 LLM，降低成本和延迟。

推荐第一阶段默认：

```text
人工题库解释为主，RAG 检索作为后续增强。
```

---

## 九、前端页面设计

### 9.1 页面入口

建议新增路由：

```text
frontend/app/history-games/page.tsx
```

如果暂时不想拆分路由，也可以先在 `frontend/app/page.tsx` 中增加小游戏入口卡片，再跳转到独立页面。

推荐第一阶段采用独立页面，避免当前历史人物对话页继续变大。

### 9.2 页面结构

```text
历史修复室
├── 顶部介绍区
│   ├── 标题：历史修复室
│   └── 副标题：用小游戏复原历史线索
├── 游戏大厅
│   ├── 时间线修复师（已开放）
│   ├── 历史人物身份推理（即将开放）
│   ├── 朝代经营小沙盘（即将开放）
│   ├── 历史事件因果链拼图（即将开放）
│   ├── 穿越历史现场（即将开放）
│   └── 历史辩论赛（即将开放）
└── 时间线游戏区
    ├── 关卡选择
    ├── 事件卡片拖拽排序
    ├── 提交按钮
    ├── 结果反馈
    └── 再来一局
```

### 9.3 交互要求

时间线闯关第一阶段应支持：

- 点击“开始修复”。
- 显示被打乱的事件卡片。
- 使用按钮上移/下移调整顺序。
- 桌面端后续可增强为拖拽。
- 提交后锁定答案。
- 显示正确/错误状态。
- 支持“再来一局”。

第一阶段优先使用“上移 / 下移”而不是复杂拖拽库。

原因：

- 不需要新增第三方依赖。
- 移动端可用性更好。
- 降低开发风险。
- 后续可以无缝替换为拖拽体验。

### 9.4 视觉状态

事件卡片状态：

| 状态 | 视觉表现 |
|------|----------|
| 未提交 | 普通纸卡 |
| 位置正确 | 青绿色边框 + “顺序正确” |
| 位置错误 | 朱砂色边框 + “应在第 N 位” |
| 锁定状态 | 禁用移动按钮 |

---

## 十、与现有历史人物对话的联动

第一阶段结果页可提供可选入口：

```text
想进一步理解这个事件？去问问相关历史人物
```

示例映射：

| 事件 | 推荐人物 | 推荐问题 |
|------|----------|----------|
| 商鞅变法 | 商鞅 | 你为什么要变法？ |
| 秦统一六国 | 秦始皇 | 统一六国后为什么要统一文字和度量衡？ |
| 张骞出使西域 | 张骞 | 出使西域为什么重要？ |
| 虎门销烟 | 林则徐 | 虎门销烟有什么历史意义？ |
| 辛亥革命 | 孙中山 | 辛亥革命有什么历史意义？ |

联动方式：

- 第一阶段可以只展示推荐问题文本。
- 后续再支持跳转并预填历史人物对话参数。

---

## 十一、实施步骤

### Step 1：新增后端游戏模块

新增：

```text
backend/agents/history_games.py
```

内容：

- 游戏定义列表。
- 时间线题库。
- 回合生成函数。
- 提交校验函数。
- 基础学习反馈函数。

验收标准：

- 能返回全部游戏配置。
- 只有 `timeline` 的状态为 `available`。
- 能生成一局乱序时间线题目。
- 提交后能返回正确顺序、得分和解释。

### Step 2：新增 FastAPI 接口

修改：

```text
backend/api/main.py
```

新增：

- `GET /api/history/games`
- `POST /api/history/games/timeline/start`
- `POST /api/history/games/timeline/submit`

验收标准：

- 接口返回 JSON。
- 前端本地可调用。
- 错误输入不导致服务崩溃。

### Step 3：新增前端小游戏页面

新增：

```text
frontend/app/history-games/page.tsx
```

实现：

- 游戏大厅。
- 时间线修复师卡片。
- 规划中游戏卡片。
- 时间线闯关交互。
- 结果反馈。

验收标准：

- 页面可访问。
- 未开放游戏不可点击或点击后显示“即将开放”。
- 时间线游戏可以完成一局。

### Step 4：补充样式

修改：

```text
frontend/app/globals.css
```

新增：

- 小游戏大厅样式。
- 游戏卡片样式。
- 时间线排序卡片样式。
- 结果反馈样式。

验收标准：

- 与现有历史教学风格一致。
- 桌面端布局清晰。
- 窄屏下不横向溢出。

### Step 5：本地验证

运行：

```bash
npm run dev
```

或分别运行：

```bash
npm run dev:backend
npm run dev:frontend
```

验证：

- 打开小游戏页面。
- 开始一局时间线闯关。
- 调整顺序。
- 提交答案。
- 查看得分和解释。
- 刷新页面后可重新开始。

---

## 十二、验收标准

第一阶段完成后，应满足：

1. “历史小游戏”模块有独立入口或独立页面。
2. 所有 6 个游戏都在大厅中展示。
3. 只有“时间线修复师”可玩。
4. 时间线游戏能完成完整闭环。
5. 提交后能看到正确顺序、得分和解释。
6. 未开放游戏不会出现半成品页面。
7. 不依赖新数据库。
8. 不新增复杂第三方拖拽库。
9. 不改变现有历史人物对话功能。
10. 代码结构为后续游戏扩展预留清晰位置。

---

## 十三、后续扩展路线

### 第二阶段：历史人物身份推理

复用：

- `backend/agents/character_catalog.py`
- `backend/agents/character_recommender.py`
- 历史人物对话推荐问题。

玩法：

- 系统给 3–5 条线索。
- 学生猜人物。
- 错误后逐步解锁更多线索。

### 第三阶段：历史事件因果链拼图

复用：

- 历史知识库中的事件解释。
- 人工整理的原因、经过、结果、影响四段式结构。

玩法：

- 将事件因果链打散。
- 学生拖动拼接。
- 系统解释因果关系。

### 第四阶段：历史辩论赛游戏化

复用：

- `backend/agents/debate_supervisor.py`
- 已有 `/api/history/debate/start`。

玩法：

- 学生选择立场。
- 系统给材料卡。
- 学生组织论据。
- AI 裁判给出评价。

### 第五阶段：穿越历史现场

复用：

- 历史人物对话。
- 知识库检索。
- 场景式任务脚本。

玩法：

- 学生进入历史场景。
- 与 NPC 对话。
- 收集史料完成任务。

---

## 十四、风险与约束

### 14.1 史实准确性

风险：

- 时间线事件年份或先后存在争议。
- LLM 动态生成题目可能引入错误。

策略：

- 第一阶段使用人工校准题库。
- 只把 LLM/RAG 用于解释增强，不用于决定正确答案。
- 有争议的事件避免考精确年份。

### 14.2 实现复杂度

风险：

- 一次性实现多个游戏会导致模块半成品过多。

策略：

- 只实现时间线闯关。
- 其他游戏只保留入口和规划信息。
- 先用上移/下移完成排序，不引入拖拽依赖。

### 14.3 教学适配

风险：

- 游戏好玩但偏离教学目标。

策略：

- 每个游戏卡片明确教学目标。
- 每局结束必须给学习反馈。
- 优先覆盖教材核心知识点。

---

## 十五、推荐第一版文件变更清单

```text
backend/agents/history_games.py                 # 新增：小游戏定义与时间线逻辑
backend/api/main.py                             # 修改：新增小游戏接口
frontend/app/history-games/page.tsx             # 新增：小游戏大厅与时间线页面
frontend/app/globals.css                        # 修改：小游戏页面样式
```

不建议第一版修改：

```text
backend/agents/history_character.py
backend/agents/debate_supervisor.py
backend/rag/knowledge_base.py
knowledge_base/history/corpus.json
```

原因：

- 第一版小游戏可以独立闭环。
- 避免影响已有历史人物对话和知识库能力。
- 后续再逐步增加 RAG 解释和人物对话联动。
