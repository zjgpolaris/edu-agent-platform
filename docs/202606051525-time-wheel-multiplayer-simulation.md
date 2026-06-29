# 时间巨轮多人模拟开发方案

**目标**：让学生单人游戏时，体验多人轮流对战，AI 模拟其他玩家出牌。

---

## 一、核心改动对照表

| 规则要求 | 当前实现 | 目标实现 |
|---------|---------|---------|
| 2–6 人轮流出牌 | 仅单人 | 学生 + N 个 AI 玩家轮流 |
| 共享牌堆（54张） | AI 动态生成固定数量 | 初始化牌堆，摸牌时从牌堆顶抽取 |
| 放错罚摸1张 | 仅牌归手中 | 从牌堆顶摸1张加入手牌 |
| 手牌5张起始 | 全部卡牌打乱后初始化 | 每人摸5张，牌堆剩余 |
| 最先出完手牌获胜 | 手牌清空结束 | 首个手牌清空的玩家获胜，其他玩家继续或终止 |

---

## 二、架构设计

### 2.1 数据结构调整

#### Backend（`history_games.py`）

```python
class MultiplayerGameState(TypedDict):
    round_id: str
    deck: list[str]  # 剩余牌堆（卡牌id列表）
    timeline: list[str]  # 公共时间轴（已翻面卡牌id，按正确顺序）
    players: list[PlayerState]
    current_player_index: int
    winner_player_id: str | None
    created_at: datetime

class PlayerState(TypedDict):
    player_id: str
    player_type: Literal["human", "ai"]
    display_name: str
    hand: list[str]  # 手牌id列表
    finished: bool  # 是否已出完手牌
    stats: PlayerStats

class PlayerStats(TypedDict):
    correct_plays: int
    wrong_plays: int
```

#### Frontend（`TimelineGameClient.tsx`）

```typescript
type Player = {
  playerId: string;
  playerType: "human" | "ai";
  displayName: string;
  handCount: number;  // AI玩家仅显示手牌数量，不显示具体卡牌
  finished: boolean;
  stats: { correct: number; wrong: number };
};

type GameState = {
  roundId: string;
  timeline: Card[];  // 公共时间轴
  players: Player[];
  currentPlayerIndex: number;
  humanPlayerId: string;
  deckCount: number;  // 剩余牌堆数量
  winnerPlayerId: string | null;
};
```

---

### 2.2 游戏流程

#### 阶段1：初始化（`POST /api/history/multiplayer/start`）

**请求参数**：
```json
{
  "grade": "七年级上",
  "difficulty": "easy",
  "topic": "中国古代史",
  "student_id": "demo-student",
  "ai_player_count": 2,  // AI玩家数量（1–5）
  "ai_difficulty": "medium"  // AI失误率：easy=30%, medium=15%, hard=5%
}
```

**后端逻辑**：
1. 生成完整卡牌池（LLM动态生成或静态语料库，目标54张或更少）
2. 洗牌后分配：
   - 翻1张作为起始时间点（anchor）
   - 每人摸5张手牌（学生 + AI玩家）
   - 剩余进入牌堆
3. 初始化玩家列表：
   - `players[0]` 固定为学生（`player_type="human"`）
   - `players[1..N]` 为AI（`player_type="ai"`，`display_name="AI 小明"/"AI 小红"`）
4. 随机决定先手（`current_player_index`）

**响应**：
```json
{
  "round_id": "multiplayer-20260605-abc123",
  "timeline": [{ "id": "anchor-card", "title": "...", ... }],
  "players": [
    {
      "player_id": "human-student",
      "player_type": "human",
      "display_name": "你",
      "hand": [{ "id": "card1", ... }, ...],  // 仅学生返回完整手牌
      "finished": false,
      "stats": { "correct": 0, "wrong": 0 }
    },
    {
      "player_id": "ai-player-1",
      "player_type": "ai",
      "display_name": "AI 小明",
      "hand_count": 5,  // AI仅返回手牌数量
      "finished": false,
      "stats": { "correct": 0, "wrong": 0 }
    }
  ],
  "current_player_index": 0,
  "deck_count": 43,  // 牌堆剩余数量
  "winner_player_id": null
}
```

---

#### 阶段2：轮次流转

##### 2.1 学生回合（`POST /api/history/multiplayer/play`）

**请求参数**：
```json
{
  "round_id": "multiplayer-20260605-abc123",
  "player_id": "human-student",
  "card_id": "card1",
  "insert_index": 2  // 插入时间轴的索引位置
}
```

**后端逻辑**：
1. 验证当前玩家是否为该学生
2. 判断插入位置正确性
3. **正确**：
   - 从手牌移除该卡，插入 `timeline`
   - `stats.correct++`
   - 检查手牌是否清空 → 设置 `winner_player_id`
4. **错误**：
   - 牌归手中（保持不变）
   - **从 `deck` 顶部抽1张加入手牌**（若牌堆为空则跳过）
   - `stats.wrong++`
5. `current_player_index = (current_player_index + 1) % len(players)`
6. 返回更新后的游戏状态

**响应**：
```json
{
  "success": true,
  "correct": false,
  "feedback": {
    "card_title": "商鞅变法",
    "display_year": "公元前356年",
    "explanation": "商鞅变法发生在战国时期...",
    "suggested_question": "你为什么要变法？"
  },
  "drew_penalty_card": true,  // 是否罚摸牌
  "penalty_card": { "id": "card-new", ... },  // 罚摸的牌（仅学生可见）
  "game_state": { /* 最新游戏状态 */ }
}
```

---

##### 2.2 AI回合（前端轮询或后端自动触发）

**方案A（推荐）**：前端轮询检测

```typescript
// 当 currentPlayerIndex 指向 AI 时，前端自动发起请求
if (gameState.players[gameState.currentPlayerIndex].playerType === "ai") {
  await fetch(`${apiBaseUrl}/api/history/multiplayer/ai-turn`, {
    method: "POST",
    body: JSON.stringify({ round_id: gameState.roundId })
  });
}
```

**后端逻辑（`POST /api/history/multiplayer/ai-turn`）**：
1. 获取当前AI玩家的手牌
2. **AI决策算法**：
   - **Hard（5%失误率）**：95%概率选正确位置，5%概率随机位置
   - **Medium（15%失误率）**：85%正确
   - **Easy（30%失误率）**：70%正确
3. 模拟出牌：
   - 从手牌中随机选一张（或优先选 `yearRank` 最早/最晚的牌）
   - 按失误率决定插入位置
4. 应用相同的正确/错误逻辑（AI错误时也会罚摸牌）
5. 流转到下一玩家
6. 返回 AI 出牌动画数据 + 最新游戏状态

**响应**：
```json
{
  "ai_player_id": "ai-player-1",
  "ai_display_name": "AI 小明",
  "card_played": { "id": "card5", "title": "秦统一六国", ... },
  "insert_index": 3,
  "correct": true,
  "drew_penalty_card": false,
  "game_state": { /* 最新状态 */ }
}
```

**方案B**：后端自动触发（需要 WebSocket 或长轮询）
- AI回合时后端延迟 1–2 秒自动执行，推送事件到前端
- 实现复杂度较高，推荐方案A

---

#### 阶段3：游戏结束

**触发条件**：某玩家手牌清空 → `winner_player_id` 不为空

**前端展示**：
- 学生获胜：庆祝动画 + "你赢了！"
- AI获胜：显示 "AI 小明 获胜！再来一局？"
- 完整排行榜：按完成顺序展示所有玩家

---

## 三、前端交互设计

### 3.1 多人信息面板

```tsx
<div className="multiplayer-players-panel">
  {players.map((player, index) => (
    <div 
      className={`player-card ${index === currentPlayerIndex ? 'active' : ''} ${player.finished ? 'finished' : ''}`}
      key={player.playerId}
    >
      <div className="player-avatar">{player.playerType === "human" ? "👤" : "🤖"}</div>
      <div className="player-info">
        <strong>{player.displayName}</strong>
        <span>手牌：{player.playerType === "human" ? player.hand?.length : player.handCount} 张</span>
        <span>✓ {player.stats.correct} / ✗ {player.stats.wrong}</span>
      </div>
      {index === currentPlayerIndex && <div className="turn-indicator">▶ 出牌中</div>}
      {player.finished && <div className="finished-badge">已完成</div>}
    </div>
  ))}
</div>
```

### 3.2 AI出牌动画

```tsx
async function executeAiTurn() {
  setPhase("ai-playing");
  const response = await fetch(`${apiBaseUrl}/api/history/multiplayer/ai-turn`, {
    method: "POST",
    body: JSON.stringify({ round_id: gameState.roundId })
  });
  const data = await response.json();
  
  // 动画：显示AI选择的牌飞向时间轴
  setAiPlayAnimation({
    playerName: data.ai_display_name,
    card: data.card_played,
    insertIndex: data.insert_index,
    correct: data.correct
  });
  
  await sleep(2000);  // 等待动画完成
  
  setGameState(data.game_state);
  setPhase("playing");
  
  // 如果下一个仍是AI，继续触发
  if (data.game_state.players[data.game_state.current_player_index].player_type === "ai") {
    await executeAiTurn();
  }
}
```

---

## 四、API端点汇总

| 端点 | 方法 | 功能 |
|-----|------|------|
| `/api/history/multiplayer/start` | POST | 初始化多人游戏 |
| `/api/history/multiplayer/play` | POST | 学生出牌 |
| `/api/history/multiplayer/ai-turn` | POST | 执行AI回合 |
| `/api/history/multiplayer/state` | GET | 获取当前游戏状态（用于断线重连）|

---

## 五、开发优先级

### P0（核心功能）
- [ ] 后端：牌堆 + 罚摸逻辑
- [ ] 后端：玩家轮转 + AI决策算法
- [ ] 前端：多人信息面板
- [ ] 前端：AI出牌动画

### P1（体验优化）
- [ ] AI失误率可配置（easy/medium/hard）
- [ ] 断线重连（通过 `GET /state` 恢复游戏）
- [ ] 游戏历史记录（记录每局的获胜者和统计）

### P2（扩展功能）
- [ ] 真人多人联机（WebSocket）
- [ ] 观战模式（旁观AI vs AI）
- [ ] 排行榜（最快完成时间、最高正确率）

---

## 六、测试用例

### 6.1 单元测试

```python
def test_penalty_draw():
    """放错罚摸1张"""
    game = create_multiplayer_game(ai_count=1)
    player = game["players"][0]
    initial_hand_count = len(player["hand"])
    
    # 学生出错
    result = play_card(game, player["player_id"], wrong_card_id, wrong_index)
    
    assert not result["correct"]
    assert result["drew_penalty_card"] == (game["deck_count"] > 0)
    assert len(player["hand"]) == initial_hand_count + 1  # 罚摸1张

def test_ai_turn():
    """AI自动出牌"""
    game = create_multiplayer_game(ai_count=2)
    game["current_player_index"] = 1  # 轮到AI
    
    result = execute_ai_turn(game)
    
    assert result["ai_player_id"] == game["players"][1]["player_id"]
    assert result["card_played"]["id"] in game["players"][1]["hand"]
    assert game["current_player_index"] == 2  # 已流转到下一玩家

def test_winner_detection():
    """首个清空手牌者获胜"""
    game = create_multiplayer_game(ai_count=2)
    player = game["players"][1]  # AI玩家
    player["hand"] = ["last-card"]
    
    play_card(game, player["player_id"], "last-card", correct_index)
    
    assert game["winner_player_id"] == player["player_id"]
    assert player["finished"] == True
```

### 6.2 前端E2E测试

1. 启动多人游戏（学生 + 2个AI）
2. 学生出错 → 验证罚摸牌出现在手牌区
3. 轮到AI → 自动执行 → 时间轴更新
4. 学生清空手牌 → 显示获胜界面

---

## 七、实现时间估算

| 任务 | 工时 |
|-----|------|
| 后端：牌堆 + 罚摸逻辑 | 2h |
| 后端：AI决策算法 | 3h |
| 前端：多人面板 + 轮转逻辑 | 4h |
| 前端：AI动画 | 3h |
| 测试 + 调试 | 4h |
| **总计** | **16h** |

---

## 八、关键风险

| 风险 | 缓解方案 |
|-----|---------|
| 牌堆不足（卡牌总数 < 玩家数×5+1） | 动态生成时保证最少生成 `(玩家数×5 + 10)` 张 |
| AI出牌过快（用户看不清） | 每次AI出牌延迟1.5–2秒 + 动画 |
| 学生退出后游戏状态丢失 | 将游戏状态持久化到数据库（或Redis TTL=2h）|

---

## 九、后续迭代方向

1. **真人联机**：WebSocket + 房间系统，支持好友组队
2. **AI人格化**：给AI玩家赋予"性格"（激进型���稳健型），影响出牌策略
3. **竞技模式**：限时对战，按完成时间和正确率综合排名
4. **教学模式**：老师创建房间，全班学生同时对战

---

**下一步行动**：从后端牌堆 + 罚摸逻辑开始实现（`start_multiplayer_round` 函数）。
