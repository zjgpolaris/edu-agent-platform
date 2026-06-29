# 时间巨轮 AI 化升级开发文档

## 一、背景与目标

当前《时间巨轮多人对战》已经具备基础多人模拟能力：学生与 AI 玩家轮流出牌，卡牌插入时间轴，放错罚摸一张，最先清空手牌获胜。

但当前 AI 玩家本质上仍是规则模拟：

- AI 名称来自固定数组，如 `AI 小明`、`AI 小红`
- AI 出牌由随机规则和失误率控制
- AI 不会表达推理过程
- 学生放错后只有静态讲解
- 卡牌主要来自静态结构化卡池 `TIMELINE_LEVELS`

本次升级目标是让游戏从“规则型小游戏”升级为“AI 历史学习对战系统”：

1. AI 玩家具有虚拟同学人设
2. AI 出牌前能展示思考理由
3. 学生出错后获得 AI 教练式提示
4. 游戏结束后生成个性化学习复盘
5. 后续支持基于知识库动态生成同专题牌局

---

## 二、当前项目相关实现

### 2.1 多人游戏后端

文件：

```text
backend/agents/multiplayer_game.py
```

当前核心函数：

```python
start_multiplayer_round(...)
play_human_turn(...)
play_ai_turn(...)
```

当前 AI 出牌逻辑：

```python
card_id = random.choice(player["hand"])
error_rate = AI_ERROR_RATES.get(state["ai_difficulty"], 0.15)

if random.random() < error_rate:
    insert_index = random.choice(wrong_indices)
else:
    insert_index = _find_correct_insert(state, card_id)
```

特点：

- AI 是规则型，不调用 LLM
- AI 只返回 `card_played`、`correct`、`game_state`
- 没有推理文本、角色性格、学习反馈

---

### 2.2 多人游戏前端

文件：

```text
frontend/app/history-games/multiplayer/MultiplayerGameClient.tsx
```

当前前端能力：

- 选择专题、难度、AI 人数、AI 水平
- 展示玩家状态
- 学生点击手牌并插入时间轴
- AI 回合自动请求 `/api/history/multiplayer/ai-turn`
- 显示简单 AI 出牌日志

当前 AI 日志示例：

```text
AI 小明 打出「秦统一六国」（公元前221年）— 正确
```

---

### 2.3 历史知识库与动态生成能力

相关文件：

```text
backend/agents/timeline_question_generator.py
knowledge_base/history/corpus.json
```

当前已有能力：

- `_load_corpus()` 读取 `corpus.json`
- `_get_corpus_context(topic, grade)` 按专题/年级筛选语料
- `generate_timeline_round_from_corpus(...)` 基于知识库语料生成时间线事件卡

注意：

- `corpus.json` 是知识片段库，不是完整事件卡库
- 动态卡牌需要 LLM 生成并由后端校验
- 多人模式当前还没有接入该动态生成流程

---

## 三、升级路线总览

建议分三期开发。

| 阶段 | 目标 | 改动范围 | 风险 |
|---|---|---|---|
| P0 | AI 虚拟同学 + AI 出牌理由 | 后端 AI 回合 + 前端展示 | 低 |
| P1 | AI 教练提示 + 结束复盘 | 学生出牌反馈 + 游戏结束报告 | 中 |
| P2 | 知识库动态牌局 | 接入 corpus + LLM 生成 + 强校验 | 高 |

推荐先做 P0 + P1，因为最容易让学生感受到“AI 在参与学习”，同时不会破坏现有游戏规则。

---

## 四、P0：AI 虚拟同学化

### 4.1 目标

让 AI 玩家从“规则机器人”变成具有轻量人设的虚拟同学。

AI 玩家应具备：

- 名字
- 性格
- 擅长领域
- 易错领域
- 出牌风格
- 出牌时的思考表达

示例：

```json
{
  "player_id": "ai-0",
  "display_name": "小明",
  "persona": "记忆力强，但有时为了抢快会草率出牌",
  "strength": "秦汉史",
  "weakness": "史前文明",
  "style": "喜欢先判断朝代，再比较事件因果"
}
```

---

### 4.2 后端数据结构调整

文件：

```text
backend/agents/multiplayer_game.py
```

新增类型：

```python
class AiPersona(TypedDict):
    name: str
    persona: str
    strength: str
    weakness: str
    style: str
```

扩展 `PlayerState`：

```python
class PlayerState(TypedDict):
    player_id: str
    player_type: Literal["human", "ai"]
    display_name: str
    hand: list[str]
    finished: bool
    correct_plays: int
    wrong_plays: int
    persona: AiPersona | None
```

新增静态 AI 人设池：

```python
AI_PERSONAS: list[AiPersona] = [
    {
        "name": "小明",
        "persona": "记忆力强，但有时为了抢快会草率出牌",
        "strength": "秦汉史",
        "weakness": "史前文明",
        "style": "喜欢先判断朝代，再比较事件因果",
    },
    {
        "name": "小红",
        "persona": "思考谨慎，喜欢根据人物线索判断时间",
        "strength": "春秋战国",
        "weakness": "世界近代史",
        "style": "会先找关键人物和制度变化",
    },
]
```

---

### 4.3 AI 出牌理由生成

#### 方案 A：规则生成，低成本

不调用 LLM，仅根据卡牌和插入位置生成模板理由。

```python
def build_ai_reason(state, player, card_id, insert_index, correct):
    card = state["all_cards"][card_id]
    persona = player.get("persona")
    if correct:
        return f"{player['display_name']}：我先看它属于{card['period']}，再比较时间轴两侧事件，所以我把《{card['title']}》放在这里。"
    return f"{player['display_name']}：我有点拿不准《{card['title']}》的先后，先试着放这里。"
```

优点：

- 稳定
- 无额外 LLM 成本
- 不会胡编史实

缺点：

- AI 感较弱
- 表达重复

---

#### 方案 B：LLM 生成，推荐用于 P0+

新增文件：

```text
backend/agents/multiplayer_ai_commentary.py
```

新增函数：

```python
def generate_ai_play_reason(
    persona: dict,
    card: dict,
    timeline_neighbors: dict,
    correct: bool,
) -> str:
    ...
```

Prompt 约束：

```text
你是初中历史学习游戏中的 AI 虚拟同学。
只能基于给定卡牌、时间轴相邻事件和人设生成一句出牌理由。
不得发明新年份、新事件或教材外知识。
输出 30–80 个汉字。
语气像同学在解释自己的判断。
```

输入示例：

```json
{
  "persona": {
    "name": "小明",
    "style": "喜欢先判断朝代，再比较事件因果"
  },
  "card": {
    "title": "商鞅变法",
    "period": "战国时期",
    "summary": "秦孝公任用商鞅进行变法，推动秦国富国强兵。"
  },
  "left_neighbor": null,
  "right_neighbor": {
    "title": "秦统一六国",
    "period": "秦朝"
  },
  "correct": true
}
```

输出示例：

```text
小明：我先看它是战国时期，又是秦国变强的原因，所以应该放在秦统一六国之前。
```

---

### 4.4 API 响应调整

当前 `/api/history/multiplayer/ai-turn` 响应：

```json
{
  "ai_player_id": "ai-0",
  "ai_display_name": "AI 小明",
  "card_played": {...},
  "correct": true,
  "game_state": {...}
}
```

升级后新增字段：

```json
{
  "ai_reason": "小明：我先看它是战国时期，又是秦国变强的原因，所以应该放在秦统一六国之前。",
  "ai_persona": {
    "name": "小明",
    "style": "喜欢先判断朝代，再比较事件因果"
  }
}
```

---

### 4.5 前端展示调整

文件：

```text
frontend/app/history-games/multiplayer/MultiplayerGameClient.tsx
```

新增 AI 思考气泡：

```tsx
{aiThought && (
  <div className="timeline-feedback correct">
    <b>{aiThought.playerName} 的思考</b>
    <p>{aiThought.reason}</p>
  </div>
)}
```

展示节奏：

1. AI 回合开始：显示“AI 小明正在思考……”
2. 1 秒后展示 AI 理由
3. 再执行出牌结果
4. 显示正确/错误反馈

---

## 五、P1：AI 教练提示

### 5.1 目标

学生出错后，AI 不只是展示事件讲解，而是给出针对性的学习提示。

示例：

```text
你把“张骞出使西域”放得太早了。可以先看朝代：张骞属于西汉，而秦统一六国属于秦朝，所以它应该更晚。
```

---

### 5.2 错误类型识别

后端可以根据卡牌和相邻事件判断错误类型。

新增函数：

```python
def classify_timeline_error(state, card_id, insert_index) -> str:
    ...
```

错误类型：

| 类型 | 判断逻辑 | 提示方向 |
|---|---|---|
| era_mismatch | 插到明显不同时代之前/之后 | 先看朝代大框架 |
| too_early | 正确位置在提交位置之后 | 这张牌放早了 |
| too_late | 正确位置在提交位置之前 | 这张牌放晚了 |
| same_period_confusion | 相邻事件 period 相同或相近 | 比较因果和人物线索 |
| topic_confusion | 不同专题事件混淆 | 先确认事件所属主题 |

---

### 5.3 教练提示生成

新增文件：

```text
backend/agents/multiplayer_coach.py
```

新增函数：

```python
def generate_coach_tip(
    card: dict,
    correct_neighbors: dict,
    submitted_neighbors: dict,
    error_type: str,
) -> str:
    ...
```

可先用规则模板实现：

```python
if error_type == "too_early":
    return f"这张牌放早了。先看它属于{card['period']}，再和时间轴上更晚的事件比较。"
```

后续可接入 LLM 生成更自然的讲解。

---

### 5.4 API 响应调整

`/api/history/multiplayer/play` 在学生出错时新增：

```json
{
  "coach_tip": "这张牌放早了。先看它属于西汉，再和秦朝事件比较。",
  "error_type": "too_early"
}
```

前端展示：

```tsx
{feedback.coach_tip && (
  <p>AI 教练：{feedback.coach_tip}</p>
)}
```

---

## 六、P1：游戏结束 AI 复盘报告

### 6.1 目标

游戏结束后，不只展示获胜者，还生成学生本局学习报告。

报告包括：

- 正确次数
- 错误次数
- 错误卡牌列表
- 主要薄弱点
- 下一步复习建议
- 下一局推荐专题或难度

---

### 6.2 状态记录调整

扩展 `MultiplayerGameState`：

```python
class MultiplayerGameState(TypedDict):
    ...
    human_wrong_records: list[WrongRecord]

class WrongRecord(TypedDict):
    card_id: str
    title: str
    display_year: str
    submitted_index: int
    correct_index: int
    error_type: str
```

学生每次出错时记录。

---

### 6.3 新增 API

```text
GET /api/history/multiplayer/report/{round_id}?player_id=demo-student
```

或在游戏结束时由 `/play` / `/ai-turn` 直接返回：

```json
{
  "game_state": {...},
  "final_report": {
    "summary": "本局你在秦汉史顺序上表现不错，但对西汉内部事件先后还需要复习。",
    "weak_points": ["西汉事件先后", "人物活动与制度变化的关系"],
    "review_suggestions": ["先画出秦—西汉—东汉的大时间轴", "重点复盘张骞出使西域和丝绸之路形成的关系"]
  }
}
```

---

## 七、P2：知识库动态生成牌局

### 7.1 目标

让多人模式不再只依赖 `TIMELINE_LEVELS`，而是基于 `knowledge_base/history/corpus.json` 生成同专题、同年级、数量足够的结构化卡牌。

---

### 7.2 推荐流程

```text
学生选择专题/难度
        ↓
从 corpus.json 按 topic / grade 筛选语料
        ↓
LLM 一次性生成 12–20 张事件卡
        ↓
后端强校验：数量、年份、专题、重复、可排序
        ↓
校验通过：进入多人发牌
校验失败：回退 TIMELINE_LEVELS 或提示补充题库
```

---

### 7.3 新增函数

文件：

```text
backend/agents/multiplayer_card_generator.py
```

函数：

```python
def generate_multiplayer_cards_from_corpus(
    grade: str | None,
    topic: str,
    difficulty: str,
    target_count: int,
) -> list[TimelineEventInternal]:
    ...
```

---

### 7.4 LLM 输出格式

```json
{
  "cards": [
    {
      "id": "shang-yang-reform",
      "title": "商鞅变法",
      "year": -356,
      "display_year": "公元前356年",
      "period": "战国时期",
      "summary": "秦孝公任用商鞅进行变法，推动秦国富国强兵。",
      "topic": "中国古代史",
      "explanation": "商鞅变法发生在战国时期，早于秦统一六国。",
      "related_character": "商鞅",
      "suggested_question": "商鞅变法为什么能让秦国强大？"
    }
  ]
}
```

---

### 7.5 强校验规则

必须校验：

1. `cards.length >= 玩家数 * 手牌数 + 1`
2. 每张卡必须有整数 `year`
3. `id` 不重复
4. `year + title` 不重复
5. `topic` 必须属于用户选择范围
6. `summary` 不应泄露精确年份
7. `display_year` 与 `year` 大体一致
8. 同年事件不超过 2 张，避免排序歧义
9. 内容必须适合初中历史教材

如果失败：

- 重试一次 LLM
- 仍失败则回退静态卡池
- 静态卡池不足则提示教师补充题库

---

## 八、前端 AI 化体验设计

### 8.1 AI 玩家卡片

左侧玩家状态从简单文本升级为卡片：

```tsx
<div className="ai-player-card active">
  <strong>小明</strong>
  <small>擅长：秦汉史</small>
  <span>手牌 4 张 · 2✓ 1✗</span>
</div>
```

---

### 8.2 AI 思考区

在主区域时间轴上方展示：

```text
小明正在思考……
小明：我先看它是战国时期，又是秦国变强的原因，所以应该放在秦统一六国之前。
```

---

### 8.3 AI 教练区

学生出错后展示：

```text
AI 教练：这张牌放早了。先看它属于西汉，而左边事件还在秦朝之后的位置更合适。
```

---

### 8.4 结束复盘区

游戏结束后展示：

```text
本局复盘
- 你正确出牌 4 次，错误 2 次
- 容易混淆：西汉内部事件先后
- 建议复习：张骞出使西域 → 丝绸之路形成
```

---

## 九、API 调整汇总

| API | 当前 | AI 化后 |
|---|---|---|
| `POST /api/history/multiplayer/start` | 返回基础玩家状态 | 返回 AI persona |
| `POST /api/history/multiplayer/play` | 返回 correct、feedback | 增加 `coach_tip`、`error_type` |
| `POST /api/history/multiplayer/ai-turn` | 返回 AI 出牌结果 | 增加 `ai_reason`、`ai_persona` |
| 新增 `GET /api/history/multiplayer/report/{round_id}` | 无 | 返回本局 AI 复盘 |

---

## 十、建议实施顺序

### 第一阶段：AI 虚拟同学

修改：

```text
backend/agents/multiplayer_game.py
frontend/app/history-games/multiplayer/MultiplayerGameClient.tsx
```

交付：

- AI 玩家有人设
- AI 出牌有理由
- 前端展示 AI 思考气泡

---

### 第二阶段：AI 教练提示

新增：

```text
backend/agents/multiplayer_coach.py
```

修改：

```text
backend/agents/multiplayer_game.py
frontend/app/history-games/multiplayer/MultiplayerGameClient.tsx
```

交付：

- 学生错牌时有针对性提示
- 记录错误类型

---

### 第三阶段：AI 复盘报告

新增：

```text
GET /api/history/multiplayer/report/{round_id}
```

交付：

- 游戏结束展示个性化报告
- 输出弱点和复习建议

---

### 第四阶段：知识库动态牌局

新增：

```text
backend/agents/multiplayer_card_generator.py
```

交付：

- 基于 `corpus.json` 动态生成同专题牌局
- 后端强校验
- 失败回退静态牌库

---

## 十一、测试方案

### 11.1 后端测试

1. 启动多人局，确认 AI persona 返回
2. 调用 AI 回合，确认返回 `ai_reason`
3. 学生故意放错，确认返回 `coach_tip`
4. 学生清空手牌，确认可生成 final report
5. 选择“中国古代史”，确认不会出现“中国近代史/世界史”卡牌
6. 动态生成牌局时，确认所有卡牌属于所选范围

---

### 11.2 前端测试

1. 开始多人对战
2. 观察 AI 回合：先显示“正在思考”，再显示 AI 理由
3. 学生出错后，看到 AI 教练提示
4. 游戏结束后，看到复盘报告
5. 切换专题后，确认手牌和时间轴都在所选范围内

---

## 十二、风险与防护

| 风险 | 说明 | 防护 |
|---|---|---|
| LLM 胡编年份 | AI 生成卡牌可能错误 | 后端强校验 + 静态回退 |
| AI 理由与真实顺序不一致 | LLM 解释可能误导 | 最终判定仍由程序规则完成 |
| 成本过高 | 每回合都调 LLM 会慢 | P0 可先用模板，或只在 AI 回合调短文本模型 |
| 响应慢 | AI 思考时间过长 | 前端展示“正在思考”，后端设置超时与模板 fallback |
| 专题混杂 | 动态生成超出范围 | topic 校验，不合格直接丢弃 |

---

## 十三、推荐结论

建议优先实现：

```text
P0 AI 虚拟同学化 + P1 AI 教练提示
```

原因：

- 对现有规则影响最小
- 学生最容易感知“AI 参与”
- 不依赖大规模动态卡牌生成
- 可以继续使用当前稳定的静态卡池
- 后续自然过渡到知识库动态出题和个性化复盘

如果只做一个最小版本，建议先做：

```text
AI 玩家人设 + AI 出牌理由 + 学生错牌教练提示
```
