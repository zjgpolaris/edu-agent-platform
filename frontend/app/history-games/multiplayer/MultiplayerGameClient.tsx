"use client";

import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

type TimelineDifficulty = "easy" | "normal" | "hard";
type AiDifficulty = "easy" | "medium" | "hard";
type GamePhase = "idle" | "starting" | "playing" | "ai-playing" | "result";

type CardPublic = {
  id: string;
  title: string;
  period: string;
  summary: string;
  topic: string;
  display_year: string;
  year_rank: number;
};

type AiPersona = {
  name: string;
  persona: string;
  strength: string;
  weakness: string;
  style: string;
};

type PlayerPublic = {
  player_id: string;
  player_type: "human" | "ai";
  display_name: string;
  persona?: AiPersona | null;
  finished: boolean;
  correct_plays: number;
  wrong_plays: number;
  hand?: CardPublic[];
  hand_count?: number;
};

type AiThought = {
  playerName: string;
  reason: string;
  persona?: AiPersona | null;
  correct?: boolean;
};

type GameState = {
  round_id: string;
  timeline: CardPublic[];
  players: PlayerPublic[];
  current_player_index: number;
  deck_count: number;
  winner_player_id: string | null;
  source?: "llm" | "static";
  fallback_used?: boolean;
  generation_reason?: string | null;
  learning_goal?: string | null;
};

type Feedback = {
  correct: boolean;
  card_title: string;
  display_year: string;
  explanation: string;
  suggested_question?: string | null;
  penalty_card?: CardPublic | null;
  coach_tip?: string | null;
  error_type?: string | null;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const topicOptions = ["中国古代史", "中国近代史", "世界史"];
const difficultyOptions: Array<{ value: TimelineDifficulty; label: string }> = [
  { value: "easy", label: "入门" },
  { value: "normal", label: "标准" },
  { value: "hard", label: "挑战" },
];
const aiDifficultyOptions: Array<{ value: AiDifficulty; label: string; desc: string }> = [
  { value: "easy", label: "简单 AI", desc: "失误率 30%" },
  { value: "medium", label: "普通 AI", desc: "失误率 15%" },
  { value: "hard", label: "强力 AI", desc: "失误率 5%" },
];

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchStartGame(body: Record<string, unknown>, timeoutMs?: number) {
  const controller = timeoutMs ? new AbortController() : undefined;
  const timer = timeoutMs ? window.setTimeout(() => controller?.abort(), timeoutMs) : undefined;
  try {
    return await fetch(`${apiBaseUrl}/api/history/multiplayer/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller?.signal,
    });
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

export default function MultiplayerGameClient() {
  const { user } = useAuth();
  const [phase, setPhase] = useState<GamePhase>("idle");
  const [topic, setTopic] = useState("中国古代史");
  const [difficulty, setDifficulty] = useState<TimelineDifficulty>("easy");
  const [aiCount, setAiCount] = useState(2);
  const [aiDifficulty, setAiDifficulty] = useState<AiDifficulty>("medium");
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [playerId, setPlayerId] = useState("student");
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [aiLog, setAiLog] = useState<string>("");
  const [aiThought, setAiThought] = useState<AiThought | null>(null);
  const [error, setError] = useState("");
  const [handOrder, setHandOrder] = useState<string[]>([]);
  const [draggingCardId, setDraggingCardId] = useState<string | null>(null);
  const [dragInsertIndex, setDragInsertIndex] = useState<number | null>(null);
  const aiRunning = useRef(false);

  // drive AI turns automatically
  useEffect(() => {
    if (!gameState || phase !== "playing" || gameState.winner_player_id) return;
    const cur = gameState.players[gameState.current_player_index];
    if (cur.player_type === "ai" && !aiRunning.current) {
      runAiTurn();
    }
  });

  async function startGame() {
    setPhase("starting");
    setError("");
    setFeedback(null);
    setAiLog("");
    setAiThought(null);
    setSelectedCardId(null);
    setHandOrder([]);
    setDraggingCardId(null);
    setDragInsertIndex(null);
    aiRunning.current = false;
    try {
      const requestBody = {
        topic, difficulty, ai_count: aiCount, ai_difficulty: aiDifficulty,
        student_id: user?.actorId ?? "",
      };
      const res = await fetchStartGame({ ...requestBody, mode: "llm" });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      const data: GameState = await res.json();
      const human = data.players.find((p) => p.player_type === "human");
      setPlayerId(human?.player_id ?? "student");
      setGameState(data);
      setPhase("playing");
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
      setPhase("idle");
    }
  }

  async function runAiTurn() {
    if (!gameState || aiRunning.current) return;
    aiRunning.current = true;
    setPhase("ai-playing");

    const cur = gameState.players[gameState.current_player_index];
    setAiLog(`${cur.display_name} 正在思考……`);
    await sleep(1500);

    try {
      const res = await fetch(`${apiBaseUrl}/api/history/multiplayer/ai-turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ round_id: gameState.round_id }),
      });
      if (!res.ok) {
        const errorData = await res.json().catch(() => null);
        throw new Error(errorData?.detail || `HTTP ${res.status}`);
      }
      const data: {
        ai_display_name: string;
        ai_persona?: AiPersona | null;
        ai_reason?: string;
        card_played: { title: string; display_year: string } | null;
        correct: boolean;
        game_state: GameState;
      } = await res.json();

      if (data.ai_reason) {
        setAiThought({
          playerName: data.ai_display_name,
          reason: data.ai_reason,
          persona: data.ai_persona ?? null,
          correct: data.correct,
        });
      } else {
        setAiThought(null);
      }

      if (data.card_played) {
        setAiLog(
          `${data.ai_display_name} 打出「${data.card_played.title}」（${data.card_played.display_year}）— ${data.correct ? "正确" : "位置错误，罚摸一张"}`
        );
      }

      setGameState(data.game_state);
      if (data.game_state.winner_player_id) {
        setPhase("result");
      } else {
        setPhase("playing");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI 出牌失败");
      setPhase("playing");
    } finally {
      aiRunning.current = false;
    }
  }

  async function insertAt(insertIndex: number, cardId = selectedCardId) {
    if (!gameState || !cardId) return;
    setFeedback(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/history/multiplayer/play`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          round_id: gameState.round_id,
          player_id: playerId,
          card_id: cardId,
          insert_index: insertIndex,
        }),
      });
      if (!res.ok) {
        const errorData = await res.json().catch(() => null);
        throw new Error(errorData?.detail || `HTTP ${res.status}`);
      }
      const data: { correct: boolean; feedback: Feedback; penalty_card: CardPublic | null; game_state: GameState } = await res.json();
      setFeedback({ ...data.feedback, correct: data.correct, penalty_card: data.penalty_card });
      setGameState(data.game_state);
      setSelectedCardId(null);
      setAiLog("");
      if (data.game_state.winner_player_id) setPhase("result");
    } catch (e) {
      setError(e instanceof Error ? e.message : "出牌失败");
    }
  }

  const humanPlayer = gameState?.players.find((p) => p.player_id === playerId);
  const orderedHand = useMemo(() => {
    const hand = humanPlayer?.hand ?? [];
    if (!hand.length) return [];
    const byId = new Map(hand.map((card) => [card.id, card]));
    const sorted = handOrder.map((id) => byId.get(id)).filter((card): card is CardPublic => Boolean(card));
    const known = new Set(sorted.map((card) => card.id));
    return [...sorted, ...hand.filter((card) => !known.has(card.id))];
  }, [handOrder, humanPlayer?.hand]);
  const isMyTurn = gameState
    ? gameState.players[gameState.current_player_index]?.player_id === playerId
    : false;
  const busy = phase === "starting" || phase === "ai-playing";
  const winner = gameState?.players.find((p) => p.player_id === gameState.winner_player_id);
  const currentPlayer = gameState?.players[gameState.current_player_index];
  const selectedCard = humanPlayer?.hand?.find((card) => card.id === selectedCardId) ?? null;
  const aiSeatPositions = ["tabletop-seat--top-left", "tabletop-seat--top-right", "tabletop-seat--left", "tabletop-seat--right", "tabletop-seat--top"];
  const getSeatPosition = (player: PlayerPublic, index: number) => {
    if (player.player_type === "human") return "tabletop-seat--bottom";
    const aiIndex = gameState?.players.slice(0, index).filter((p) => p.player_type === "ai").length ?? 0;
    return aiSeatPositions[aiIndex % aiSeatPositions.length];
  };
  const reorderHand = (targetCardId: string) => {
    if (!draggingCardId || draggingCardId === targetCardId) return;
    const ids = orderedHand.map((card) => card.id);
    const fromIndex = ids.indexOf(draggingCardId);
    const toIndex = ids.indexOf(targetCardId);
    if (fromIndex < 0 || toIndex < 0) return;
    const next = [...ids];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    setHandOrder(next);
  };
  const handleHandDragStart = (event: DragEvent<HTMLElement>, cardId: string) => {
    setDraggingCardId(cardId);
    setSelectedCardId(cardId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", cardId);
  };
  const handleHandDragOver = (event: DragEvent<HTMLElement>, cardId: string) => {
    if (!draggingCardId || draggingCardId === cardId) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    reorderHand(cardId);
  };
  const handleHandDrop = (event: DragEvent<HTMLElement>, cardId: string) => {
    event.preventDefault();
    event.stopPropagation();
    reorderHand(cardId);
    setDraggingCardId(null);
  };
  const handleTimelineDragOver = (event: DragEvent<HTMLElement>, insertIndex: number) => {
    if (!isMyTurn || !draggingCardId) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setDragInsertIndex(insertIndex);
  };
  const handleTimelineDrop = (event: DragEvent<HTMLElement>, insertIndex: number) => {
    if (!isMyTurn || !draggingCardId) return;
    event.preventDefault();
    event.stopPropagation();
    const cardId = event.dataTransfer.getData("text/plain") || draggingCardId;
    setSelectedCardId(cardId);
    setDraggingCardId(null);
    setDragInsertIndex(null);
    void insertAt(insertIndex, cardId);
  };
  const handleTimelineDragLeave = (event: DragEvent<HTMLElement>, insertIndex: number) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setDragInsertIndex((current) => current === insertIndex ? null : current);
    }
  };
  const handleHandDragEnd = () => {
    setDraggingCardId(null);
    setDragInsertIndex(null);
  };

  return (
    <main className="academy-shell history-games-shell timeline-studio-shell timewheel-table-page">
      <section className="timeline-studio-layout">
        <section className="panel timeline-workshop tabletop-stage">
          <div className="timeline-workshop-header timeline-workbench-header tabletop-header timewheel-hud">
            <div>
              <div className="panel-kicker">Time Wheel Table</div>
              <h2>时间巨轮 · 桌游牌局</h2>
              <p>
                {phase === "idle" && "选择规则后入座开局。"}
                {phase === "starting" && "正在洗牌发牌……"}
                {phase === "ai-playing" && aiLog}
                {phase === "playing" && (isMyTurn ? (selectedCardId ? "点击公共时间轴的「＋」落子。" : "轮到你，选择一张手牌。") : `${currentPlayer?.display_name ?? "AI"} 正在出牌。`)}
                {phase === "result" && (winner ? `${winner.display_name} 获胜！` : "本局结束。")}
              </p>
            </div>
            <div className="timewheel-hud-actions">
              {gameState && (
                <div className="tabletop-source-chip">
                  牌堆 {gameState.deck_count} · {gameState.source === "llm" && !gameState.fallback_used ? "AI 出题" : "静态题库"}
                </div>
              )}
              <button className="timewheel-ghost-btn" type="button" disabled={busy} onClick={startGame}>
                {phase === "starting" ? "洗牌中" : phase === "idle" ? "开始" : "重开"}
              </button>
              <a className="timewheel-ghost-btn" href="/student/history/games">大厅</a>
            </div>
          </div>

          {!gameState ? (
            <div className="tabletop-board tabletop-board--empty timewheel-board timewheel-board--empty">
              <div className="tabletop-felt tabletop-felt--empty">
                <div className="timewheel-start-modal">
                  <div className="timewheel-start-hero">
                    <div className="empty-stamp">战</div>
                    <div>
                      <span className="panel-kicker">Time Wheel Setup</span>
                      <strong>时间巨轮开局</strong>
                      <p>像斗地主一样围桌入座：你与 AI 轮流出牌，把历史事件放到正确年代顺序。</p>
                    </div>
                  </div>
                  {error ? <div className="error-card">{error}</div> : null}
                  <div className="timewheel-start-summary" aria-label="当前对战设置">
                    <span>{topic}</span>
                    <span>{difficultyOptions.find((o) => o.value === difficulty)?.label ?? "入门"}难度</span>
                    <span>{aiCount} 位 AI</span>
                    <span>{aiDifficultyOptions.find((o) => o.value === aiDifficulty)?.label ?? "普通 AI"}</span>
                  </div>
                  <div className="timewheel-start-grid">
                    <div className="timeline-control-group timewheel-start-card timewheel-start-card--wide">
                      <span>专题</span>
                      <small>选择本局事件范围</small>
                      <div className="timeline-choice-row">
                        {topicOptions.map((t) => (
                          <button key={t} className={topic === t ? "active" : ""} type="button" onClick={() => setTopic(t)}>{t}</button>
                        ))}
                      </div>
                    </div>
                    <div className="timeline-control-group timewheel-start-card">
                      <span>难度</span>
                      <small>决定年代跨度与干扰项</small>
                      <div className="timeline-choice-row timewheel-chip-row">
                        {difficultyOptions.map((o) => (
                          <button key={o.value} className={difficulty === o.value ? "active" : ""} type="button" onClick={() => setDifficulty(o.value)}>{o.label}</button>
                        ))}
                      </div>
                    </div>
                    <div className="timeline-control-group timewheel-start-card">
                      <span>AI 人数</span>
                      <small>当前 {aiCount} 位同桌玩家</small>
                      <div className="timeline-choice-row timewheel-player-count-row">
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button key={n} className={aiCount === n ? "active" : ""} type="button" onClick={() => setAiCount(n)}>{n}</button>
                        ))}
                      </div>
                    </div>
                    <div className="timeline-control-group timewheel-start-card">
                      <span>AI 水平</span>
                      <small>{aiDifficultyOptions.find((o) => o.value === aiDifficulty)?.desc ?? "失误率 15%"}</small>
                      <div className="timeline-choice-row timewheel-ai-level-row">
                        {aiDifficultyOptions.map((o) => (
                          <button key={o.value} className={aiDifficulty === o.value ? "active" : ""} type="button" onClick={() => setAiDifficulty(o.value)} title={o.desc}>{o.label}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                  <button className="primary timewheel-start-btn" type="button" disabled={busy} onClick={startGame}>
                    <span>{phase === "starting" ? "正在洗牌发牌……" : "开始对战"}</span>
                    <small>发牌后进入桌面牌局</small>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="tabletop-board timewheel-board">
              <div className="tabletop-felt">
                <div className="tabletop-table-ring" />
                <div className="tabletop-era-rail tabletop-era-rail--left" aria-hidden="true">
                  <span>远古</span><span>先秦</span><span>秦汉</span><span>隋唐</span>
                </div>
                <div className="tabletop-era-rail tabletop-era-rail--right" aria-hidden="true">
                  <span>宋元</span><span>明清</span><span>近代</span><span>现代</span>
                </div>
                <div className="tabletop-deck-stack" aria-label={`牌堆剩余 ${gameState.deck_count} 张`}>
                  <span>牌堆</span>
                  <strong>{gameState.deck_count}</strong>
                </div>
                {gameState.players.map((p, i) => (
                  <div
                    key={p.player_id}
                    className={[
                      "tabletop-seat",
                      getSeatPosition(p, i),
                      i === gameState.current_player_index && !p.finished ? "active" : "",
                      p.finished ? "finished" : "",
                      aiThought?.playerName === p.display_name ? "has-thought" : "",
                    ].filter(Boolean).join(" ")}
                  >
                    <div className="tabletop-seat-body">
                      <div className="tabletop-avatar">{p.player_type === "human" ? "你" : p.persona?.name.slice(0, 1) ?? "AI"}</div>
                      <div>
                        <strong>{p.display_name}</strong>
                        <span>手牌 {p.player_type === "human" ? (p.hand?.length ?? 0) : (p.hand_count ?? 0)} · {p.correct_plays}✓ {p.wrong_plays}✗</span>
                        {p.player_type === "ai" && p.persona && <small>{p.persona.style}</small>}
                      </div>
                    </div>
                    {aiThought?.playerName === p.display_name && (
                      <div className={`tabletop-seat-thought ${aiThought.correct ? "correct" : "incorrect"}`}>
                        <b>{p.display_name} 的思考</b>
                        <p>{aiThought.reason}</p>
                      </div>
                    )}
                  </div>
                ))}

                <div className="tabletop-center timewheel-play-zone">
                  {gameState.learning_goal && <div className="tabletop-goal">本局目标：{gameState.learning_goal}</div>}
                  {phase !== "result" && currentPlayer && (
                    <div className={["tabletop-turn-banner", isMyTurn ? "is-human-turn" : ""].filter(Boolean).join(" ")}>
                      <span className="tabletop-turn-orb">{isMyTurn ? "你" : "AI"}</span>
                      <div>
                        <b>{isMyTurn ? "轮到你出牌" : `${currentPlayer.display_name} 正在布局`}</b>
                        <p>{selectedCard ? `已选中「${selectedCard.title}」，可点击「＋」或拖拽到时间轴插入位。` : isMyTurn ? "可点击手牌再插入，也可直接拖拽手牌到公共时间轴。" : "观察 AI 的推理，判断它是否把事件放在了正确年代。"}</p>
                      </div>
                    </div>
                  )}

                  {phase === "result" ? (
                    <div className="card-game-report-panel tabletop-result-panel">
                      <span className="panel-kicker">Game Over</span>
                      <h3>{winner ? `${winner.display_name} 获胜！` : "游戏结束"}</h3>
                      <div className="card-game-report-stats">
                        {gameState.players.map((p) => (
                          <span key={p.player_id}>{p.display_name}：{p.correct_plays}✓ {p.wrong_plays}✗</span>
                        ))}
                      </div>
                      <div className="card-game-section-title" style={{ marginTop: 16 }}>
                        <strong>完整时间轴</strong>
                      </div>
                      <ol className="tabletop-final-timeline">
                        {gameState.timeline.map((c) => <li key={c.id}>{c.title}（{c.display_year}）</li>)}
                      </ol>
                    </div>
                  ) : (
                    <>
                      {feedback && (
                        <div className={`timeline-feedback tabletop-bubble ${feedback.correct ? "correct" : "incorrect"}`}>
                          <b>{feedback.correct
                            ? `✓ ${feedback.card_title}（${feedback.display_year}）放置正确！`
                            : `✗ ${feedback.card_title}（${feedback.display_year}）位置不对，放回牌堆底部。`}
                          </b>
                          {!feedback.correct && feedback.explanation && <p>{feedback.explanation}</p>}
                          {!feedback.correct && feedback.coach_tip && <p>AI 教练：{feedback.coach_tip}</p>}
                          {feedback.penalty_card && <p>罚摸一张：{feedback.penalty_card.title}</p>}
                          {feedback.suggested_question && <small>追问：{feedback.suggested_question}</small>}
                        </div>
                      )}

                      <div className="tabletop-zone-title">
                        <strong>公共时间轴</strong>
                        <span>从早到晚摆放：拖到「拖到这里」才会出牌，空白处不会提交</span>
                      </div>
                      <div
                        className={[
                          "card-game-rail",
                          "tabletop-timeline",
                          selectedCardId ? "is-placing" : "",
                          isMyTurn && draggingCardId ? "is-drag-placing" : "",
                          dragInsertIndex !== null ? "has-drag-target" : "",
                        ].filter(Boolean).join(" ")}
                      >
                        {gameState.timeline.length === 0 && !selectedCardId && !draggingCardId && (
                          <div className="tabletop-empty-timeline">
                            <span>尚未翻开公共事件</span>
                            <strong>点击手牌后点「＋」，或拖拽手牌到插入位作为时间轴起点</strong>
                          </div>
                        )}
                        {isMyTurn && (selectedCardId || draggingCardId) && (
                          <button
                            className={["timeline-insert-btn", dragInsertIndex === 0 ? "drag-over" : ""].filter(Boolean).join(" ")}
                            type="button"
                            onClick={() => insertAt(0)}
                            onDragEnter={(event) => handleTimelineDragOver(event, 0)}
                            onDragOver={(event) => handleTimelineDragOver(event, 0)}
                            onDragLeave={(event) => handleTimelineDragLeave(event, 0)}
                            onDrop={(event) => handleTimelineDrop(event, 0)}
                          ><span>插入这里</span><small>放在最前</small></button>
                        )}
                        {gameState.timeline.map((card, i) => (
                          <div key={card.id} style={{ display: "contents" }}>
                            <article className="card-game-placed-card tabletop-placed-card" draggable={false}>
                              <div className="history-card-topline">
                                <span>{card.display_year}</span>
                                <em>{card.topic}</em>
                              </div>
                              <strong>{card.title}</strong>
                              <p>{card.summary}</p>
                            </article>
                            {isMyTurn && (selectedCardId || draggingCardId) && (
                              <button
                                className={["timeline-insert-btn", dragInsertIndex === i + 1 ? "drag-over" : ""].filter(Boolean).join(" ")}
                                type="button"
                                onClick={() => insertAt(i + 1)}
                                onDragEnter={(event) => handleTimelineDragOver(event, i + 1)}
                                onDragOver={(event) => handleTimelineDragOver(event, i + 1)}
                                onDragLeave={(event) => handleTimelineDragLeave(event, i + 1)}
                                onDrop={(event) => handleTimelineDrop(event, i + 1)}
                              ><span>插入这里</span><small>{i + 1 === gameState.timeline.length ? "放在最后" : `第 ${i + 2} 位`}</small></button>
                            )}
                          </div>
                        ))}
                      </div>

                      {humanPlayer?.hand ? (
                        <div className={["tabletop-hand-tray", !isMyTurn ? "is-waiting-turn" : ""].filter(Boolean).join(" ")}>
                          <div className="tabletop-zone-title">
                            <strong>你的手牌</strong>
                            <span>{isMyTurn ? `${humanPlayer.hand.length} 张 · 可拖拽出牌` : `${humanPlayer.hand.length} 张 · 等待其他玩家出牌`}</span>
                          </div>
                          <div className="card-game-hand-grid tabletop-hand-grid">
                            {orderedHand.map((card) => (
                              <article
                                key={card.id}
                                className={[
                                  "history-card",
                                  "tabletop-hand-card",
                                  selectedCardId === card.id ? "selected" : "",
                                  draggingCardId === card.id ? "dragging" : "",
                                  !isMyTurn ? "disabled" : "",
                                ].filter(Boolean).join(" ")}
                                draggable={isMyTurn}
                                onClick={() => {
                                  if (!isMyTurn) return;
                                  setSelectedCardId((prev) => prev === card.id ? null : card.id);
                                }}
                                onDragStart={(event) => handleHandDragStart(event, card.id)}
                                onDragOver={(event) => handleHandDragOver(event, card.id)}
                                onDrop={(event) => handleHandDrop(event, card.id)}
                                onDragEnd={handleHandDragEnd}
                              >
                                <div className="history-card-topline">
                                  <span>{card.period}</span>
                                  <em>{card.topic}</em>
                                </div>
                                <strong>{card.title}</strong>
                                <p>{card.summary}</p>
                                <div className="tabletop-card-secret">出牌后揭晓年代</div>
                              </article>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="tabletop-waiting-note">
                          {phase === "ai-playing" ? aiLog : "等待其他玩家出牌"}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
