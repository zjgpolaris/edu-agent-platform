"use client";

import { FormEvent, useState, useRef, ReactNode } from "react";

function inlineMd(raw: string): string {
  return raw
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}

function MdBlock({ text }: { text: string }) {
  const nodes: ReactNode[] = [];
  let listItems: string[] = [];
  let listType: "ul" | "ol" | null = null;

  function flushList() {
    if (!listItems.length) return;
    const Tag = listType!;
    nodes.push(
      <Tag key={nodes.length} className="db-md-list">
        {listItems.map((item, i) => (
          <li key={i} dangerouslySetInnerHTML={{ __html: inlineMd(item) }} />
        ))}
      </Tag>
    );
    listItems = []; listType = null;
  }

  for (const line of text.split("\n")) {
    const h = line.match(/^#{1,3}\s+(.+)/)
      || line.match(/^[一二三四五六七八九十百]+[、.]\s*(.+)/)
      || line.match(/^【(.+?)】\s*$/)
      || line.match(/^（[一二三四五六七八九十]+）(.+)/);
    const b = line.match(/^[-*]\s+(.+)/);
    const o = line.match(/^\d+\.\s+(.+)/);
    if (h) {
      flushList();
      nodes.push(<p key={nodes.length} className="db-md-heading" dangerouslySetInnerHTML={{ __html: inlineMd(h[1] ?? h[0]) }} />);
    } else if (b) {
      if (listType === "ol") flushList();
      listType = "ul"; listItems.push(b[1]);
    } else if (o) {
      if (listType === "ul") flushList();
      listType = "ol"; listItems.push(o[1]);
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      nodes.push(<p key={nodes.length} className="db-md-p" dangerouslySetInnerHTML={{ __html: inlineMd(line) }} />);
    }
  }
  flushList();
  return <div className="db-md">{nodes}</div>;
}

function CollapsibleCard({ children, title, badge, badgeCls, defaultExpanded = true }: {
  children: ReactNode; title: string; badge: string; badgeCls: string; defaultExpanded?: boolean;
}) {
  const [open, setOpen] = useState(defaultExpanded);
  return (
    <div className="db-collapsible-card">
      <button className="db-collapsible-header" onClick={() => setOpen(v => !v)}>
        <span className={`db-agent-badge ${badgeCls}`}>{badge}</span>
        <span>{title}</span>
        <span className="db-collapsible-arrow">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="db-collapsible-body">{children}</div>}
    </div>
  );
}

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type DebateRound = { side: "pro" | "con"; argument: string; round: number };
type FactCheck = { result: string; sources: { topic: string; score: number }[] };
type AgentStep = { agent: string; label: string; status: "done" | "running" | "pending" };

const EXAMPLE_TOPICS = [
  "秦始皇统一六国利大于弊",
  "商鞅变法对秦国的利弊",
  "汉武帝的历史功过",
  "郑和下西洋的意义",
];

function stripMd(text: string) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/#{1,6}\s+/g, "")
    .replace(/---+/g, "")
    .trim();
}

function DebateCard({ round, index }: { round: DebateRound; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const isPro = round.side === "pro";
  const text = stripMd(round.argument);
  const preview = text.slice(0, 140);
  const hasMore = text.length > 140;

  return (
    <div className={`db-bubble-row ${isPro ? "db-row-pro" : "db-row-con"}`}
      style={{ animationDelay: `${index * 60}ms` }}>
      <div className={`db-bubble ${isPro ? "db-bubble-pro" : "db-bubble-con"}`}>
        <div className="db-bubble-header">
          <span className={`db-side-pill db-side-${round.side}`}>{isPro ? "正方" : "反方"}</span>
          <span className="db-round-label">第 {round.round} 轮</span>
        </div>
        <p className="db-bubble-text">{expanded || !hasMore ? text : `${preview}…`}</p>
        {hasMore && (
          <button className={`db-expand ${isPro ? "db-expand-pro" : "db-expand-con"}`}
            onClick={() => setExpanded(v => !v)}>
            {expanded ? "收起" : "展开全文"}
          </button>
        )}
      </div>
    </div>
  );
}

const AGENT_PIPELINE: AgentStep[] = [
  { agent: "pro_debater", label: "正方发言", status: "pending" },
  { agent: "con_debater", label: "反方发言", status: "pending" },
  { agent: "fact_checker", label: "事实核查", status: "pending" },
  { agent: "judge", label: "裁判评分", status: "pending" },
  { agent: "learning_coach", label: "学习总结", status: "pending" },
];

export default function HistoryDebatePage() {
  const [topic, setTopic] = useState("");
  const [rounds, setRounds] = useState<DebateRound[]>([]);
  const [verdict, setVerdict] = useState("");
  const [factCheck, setFactCheck] = useState<FactCheck | null>(null);
  const [coachSummary, setCoachSummary] = useState("");
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState<"idle" | "debating" | "fact_checking" | "judging" | "coaching" | "done">("idle");
  const [error, setError] = useState("");
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>(AGENT_PIPELINE.map(s => ({ ...s })));
  const abortRef = useRef<AbortController | null>(null);

  function markAgent(agent: string, status: AgentStep["status"]) {
    setAgentSteps(prev => prev.map(s => s.agent === agent ? { ...s, status } : s));
  }

  async function startDebate(e: FormEvent) {
    e.preventDefault();
    const t = topic.trim();
    if (!t) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setLoading(true);
    setError("");
    setRounds([]);
    setVerdict("");
    setFactCheck(null);
    setCoachSummary("");
    setPhase("debating");
    setAgentSteps(AGENT_PIPELINE.map(s => ({ ...s, status: "pending" })));
    markAgent("pro_debater", "running");

    try {
      const res = await fetch(`${API}/api/history/debate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: t }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const blocks = buf.split("\n\n");
        buf = blocks.pop() ?? "";
        for (const block of blocks) {
          const eventLine = block.match(/^event: (.+)/m)?.[1];
          const dataLine = block.match(/^data: (.+)/m)?.[1];
          if (!eventLine || !dataLine) continue;
          const data = JSON.parse(dataLine);
          if (eventLine === "round") {
            const rd = data as DebateRound;
            setRounds(prev => [...prev, rd]);
            markAgent(rd.side === "pro" ? "pro_debater" : "con_debater", "done");
            const nextAgent = rd.side === "pro" ? "con_debater" : "pro_debater";
            markAgent(nextAgent, "running");
          } else if (eventLine === "fact_check") {
            markAgent("pro_debater", "done");
            markAgent("con_debater", "done");
            markAgent("fact_checker", "running");
            setPhase("fact_checking");
            setFactCheck(data as FactCheck);
            markAgent("fact_checker", "done");
            markAgent("judge", "running");
          } else if (eventLine === "verdict") {
            setPhase("judging");
            setVerdict(data.verdict);
            markAgent("judge", "done");
            markAgent("learning_coach", "running");
          } else if (eventLine === "coach_summary") {
            setCoachSummary(data.summary);
            markAgent("learning_coach", "done");
            setPhase("coaching");
          } else if (eventLine === "done") {
            setPhase("done");
          }
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "辩论失败");
        setPhase("idle");
      }
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    abortRef.current?.abort();
    setRounds([]); setVerdict(""); setFactCheck(null); setCoachSummary("");
    setPhase("idle"); setTopic("");
    setAgentSteps(AGENT_PIPELINE.map(s => ({ ...s, status: "pending" })));
  }

  const started = phase !== "idle" || rounds.length > 0;

  return (
    <div className="db-page">
      <div className="db-arena-header">
        <div className="db-arena-label">HISTORY DEBATE · 多 Agent 历史辩论场</div>
        <div className="db-arena-scoreboard">
          <div className="db-score-side pro-score">
            <span className="db-score-char">正</span>
            <span className="db-score-name">正方</span>
          </div>
          <div className="db-score-vs">VS</div>
          <div className="db-score-side con-score">
            <span className="db-score-char">反</span>
            <span className="db-score-name">反方</span>
          </div>
        </div>
      </div>

      {!started && (
        <div className="db-input-zone">
          <form onSubmit={startDebate} className="db-form">
            <input className="db-topic-input"
              placeholder="输入辩题，如：秦始皇统一六国利大于弊"
              value={topic} onChange={e => setTopic(e.target.value)} autoFocus />
            <button className="db-submit-btn" type="submit" disabled={!topic.trim()}>开始辩论</button>
          </form>
          <div className="db-chip-row">
            <span className="db-chip-hint">示例辩题</span>
            {EXAMPLE_TOPICS.map(t => (
              <button key={t} className="db-chip" onClick={() => setTopic(t)}>{t}</button>
            ))}
          </div>
          {error && <p className="db-error">{error}</p>}
        </div>
      )}

      {started && (
        <div className="db-arena db-arena-with-sidebar">
          <div className="db-arena-main">
            <div className="db-topic-row">
              <div>
                <span className="db-topic-kicker">本场辩题</span>
                <h2 className="db-topic-text">{topic}</h2>
              </div>
              <button className="db-restart" onClick={reset}>换题再辩</button>
            </div>

            <div className="db-chat-feed">
              {rounds.map((r, i) => <DebateCard key={i} round={r} index={i} />)}

              {loading && phase === "debating" && (
                <div className={`db-bubble-row ${rounds.length % 2 === 0 ? "db-row-pro" : "db-row-con"}`}>
                  <div className={`db-bubble db-bubble-typing ${rounds.length % 2 === 0 ? "db-bubble-pro" : "db-bubble-con"}`}>
                    <div className="db-typing-dots"><span /><span /><span /></div>
                  </div>
                </div>
              )}

              {(loading && phase === "fact_checking") && (
                <div className="db-agent-indicator">
                  <span className="db-agent-icon">🔍</span>
                  <span>事实核查员正在核实史料…</span>
                </div>
              )}

              {loading && phase === "judging" && (
                <div className="db-judging-indicator">
                  <span className="db-judging-icon">⚖</span>
                  <span>裁判正在综合论点…</span>
                </div>
              )}

              {loading && phase === "coaching" && (
                <div className="db-agent-indicator">
                  <span className="db-agent-icon">📚</span>
                  <span>学习教练正在生成总结…</span>
                </div>
              )}
            </div>

            {factCheck && (
              <CollapsibleCard badge="Fact Checker" badgeCls="fact-checker" title="史实核查结果">
                <MdBlock text={factCheck.result} />
                {factCheck.sources.length > 0 && (
                  <div className="db-fact-sources" style={{ marginTop: 10 }}>
                    {factCheck.sources.map((s, i) => (
                      <span key={i} className="db-source-chip">{s.topic} · {s.score}</span>
                    ))}
                  </div>
                )}
              </CollapsibleCard>
            )}

            {verdict && (
              <CollapsibleCard badge="Judge" badgeCls="judge" title="裁判结论" defaultExpanded={false}>
                <MdBlock text={verdict} />
              </CollapsibleCard>
            )}

            {coachSummary && (
              <CollapsibleCard badge="Learning Coach" badgeCls="coach" title="学习总结" defaultExpanded={false}>
                <MdBlock text={coachSummary} />
              </CollapsibleCard>
            )}

            {error && <p className="db-error">连接已中断，请刷新页面重试。</p>}
          </div>

          <aside className="db-agent-pipeline">
            <p className="db-pipeline-kicker">Multi-Agent Pipeline</p>
            {agentSteps.map((step) => (
              <div key={step.agent} className={`db-pipeline-step ${step.status}`}>
                <span className={`db-pipeline-dot ${step.status}`} />
                <span>{step.label}</span>
                {step.status === "running" && <small>运行中…</small>}
                {step.status === "done" && <small>完成</small>}
              </div>
            ))}
          </aside>
        </div>
      )}
    </div>
  );
}
