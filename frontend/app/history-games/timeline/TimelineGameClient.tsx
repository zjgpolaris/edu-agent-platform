"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

type TimelineDifficulty = "easy" | "normal" | "hard";
type GamePhase = "idle" | "starting" | "initializing" | "playing" | "result";

type EventApiItem = {
  id: string;
  title: string;
  display_year?: string;
  period: string;
  summary: string;
  topic: string;
};

type RoundApiResponse = {
  round_id: string;
  round_title?: string;
  title: string;
  learning_goal?: string | null;
  grade?: string;
  difficulty: TimelineDifficulty;
  topic?: string;
  events: EventApiItem[];
};

type SubmitApiItem = {
  event_id: string;
  title: string;
  display_year?: string;
  correct_index: number;
  submitted_index: number;
  explanation: string;
  suggested_question?: string | null;
};

type SubmitApiResponse = {
  round_id: string;
  score: number;
  total: number;
  correct_order: string[];
  items: SubmitApiItem[];
  learning_tip: string;
};

type Card = {
  id: string;
  title: string;
  period: string;
  summary: string;
  topic: string;
  yearRank: number; // index in correct_order
  displayYear: string;
  explanation: string;
  suggestedQuestion: string | null;
};

type Feedback = {
  correct: boolean;
  cardTitle: string;
  displayYear: string;
  explanation: string;
  suggestedQuestion: string | null;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const topicOptions = ["中国古代史", "中国近代史", "世界史"];
const difficultyOptions: Array<{ value: TimelineDifficulty; label: string; disabled?: boolean }> = [
  { value: "easy", label: "入门" },
  { value: "normal", label: "标准" },
  { value: "hard", label: "挑战", disabled: true },
];

export default function TimelineGameClient() {
  const { user } = useAuth();
  const [phase, setPhase] = useState<GamePhase>("idle");
  const [selectedTopic, setSelectedTopic] = useState("中国古代史");
  const [selectedDifficulty, setSelectedDifficulty] = useState<TimelineDifficulty>("easy");
  const [roundId, setRoundId] = useState<string | null>(null);
  const [roundTitle, setRoundTitle] = useState("");
  const [timeline, setTimeline] = useState<Card[]>([]);   // 公共时间轴（已翻面）
  const [handCards, setHandCards] = useState<Card[]>([]);  // 手牌
  const [activeId, setActiveId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [score, setScore] = useState({ correct: 0, wrong: 0 });
  const [newlyPlaced, setNewlyPlaced] = useState<Set<string>>(new Set());
  const [shakingCard, setShakingCard] = useState<string | null>(null);
  const [learningTip, setLearningTip] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function initializeRound(d1: RoundApiResponse) {
    setPhase("initializing");
    const r2 = await fetch(`${apiBaseUrl}/api/history/games/timeline/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_id: d1.round_id, ordered_event_ids: d1.events.map((e) => e.id), record_event: false }),
    });
    if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
    const d2: SubmitApiResponse = await r2.json();

    const metaById = new Map(d2.items.map((item) => [item.event_id, item]));
    const eventById = new Map(d1.events.map((e) => [e.id, e]));

    const cards: Card[] = d2.correct_order.map((id, rank) => {
      const e = eventById.get(id)!;
      const m = metaById.get(id)!;
      return {
        id,
        title: e.title,
        period: e.period,
        summary: e.summary,
        topic: e.topic,
        yearRank: rank,
        displayYear: m.display_year ?? e.display_year ?? "",
        explanation: m.explanation,
        suggestedQuestion: m.suggested_question ?? null,
      };
    });

    const anchor = cards[0];
    const hand = [...cards.slice(1)].sort(() => Math.random() - 0.5);

    setRoundId(d1.round_id);
    setRoundTitle(d1.round_title ?? d1.title);
    setSelectedTopic(d1.topic || selectedTopic);
    setSelectedDifficulty(d1.difficulty || selectedDifficulty);
    setTimeline([anchor]);
    setHandCards(hand);
    setLearningTip(d2.learning_tip);
    setPhase("playing");
  }

  useEffect(() => {
    const raw = window.localStorage.getItem("edu-agent:pending-timeline-round");
    if (!raw) return;
    window.localStorage.removeItem("edu-agent:pending-timeline-round");
    try {
      const round = JSON.parse(raw) as RoundApiResponse;
      if (!round.round_id || !Array.isArray(round.events)) return;
      setErrorMessage("");
      setFeedback(null);
      setScore({ correct: 0, wrong: 0 });
      setActiveId(null);
      void initializeRound(round).catch((error) => {
        setPhase("idle");
        setErrorMessage(error instanceof Error ? error.message : "启动失败，请重试。");
      });
    } catch {
      setErrorMessage("学习助手传来的游戏数据无法读取，请重新开始一局。");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startRound() {
    setPhase("starting");
    setErrorMessage("");
    setFeedback(null);
    setScore({ correct: 0, wrong: 0 });
    setActiveId(null);

    try {
      // Step 1: get events
      const r1 = await fetch(`${apiBaseUrl}/api/history/games/timeline/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grade: null, difficulty: selectedDifficulty, topic: selectedTopic, student_id: user?.actorId ?? "", mode: "llm" }),
      });
      if (!r1.ok) throw new Error(`HTTP ${r1.status}`);
      const d1: RoundApiResponse = await r1.json();

      await initializeRound(d1);
    } catch (e) {
      setPhase("idle");
      setErrorMessage(e instanceof Error ? e.message : "启动失败，请重试。");
    }
  }

  function selectCard(id: string) {
    if (phase !== "playing") return;
    setActiveId((prev) => (prev === id ? null : id));
    setFeedback(null);
  }

  function insertAt(index: number) {
    if (phase !== "playing" || !activeId) return;
    const card = handCards.find((c) => c.id === activeId);
    if (!card) return;

    // Check if yearRank fits between timeline[index-1] and timeline[index]
    const leftRank = index > 0 ? timeline[index - 1].yearRank : -Infinity;
    const rightRank = index < timeline.length ? timeline[index].yearRank : Infinity;
    const correct = card.yearRank > leftRank && card.yearRank < rightRank;

    setFeedback({
      correct,
      cardTitle: card.title,
      displayYear: card.displayYear,
      explanation: card.explanation,
      suggestedQuestion: card.suggestedQuestion,
    });

    if (correct) {
      const newTimeline = [...timeline.slice(0, index), card, ...timeline.slice(index)];
      const newHand = handCards.filter((c) => c.id !== activeId);
      setTimeline(newTimeline);
      setHandCards(newHand);
      setScore((s) => ({ ...s, correct: s.correct + 1 }));
      setNewlyPlaced((prev) => new Set(Array.from(prev).concat(card.id)));
      setTimeout(() => setNewlyPlaced((prev) => { const next = new Set(Array.from(prev)); next.delete(card.id); return next; }), 500);
      if (newHand.length === 0) setPhase("result");
    } else {
      setScore((s) => ({ ...s, wrong: s.wrong + 1 }));
      setShakingCard(card.id);
      setTimeout(() => setShakingCard(null), 400);
    }

    setActiveId(null);
  }

  const busy = phase === "starting" || phase === "initializing";
  const total = score.correct + score.wrong;

  return (
    <main className="academy-shell history-games-shell timeline-studio-shell">
      <section className="academy-hero history-games-hero timeline-studio-hero">
        <div className="hero-copy">
          <div className="eyebrow">Time Wheel Card Game</div>
          <h1>时间巨轮卡牌</h1>
          <p>每次出一张牌，插入时间轴的正确位置。位置对了留下，位置错了牌归手中。手牌清空即胜利。</p>
          <div className="hero-flow">
            <span>发牌</span>
            <span>选牌</span>
            <span>插入时间轴</span>
            <span>翻面验证</span>
          </div>
          <a className="hero-game-link" href="/student/history/games">返回游戏大厅</a>
        </div>
        <div className="teaching-card history-games-mission">
          <div className="seal-mark">牌</div>
          <strong>不需要背年份，只需判断先后</strong>
          <p>根据事件内容和朝代，判断这张牌应该插在时间轴的哪个位置。插对了才能出牌成功。</p>
        </div>
      </section>

      <section className="timeline-studio-layout">
        <aside className="panel timeline-command-panel">
          <div className="timeline-workshop-header">
            <div>
              <div className="panel-kicker">Game Console</div>
              <h2>游戏指挥台</h2>
              <p>
                {phase === "idle" && "选择专题和难度，开始发牌。"}
                {phase === "starting" && "正在生成历史事件……"}
                {phase === "initializing" && "正在整理时间顺序……"}
                {phase === "playing" && (activeId ? "点击时间轴上的插入位置放置卡牌。" : "从手牌区选一张牌。")}
                {phase === "result" && "手牌清空！游戏结束。"}
              </p>
            </div>
            <div key={score.correct} className="timeline-score-seal seal-pop">
              {phase === "result" ? `${score.correct}/${total}` : phase === "playing" ? `${score.correct}✓ ${score.wrong}✗` : "待开始"}
            </div>
          </div>

          {errorMessage ? <div className="error-card">{errorMessage}</div> : null}

          <div className="timeline-controls">
            <div className="timeline-control-group">
              <span>选择专题</span>
              <div className="timeline-choice-row">
                {topicOptions.map((t) => (
                  <button key={t} className={selectedTopic === t ? "active" : ""} type="button" disabled={busy} onClick={() => setSelectedTopic(t)}>{t}</button>
                ))}
              </div>
            </div>
            <div className="timeline-control-group">
              <span>选择难度</span>
              <div className="timeline-choice-row">
                {difficultyOptions.map((o) => (
                  <button key={o.value} className={selectedDifficulty === o.value ? "active" : ""} type="button" disabled={o.disabled || busy} onClick={() => setSelectedDifficulty(o.value)}>
                    {o.disabled ? `${o.label} · 待开放` : o.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="timeline-action-row">
            <button className="primary" type="button" disabled={busy} onClick={startRound}>
              {phase === "starting" ? "生成事件中……" : phase === "initializing" ? "整理顺序中……" : phase === "result" ? "再来一局" : "开始发牌"}
            </button>
          </div>

          <div className="timeline-rules-card">
            <strong>玩法说明</strong>
            <span>从手牌区点选一张卡。</span>
            <span>点击时间轴的插入位置。</span>
            <span>放对：卡留在时间轴；放错：牌回手中。</span>
            <span>手牌清空即胜利。</span>
          </div>
        </aside>

        <section className="panel timeline-workshop">
          <div className="timeline-workshop-header timeline-workbench-header">
            <div>
              <div className="panel-kicker">Card Game Table</div>
              <h2>{roundTitle || "时间巨轮卡牌台"}</h2>
            </div>
          </div>

          {phase === "idle" || phase === "starting" || phase === "initializing" ? (
            <div className="empty-state timeline-empty-state">
              <div className="empty-stamp">牌</div>
              <strong>{busy ? "准备中……" : "等待发牌"}</strong>
              <p>在左侧选择专题和难度，点击「开始发牌」。</p>
            </div>
          ) : (
            <>
              {/* Feedback bar */}
              {feedback ? (
                <div className={`timeline-feedback ${feedback.correct ? "correct" : "incorrect"}`} style={{ marginBottom: 16, borderRadius: 16, padding: "12px 16px" }}>
                  <b>{feedback.correct ? `✓ ${feedback.cardTitle}（${feedback.displayYear}）放置正确！` : `✗ ${feedback.cardTitle}（${feedback.displayYear}）位置不对，牌归手中。`}</b>
                  {!feedback.correct && <p style={{ margin: "6px 0 0" }}>{feedback.explanation}</p>}
                  {feedback.suggestedQuestion && <small>追问：{feedback.suggestedQuestion}</small>}
                </div>
              ) : null}

              <div className="game-table-surface" style={{ marginTop: 8 }}>
                {/* Timeline */}
                <div className="card-game-section-title" style={{ color: "rgba(255,252,244,0.9)" }}>
                  <strong>时间轴</strong>
                  <span style={{ color: "rgba(255,252,244,0.6)" }}>从早到晚，左侧为最早</span>
                </div>
                <div className="card-game-rail" style={{ alignItems: "flex-start" }}>
                  {phase === "playing" && activeId ? (
                    <button className="timeline-insert-btn" type="button" onClick={() => insertAt(0)} title="插入最左侧">↓</button>
                  ) : null}

                  {timeline.map((card, i) => (
                    <div key={card.id} style={{ display: "contents" }}>
                      <article className={["card-game-placed-card", newlyPlaced.has(card.id) ? "card-flip-in" : ""].filter(Boolean).join(" ")} style={{ minWidth: 160 }}>
                        <div className="history-card-topline">
                          <span>{card.displayYear}</span>
                          <em>{card.topic}</em>
                        </div>
                        <strong>{card.title}</strong>
                        <p>{card.summary}</p>
                      </article>
                      {phase === "playing" && activeId ? (
                        <button className="timeline-insert-btn" type="button" onClick={() => insertAt(i + 1)} title={`插入第 ${i + 2} 位`}>↓</button>
                      ) : null}
                    </div>
                  ))}
                </div>

                {/* Hand */}
                {phase !== "result" ? (
                  <>
                    <div className="card-game-section-title" style={{ marginTop: 24, color: "rgba(255,252,244,0.9)" }}>
                      <strong>手牌区</strong>
                      <span style={{ color: "rgba(255,252,244,0.6)" }}>{handCards.length} 张</span>
                    </div>
                    <div className="fan-hand">
                      {handCards.map((card) => (
                        <article
                          key={card.id}
                          className={["history-card", activeId === card.id ? "selected" : "", shakingCard === card.id ? "card-shake" : ""].filter(Boolean).join(" ")}
                          onClick={() => selectCard(card.id)}
                          style={{ cursor: "pointer" }}
                        >
                          <div className="history-card-topline">
                            <span>{card.period}</span>
                            <em>{card.topic}</em>
                          </div>
                          <strong>{card.title}</strong>
                          <p>{card.summary}</p>
                        </article>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>

              {/* Result */}
              {phase === "result" ? (
                <div className="card-game-report-panel" style={{ marginTop: 24 }}>
                  <span className="panel-kicker">Game Report</span>
                  <h3>手牌清空！得分 {score.correct} / {total}</h3>
                  <p>{learningTip}</p>
                  <div className="card-game-report-stats">
                    <span>正确 {score.correct} 次</span>
                    <span>错误 {score.wrong} 次</span>
                    <span>正确率 {total > 0 ? Math.round((score.correct / total) * 100) : 0}%</span>
                  </div>
                  <div className="card-game-section-title" style={{ marginTop: 16 }}>
                    <strong>完整时间轴</strong>
                  </div>
                  <ol style={{ paddingLeft: 22, lineHeight: 2 }}>
                    {timeline.map((c) => <li key={c.id}>{c.title}（{c.displayYear}）</li>)}
                  </ol>
                </div>
              ) : null}
            </>
          )}
        </section>
      </section>
    </main>
  );
}
