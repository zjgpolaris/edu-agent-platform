"use client";

import { type DragEvent, useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

type CardGameDifficulty = "easy" | "normal" | "hard";
type GamePhase = "idle" | "starting" | "playing" | "submitting" | "result" | "retrying" | "report";

type HistoryCardApiItem = {
  id: string;
  card_type: "event";
  title: string;
  period: string;
  clue: string;
  topic: string;
};

type CardGameRoundApiResponse = {
  round_id: string;
  title: string;
  learning_goal?: string | null;
  grade: string;
  topic: string;
  difficulty: CardGameDifficulty;
  cards: HistoryCardApiItem[];
  slot_count: number;
  source?: "llm" | "static";
  fallback_used?: boolean;
};

type CardResultApiItem = {
  card_id: string;
  title: string;
  display_year: string;
  period: string;
  is_correct: boolean;
  correct_slot: number;
  submitted_slot: number;
  explanation: string;
  follow_up_question?: string | null;
};

type RoundResultApiResponse = {
  round_id: string;
  score: number;
  total: number;
  can_retry: boolean;
  items: CardResultApiItem[];
  learning_tip: string;
  correct_order: string[];
  submitted_order: string[];
};

type CardGameReportApiResponse = {
  student_id: string;
  rounds_played: number;
  total_score: number;
  total_cards: number;
  accuracy: number;
  wrong_card_ids: string[];
  recent_rounds: Array<{
    round_id: string;
    title: string;
    topic: string;
    difficulty: CardGameDifficulty;
    score: number;
    total: number;
    wrong_card_ids: string[];
    is_retry: boolean;
  }>;
  review_tip: string;
  next_recommendation: string;
};

type HistoryCard = {
  id: string;
  cardType: "event";
  title: string;
  period: string;
  clue: string;
  topic: string;
  difficulty: CardGameDifficulty;
};

type CardGameRound = {
  roundId: string;
  title: string;
  learningGoal?: string | null;
  grade: string;
  topic: string;
  difficulty: CardGameDifficulty;
  cards: HistoryCard[];
  slotCount: number;
  source?: "llm" | "static";
  fallbackUsed?: boolean;
};

type CardResult = {
  cardId: string;
  title: string;
  displayYear: string;
  period: string;
  isCorrect: boolean;
  correctSlot: number;
  submittedSlot: number;
  explanation: string;
  followUpQuestion?: string | null;
};

type RoundResult = {
  roundId: string;
  score: number;
  total: number;
  canRetry: boolean;
  items: CardResult[];
  learningTip: string;
  correctOrder: string[];
  submittedOrder: string[];
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const gradeOptions = ["七年级上", "七年级下", "八年级上", "八年级下", "九年级上", "九年级下"];
const topicOptions = ["中国古代史", "中国近代史", "中国现代史", "世界近代史", "世界现代史", "世界史"];
const difficultyOptions: Array<{ value: CardGameDifficulty; label: string; note: string }> = [
  { value: "easy", label: "入门", note: "有朝代提示，4张卡" },
  { value: "normal", label: "标准", note: "无年份，5张卡" },
  { value: "hard", label: "挑战", note: "含更隐性的线索，5张卡" },
];

function mapRound(data: CardGameRoundApiResponse): CardGameRound {
  return {
    roundId: data.round_id,
    title: data.title,
    learningGoal: data.learning_goal,
    grade: data.grade,
    topic: data.topic,
    difficulty: data.difficulty,
    source: data.source,
    fallbackUsed: data.fallback_used,
    slotCount: data.slot_count,
    cards: data.cards.map((card) => ({
      id: card.id,
      cardType: card.card_type,
      title: card.title,
      period: card.period,
      clue: card.clue,
      topic: card.topic,
      difficulty: data.difficulty,
    })),
  };
}

function mapResult(data: RoundResultApiResponse): RoundResult {
  return {
    roundId: data.round_id,
    score: data.score,
    total: data.total,
    canRetry: data.can_retry,
    learningTip: data.learning_tip,
    correctOrder: data.correct_order,
    submittedOrder: data.submitted_order,
    items: data.items.map((item) => ({
      cardId: item.card_id,
      title: item.title,
      displayYear: item.display_year,
      period: item.period,
      isCorrect: item.is_correct,
      correctSlot: item.correct_slot,
      submittedSlot: item.submitted_slot,
      explanation: item.explanation,
      followUpQuestion: item.follow_up_question,
    })),
  };
}

function getFriendlyErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    if (error.message.includes("Failed to fetch")) return "暂时连接不到后端服务，请确认历史教学 API 已启动。";
    if (error.message.includes("400")) return "本局卡牌提交内容不完整，请检查时间轴插槽。";
    if (error.message.includes("404")) return "这局时间巨轮已经失效，请重新开始一局。";
    if (error.message.includes("422")) return "提交格式不符合要求，请刷新页面后重试。";
    return error.message;
  }
  return "时间巨轮暂时无法响应，请稍后再试。";
}

export default function CardGameClient() {
  const { user } = useAuth();
  const [phase, setPhase] = useState<GamePhase>("idle");
  const [selectedGrade, setSelectedGrade] = useState("七年级上");
  const [selectedTopic, setSelectedTopic] = useState("中国古代史");
  const [selectedDifficulty, setSelectedDifficulty] = useState<CardGameDifficulty>("easy");
  const [round, setRound] = useState<CardGameRound | null>(null);
  const [slots, setSlots] = useState<Array<string | null>>([]);
  const [draggedCardId, setDraggedCardId] = useState<string | null>(null);
  const [dragOverSlot, setDragOverSlot] = useState<number | null>(null);
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [result, setResult] = useState<RoundResult | null>(null);
  const [report, setReport] = useState<CardGameReportApiResponse | null>(null);
  const [revisionMode, setRevisionMode] = useState(false);
  const [statusText, setStatusText] = useState("选择年级、专题和难度，启动一局时间巨轮卡牌挑战。");
  const [errorMessage, setErrorMessage] = useState("");

  const cardById = useMemo(() => new Map(round?.cards.map((card) => [card.id, card]) ?? []), [round]);
  const placedIds = useMemo(() => new Set(slots.filter((cardId): cardId is string => Boolean(cardId))), [slots]);
  const resultByCardId = useMemo(() => new Map(result?.items.map((item) => [item.cardId, item]) ?? []), [result]);
  const wrongCardIds = useMemo(
    () => new Set(result?.items.filter((item) => !item.isCorrect).map((item) => item.cardId) ?? []),
    [result],
  );
  const handCards = useMemo(() => round?.cards.filter((card) => !placedIds.has(card.id)) ?? [], [placedIds, round]);
  const allSlotsFilled = slots.length > 0 && slots.every(Boolean);

  async function startRound() {
    setPhase("starting");
    setErrorMessage("");
    setResult(null);
    setReport(null);
    setRevisionMode(false);
    setSelectedCardId(null);
    setDraggedCardId(null);
    setStatusText("正在从知识库和错题记录中生成本局卡牌……");
    try {
      const response = await fetch(`${apiBaseUrl}/api/history/card-game/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grade: selectedGrade,
          difficulty: selectedDifficulty,
          topic: selectedTopic,
          student_id: user?.actorId ?? "",
          mode: "llm",
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const nextRound = mapRound(await response.json());
      setRound(nextRound);
      setSlots(Array.from({ length: nextRound.slotCount }, () => null));
      setPhase("playing");
      setStatusText("把手牌拖到时间轴插槽中，也可以点击手牌后点击插槽完成放置。提交前不会显示精确年份。");
    } catch (error) {
      setPhase("idle");
      setErrorMessage(getFriendlyErrorMessage(error));
      setStatusText("卡牌生成失败，请检查后端服务后重试。");
    }
  }

  function canMoveCard(cardId: string) {
    return phase === "playing" && (!revisionMode || wrongCardIds.has(cardId));
  }

  function placeCard(cardId: string, slotIndex: number) {
    if (!round || !canMoveCard(cardId)) return;
    const targetCardId = slots[slotIndex];
    if (revisionMode && targetCardId && !wrongCardIds.has(targetCardId)) return;

    setSlots((current) => {
      const next = current.map((id) => (id === cardId ? null : id));
      next[slotIndex] = cardId;
      return next;
    });
    setSelectedCardId(null);
  }

  function moveSlot(slotIndex: number, direction: -1 | 1) {
    const cardId = slots[slotIndex];
    const targetIndex = slotIndex + direction;
    if (!cardId || targetIndex < 0 || targetIndex >= slots.length || !canMoveCard(cardId)) return;
    const targetCardId = slots[targetIndex];
    if (revisionMode && targetCardId && !wrongCardIds.has(targetCardId)) return;
    setSlots((current) => {
      const next = [...current];
      [next[slotIndex], next[targetIndex]] = [next[targetIndex], next[slotIndex]];
      return next;
    });
  }

  function removeFromSlot(slotIndex: number) {
    const cardId = slots[slotIndex];
    if (!cardId || !canMoveCard(cardId)) return;
    setSlots((current) => current.map((id, index) => (index === slotIndex ? null : id)));
  }

  function handleDragStart(event: DragEvent<HTMLElement>, cardId: string) {
    if (!canMoveCard(cardId)) return;
    setDraggedCardId(cardId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", cardId);
  }

  function handleSlotDragOver(event: DragEvent<HTMLElement>, slotIndex: number) {
    if (!draggedCardId || !canMoveCard(draggedCardId)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDragOverSlot(slotIndex);
  }

  function handleSlotDrop(event: DragEvent<HTMLElement>, slotIndex: number) {
    event.preventDefault();
    const cardId = event.dataTransfer.getData("text/plain") || draggedCardId;
    if (cardId) placeCard(cardId, slotIndex);
    setDraggedCardId(null);
    setDragOverSlot(null);
  }

  function handleDragEnd() {
    setDraggedCardId(null);
    setDragOverSlot(null);
  }

  function handleSlotClick(slotIndex: number) {
    if (selectedCardId) {
      placeCard(selectedCardId, slotIndex);
    }
  }

  async function submitRound() {
    if (!round || !allSlotsFilled) return;
    setPhase(revisionMode ? "retrying" : "submitting");
    setErrorMessage("");
    setStatusText(revisionMode ? "正在核对修正后的时间巨轮……" : "正在判定卡牌位置并生成讲解……");
    try {
      const response = await fetch(`${apiBaseUrl}/api/history/card-game/${revisionMode ? "retry" : "submit"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          revisionMode
            ? { round_id: round.roundId, revised_card_ids: slots }
            : { round_id: round.roundId, submitted_card_ids: slots },
        ),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setResult(mapResult(await response.json()));
      setRevisionMode(false);
      setPhase("result");
      setStatusText("判定完成，请查看错误卡讲解、正确位置和复盘建议。");
    } catch (error) {
      setPhase("playing");
      setErrorMessage(getFriendlyErrorMessage(error));
      setStatusText("提交失败，请确认所有插槽都有卡牌。");
    }
  }

  function beginRevision() {
    if (!result?.canRetry) return;
    setRevisionMode(true);
    setPhase("playing");
    setSelectedCardId(null);
    setStatusText("修正模式已开启：仅错误卡解锁，可拖动或用按钮调整后再次提交。");
  }

  async function loadReport() {
    setPhase("report");
    setErrorMessage("");
    setStatusText("正在整理你的时间巨轮复盘报告……");
    try {
      const response = await fetch(`${apiBaseUrl}/api/history/card-game/report/${user?.actorId ?? ""}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setReport(await response.json());
      setStatusText("复盘报告已生成，下一局会优先照顾最近错过的事件卡。");
    } catch (error) {
      setErrorMessage(getFriendlyErrorMessage(error));
      setStatusText("复盘报告读取失败，请稍后再试。");
    }
  }

  return (
    <main className="academy-shell history-games-shell timeline-studio-shell card-game-shell">
      <section className="academy-hero history-games-hero timeline-studio-hero card-game-hero">
        <div className="hero-copy">
          <div className="eyebrow">Time Wheel Card Studio</div>
          <h1>时间巨轮 AI 卡牌游戏</h1>
          <p>抽取历史事件卡，把它们放进横向时间轴。系统会按真实年份判定顺序，并对错误卡给出讲解和追问。</p>
          <div className="hero-flow">
            <span>选择题组</span>
            <span>拖放卡牌</span>
            <span>AI 判题</span>
            <span>修正复盘</span>
          </div>
          <a className="hero-game-link" href="/student/history/games">返回游戏大厅</a>
        </div>
        <div className="teaching-card history-games-mission">
          <div className="seal-mark">轮</div>
          <strong>本舱任务：校准被打乱的时间巨轮</strong>
          <p>每局 4 到 5 张事件卡。提交后错误卡会显示正确位置、讲解和延伸追问，并保留一次修正机会。</p>
        </div>
      </section>

      <section className="timeline-studio-layout card-game-layout">
        <aside className="panel timeline-command-panel card-game-command-panel">
          <div className="timeline-workshop-header">
            <div>
              <div className="panel-kicker">Card Console</div>
              <h2>发牌指挥台</h2>
              <p>{statusText}</p>
            </div>
            <div key={result?.score ?? 0} className="timeline-score-seal seal-pop">
              {result ? `${result.score}/${result.total}` : phase === "playing" ? "摆放中" : "待发牌"}
            </div>
          </div>

          {errorMessage ? <div className="error-card">{errorMessage}</div> : null}

          <div className="timeline-controls">
            <div className="timeline-control-group">
              <span>选择年级</span>
              <div className="timeline-choice-row">
                {gradeOptions.map((grade) => (
                  <button key={grade} className={selectedGrade === grade ? "active" : ""} type="button" onClick={() => setSelectedGrade(grade)} disabled={phase === "starting" || phase === "submitting" || phase === "retrying"}>
                    {grade}
                  </button>
                ))}
              </div>
            </div>
            <div className="timeline-control-group">
              <span>选择专题</span>
              <div className="timeline-choice-row">
                {topicOptions.map((topic) => (
                  <button key={topic} className={selectedTopic === topic ? "active" : ""} type="button" onClick={() => setSelectedTopic(topic)} disabled={phase === "starting" || phase === "submitting" || phase === "retrying"}>
                    {topic}
                  </button>
                ))}
              </div>
            </div>
            <div className="timeline-control-group">
              <span>选择难度</span>
              <div className="timeline-choice-row">
                {difficultyOptions.map((option) => (
                  <button key={option.value} className={selectedDifficulty === option.value ? "active" : ""} type="button" onClick={() => setSelectedDifficulty(option.value)} disabled={phase === "starting" || phase === "submitting" || phase === "retrying"} title={option.note}>
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="timeline-action-row">
            <button className="primary" type="button" disabled={phase === "starting" || phase === "submitting" || phase === "retrying"} onClick={startRound}>
              {phase === "starting" ? "正在发牌……" : result ? "再来一局" : "启动发牌"}
            </button>
            <button className="secondary" type="button" disabled={phase !== "playing" || !allSlotsFilled} onClick={submitRound}>
              {phase === "retrying" || phase === "submitting" ? "正在判定……" : revisionMode ? "提交修正" : "提交排序"}
            </button>
          </div>

          <div className="timeline-action-row card-game-secondary-actions">
            <button className="secondary" type="button" disabled={!result?.canRetry || revisionMode} onClick={beginRevision}>
              修正一次
            </button>
            <button className="secondary" type="button" onClick={loadReport}>
              查看复盘
            </button>
          </div>
        </aside>

        <section className="panel timeline-workshop card-game-workshop">
          <div className="timeline-workshop-header timeline-workbench-header">
            <div>
              <div className="panel-kicker">Time Rail</div>
              <h2>时间轴插槽</h2>
              <p>{round ? `${round.title} · ${round.grade} · ${round.topic}` : "启动发牌后，手牌和时间轴会出现在这里。"}</p>
            </div>
          </div>

          {!round && !report ? (
            <div className="empty-state timeline-empty-state">
              <div className="empty-stamp">卡</div>
              <strong>时间巨轮待启动</strong>
              <p>选择年级、专题和难度后启动发牌。系统会隐藏精确年份，只留下线索和时期供你判断。</p>
            </div>
          ) : null}

          {round ? (
            <>
              <div className="timeline-round-meta">
                <span>{round.learningGoal ?? "训练历史时间观念"}</span>
                <span>{round.source === "static" || round.fallbackUsed ? "静态兜底题组" : "AI 动态题组"}</span>
                {revisionMode ? <span>修正模式</span> : null}
              </div>

              <div className="game-table-surface" style={{ marginTop: 8 }}>
                <div className="card-game-hand" aria-label="手牌区">
                  <div className="card-game-section-title" style={{ color: "rgba(255,252,244,0.9)" }}>
                    <strong>手牌区</strong>
                    <span style={{ color: "rgba(255,252,244,0.6)" }}>{handCards.length ? "拖到下方插槽，或点击卡牌后点击插槽" : "手牌已全部放入时间轴"}</span>
                  </div>
                  <div className="fan-hand">
                    {handCards.map((card) => (
                      <article
                        key={card.id}
                        className={["history-card", selectedCardId === card.id ? "selected" : ""].filter(Boolean).join(" ")}
                        draggable={canMoveCard(card.id)}
                        onClick={() => setSelectedCardId((current) => (current === card.id ? null : card.id))}
                        onDragStart={(event) => handleDragStart(event, card.id)}
                        onDragEnd={handleDragEnd}
                      >
                        <div className="history-card-topline">
                          <span>{card.period}</span>
                          <em>{card.topic}</em>
                        </div>
                        <strong>{card.title}</strong>
                        <p>{card.clue}</p>
                      </article>
                    ))}
                  </div>
                </div>

                <div className="card-game-rail" aria-label="时间轴插槽">
                {slots.map((cardId, slotIndex) => {
                  const card = cardId ? cardById.get(cardId) : null;
                  const itemResult = cardId ? resultByCardId.get(cardId) : null;
                  const lockedCorrect = revisionMode && cardId ? !wrongCardIds.has(cardId) : false;
                  return (
                    <div
                      key={slotIndex}
                      className={[
                        "card-game-slot",
                        dragOverSlot === slotIndex ? "drop-target" : "",
                        itemResult ? itemResult.isCorrect ? "correct" : "incorrect" : "",
                        lockedCorrect ? "locked" : "",
                      ].filter(Boolean).join(" ")}
                      onClick={() => handleSlotClick(slotIndex)}
                      onDragOver={(event) => handleSlotDragOver(event, slotIndex)}
                      onDrop={(event) => handleSlotDrop(event, slotIndex)}
                    >
                      <div className="card-game-slot-index">第 {slotIndex + 1} 位</div>
                      {card ? (
                        <article className="card-game-placed-card" draggable={canMoveCard(card.id)} onDragStart={(event) => handleDragStart(event, card.id)} onDragEnd={handleDragEnd}>
                          <strong>{card.title}</strong>
                          <p>{card.clue}</p>
                          <div className="timeline-event-tags">
                            <span>{itemResult?.displayYear ?? card.period}</span>
                            <span>{card.topic}</span>
                          </div>
                          {itemResult ? (
                            <div className="timeline-feedback">
                              <b>{itemResult.isCorrect ? "位置正确" : `应在第 ${itemResult.correctSlot + 1} 位`}</b>
                              <p>{itemResult.explanation}</p>
                              {itemResult.followUpQuestion ? <small>延伸追问：{itemResult.followUpQuestion}</small> : null}
                            </div>
                          ) : null}
                          <div className="timeline-move-actions">
                            <button type="button" disabled={!canMoveCard(card.id) || slotIndex === 0} onClick={() => moveSlot(slotIndex, -1)}>左移</button>
                            <button type="button" disabled={!canMoveCard(card.id) || slotIndex === slots.length - 1} onClick={() => moveSlot(slotIndex, 1)}>右移</button>
                            <button type="button" disabled={!canMoveCard(card.id)} onClick={() => removeFromSlot(slotIndex)}>收回</button>
                          </div>
                        </article>
                      ) : (
                        <div className="card-game-empty-slot">放入事件卡</div>
                      )}
                    </div>
                  );
                })}
              </div>
              </div>

              {result ? (
                <div className="timeline-result-summary card-game-result-summary">
                  <div>
                    <span className="panel-kicker">Wheel Report</span>
                    <h3>本局得分：{result.score} / {result.total}</h3>
                    <p>{result.learningTip}</p>
                  </div>
                  <ol>
                    {result.correctOrder.map((cardId) => <li key={cardId}>{resultByCardId.get(cardId)?.title ?? cardId}</li>)}
                  </ol>
                </div>
              ) : null}
            </>
          ) : null}

          {report ? (
            <div className="card-game-report-panel">
              <div>
                <span className="panel-kicker">Review Ledger</span>
                <h3>复盘报告</h3>
                <p>{report.review_tip}</p>
              </div>
              <div className="card-game-report-stats">
                <span>完成 {report.rounds_played} 次</span>
                <span>正确率 {Math.round(report.accuracy * 100)}%</span>
                <span>错题 {report.wrong_card_ids.length} 张</span>
              </div>
              <p>{report.next_recommendation}</p>
              {report.recent_rounds.length ? (
                <ol>
                  {report.recent_rounds.map((item) => (
                    <li key={`${item.round_id}-${item.is_retry ? "retry" : "submit"}`}>
                      {item.title}：{item.score}/{item.total}{item.is_retry ? " · 修正" : ""}
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : null}
        </section>
      </section>
    </main>
  );
}
