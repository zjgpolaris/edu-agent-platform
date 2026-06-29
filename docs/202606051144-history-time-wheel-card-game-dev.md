# 时间巨轮 AI 卡牌游戏 — 开发文档

> 日期：2026-06-05 | 项目：edu-agent-platform | 关联 PRD：`202606051127-history-time-wheel-ai-card-game-prd.md`

---

## 一、目标与范围

在现有"时间线修复师"基础上，扩展为完整的**时间巨轮 AI 卡牌游戏**（MVP 阶段）。

**复用现有能力：**

| 现有资产 | 复用方式 |
|---|---|
| `textbooks/structured/*.yaml` | 卡牌候选事件数据来源（六册全覆盖） |
| `backend/agents/timeline_question_generator.py` | 动态组题逻辑，扩展卡牌类型 |
| `backend/agents/history_games.py` | 游戏状态管理，扩展新玩法接口 |
| `backend/api/main.py` | FastAPI 路由，新增卡牌游戏端点 |
| `frontend/app/history-games/timeline/` | 现有时间轴 UI 组件，扩展为卡牌拖放界面 |
| `.chroma` 向量库 | AI 讲解和追问时检索背景知识 |

**MVP 交付范围（对应 PRD §13）：**

- 时间排序玩法（事件卡拖放到横向时间轴）
- 年级 + 册别 + 专题选择
- AI 动态出题（LLM + 知识库候选事件）
- 提交后判题 + AI 错误讲解 + 追问
- 一次修正机会
- 局后复盘报告
- 错题记录持久化（session 级别，本期内存存储）

---

## 二、数据流与架构

```
前端卡牌游戏界面
  │
  ├─ POST /api/history/card-game/start   → 发牌（AI 动态选题）
  ├─ POST /api/history/card-game/submit  → 判题 + 讲解
  ├─ POST /api/history/card-game/retry   → 修正提交（一次机会）
  └─ GET  /api/history/card-game/report/{session_id}  → 复盘报告
```

```
知识库数据流：

textbooks/structured/*.yaml
  └─ flatten_static_levels()  ← 已有，复用
        └─ filter_candidates()   按年级/专题/难度/去重筛选
              └─ LLM 组题          选卡 + 生成线索 + 讲解 + 追问
                    └─ validate_plan()  年份校验 + 防幻觉
                          └─ 返回前端卡牌数据
```

---

## 三、卡牌数据结构

MVP 阶段只实现**历史事件卡**，其余卡类型（人物卡、朝代卡、影响卡）后续增量加入。

### 3.1 前端卡牌类型

```typescript
// 游戏卡牌（展示用，不含标准答案）
type HistoryCard = {
  id: string;
  cardType: "event";            // MVP 只有 event
  title: string;
  period: string;               // 朝代/时期（提交前可见）
  clue: string;                 // 线索描述，不含精确年份
  topic: string;
  difficulty: "easy" | "normal" | "hard";
};

// 时间轴插槽
type TimelineSlot = {
  slotIndex: number;            // 0-based，从左到右
  placedCardId: string | null;
};

// 游戏局
type CardGameRound = {
  roundId: string;
  title: string;
  learningGoal: string | null;
  grade: string;
  topic: string;
  difficulty: "easy" | "normal" | "hard";
  cards: HistoryCard[];         // 打乱后的手牌
  slotCount: number;            // 等于 cards.length
};

// 提交结果（单卡）
type CardResult = {
  cardId: string;
  title: string;
  displayYear: string;
  period: string;
  isCorrect: boolean;
  correctSlot: number;
  submittedSlot: number;
  explanation: string;
  followUpQuestion: string | null;
};

// 局结果
type RoundResult = {
  roundId: string;
  score: number;
  total: number;
  canRetry: boolean;            // 是否还有一次修正机会
  items: CardResult[];
  learningTip: string;
  correctOrder: string[];       // card id 按正确顺序
};
```

### 3.2 后端内部结构（扩展现有 `TimelineEventInternal`）

现有 `TimelineEventInternal` 字段完整沿用，新增：

```python
class CardGameRoundRecord(TypedDict):
    round_id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    cards: list[TimelineEventInternal]   # 复用现有结构
    correct_order: list[str]             # card id 按 year 排序
    created_at: datetime
    learning_goal: str | None
    retry_used: bool                     # 是否已用修正机会
    source: Literal["llm", "static"]
```

---

## 四、后端实现

### 4.1 新增 Agent：`backend/agents/card_game.py`

复用 `timeline_question_generator.py` 的全部候选事件逻辑，新增：

**`build_card_game_prompt()`** — 相比 timeline 版本，调整：
- `clue` 字段增加难度感知（easy 级别允许说明所属朝代，hard 不给时期提示）
- 增加 `follow_up_question`（用于追问，区别于 `suggested_question`）

**`generate_card_game_round()`** — 入口函数，签名：

```python
def generate_card_game_round(
    levels: list[dict],           # 来自 YAML flatten 后的静态关卡
    grade: str | None,
    difficulty: str,
    topic: str | None,
    student_id: str | None,
    recent_store: dict[str, list[str]],
    wrong_card_ids: list[str],    # 新增：错题优先权重
) -> dict:
    ...
```

`wrong_card_ids` 不为空时，`filter_candidates` 优先保留这些 id，让错题复出。

**`generate_retry_explanation()`** — 修正提交后调用，针对仍错的卡片生成二次讲解：

```python
def generate_retry_explanation(
    wrong_items: list[dict],      # 仍然错误的卡
    round_context: str,           # 本局主题
) -> dict[str, str]:              # card_id -> 二次讲解文本
    ...
```

### 4.2 游戏状态存储：`backend/agents/history_games.py` 扩展

在现有 `ACTIVE_ROUNDS: dict[str, TimelineRoundRecord]` 旁边新增：

```python
ACTIVE_CARD_GAME_ROUNDS: dict[str, CardGameRoundRecord] = {}
CARD_GAME_WRONG_RECORDS: dict[str, list[str]] =    # student_id -> [card_id]
```

新增函数：

```python
def start_card_game_round(grade, difficulty, topic, student_id, mode) -> dict: ...
def submit_card_game_round(round_id, submitted_order) -> dict: ...
def retry_card_game_round(round_id, revised_order) -> dict: ...
def get_card_game_report(student_id) -> dict: ...
```

`submit_card_game_round` 判分逻辑与现有 `submit_timeline_round` 完全一致（按 year 对比 index），可直接复用。

### 4.3 API 路由：`backend/api/main.py` 新增

```python
class CardGameStartRequest(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None
    student_id: str | None = None

class CardGameSubmitRequest(BaseModel):
    round_id: str
    submitted_card_ids: list[str]   # 按玩家排列顺序

class CardGameRetryRequest(BaseModel):
    round_id: str
    revised_card_ids: list[str]

@app.post("/api/history/card-game/start")
@app.post("/api/history/card-game/submit")
@app.post("/api/history/card-game/retry")
@app.get("/api/history/card-game/report/{student_id}")
```

---

## 五、前端实现

### 5.1 路由结构

```
frontend/app/
  history-games/
    card-game/
      page.tsx               ← 服务端壳，导入 Client
      CardGameClient.tsx     ← 全部交互逻辑
```

### 5.2 游戏阶段状态机

```typescript
type GamePhase =
  | "idle"          // 选择年级/专题/难度
  | "starting"      // API 请求中
  | "playing"       // 手牌在手，时间轴等待放置
  | "submitting"    // 判题请求中
  | "result"        // 显示结果，可修正或下一局
  | "retrying"      // 修正提交中
  | "report";       // 复盘报告
```

### 5.3 关键交互

**手牌区（Card Hand）**  
- 卡牌从 API 响应中生成，展示 `title` + `clue` + `period`
- 状态：`inHand | placed | dragging`
- 拖起一张卡时，其他卡给出 drop-zone 高亮

**时间轴区（Timeline Rail）**  
- `slotCount` 个插槽，从左到右编号 1…N
- 每个插槽接受 `onDrop`，放置后卡牌从手牌区移除
- 插槽间可拖动交换（已在 Timeline 组件实现，复用）
- 备用交互：点击卡片 → 点击目标插槽（移动端适配）

**提交流程**  
- 所有插槽非空时"提交"按钮激活
- 提交后卡牌锁定，显示 `correct/incorrect` 颜色状态
- 错误卡显示正确位置 + `explanation` + `followUpQuestion`

**修正机会**  
- `result.canRetry === true` 时显示"修正一次"按钮
- 修正模式：仅错误卡解锁，可重新拖放
- 修正提交后 `canRetry` 变为 `false`

### 5.4 选题控件

沿用 `TimelineGameClient.tsx` 的选择控件，扩展年级选项：

```typescript
const gradeOptions = ["七年级上", "七年级下", "八年级上", "八年级下", "九年级上", "九年级下"];
const topicOptions = ["中国古代史", "中国近代史", "中国现代史", "世界近代史", "世界现代史"];
const difficultyOptions = [
  { value: "easy",   label: "入门", note: "有朝代提示，4张卡" },
  { value: "normal", label: "标准", note: "无年份，5张卡" },
  { value: "hard",   label: "挑战", note: "含干扰卡，5张卡" },
];
```

---

## 六、知识库接入策略

### 6.1 候选事件来源

**第一优先**：现有 `TIMELINE_LEVELS`（`history_games.py` 静态常量），已有结构化 `year` 字段，可直接判分。

**第二优先**：从 `textbooks/structured/*.yaml` 构建的扩展关卡（需要补充 `year` 字段）。目前六个 YAML 文件只有 `grade` 和 `book` 两个顶层字段，尚未录入课程内容。在知识库补齐前，使用 LLM 从 corpus.json 抽取带年份的事件候选池。

### 6.2 corpus.json 事件候选池构建（临时方案）

```python
# scripts/build_card_candidates.py
# 从 corpus.json 中抽取带年份的历史事件，构建候选池 JSON
# 供 card_game.py 的 filter_candidates() 使用
```

脚本逻辑：
1. 读取 `knowledge_base/history/corpus.json`
2. 对每条 `type=textbook` 的条目，用 LLM 提取 `{title, year, display_year, period, summary, topic}`
3. `year` 为 int，无法提取精确年份则跳过（不猜测）
4. 输出 `knowledge_base/history/card_candidates.json`

> **注意**：`year` 字段是判分基准，必须来自教材标准表述，LLM 提取后人工抽检。

### 6.3 RAG 在 AI 讲解中的用法

AI 讲解（`explanation`）和追问（`follow_up_question`）生成时，通过 `get_retriever("history")` 检索相关段落，注入 prompt，保持与现有 `history_character.py` 一致的 RAG 模式。

---

## 七、开发任务

### Phase 1：后端扩展（2~3 天）

- [ ] `scripts/build_card_candidates.py` — 从 corpus.json 构建候选池
- [ ] `backend/agents/card_game.py` — 复用 timeline_question_generator，新增难度感知 prompt 和 retry 讲解
- [ ] `backend/agents/history_games.py` — 新增 CardGameRoundRecord + 四个函数
- [ ] `backend/api/main.py` — 新增四个路由
- [ ] 单元测试：判分逻辑、LLM plan 校验（参考现有 eval/history_character_smoke.py 模式）

### Phase 2：前端实现（2~3 天）

- [ ] `frontend/app/history-games/card-game/page.tsx`
- [ ] `frontend/app/history-games/card-game/CardGameClient.tsx`
  - 手牌区组件
  - 时间轴区组件（复用 timeline 拖放逻辑）
  - 结果面板（判题反馈 + 讲解 + 修正按钮）
  - 复盘报告展示
- [ ] 在 `history-games/page.tsx` 游戏大厅添加入口卡片

### Phase 3：知识库补齐（并行，影响题目多样性）

- [ ] 补充 `textbooks/structured/*.yaml` 内容（参考知识库补齐文档）
- [ ] 或直接用 `build_card_candidates.py` 从 corpus 自动构建候选池

---

## 八、与现有模块的差异说明

| 对比项 | 时间线修复师（现有） | 时间巨轮卡牌游戏（本期） |
|---|---|---|
| 交互方式 | 列表拖动 + 上移/下移 | 手牌区 → 时间轴插槽拖放 |
| 卡牌来源 | 静态 TIMELINE_LEVELS + LLM 选题 | 同左 + corpus.json 候选池扩展 |
| 修正机会 | 无 | 一次修正 |
| 错题记录 | 无 | session 内持久化，影响下局出题 |
| 复盘报告 | `learning_tip`（单条文本） | 结构化报告：正确率 + 易错点 + 推荐下一局 |
| 年级选择 | 未实现 | 支持七上～九下 |

---

## 九、验收标准（MVP）

| 检查项 | 标准 |
|---|---|
| 出题 | 每局生成 4~5 张不重复事件卡，LLM 失败时 fallback 到静态关卡 |
| 判分 | 按 `year` int 字段判断，不依赖 LLM |
| 讲解 | 每张错误卡有 ≥ 20 字 explanation，不出现精确年份泄露 |
| 修正 | 一次修正后 `canRetry` 变为 false，修正结果独立记录 |
| 错题记录 | 错误 card_id 写入 `CARD_GAME_WRONG_RECORDS[student_id]`，下局调用时优先复用 |
| 拖放交互 | 桌面端鼠标拖放、上移/下移按钮均可完成排序 |
| 移动端备用 | 点击选卡 + 点击插槽放置可用 |

---

## 十、暂不实现（本期排除）

- 多人实时联机
- 圆盘式时间巨轮（保留横向时间轴）
- 朝代归类玩法、因果接龙玩法、人物配对玩法
- 教师主持模式
- 语音主持人
- 卡牌收集成长体系
