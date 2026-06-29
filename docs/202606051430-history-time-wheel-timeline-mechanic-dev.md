# 时间巨轮卡牌游戏 — 对齐原版《时间线》玩法开发文档

> 日期：2026-06-05 | 项目：edu-agent-platform | 关联：`202606051144-history-time-wheel-card-game-dev.md`

---

## 一、背景与目标

当前实现是"一次性发完所有牌、全部放置后一次判分"，与原版《时间线》（Timeline）桌游的核心机制差距较大。

原版核心规则：
- 每张牌正面事件、背面年份，出牌前不看年份
- 桌面有一条持续增长的公共时间轴作为参照（含一张已翻面的基准卡）
- 玩家每回合只出**一张**牌，插入时间轴的某个位置
- 翻面验证：放对留下、手牌减一；放错回手牌（手牌总数不变）
- 手牌清空即胜利

本次改造目标：**只改前端** `TimelineGameClient.tsx`，不改后端 API，让线上版本的节奏感与原版对齐。

---

## 二、后端 API 复用策略

后端 `/start` 和 `/submit` 保持不变。利用方式：

1. **开局**：调用 `/start` 获取 5 张事件（打乱顺序，不含 year int）
2. **初始化**：立即用这 5 张的 id 顺序调用 `/submit`，拿到 `correct_order` 和每张卡的 `explanation` + `display_year`
3. 把 `correct_order[0]` 的事件作为**基准卡**（已翻面显示年份），其余 4 张打乱作为手牌
4. 后续每次玩家插入一张牌，**纯前端判断**：比对玩家选的插入位置在 `correct_order` 中是否正确，不再调用 API

整局只需 2 次 API 调用（`/start` + 开局 `/submit`），后续交互全在前端完成，响应即时。

---

## 三、状态模型重构

### 3.1 删除的状态

```ts
// 删除
slots: (TimelineEventCard | null)[]   // 固定槽位模型
allPlaced: boolean
```

### 3.2 新增的状态

```ts
timeline: TimelineEventCardWithYear[]  // 公共时间轴（含 year 和 displayYear）
handCards: TimelineEventCardWithYear[] // 玩家手牌
activeCardId: string | null            // 当前选中准备出的牌
correctOrder: string[]                 // 开局 submit 拿到的正确顺序（event id 列表）
cardMeta: Map<string, CardMeta>        // id → { displayYear, explanation, suggestedQuestion }
lastFeedback: Feedback | null          // 上一次出牌的反馈（正确/错误+讲解）
score: { correct: number; wrong: number }
```

```ts
type TimelineEventCardWithYear = TimelineEventCard & { yearRank: number }
// yearRank = 在 correct_order 中的 index，用于前端判断位置是否合法

type CardMeta = {
  displayYear: string
  explanation: string
  suggestedQuestion: string | null
}

type Feedback = {
  cardId: string
  cardTitle: string
  correct: boolean
  displayYear: string
  explanation: string
  suggestedQuestion: string | null
}
```

### 3.3 游戏阶段

```ts
type GamePhase =
  | "idle"
  | "starting"      // /start 调用中
  | "initializing"  // /submit 初始化调用中
  | "playing"       // 正常游戏中
  | "result"        // 手牌清空，胜利
```

---

## 四、游戏流程

```
startRound()
  → POST /start           拿到 5 张事件（打乱）
  → POST /submit          传入打乱顺序，拿 correct_order + items
  → 初始化：
      timeline = [events[correct_order[0]]]（基准卡，已翻面）
      handCards = shuffle(correct_order.slice(1) 对应的事件)
      phase = "playing"

每回合：
  玩家点击手牌 → activeCardId 设置，手牌高亮
  时间轴显示插入位置指示器（timeline.length + 1 个位置）
  玩家点击插入位置 i（0 = 最左，timeline.length = 最右）
  
  前端判断：
    card.yearRank 是否满足：
      timeline[i-1].yearRank < card.yearRank < timeline[i].yearRank
      （边界：i=0 时只需 < timeline[0].yearRank；i=length 时只需 > timeline[last].yearRank）

  放对：
    将卡插入 timeline[i]，翻面显示 displayYear
    handCards.remove(card)
    score.correct++
    lastFeedback = { correct: true, ... }
    if handCards.length === 0 → phase = "result"

  放错：
    lastFeedback = { correct: false, displayYear, explanation, ... }
    activeCardId = null（牌留在手牌区，不移动）
    score.wrong++
```

---

## 五、UI 结构

### 5.1 时间轴区（主要操作区，上方）

```
[基准卡 翻面] ·插· [已放卡1 翻面] ·插· [已放卡2 翻面] ·插·
```

- 基准卡和已放置卡：显示事件名 + `displayYear`
- `·插·`：插入位置指示器，仅在 `activeCardId !== null` 时可见和可点击
- 点击插入位置 → 触发判定逻辑

### 5.2 手牌区（下方横排）

- 每张手牌只显示事件名 + period（不显示年份）
- 点击选中 → `activeCardId` 设置，高亮
- 再次点击已选中的牌 → 取消选中

### 5.3 反馈区（手牌区上方）

判定后显示一条反馈条：
- 放对：「✓ 秦始皇统一六国 放置正确！（公元前221年）」绿色
- 放错：「✗ 商鞅变法 应该更早。（公元前356年）商鞅变法发生在…」红色，3秒后淡出或点击关闭

---

## 六、CSS 类复用

已有 CSS 类（`globals.css`）：

| 用途 | 类名 |
|---|---|
| 手牌区容器 | `.card-game-hand-grid` |
| 手牌卡片 | `.history-card`，`.history-card.selected` |
| 时间轴容器 | `.card-game-rail` |
| 已放置卡 | `.card-game-placed-card` |
| 反馈 | `.timeline-feedback` |
| 报告面板 | `.card-game-report-panel`，`.card-game-report-stats` |

新增仅需两个 CSS 规则（写在 `globals.css` 末尾）：

```css
/* 插入位置指示器 */
.timeline-insert-point { ... }
.timeline-insert-point.active:hover { ... }
```

---

## 七、开发任务

- [ ] 重构 `TimelineGameClient.tsx` 状态（删 slots，加 timeline/handCards/activeCardId/correctOrder/cardMeta）
- [ ] 改 `startRound`：串行调 `/start` → `/submit` → 初始化状态
- [ ] 实现 `selectCard(id)` / `insertAt(index)` 逻辑
- [ ] 重写时间轴 JSX：已放卡 + 插入位置指示器交替排列
- [ ] 重写手牌区 JSX：点击选中，activeCard 高亮
- [ ] 新增反馈条 JSX
- [ ] `globals.css` 补两条插入指示器样式

---

## 八、验收标准

| 检查项 | 标准 |
|---|---|
| 基准卡 | 发牌后时间轴显示 1 张已翻面的基准卡（含年份） |
| 手牌 | 剩余 4 张在手牌区，不显示年份 |
| 选牌 | 点击手牌高亮，时间轴出现插入指示器 |
| 放对 | 卡翻面（显示年份）进入时间轴，手牌减一，绿色反馈 |
| 放错 | 红色反馈 + 年份 + 讲解，手牌不减 |
| 胜利 | 手牌清空后进入结果页，显示得分和 AI 学习提示 |
| 取消 API | 逐张判定不调用 API，只用开局拿到的 correct_order 判断 |
