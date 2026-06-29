"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import { Select, type SelectOption } from "./Select";
import { TraceTimeline } from "@/components/TraceTimeline";

type Textbook = { id: string; grade: string; book: string; status: string };
type TocLesson = { id: string; title: string };
type TocUnit = { unit: string; lessons: TocLesson[] };
type StreamEvent = { event: string; data: Record<string, unknown> };
type ToolResult = {
  tool_name: string;
  ok: boolean;
  data?: Record<string, unknown>;
  error?: { code: string; message: string; retryable?: boolean } | null;
  metadata?: Record<string, unknown>;
};
type UsedMemory = { memory_id: string; type: string; content: unknown; reason: string };
type ProfileContext = {
  profile?: { recent_topics?: string[]; weak_topics?: string[]; character_interests?: string[] };
  review_plan?: { recommended_actions?: string[]; weak_topics?: string[]; recent_topics?: string[] };
  used_memory?: UsedMemory[];
};
type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  intent?: string;
  tools?: ToolResult[];
  suggestions?: string[];
  activeGame?: Record<string, unknown>;
};
type ToolSummary = Record<string, unknown> & { tool_name?: string; ok?: boolean | undefined };
type RuntimeStepStatus = "running" | "success" | "failed" | "waiting_confirmation" | "confirmed" | "cancelled";
type RuntimeStep = {
  trace_id?: string | null;
  agent_name: string;
  step_id: string;
  step_name: string;
  sequence?: number;
  event_type: string;
  status: RuntimeStepStatus;
  latency_ms?: number | null;
  metadata?: Record<string, unknown>;
  error?: { code?: string; message?: string; retryable?: boolean } | null;
};
type PendingConfirmation = {
  toolName: string;
  token: string;
  message: string;
  riskLevel?: string;
  sideEffect?: string;
  requiredRole?: string;
};
type ToolInfo = {
  name: string;
  description?: string;
  risk_level?: string;
  side_effect?: string;
  required_role?: string;
  requires_confirmation?: boolean;
  audit_enabled?: boolean;
};
type RagChunk = {
  topic?: string;
  source?: string;
  grade?: string;
  unit?: string;
  lesson?: string;
  page?: string;
  score?: number;
  source_mode?: string;
  snippet?: string;
};
type RagInspectorSummary = {
  query: string;
  sourceCount: number;
  topScore?: number;
  sourceModes: string[];
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const examples = ["鸦片战争为什么重要？", "我想了解秦始皇，推荐一个历史人物", "来一局中国近代史时间线游戏", "帮我出 3 道本课练习题"];
const intentLabels: Record<string, string> = {
  textbook_qa: "教材问答",
  quiz_generation: "生成测验",
  character_recommendation: "人物推荐",
  timeline_game: "时间线游戏",
  history_search: "历史检索",
  memory_delete_demo: "高风险工具演示",
  chat: "学习引导",
};
const toolLabels: Record<string, string> = {
  search_history_knowledge: "史料检索",
  get_textbook_lesson: "读取课文",
  generate_quiz: "生成练习",
  recommend_character: "推荐人物",
  start_timeline_game: "启动游戏",
  delete_demo_memory: "删除演示记忆",
};

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function parseSseFrame(frame: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
}

function asToolResult(value: unknown): ToolResult | null {
  if (!value || typeof value !== "object") return null;
  const item = value as ToolResult;
  if (!item.tool_name) return null;
  return item;
}

function toolLabel(name?: string) {
  return name ? toolLabels[name] || name : "工具";
}

function formatMetadataValue(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.slice(0, 3).map(formatMetadataValue).join("、");
  return JSON.stringify(value).slice(0, 120);
}

function isRuntimeStep(value: unknown): value is RuntimeStep {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.step_id === "string" && typeof item.step_name === "string" && typeof item.status === "string";
}

function runtimeStepSummary(step: RuntimeStep): string {
  const metadata = step.metadata || {};
  const fromError = step.error?.message || (typeof metadata.message === "string" ? metadata.message : "");
  const fromResult = typeof metadata.result_summary === "string" ? metadata.result_summary : "";
  const fromInput = metadata.input_summary != null ? `输入：${formatMetadataValue(metadata.input_summary)}` : "";
  return fromError || fromResult || fromInput || "";
}

const PIPELINE_PHASES = [
  { label: "意图识别", en: "Intent", sequences: [1, 2, 3] },
  { label: "工具调用", en: "Tool", sequences: [4, 5] },
  { label: "结果整合", en: "Synthesis", sequences: [6, 7] },
];

function AgentPipeline({ steps }: { steps: RuntimeStep[] }) {
  const seqToStep = new Map(steps.map((s) => [s.sequence, s]));
  return (
    <div className="db-agent-pipeline" style={{ marginBottom: 12 }}>
      <p className="db-pipeline-kicker">Agent Pipeline</p>
      {PIPELINE_PHASES.map((phase, i) => {
        const phaseSteps = phase.sequences.map((s) => seqToStep.get(s)).filter(Boolean) as RuntimeStep[];
        const running = phaseSteps.some((s) => s.status === "running");
        const done = phaseSteps.length > 0 && phaseSteps.every((s) => s.status === "success" || s.status === "confirmed");
        const failed = phaseSteps.some((s) => s.status === "failed");
        const dotClass = failed ? "done" : running ? "running" : done ? "done" : "pending";
        const totalMs = phaseSteps.reduce((acc, s) => acc + (s.latency_ms || 0), 0);
        return (
          <div key={phase.label} className={`db-pipeline-step${done ? " done" : running ? " running" : ""}`}>
            <span className={`db-pipeline-dot ${dotClass}`} style={failed ? { background: "var(--cinnabar)", borderColor: "var(--cinnabar)" } : undefined} />
            <span>{i + 1}. {phase.label}</span>
            {totalMs > 0 && <small>{totalMs}ms</small>}
          </div>
        );
      })}
    </div>
  );
}

function sortedRuntimeSteps(steps: RuntimeStep[]): RuntimeStep[] {
  return steps
    .map((step, index) => ({ step, index }))
    .sort((a, b) => {
      const aSeq = typeof a.step.sequence === "number" ? a.step.sequence : Number.MAX_SAFE_INTEGER;
      const bSeq = typeof b.step.sequence === "number" ? b.step.sequence : Number.MAX_SAFE_INTEGER;
      return aSeq === bSeq ? a.index - b.index : aSeq - bSeq;
    })
    .map((item) => item.step);
}

function confirmationFromTool(tool: ToolResult | ToolSummary): PendingConfirmation | null {
  const error = "error" in tool ? tool.error as ToolResult["error"] : null;
  const metadata = (tool.metadata || {}) as Record<string, unknown>;
  const token = typeof metadata.confirmation_token === "string" ? metadata.confirmation_token : "";
  if (error?.code !== "confirmation_required" || !token) return null;
  return {
    toolName: String(tool.tool_name || ""),
    token,
    message: error.message || "该工具需要确认后才会执行。",
    riskLevel: typeof metadata.risk_level === "string" ? metadata.risk_level : undefined,
    sideEffect: typeof metadata.side_effect === "string" ? metadata.side_effect : undefined,
    requiredRole: typeof metadata.required_role === "string" ? metadata.required_role : undefined,
  };
}

function openTimelineGame(game: unknown) {
  if (!game || typeof game !== "object") return;
  window.localStorage.setItem("edu-agent:pending-timeline-round", JSON.stringify(game));
  window.location.href = "/history-games/timeline?from=assistant";
}

type QuizQuestion = { id: string; question: string; answer?: string; options?: string[] | null };

function QuizCard({ q, index, weakpointTag }: { q: QuizQuestion; index: number; weakpointTag?: string }) {
  const { user } = useAuth();
  const [selected, setSelected] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [cleared, setCleared] = useState(false);
  const answered = selected !== null || revealed;
  const correctLetter = q.answer?.trim().charAt(0).toUpperCase();

  async function handleSelect(letter: string) {
    if (answered) return;
    setSelected(letter);
    if (weakpointTag && letter === correctLetter && user?.actorId && user?.token) {
      try {
        await fetch(`${apiBaseUrl}/api/student/${user.actorId}/weakpoints/${encodeURIComponent(weakpointTag)}`, {
          method: "DELETE",
          headers: authHeaders(user.token),
        });
        setCleared(true);
      } catch { /* silent */ }
    }
  }

  if (q.options?.length) {
    return (
      <div className="quiz-question-card">
        <p className="quiz-question-text"><span className="quiz-q-num">{index + 1}</span>{q.question}</p>
        <ul className="quiz-options">
          {q.options.map((opt, i) => {
            const letter = String.fromCharCode(65 + i);
            const isSelected = selected === letter;
            const isCorrect = letter === correctLetter;
            let state = "";
            if (answered) state = isCorrect ? "correct" : isSelected ? "wrong" : "";
            return (
              <li key={i}>
                <button type="button" className={`quiz-option-btn ${isSelected ? "selected" : ""} ${state}`}
                  onClick={() => handleSelect(letter)} disabled={answered}>
                  {opt}
                </button>
              </li>
            );
          })}
        </ul>
        {answered && q.answer && <p className="quiz-answer"><strong>答案：</strong>{q.answer}</p>}
        {!answered && q.answer && <button className="quiz-reveal-btn" type="button" onClick={() => setRevealed(true)}>查看答案</button>}
        {cleared && <p style={{ fontSize: "0.82rem", color: "#4b9560", marginTop: "6px" }}>✅ 已从错题本移除</p>}
      </div>
    );
  }

  return (
    <div className="quiz-question-card">
      <p className="quiz-question-text"><span className="quiz-q-num">{index + 1}</span>{q.question}</p>
      {q.answer ? (
        revealed
          ? <p className="quiz-answer"><strong>答案：</strong>{q.answer}</p>
          : <button className="quiz-reveal-btn" type="button" onClick={() => setRevealed(true)}>查看答案</button>
      ) : null}
    </div>
  );
}

function QuizPreview({ questions, weakpointTag }: { questions: QuizQuestion[]; weakpointTag?: string }) {
  return <div className="quiz-question-list">{questions.map((q, i) => <QuizCard key={q.id} q={q} index={i} weakpointTag={i === 0 ? weakpointTag : undefined} />)}</div>;
}

function renderToolPreview(tool: ToolResult) {
  const data = tool.data || {};
  const quiz = data.quiz as { questions?: QuizQuestion[] } | undefined;
  const recommendations = data.recommendations as { name: string; reason?: string; suggested_question?: string }[] | undefined;
  const game = data.game as { round_id?: string; title?: string; round_title?: string; topic?: string; difficulty?: string; events?: { id: string; title: string; period?: string }[] } | undefined;
  const sources = data.sources as { topic?: string; snippet?: string; score?: number; source_mode?: string }[] | undefined;
  const lesson = data.lesson as { lesson_title?: string; items?: { id: string; topic: string; text: string }[] } | undefined;

  if (quiz?.questions?.length) {
    return <QuizPreview questions={quiz.questions} weakpointTag={tool.metadata?.weakpoint_tag as string | undefined} />;
  }
  if (recommendations?.length) {
    return <div className="learning-tool-list">{recommendations.slice(0, 3).map((item) => <p key={item.name}><strong>{item.name}</strong>：{item.reason}</p>)}</div>;
  }
  if (game) {
    return (
      <div className="learning-tool-list">
        <p><strong>{game.title || game.round_title}</strong></p>
        <p>{game.topic} · {game.difficulty}</p>
        <p>事件数：{game.events?.length || 0}</p>
        <button className="learning-tool-action" type="button" onClick={() => openTimelineGame(game)}>进入游戏</button>
      </div>
    );
  }
  if (sources?.length) {
    return <div className="learning-tool-list">{sources.slice(0, 3).map((source, index) => <p key={`${source.topic}-${index}`}><strong>{source.topic || "史料"}</strong>：{source.snippet}</p>)}</div>;
  }
  if (lesson) {
    return <div className="learning-tool-list"><p><strong>{lesson.lesson_title}</strong></p>{lesson.items?.slice(0, 3).map((item) => <p key={item.id}>{item.topic}：{item.text}</p>)}</div>;
  }
  return null;
}

export default function LearningAssistantPage() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const [message, setMessage] = useState(searchParams.get("q") ?? "");
  const studentId = user?.actorId ?? "";
  const [books, setBooks] = useState<Textbook[]>([]);
  const [bookId, setBookId] = useState("");
  const [units, setUnits] = useState<TocUnit[]>([]);
  const [lessonId, setLessonId] = useState("");

  useEffect(() => {
    const headers = user?.token ? authHeaders(user.token) : undefined;
    fetch(`${apiBaseUrl}/api/textbooks`, { headers }).then((r) => r.json())
      .then((d) => setBooks((d.textbooks || []).filter((b: Textbook) => b.status === "ready")))
      .catch(() => null);
    fetch(`${apiBaseUrl}/api/learning/assistant/tools`, { headers }).then((r) => r.json())
      .then((d) => { if (Array.isArray(d.tools)) setToolRegistry(d.tools as ToolInfo[]); })
      .catch(() => null);
  }, [user?.token]);

  useEffect(() => {
    if (!bookId) { setUnits([]); setLessonId(""); return; }
    const headers = user?.token ? authHeaders(user.token) : undefined;
    fetch(`${apiBaseUrl}/api/textbooks/${bookId}/toc`, { headers }).then((r) => r.json())
      .then((d) => { setUnits(d.units || []); setLessonId(""); })
      .catch(() => null);
  }, [bookId, user?.token]);

  const grade = books.find((b) => b.id === bookId)?.grade ?? "";
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "我是统一学习助手。你可以让我查历史问题、生成练习、推荐历史人物，或者启动时间线游戏。",
      suggestions: examples,
    },
  ]);
  const [status, setStatus] = useState("等待学习任务");
  const [intent, setIntent] = useState<Record<string, unknown> | null>(null);
  const [profileContext, setProfileContext] = useState<ProfileContext | null>(null);
  const [traceId, setTraceId] = useState("");
  const [runtimeSteps, setRuntimeSteps] = useState<RuntimeStep[]>([]);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [lastRequestText, setLastRequestText] = useState("");
  const [ragChunks, setRagChunks] = useState<RagChunk[]>([]);
  const [ragQuery, setRagQuery] = useState("");
  const [ragSummary, setRagSummary] = useState<RagInspectorSummary | null>(null);
  const [sideTab, setSideTab] = useState<"timeline" | "rag" | "tools" | "memory">("timeline");
  const [toolRegistry, setToolRegistry] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const msgListRef = useRef<HTMLDivElement>(null);

  useEffect(() => { msgListRef.current?.scrollTo({ top: msgListRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  const assistantReady = useMemo(() => !loading && message.trim().length > 0, [loading, message]);
  const orderedRuntimeSteps = useMemo(() => sortedRuntimeSteps(runtimeSteps), [runtimeSteps]);

  function updateAssistant(id: string, updater: (current: Message) => Message) {
    setMessages((current) => current.map((item) => (item.id === id ? updater(item) : item)));
  }

  function upsertRuntimeStep(step: RuntimeStep) {
    setRuntimeSteps((current) => {
      const index = current.findIndex((item) => item.step_id === step.step_id && item.trace_id === step.trace_id);
      if (index === -1) return [...current, step];
      return current.map((item, itemIndex) => itemIndex === index ? { ...item, ...step, metadata: { ...item.metadata, ...step.metadata } } : item);
    });
  }

  async function handleStream(response: Response, assistantId: string) {
    if (!response.body) throw new Error("浏览器没有收到流式响应，请稍后重试。");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    async function handleEvent(streamEvent: StreamEvent) {
      const { event, data } = streamEvent;
      if (event === "trace") {
        if (typeof data.trace_id === "string") setTraceId(data.trace_id);
        return;
      }
      if (event === "runtime_step") {
        if (isRuntimeStep(data)) {
          upsertRuntimeStep(data);
          if (data.trace_id) setTraceId(String(data.trace_id));
          const metadata = data.metadata || {};
          const token = typeof metadata.confirmation_token === "string" ? metadata.confirmation_token : "";
          if (data.status === "waiting_confirmation" && token) {
            const error = data.error;
            setPendingConfirmation({
              toolName: typeof metadata.tool_name === "string" ? metadata.tool_name : "",
              token,
              message: error?.message ? String(error.message) : "该工具需要确认后才会执行。",
              riskLevel: typeof metadata.risk_level === "string" ? metadata.risk_level : undefined,
              sideEffect: typeof metadata.side_effect === "string" ? metadata.side_effect : undefined,
              requiredRole: typeof metadata.required_role === "string" ? metadata.required_role : undefined,
            });
          }
        }
        return;
      }
      if (event === "intent") {
        const intentName = typeof data.intent === "string" ? data.intent : "";
        setIntent(data);
        setStatus(`已识别：${intentLabels[intentName] || intentName || "学习任务"}`);
        updateAssistant(assistantId, (current) => ({ ...current, intent: intentName }));
        return;
      }
      if (event === "tool_start") {
        const toolName = typeof data.tool_name === "string" ? data.tool_name : "tool";
        setStatus(`正在调用${toolLabel(toolName)}`);
        return;
      }
      if (event === "tool_result") {
        const tool = data as ToolSummary;
        const confirmation = confirmationFromTool(tool);
        if (confirmation) setPendingConfirmation(confirmation);
        if (tool.tool_name === "search_history_knowledge" && tool.ok && Array.isArray((tool as unknown as { data?: { sources?: RagChunk[] } }).data?.sources)) {
          const sources = (tool as unknown as { data: { sources: RagChunk[] } }).data.sources;
          const metadata = (tool.metadata || {}) as Record<string, unknown>;
          const q = typeof metadata.query === "string" ? metadata.query : "";
          const sourceCount = typeof metadata.source_count === "number" ? metadata.source_count : sources.length;
          setRagChunks(sources);
          if (q) setRagQuery(q);
          setRagSummary({
            query: q,
            sourceCount,
            topScore: sources.find((source) => typeof source.score === "number")?.score,
            sourceModes: Array.from(new Set(sources.map((source) => source.source_mode).filter((value): value is string => Boolean(value)))),
          });
          setSideTab("rag");
        }
        setStatus(data.ok === false ? "工具返回了可处理错误" : "工具执行完成");
        return;
      }
      if (event === "delta") {
        const text = typeof data.text === "string" ? data.text : "";
        updateAssistant(assistantId, (current) => ({ ...current, text: current.text + text }));
        return;
      }
      if (event === "final") {
        const finalText = typeof data.response === "string" ? data.response : "";
        const tools = Array.isArray(data.tool_results) ? data.tool_results.map(asToolResult).filter(Boolean) as ToolResult[] : [];
        const activeGame = tools.find((tool) => tool.tool_name === "start_timeline_game")?.data?.game;
        const nextProfileContext = data.profile_context && typeof data.profile_context === "object" ? data.profile_context as ProfileContext : null;
        setProfileContext(nextProfileContext);
        updateAssistant(assistantId, (current) => ({ ...current, text: finalText || current.text, tools, activeGame: activeGame && typeof activeGame === "object" ? activeGame as Record<string, unknown> : undefined }));
        setStatus("已完成");
        return;
      }
      if (event === "suggestions") {
        const suggestions = Array.isArray(data.suggestions) ? data.suggestions.filter((item): item is string => typeof item === "string") : [];
        updateAssistant(assistantId, (current) => ({ ...current, suggestions }));
        return;
      }
      if (event === "error") throw new Error(typeof data.message === "string" ? data.message : "学习助手请求失败");
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const parsed = parseSseFrame(frame.trim());
        if (parsed) await handleEvent(parsed);
      }
    }
  }

  async function submit(nextMessage?: string, confirmation?: { confirmed_tool_name: string; confirmation_token: string; confirmation_decision: "confirmed" }) {
    const text = (nextMessage || message).trim();
    if (!text || loading) return;
    const userId = createId("user");
    const assistantId = createId("assistant");
    setMessages((current) => [...current, { id: userId, role: "user", text }, { id: assistantId, role: "assistant", text: "" }]);
    setMessage("");
    setLoading(true);
    setErrorMessage("");
    setIntent(null);
    setProfileContext(null);
    if (!confirmation) {
      setTraceId("");
      setRuntimeSteps([]);
      setRagChunks([]);
      setRagSummary(null);
    }
    setPendingConfirmation(null);
    setLastRequestText(text);
    setStatus("正在发送学习任务");

    try {
      const response = await fetch(`${apiBaseUrl}/api/learning/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) },
        body: JSON.stringify({
          message: text,
          student_id: studentId || null,
          grade: grade || null,
          book_id: bookId || null,
          lesson_id: lessonId || null,
          stream: true,
          ...(confirmation || {}),
        }),
      });
      if (!response.ok) throw new Error(`请求失败：${response.status}`);
      await handleStream(response, assistantId);
    } catch (error) {
      const fallback = error instanceof Error ? error.message : "学习助手请求失败";
      setErrorMessage(fallback);
      updateAssistant(assistantId, (current) => ({ ...current, text: current.text || fallback }));
      setStatus("请求失败");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  async function confirmToolExecution() {
    if (!pendingConfirmation || !lastRequestText) return;
    setRuntimeSteps((current) => current.map((step) => step.status === "waiting_confirmation" ? { ...step, status: "confirmed" } : step));
    setStatus("已确认高风险工具，正在重新执行");
    await submit(lastRequestText, {
      confirmed_tool_name: pendingConfirmation.toolName,
      confirmation_token: pendingConfirmation.token,
      confirmation_decision: "confirmed",
    });
  }

  async function cancelToolExecution() {
    if (!pendingConfirmation) return;
    try {
      const response = await fetch(`${apiBaseUrl}/api/learning/assistant/tool-confirmation/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) },
        body: JSON.stringify({ tool_name: pendingConfirmation.toolName, confirmation_token: pendingConfirmation.token, student_id: studentId || null }),
      });
      const data = await response.json().catch(() => ({}));
      if (typeof data.trace_id === "string") setTraceId(data.trace_id);
    } finally {
      setRuntimeSteps((current) => current.map((step) => step.status === "waiting_confirmation" ? { ...step, status: "cancelled", metadata: { ...step.metadata, result_summary: "用户取消高风险工具确认" } } : step));
      setPendingConfirmation(null);
      setStatus("已取消高风险工具");
    }
  }

  return (
    <main className="academy-shell learning-assistant-shell">
      <section className="academy-hero learning-command-hero">
        <div className="hero-copy">
          <div className="eyebrow">Learning Command Desk</div>
          <h1>统一学习助手</h1>
          <p>把史料检索、教材问答、测验生成、人物推荐和时间线游戏收束到一个对话入口。你提出学习目标，助手选择合适工具并把结果整理成下一步行动。</p>
          <div className="hero-flow" aria-label="学习助手能力">
            <span>识别意图</span>
            <span>调用工具</span>
            <span>组织答案</span>
            <span>给出建议</span>
          </div>
        </div>
        <div className="teaching-card learning-command-card" aria-label="助手状态">
          <div className="seal-mark" aria-hidden="true">策</div>
          <span className="card-label">任务台状态</span>
          <strong>{status}</strong>
          <p>{intent ? `当前意图：${intentLabels[String(intent.intent)] || String(intent.intent)}` : "输入一个历史学习任务，助手会先判断要使用哪种能力。"}</p>
        </div>
      </section>

      <section className="learning-command-grid">
        <aside className="panel learning-control-panel">
          <div className="panel-kicker">Context</div>
          <h2>学习上下文</h2>
          <label>
            教材
            <Select
              value={bookId}
              onChange={setBookId}
              options={books.map((b) => ({ value: b.id, label: `${b.grade} · ${b.book}` } as SelectOption))}
            />
          </label>
          <label>
            课文
            <Select
              value={lessonId}
              onChange={setLessonId}
              disabled={!units.length}
              options={units.flatMap((u) => u.lessons.map((l) => ({ value: l.id, label: l.title, group: u.unit } as SelectOption)))}
            />
          </label>
          <div className="learning-example-stack">
            {examples.map((example) => <button type="button" key={example} onClick={() => void submit(example)} disabled={loading}>{example}</button>)}
          </div>
        </aside>

        <section className="panel learning-dialog-panel" aria-label="学习助手对话">
          <div className="learning-message-list" ref={msgListRef}>
            {messages.map((item) => (
              <article className={`learning-message ${item.role}`} key={item.id}>
                <div className="learning-message-meta">
                  <span>{item.role === "user" ? "学习任务" : "助手回执"}</span>
                  {item.intent && <em>{intentLabels[item.intent] || item.intent}</em>}
                </div>
                <p>{item.text || "正在组织回答……"}</p>
                {item.tools?.filter((tool) => !(item.intent === "quiz_generation" && tool.tool_name === "search_history_knowledge")).map((tool) => (
                  <div className={`learning-tool-card ${tool.ok ? "ok" : "error"}`} key={`${item.id}-${tool.tool_name}`}>
                    <div><strong>{toolLabel(tool.tool_name)}</strong><span>{tool.ok ? "已完成" : tool.error?.message || "执行失败"}</span></div>
                    {renderToolPreview(tool)}
                  </div>
                ))}
                {item.suggestions?.length ? (
                  <div className="learning-suggestion-row">
                    {item.suggestions.map((suggestion) => (
                      <button
                        type="button"
                        key={suggestion}
                        onClick={() => suggestion.includes("开始游戏") && item.activeGame ? openTimelineGame(item.activeGame) : void submit(suggestion)}
                        disabled={loading}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
          <form className="learning-input-bar" onSubmit={handleSubmit}>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="例如：鸦片战争为什么重要？ / 推荐一个适合对话的历史人物 / 来一局时间线游戏" />
            <button type="submit" disabled={!assistantReady}>发送任务</button>
          </form>
          {errorMessage && <p className="learning-error">{errorMessage}</p>}
        </section>

        <aside className="panel learning-observation-panel">
          <div className="panel-kicker">Agent Observability</div>
          <h2>运行时观察</h2>
          <div className="learning-panel-tabs">
            <button type="button" className={`learning-panel-tab ${sideTab === "timeline" ? "active" : ""}`} onClick={() => setSideTab("timeline")}>Timeline</button>
            <button type="button" className={`learning-panel-tab ${sideTab === "rag" ? "active" : ""}`} onClick={() => setSideTab("rag")}>RAG Inspector {ragChunks.length > 0 ? `(${ragChunks.length})` : ""}</button>
            <button type="button" className={`learning-panel-tab ${sideTab === "tools" ? "active" : ""}`} onClick={() => setSideTab("tools")}>Tools ({toolRegistry.length})</button>
            <button type="button" className={`learning-panel-tab ${sideTab === "memory" ? "active" : ""}`} onClick={() => setSideTab("memory")}>Memory {profileContext?.used_memory?.length ? `(${profileContext.used_memory.length})` : ""}</button>
          </div>
          {sideTab === "timeline" && (
            <>
              <AgentPipeline steps={orderedRuntimeSteps} />
              {traceId && <p className="learning-trace-id">Trace: {traceId}</p>}
              <TraceTimeline traceId={traceId} token={user?.token} />
              {runtimeSteps.length === 0 && <p style={{ fontSize: 12, color: "var(--muted)" }}>发送一条消息后，这里会展示 agent 执行的每个步骤。</p>}
            </>
          )}
          {sideTab === "rag" && ragChunks.length === 0 && (
            <p>当学习助手调用史料检索时，RAG Inspector 会在这里展示召回的知识块、得分和来源。</p>
          )}
          {sideTab === "tools" && (
            <div className="learning-tool-registry">
              <p className="learning-trace-id">Tool Governance · {toolRegistry.length} 个工具</p>
              {toolRegistry.map((tool) => {
                const activeToolName = orderedRuntimeSteps.find((s) => s.status === "running")?.metadata?.tool_name;
                const isActive = activeToolName === tool.name;
                return (
                  <div key={tool.name} className={`learning-runtime-step${isActive ? " running" : ""}`} style={{ marginBottom: 6 }}>
                    <div className="learning-runtime-step-head">
                      <span>{toolLabels[tool.name] || tool.name}</span>
                      <strong style={{ color: tool.risk_level === "high" ? "var(--cinnabar)" : tool.risk_level === "medium" ? "#b87a00" : "var(--jade-dark)" }}>
                        {tool.risk_level}
                      </strong>
                    </div>
                    <div className="learning-runtime-chips">
                      <small>role: {tool.required_role}</small>
                      {tool.requires_confirmation && <small style={{ color: "var(--cinnabar)" }}>requires_confirmation</small>}
                      {tool.audit_enabled && <small>audit</small>}
                      {tool.side_effect && <small>effect: {tool.side_effect}</small>}
                    </div>
                  </div>
                );
              })}
              {toolRegistry.length === 0 && <p style={{ fontSize: 12, color: "var(--muted)" }}>工具注册表加载中…</p>}
            </div>
          )}
          {sideTab === "memory" && (
            <div className="learning-tool-registry">
              <p className="learning-trace-id">
                Agent Memory · 本次回答
                {profileContext?.used_memory?.length ? ` · 使用了 ${profileContext.used_memory.length} 条记忆` : ""}
              </p>
              {!profileContext?.used_memory?.length ? (
                <p style={{ fontSize: 12, color: "var(--muted)" }}>
                  {profileContext ? "本次回答未使用长期记忆。" : "发送一条消息后，这里会展示本次回答使用了哪些记忆。"}
                </p>
              ) : (
                profileContext.used_memory.map((mem) => (
                  <div key={mem.memory_id} className="learning-runtime-step" style={{ marginBottom: 6 }}>
                    <div className="learning-runtime-step-head">
                      <span>{String(mem.type)}</span>
                      <strong style={{ fontSize: "0.75rem", color: "var(--jade-dark)" }}>used</strong>
                    </div>
                    <p style={{ fontSize: "0.8rem", margin: "2px 0" }}>{String(typeof mem.content === "object" ? JSON.stringify(mem.content) : mem.content)}</p>
                    {mem.reason && <div className="learning-runtime-chips"><small>{mem.reason}</small></div>}
                    <div className="learning-runtime-chips"><small>id: {mem.memory_id}</small></div>
                  </div>
                ))
              )}
              <a href="/memory" style={{ fontSize: "0.78rem", color: "var(--accent, #4b9560)", marginTop: 8, display: "inline-block" }}>Memory Center →</a>
            </div>
          )}
          <div className="learning-runtime-list">
            {sideTab === "timeline" && orderedRuntimeSteps.map((step) => {
              const metadata = step.metadata || {};
              const chips = [
                "intent", "confidence", "tool_name", "risk_level", "side_effect", "required_role",
                "requires_confirmation", "error_code", "used_tool_count", "profile_context_loaded",
                "llm_name", "configured_model", "generation_mode", "response_chars",
              ];
              const summary = runtimeStepSummary(step);
              return (
                <div className={`learning-runtime-step ${step.status}`} key={`${step.trace_id || "local"}-${step.step_id}`}>
                  <div className="learning-runtime-step-head">
                    <span>{typeof step.sequence === "number" ? `${step.sequence}. ` : ""}{step.step_name}</span>
                    <strong>{step.status.replace("_", " ")}</strong>
                  </div>
                  {step.latency_ms != null && <em>{step.latency_ms}ms</em>}
                  {summary && <p className="learning-runtime-summary">{summary}</p>}
                  <div className="learning-runtime-chips">
                    {chips.filter((key) => metadata[key] != null).map((key) => (
                      <small key={key}>{key}: {formatMetadataValue(metadata[key])}</small>
                    ))}
                  </div>
                  {(metadata.input_summary != null || metadata.result_summary != null || step.error) && (
                    <details className="learning-runtime-details">
                      <summary>查看 step metadata</summary>
                      <pre>{JSON.stringify({ metadata, error: step.error || null }, null, 2)}</pre>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
          {sideTab === "rag" && ragChunks.length > 0 && (
            <div className="rag-inspector-panel">
              {ragSummary && (
                <div className="rag-inspector-summary">
                  <strong>召回概览</strong>
                  <span>{ragSummary.sourceCount} 个片段</span>
                  {ragSummary.topScore != null && <span>top score {ragSummary.topScore}</span>}
                  {ragSummary.sourceModes.length > 0 && <span>{ragSummary.sourceModes.join(" / ")}</span>}
                </div>
              )}
              {(ragQuery || ragSummary?.query) && <p className="rag-inspector-query">查询：{ragQuery || ragSummary?.query}</p>}
              {ragChunks.map((chunk, i) => (
                <div className="rag-chunk" key={i}>
                  <div className="rag-chunk-head">
                    <strong>{chunk.topic || chunk.lesson || "片段"}</strong>
                    {chunk.source_mode && <em>{chunk.source_mode}</em>}
                    {chunk.score != null && <b>score {chunk.score}</b>}
                    {chunk.grade && <span>{chunk.grade}</span>}
                    {chunk.source && <span>{chunk.source}</span>}
                  </div>
                  {chunk.score != null && (
                    <div className="rag-score-bar" style={{ width: `${Math.min(100, Math.round(chunk.score * 100))}%` }} title={`score: ${chunk.score}`} />
                  )}
                  {chunk.snippet && <p>{chunk.snippet}</p>}
                </div>
              ))}
            </div>
          )}
          {pendingConfirmation && (
            <div className="learning-confirmation-card">
              <span>Human Confirmation</span>
              <strong>Agent 想调用高风险工具：{toolLabel(pendingConfirmation.toolName)}</strong>
              <p>{pendingConfirmation.message}</p>
              <div className="learning-runtime-chips">
                {pendingConfirmation.riskLevel && <small>risk: {pendingConfirmation.riskLevel}</small>}
                {pendingConfirmation.sideEffect && <small>effect: {pendingConfirmation.sideEffect}</small>}
                {pendingConfirmation.requiredRole && <small>role: {pendingConfirmation.requiredRole}</small>}
              </div>
              <div className="learning-confirmation-actions">
                <button type="button" onClick={() => void confirmToolExecution()} disabled={loading}>确认执行</button>
                <button type="button" onClick={() => void cancelToolExecution()} disabled={loading}>取消</button>
              </div>
            </div>
          )}
          {profileContext && (
            <div className="learning-profile-card">
              <span>学习画像</span>
              {profileContext.profile?.weak_topics?.length ? <p>薄弱点：{profileContext.profile.weak_topics.slice(0, 3).join("、")}</p> : null}
              {profileContext.profile?.recent_topics?.length ? <p>最近主题：{profileContext.profile.recent_topics.slice(0, 3).join("、")}</p> : null}
              {profileContext.review_plan?.recommended_actions?.length ? <p>建议：{profileContext.review_plan.recommended_actions[0]}</p> : null}
              {profileContext.used_memory?.length ? (
                <div className="learning-used-memory-list">
                  <strong>本次使用的记忆</strong>
                  {profileContext.used_memory.map((memory) => (
                    <p key={memory.memory_id}><em>{memory.type}</em>{formatMetadataValue(memory.content)} · {memory.reason}</p>
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}
