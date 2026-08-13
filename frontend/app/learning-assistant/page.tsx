"use client";

import { FormEvent, KeyboardEvent, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Archive, ArrowUp, BookOpen, Check, ChevronDown, History, Pencil, Plus, RotateCcw, Square, X } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import { Select, type SelectOption } from "./Select";
import { TraceTimeline } from "@/components/TraceTimeline";
import { assistantCompletionLabel, buildTextbookRequestFields, shouldSubmitComposerKey, updateAssistantPlanStep, type AssistantPlanStep } from "@/components/learningAssistantComposer";

type Textbook = { id: string; grade: string; book: string; status: string };
type TocLesson = { id: string; title: string };
type TocUnit = { title?: string; unit?: string; lessons: TocLesson[] };
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
type RoutingEvidence = { mode?: string; task_count?: number; reason_code?: string; missing_slots?: string[] };
type PlanSummary = { completed_steps?: number; total_steps?: number; partial_reason?: string | null; failed_step?: string | null };
type Message = {
  id: string;
  persistedId?: string;
  role: "user" | "assistant";
  text: string;
  intent?: string;
  tools?: ToolResult[];
  suggestions?: string[];
  activeGame?: Record<string, unknown>;
  feedback?: "resolved" | "unresolved";
  plan?: AssistantPlanStep[];
  completionStatus?: string;
  routeMode?: string;
  evidence?: {
    history_messages?: number;
    generation_mode?: string;
    source_feature?: string;
    source_session_id?: string | null;
    textbook?: { book_id?: string; lesson_id?: string; grade?: string; book?: string; lesson_title?: string } | null;
    used_memory_count?: number;
    tool_names?: string[];
    routing?: RoutingEvidence;
    plan_summary?: PlanSummary;
    completion_status?: string;
  };
};
type AssistantSession = {
  session_id: string;
  student_id: string;
  title?: string | null;
  status: "active" | "archived";
  source_feature: "standalone" | "auto_tutor" | "textbook";
  source_session_id?: string | null;
  context?: {
    knowledge_point?: string;
    return_path?: string;
    textbook?: { book_id: string; lesson_id: string; grade: string; book: string; lesson_title: string };
  };
  messages?: Array<{
    message_id: string;
    role: "user" | "assistant" | "system_context";
    content: string;
    intent?: string | null;
    trace_id?: string | null;
    tool_results?: ToolResult[];
    metadata?: Message["evidence"] & { feedback?: "resolved" | "unresolved" };
  }>;
};
type AssistantSessionSummary = Omit<AssistantSession, "messages"> & { message_count: number; last_message?: string | null; updated_at: string; created_at: string };
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
type TextbookContext = {
  type: "textbook_lesson";
  bookId: string;
  lessonId: string;
  grade: string;
  bookLabel: string;
  lessonLabel: string;
};
type ConfirmationPayload = { confirmed_tool_name: string; confirmation_token: string; confirmation_decision: "confirmed" };
type SubmitOptions = {
  confirmation?: ConfirmationPayload;
  regenerateMessageId?: string;
  replaceAssistantId?: string;
  appendUser?: boolean;
  reuseLastUser?: boolean;
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
  chat: "自由问答",
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
  { label: "理解上下文", en: "Context", sequences: [1, 2, 3] },
  { label: "工具调用", en: "Tool", sequences: [4, 5, 6] },
  { label: "回答与记录", en: "Synthesis", sequences: [7, 8] },
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

function LearningAssistantContent() {
  const { user } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [message, setMessage] = useState(searchParams.get("q") ?? searchParams.get("prompt") ?? "");
  const studentId = user?.actorId ?? "";
  const sourceAutoTutorId = searchParams.get("autotutor_session_id") ?? "";
  const requestedSessionId = searchParams.get("session_id") ?? "";
  const queryBookId = searchParams.get("book_id") ?? "";
  const queryLessonId = searchParams.get("lesson_id") ?? "";
  const debugMode = searchParams.get("debug") === "1" || process.env.NODE_ENV === "development";
  const [books, setBooks] = useState<Textbook[]>([]);
  const [bookId, setBookId] = useState("");
  const [units, setUnits] = useState<TocUnit[]>([]);
  const [lessonId, setLessonId] = useState("");
  const [contextPickerOpen, setContextPickerOpen] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState("");
  const [textbookContext, setTextbookContext] = useState<TextbookContext | null>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState("等待学习任务");
  const [profileContext, setProfileContext] = useState<ProfileContext | null>(null);
  const [traceId, setTraceId] = useState("");
  const [runtimeSteps, setRuntimeSteps] = useState<RuntimeStep[]>([]);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [lastRequestText, setLastRequestText] = useState("");
  const [ragChunks, setRagChunks] = useState<RagChunk[]>([]);
  const [ragQuery, setRagQuery] = useState("");
  const [ragSummary, setRagSummary] = useState<RagInspectorSummary | null>(null);
  const [toolRegistry, setToolRegistry] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [assistantSession, setAssistantSession] = useState<AssistantSession | null>(null);
  const [sessions, setSessions] = useState<AssistantSessionSummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessionListLoading, setSessionListLoading] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState("");
  const [editingTitle, setEditingTitle] = useState("");
  const [feedbackLoadingId, setFeedbackLoadingId] = useState("");
  const [sessionReady, setSessionReady] = useState(false);
  const msgListRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sourceInitializedRef = useRef("");
  const abortControllerRef = useRef<AbortController | null>(null);

  const requestHeaders = useMemo(
    () => ({ "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) }),
    [user?.token]
  );

  const loadBooks = useCallback(async () => {
    if (books.length) return books;
    setContextLoading(true);
    setContextError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/textbooks`, { headers: user?.token ? authHeaders(user.token) : undefined });
      if (!response.ok) throw new Error("教材暂时无法加载");
      const data = await response.json();
      const readyBooks = (data.textbooks || []).filter((book: Textbook) => book.status === "ready") as Textbook[];
      setBooks(readyBooks);
      return readyBooks;
    } catch {
      setContextError("教材暂时无法加载，你仍可以直接提问。");
      return [];
    } finally {
      setContextLoading(false);
    }
  }, [books, user?.token]);

  const loadToc = useCallback(async (nextBookId: string, preferredLessonId = "") => {
    if (!nextBookId) {
      setUnits([]);
      setLessonId("");
      return [] as TocUnit[];
    }
    setContextLoading(true);
    setContextError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/textbooks/${nextBookId}/toc`, { headers: user?.token ? authHeaders(user.token) : undefined });
      if (!response.ok) throw new Error("课文目录暂时无法加载");
      const data = await response.json();
      const nextUnits = (data.units || []) as TocUnit[];
      setUnits(nextUnits);
      setLessonId(preferredLessonId && nextUnits.some((unit) => unit.lessons.some((lesson) => lesson.id === preferredLessonId)) ? preferredLessonId : "");
      return nextUnits;
    } catch {
      setUnits([]);
      setLessonId("");
      setContextError("教材暂时无法加载，你仍可以直接提问。");
      return [] as TocUnit[];
    } finally {
      setContextLoading(false);
    }
  }, [user?.token]);

  useEffect(() => {
    if (!debugMode) return;
    const headers = user?.token ? authHeaders(user.token) : undefined;
    fetch(`${apiBaseUrl}/api/learning/assistant/tools`, { headers }).then((response) => response.json())
      .then((data) => { if (Array.isArray(data.tools)) setToolRegistry(data.tools as ToolInfo[]); })
      .catch(() => null);
  }, [debugMode, user?.token]);

  useEffect(() => {
    if (!queryBookId || !queryLessonId || sourceAutoTutorId || textbookContext) return;
    let cancelled = false;
    (async () => {
      const availableBooks = await loadBooks();
      const selectedBook = availableBooks.find((book) => book.id === queryBookId);
      if (!selectedBook || cancelled) return;
      setBookId(queryBookId);
      const nextUnits = await loadToc(queryBookId, queryLessonId);
      const selectedLesson = nextUnits.flatMap((unit) => unit.lessons).find((lesson) => lesson.id === queryLessonId);
      if (!selectedLesson || cancelled) return;
      setTextbookContext({
        type: "textbook_lesson",
        bookId: queryBookId,
        lessonId: queryLessonId,
        grade: selectedBook.grade,
        bookLabel: selectedBook.book,
        lessonLabel: selectedLesson.title,
      });
    })();
    return () => { cancelled = true; };
  }, [loadBooks, loadToc, queryBookId, queryLessonId, sourceAutoTutorId, textbookContext]);

  const hydrateSession = useCallback((session: AssistantSession) => {
    setAssistantSession(session);
    const persistedTextbook = session.context?.textbook;
    if (persistedTextbook) {
      setTextbookContext({
        type: "textbook_lesson",
        bookId: persistedTextbook.book_id,
        lessonId: persistedTextbook.lesson_id,
        grade: persistedTextbook.grade,
        bookLabel: persistedTextbook.book,
        lessonLabel: persistedTextbook.lesson_title,
      });
      setBookId(persistedTextbook.book_id);
      setLessonId(persistedTextbook.lesson_id);
    } else {
      setTextbookContext(null);
      setBookId("");
      setLessonId("");
      setUnits([]);
    }
    const restored = (session.messages || []).filter((item) => item.role !== "system_context").map((item) => ({
      id: item.message_id,
      persistedId: item.role === "assistant" ? item.message_id : undefined,
      role: item.role as "user" | "assistant",
      text: item.content,
      intent: item.intent || undefined,
      tools: item.role === "assistant" ? (item.tool_results || []).map(asToolResult).filter(Boolean) as ToolResult[] : undefined,
      feedback: item.metadata?.feedback,
      completionStatus: item.metadata?.completion_status,
      routeMode: item.metadata?.routing?.mode,
      evidence: item.metadata,
    }));
    setMessages(restored);
    setTraceId("");
    setRuntimeSteps([]);
    setRagChunks([]);
    setRagSummary(null);
    setProfileContext(null);
    setPendingConfirmation(null);
  }, []);

  const createSession = useCallback(async (sourceSessionId?: string): Promise<AssistantSession> => {
    const response = await fetch(`${apiBaseUrl}/api/learning/assistant/sessions`, {
      method: "POST",
      headers: requestHeaders,
      body: JSON.stringify({
        student_id: studentId,
        source_feature: sourceSessionId ? "auto_tutor" : "standalone",
        source_session_id: sourceSessionId || null,
      }),
    });
    if (!response.ok) throw new Error(`创建随问会话失败：${response.status}`);
    const session = await response.json() as AssistantSession;
    setAssistantSession(session);
    return session;
  }, [requestHeaders, studentId]);

  const loadSessions = useCallback(async () => {
    if (!studentId || !user?.token) return [] as AssistantSessionSummary[];
    setSessionListLoading(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/learning/assistant/students/${studentId}/sessions?status=all&limit=50`, { headers: requestHeaders });
      if (!response.ok) throw new Error(`加载历史会话失败：${response.status}`);
      const data = await response.json();
      const nextSessions = (data.sessions || []) as AssistantSessionSummary[];
      setSessions(nextSessions);
      return nextSessions;
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载历史会话失败");
      return [] as AssistantSessionSummary[];
    } finally {
      setSessionListLoading(false);
    }
  }, [requestHeaders, studentId, user?.token]);

  const fetchSession = useCallback(async (sessionId: string) => {
    const response = await fetch(`${apiBaseUrl}/api/learning/assistant/sessions/${sessionId}`, { headers: requestHeaders });
    if (!response.ok) throw new Error(response.status === 404 ? "随问会话不存在" : `恢复随问会话失败：${response.status}`);
    return response.json() as Promise<AssistantSession>;
  }, [requestHeaders]);

  useEffect(() => {
    if (!studentId || !user?.token || sessionReady) return;
    let cancelled = false;
    (async () => {
      try {
        if (sourceAutoTutorId) {
          if (sourceInitializedRef.current === sourceAutoTutorId) return;
          sourceInitializedRef.current = sourceAutoTutorId;
          const session = await createSession(sourceAutoTutorId);
          if (!cancelled) hydrateSession(session);
        } else if (requestedSessionId) {
          const session = await fetchSession(requestedSessionId);
          if (!cancelled) hydrateSession(session);
        } else {
          const response = await fetch(`${apiBaseUrl}/api/learning/assistant/students/${studentId}/latest-session`, { headers: requestHeaders });
          if (response.ok) {
            const session = await response.json() as AssistantSession;
            if (!cancelled) hydrateSession(session);
          }
        }
      } catch (error) {
        if (!cancelled) setErrorMessage(error instanceof Error ? error.message : "恢复随问会话失败");
      } finally {
        if (!cancelled) setSessionReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, [studentId, user?.token, sourceAutoTutorId, requestedSessionId, sessionReady, requestHeaders, createSession, fetchSession, hydrateSession]);

  async function startNewConversation() {
    if (!studentId || loading) return;
    setLoading(true);
    setErrorMessage("");
    try {
      const session = await createSession();
      setMessages([]);
      setAssistantSession(session);
      setBookId("");
      setLessonId("");
      setUnits([]);
      setTextbookContext(null);
      setTraceId("");
      setRuntimeSteps([]);
      setStatus("等待你的问题");
      router.replace(`/student/assistant?session_id=${encodeURIComponent(session.session_id)}`, { scroll: false });
      if (historyOpen) await loadSessions();
      setHistoryOpen(false);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "创建新对话失败");
    } finally {
      setLoading(false);
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    await loadSessions();
  }

  async function switchSession(sessionId: string) {
    if (loading || sessionId === assistantSession?.session_id) {
      setHistoryOpen(false);
      return;
    }
    setSessionListLoading(true);
    setErrorMessage("");
    try {
      const session = await fetchSession(sessionId);
      hydrateSession(session);
      setHistoryOpen(false);
      setSessionReady(true);
      router.replace(`/student/assistant?session_id=${encodeURIComponent(sessionId)}`, { scroll: false });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "恢复随问会话失败");
    } finally {
      setSessionListLoading(false);
    }
  }

  async function patchSession(sessionId: string, patch: { title?: string; status?: "active" | "archived" }) {
    const response = await fetch(`${apiBaseUrl}/api/learning/assistant/sessions/${sessionId}`, {
      method: "PATCH",
      headers: requestHeaders,
      body: JSON.stringify(patch),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `更新会话失败：${response.status}`);
    }
    return response.json() as Promise<AssistantSession>;
  }

  async function saveSessionTitle(sessionId: string) {
    const title = editingTitle.trim();
    if (!title) return;
    try {
      const updated = await patchSession(sessionId, { title });
      if (assistantSession?.session_id === sessionId) setAssistantSession((current) => current ? { ...current, title: updated.title } : current);
      setEditingSessionId("");
      setEditingTitle("");
      await loadSessions();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "重命名会话失败");
    }
  }

  async function setSessionArchived(sessionId: string, archived: boolean) {
    try {
      await patchSession(sessionId, { status: archived ? "archived" : "active" });
      const nextSessions = await loadSessions();
      if (!archived) {
        await switchSession(sessionId);
        return;
      }
      if (assistantSession?.session_id === sessionId) {
        const nextActive = nextSessions.find((item) => item.status === "active" && item.session_id !== sessionId);
        if (nextActive) await switchSession(nextActive.session_id);
        else await startNewConversation();
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "更新会话状态失败");
    }
  }

  async function persistTextbookContext(context: TextbookContext | null, targetSession?: AssistantSession | null) {
    const activeSession = targetSession || assistantSession || await createSession();
    const response = await fetch(`${apiBaseUrl}/api/learning/assistant/sessions/${activeSession.session_id}/context`, {
      method: "PATCH",
      headers: requestHeaders,
      body: JSON.stringify({
        textbook: context ? { book_id: context.bookId, lesson_id: context.lessonId } : null,
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `保存教材上下文失败：${response.status}`);
    }
    const updated = await response.json() as AssistantSession;
    setAssistantSession((current) => ({ ...(current || activeSession), ...updated, messages: current?.messages }));
    if (!requestedSessionId && !sourceAutoTutorId) router.replace(`/student/assistant?session_id=${encodeURIComponent(activeSession.session_id)}`, { scroll: false });
    return updated;
  }

  useEffect(() => {
    if (!assistantSession || !textbookContext || !queryBookId || !queryLessonId || sourceAutoTutorId) return;
    const persisted = assistantSession.context?.textbook;
    if (persisted?.book_id === textbookContext.bookId && persisted?.lesson_id === textbookContext.lessonId) return;
    void persistTextbookContext(textbookContext, assistantSession).catch((error) => {
      setContextError(error instanceof Error ? error.message : "保存教材上下文失败");
    });
    // Query deep links should attach once after both the session and trusted lesson labels are ready.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistantSession?.session_id, textbookContext?.bookId, textbookContext?.lessonId, queryBookId, queryLessonId, sourceAutoTutorId]);

  useEffect(() => { msgListRef.current?.scrollTo({ top: msgListRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 132)}px`;
  }, [message]);

  const assistantReady = useMemo(() => !loading && message.trim().length > 0, [loading, message]);
  const orderedRuntimeSteps = useMemo(() => sortedRuntimeSteps(runtimeSteps), [runtimeSteps]);
  const selectedBook = books.find((book) => book.id === bookId);
  const selectedLesson = units.flatMap((unit) => unit.lessons).find((lesson) => lesson.id === lessonId);
  const lastAssistantId = [...messages].reverse().find((item) => item.role === "assistant")?.id;

  async function openContextPicker() {
    if (sourceAutoTutorId || assistantSession?.source_feature === "auto_tutor") return;
    setContextPickerOpen(true);
    await loadBooks();
  }

  async function chooseBook(nextBookId: string) {
    setBookId(nextBookId);
    setLessonId("");
    await loadToc(nextBookId);
  }

  async function applyTextbookContext() {
    if (!selectedBook || !selectedLesson) return;
    const nextContext: TextbookContext = {
      type: "textbook_lesson",
      bookId: selectedBook.id,
      lessonId: selectedLesson.id,
      grade: selectedBook.grade,
      bookLabel: selectedBook.book,
      lessonLabel: selectedLesson.title,
    };
    setContextLoading(true);
    setContextError("");
    try {
      await persistTextbookContext(nextContext);
      setTextbookContext(nextContext);
      setContextPickerOpen(false);
      textareaRef.current?.focus();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : "保存教材上下文失败");
    } finally {
      setContextLoading(false);
    }
  }

  async function removeTextbookContext() {
    setContextError("");
    try {
      await persistTextbookContext(null);
      setTextbookContext(null);
      setBookId("");
      setLessonId("");
      setUnits([]);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "移除教材上下文失败");
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!shouldSubmitComposerKey({ key: event.key, shiftKey: event.shiftKey, isComposing: event.nativeEvent.isComposing })) return;
    event.preventDefault();
    if (assistantReady && sessionReady) void submit();
  }

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
        setStatus(`已识别：${intentLabels[intentName] || intentName || "学习任务"}`);
        updateAssistant(assistantId, (current) => ({ ...current, intent: intentName }));
        return;
      }
      if (event === "route") {
        const taskCount = Array.isArray(data.tasks) ? data.tasks.length : 1;
        const mode = typeof data.mode === "string" ? data.mode : "rule";
        setStatus(taskCount > 1 ? `已拆分为 ${taskCount} 个学习目标` : "已理解学习目标");
        updateAssistant(assistantId, (current) => ({ ...current, routeMode: mode }));
        return;
      }
      if (event === "plan") {
        const steps = Array.isArray(data.steps) ? data.steps.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")).map((item, index): AssistantPlanStep => ({
          step_id: typeof item.step_id === "string" ? item.step_id : `step_${index + 1}`,
          title: typeof item.title === "string" ? item.title : `步骤 ${index + 1}`,
          kind: item.kind === "tool" || item.kind === "generation" ? item.kind : undefined,
          operation: typeof item.operation === "string" ? item.operation : undefined,
          status: "pending" as const,
        })) : [];
        updateAssistant(assistantId, (current) => ({ ...current, plan: steps }));
        if (steps.length) setStatus(`正在执行学习计划 · 0/${steps.length}`);
        return;
      }
      if (event === "plan_step") {
        const stepId = typeof data.step_id === "string" ? data.step_id : "";
        if (!stepId) return;
        updateAssistant(assistantId, (current) => {
          const currentPlan = current.plan || [];
          const nextPlan = updateAssistantPlanStep(currentPlan, {
            step_id: stepId,
            status: typeof data.status === "string" ? data.status as AssistantPlanStep["status"] : undefined,
            sequence: typeof data.sequence === "number" ? data.sequence : undefined,
            latency_ms: typeof data.latency_ms === "number" ? data.latency_ms : undefined,
            result_summary: typeof data.result_summary === "string" ? data.result_summary : undefined,
          });
          const completed = nextPlan.filter((step) => step.status === "completed").length;
          setStatus(data.status === "waiting_confirmation" ? "学习计划等待确认" : data.status === "failed" ? "学习计划部分未完成" : `正在执行学习计划 · ${completed}/${nextPlan.length}`);
          return { ...current, plan: nextPlan };
        });
        return;
      }
      if (event === "clarification") {
        setStatus("需要补充学习范围");
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
        const persistedId = typeof data.message_id === "string" ? data.message_id : undefined;
        const contextUsage = data.context_usage && typeof data.context_usage === "object" ? data.context_usage as Record<string, unknown> : {};
        updateAssistant(assistantId, (current) => ({
          ...current,
          persistedId,
          text: finalText || current.text,
          completionStatus: typeof data.completion_status === "string" ? data.completion_status : "completed",
          routeMode: data.routing && typeof data.routing === "object" && typeof (data.routing as Record<string, unknown>).mode === "string" ? String((data.routing as Record<string, unknown>).mode) : current.routeMode,
          tools,
          activeGame: activeGame && typeof activeGame === "object" ? activeGame as Record<string, unknown> : undefined,
          evidence: {
            history_messages: Number(contextUsage.history_messages || 0),
            generation_mode: typeof data.generation_mode === "string" ? data.generation_mode : undefined,
            source_feature: typeof contextUsage.source_feature === "string" ? contextUsage.source_feature : assistantSession?.source_feature,
            source_session_id: typeof contextUsage.source_session_id === "string" ? contextUsage.source_session_id : assistantSession?.source_session_id,
            textbook: textbookContext ? {
              book_id: textbookContext.bookId,
              lesson_id: textbookContext.lessonId,
              grade: textbookContext.grade,
              book: textbookContext.bookLabel,
              lesson_title: textbookContext.lessonLabel,
            } : null,
            used_memory_count: nextProfileContext?.used_memory?.length || 0,
            tool_names: tools.map((tool) => tool.tool_name),
            routing: data.routing && typeof data.routing === "object" ? data.routing as RoutingEvidence : undefined,
            plan_summary: data.plan_summary && typeof data.plan_summary === "object" ? data.plan_summary as PlanSummary : undefined,
            completion_status: typeof data.completion_status === "string" ? data.completion_status : undefined,
          },
        }));
        const completionStatus = typeof data.completion_status === "string" ? data.completion_status : "completed";
        setStatus(assistantCompletionLabel(completionStatus));
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

  async function submit(nextMessage?: string, options: SubmitOptions = {}) {
    const text = (nextMessage || message).trim();
    if (!text || loading) return;
    const assistantId = options.replaceAssistantId || createId("assistant");
    const appendUser = options.appendUser !== false && !options.regenerateMessageId && !options.confirmation;
    setMessages((current) => {
      if (options.replaceAssistantId) {
        return current.map((item) => item.id === options.replaceAssistantId ? { id: assistantId, role: "assistant", text: "" } : item);
      }
      const next = [...current];
      if (appendUser) next.push({ id: createId("user"), role: "user", text });
      next.push({ id: assistantId, role: "assistant", text: "" });
      return next;
    });
    setMessage("");
    setLoading(true);
    setErrorMessage("");
    setProfileContext(null);
    if (!options.confirmation) {
      setTraceId("");
      setRuntimeSteps([]);
      setRagChunks([]);
      setRagSummary(null);
    }
    setPendingConfirmation(null);
    setLastRequestText(text);
    setStatus("正在发送学习任务");
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const activeSession = assistantSession || await createSession(sourceAutoTutorId || undefined);
      const response = await fetch(`${apiBaseUrl}/api/learning/assistant/chat`, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify({
          session_id: activeSession.session_id,
          message: text,
          student_id: studentId || null,
          ...buildTextbookRequestFields(textbookContext),
          stream: true,
          regenerate_message_id: options.regenerateMessageId || null,
          reuse_last_user: options.reuseLastUser === true,
          ...(options.confirmation || {}),
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : `请求失败：${response.status}`);
      }
      await handleStream(response, assistantId);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        updateAssistant(assistantId, (current) => ({ ...current, text: current.text || "已停止生成。" }));
        setStatus("已停止生成");
        return;
      }
      const fallback = error instanceof Error ? error.message : "学习助手请求失败";
      setErrorMessage(fallback);
      updateAssistant(assistantId, (current) => ({ ...current, text: current.text || fallback }));
      setStatus("请求失败");
    } finally {
      if (abortControllerRef.current === controller) abortControllerRef.current = null;
      setLoading(false);
    }
  }

  function stopGeneration() {
    abortControllerRef.current?.abort();
  }

  function regenerateAnswer(item: Message) {
    if (!item.persistedId || loading) return;
    const index = messages.findIndex((messageItem) => messageItem.id === item.id);
    const previousUser = index > 0 ? messages[index - 1] : null;
    if (!previousUser || previousUser.role !== "user") return;
    void submit(previousUser.text, {
      regenerateMessageId: item.persistedId,
      replaceAssistantId: item.id,
      appendUser: false,
    });
  }

  function retryInterruptedAnswer() {
    const lastAssistant = [...messages].reverse().find((item) => item.role === "assistant");
    if (!lastAssistant || !lastRequestText) return;
    if (lastAssistant.persistedId) {
      regenerateAnswer(lastAssistant);
      return;
    }
    void submit(lastRequestText, {
      replaceAssistantId: lastAssistant.id,
      appendUser: false,
      reuseLastUser: true,
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  async function submitFeedback(item: Message, feedback: "resolved" | "unresolved") {
    if (!assistantSession || !item.persistedId || item.feedback || feedbackLoadingId) return;
    setFeedbackLoadingId(item.id);
    setErrorMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/learning/assistant/sessions/${assistantSession.session_id}/messages/${item.persistedId}/feedback`, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify({ feedback }),
      });
      if (!response.ok) throw new Error(`提交反馈失败：${response.status}`);
      const result = await response.json() as { followup_prompt?: string | null };
      updateAssistant(item.id, (current) => ({ ...current, feedback }));
      if (feedback === "unresolved" && result.followup_prompt) void submit(result.followup_prompt);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "提交反馈失败");
    } finally {
      setFeedbackLoadingId("");
    }
  }

  async function returnToAutoTutor() {
    if (!assistantSession || assistantSession.source_feature !== "auto_tutor") return;
    setErrorMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/learning/assistant/sessions/${assistantSession.session_id}/return-to-source`, {
        method: "POST",
        headers: requestHeaders,
      });
      if (!response.ok) throw new Error(`返回辅导失败：${response.status}`);
      const result = await response.json() as { return_path?: string };
      window.location.assign(result.return_path || assistantSession.context?.return_path || "/student/auto-tutor");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "返回辅导失败");
    }
  }

  async function confirmToolExecution() {
    if (!pendingConfirmation || !lastRequestText) return;
    setRuntimeSteps((current) => current.map((step) => step.status === "waiting_confirmation" ? { ...step, status: "confirmed" } : step));
    setStatus("已确认高风险工具，正在重新执行");
    const lastAssistant = [...messages].reverse().find((item) => item.role === "assistant");
    await submit(lastRequestText, {
      confirmation: {
        confirmed_tool_name: pendingConfirmation.toolName,
        confirmation_token: pendingConfirmation.token,
        confirmation_decision: "confirmed",
      },
      replaceAssistantId: lastAssistant?.id,
      appendUser: false,
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
    <main className="learning-assistant-shell learning-conversation-shell">
      <header className="learning-conversation-header">
        <div>
          <span className="panel-kicker">学习对话</span>
          <h1>随问</h1>
          <p>有问题直接问，我会结合对话和学习进度帮助你。</p>
        </div>
        <div className="learning-header-actions">
          <button type="button" className="learning-new-chat" onClick={() => void openHistory()} disabled={loading || !studentId}>
            <History size={16} aria-hidden="true" />
            历史会话
          </button>
          <button type="button" className="learning-new-chat" onClick={() => void startNewConversation()} disabled={loading || !studentId}>
            <RotateCcw size={16} aria-hidden="true" />
            新对话
          </button>
        </div>
      </header>

      {historyOpen && (
        <div className="learning-history-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHistoryOpen(false); }}>
          <aside className="learning-history-drawer" role="dialog" aria-label="历史会话">
            <div className="learning-history-head">
              <div><span className="panel-kicker">Conversations</span><h2>历史会话</h2></div>
              <button type="button" onClick={() => setHistoryOpen(false)} aria-label="关闭历史会话"><X size={19} /></button>
            </div>
            <button type="button" className="learning-history-new" onClick={() => void startNewConversation()} disabled={loading}>
              <Plus size={16} /> 新对话
            </button>
            <div className="learning-history-list">
              {sessionListLoading && sessions.length === 0 ? <p className="learning-history-empty">正在加载会话…</p> : null}
              {!sessionListLoading && sessions.length === 0 ? <p className="learning-history-empty">还没有历史会话。</p> : null}
              {sessions.map((session) => (
                <article className={`learning-history-item ${assistantSession?.session_id === session.session_id ? "active" : ""} ${session.status}`} key={session.session_id}>
                  {editingSessionId === session.session_id ? (
                    <div className="learning-history-rename">
                      <input value={editingTitle} maxLength={80} onChange={(event) => setEditingTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveSessionTitle(session.session_id); if (event.key === "Escape") setEditingSessionId(""); }} aria-label="会话标题" autoFocus />
                      <button type="button" onClick={() => void saveSessionTitle(session.session_id)} aria-label="保存会话标题"><Check size={15} /></button>
                    </div>
                  ) : (
                    <button type="button" className="learning-history-select" onClick={() => void switchSession(session.session_id)} disabled={loading}>
                      <strong>{session.title || "新对话"}</strong>
                      <span>{session.last_message || "暂无消息"}</span>
                      <small>{session.message_count} 条消息{session.status === "archived" ? " · 已归档" : ""}</small>
                    </button>
                  )}
                  <div className="learning-history-actions">
                    <button type="button" onClick={() => { setEditingSessionId(session.session_id); setEditingTitle(session.title || "新对话"); }} aria-label={`重命名${session.title || "新对话"}`}><Pencil size={14} /></button>
                    <button type="button" onClick={() => void setSessionArchived(session.session_id, session.status !== "archived")} aria-label={session.status === "archived" ? `恢复${session.title || "新对话"}` : `归档${session.title || "新对话"}`}><Archive size={14} /></button>
                  </div>
                </article>
              ))}
            </div>
          </aside>
        </div>
      )}

      <section className="learning-conversation-card" aria-label="随问学习对话">
        {assistantSession?.source_feature === "auto_tutor" && (
          <div className="learning-source-banner">
            <span><strong>正在询问自主辅导</strong> · {assistantSession.context?.knowledge_point || "当前知识点"}</span>
            <button type="button" onClick={() => void returnToAutoTutor()}>返回自主辅导</button>
          </div>
        )}

        <div className={`learning-message-list ${messages.length === 0 ? "empty" : ""}`} ref={msgListRef} aria-live="polite">
          {messages.length === 0 ? (
            <div className="learning-empty-state">
              <div className="learning-empty-mark" aria-hidden="true">问</div>
              <h2>今天想弄懂什么？</h2>
              <p>直接提问，或者从一个学习任务开始。</p>
              <div className="learning-empty-prompts">
                {examples.map((example) => (
                  <button type="button" key={example} onClick={() => setMessage(example)} disabled={loading}>{example}</button>
                ))}
              </div>
            </div>
          ) : messages.map((item) => (
            <article className={`learning-message ${item.role}`} key={item.id}>
              {item.role === "assistant" && <div className="learning-assistant-label"><span aria-hidden="true">问</span> 随问</div>}
              {item.role === "assistant" && item.plan?.length ? (
                <div className="learning-plan-progress" aria-live="polite" aria-label="学习计划进度">
                  {item.plan.map((step, index) => (
                    <span className={`learning-plan-step ${step.status}`} key={`${item.id}-${step.step_id}`}>
                      <i aria-hidden="true">{step.status === "completed" ? "✓" : step.status === "failed" ? "!" : index + 1}</i>
                      {step.title}
                    </span>
                  ))}
                </div>
              ) : null}
              <p>{item.text || "正在组织回答……"}</p>
              {item.role === "assistant" && item.completionStatus === "partial" ? <p className="learning-partial-notice">部分任务未完成，已保留可验证的结果。</p> : null}
              {item.tools?.filter((tool) => !(item.intent === "quiz_generation" && tool.tool_name === "search_history_knowledge")).map((tool) => (
                <div className={`learning-tool-card ${tool.ok ? "ok" : "error"}`} key={`${item.id}-${tool.tool_name}`}>
                  <div><strong>{toolLabel(tool.tool_name)}</strong><span>{tool.ok ? "已完成" : tool.error?.message || "执行失败"}</span></div>
                  {renderToolPreview(tool)}
                </div>
              ))}
              {item.role === "assistant" && item.persistedId && item.text ? (
                <div className="learning-suggestion-row learning-feedback-row" aria-label="回答是否解决问题">
                  {item.feedback ? (
                    <span>{item.feedback === "resolved" ? "已反馈：解决了" : "已换一种方式解释"}</span>
                  ) : (
                    <>
                      <button type="button" onClick={() => void submitFeedback(item, "resolved")} disabled={loading || Boolean(feedbackLoadingId)}>解决了</button>
                      <button type="button" onClick={() => void submitFeedback(item, "unresolved")} disabled={loading || Boolean(feedbackLoadingId)}>换种方式讲</button>
                    </>
                  )}
                  {item.id === lastAssistantId && <button type="button" onClick={() => regenerateAnswer(item)} disabled={loading}>重新生成</button>}
                </div>
              ) : null}
              {item.suggestions?.length ? (
                <div className="learning-suggestion-row">
                  {item.suggestions.map((suggestion) => (
                    <button type="button" key={suggestion} onClick={() => suggestion.includes("开始游戏") && item.activeGame ? openTimelineGame(item.activeGame) : void submit(suggestion)} disabled={loading}>
                      {suggestion}
                    </button>
                  ))}
                </div>
              ) : null}
              {item.role === "assistant" && item.text && (item.intent || item.tools?.length || item.evidence) ? (
                <details className="learning-answer-evidence">
                  <summary>查看回答依据 <ChevronDown size={14} aria-hidden="true" /></summary>
                  <div>
                    {item.evidence?.textbook ? <p><BookOpen size={14} aria-hidden="true" />参考教材：{item.evidence.textbook.grade} · {item.evidence.textbook.book} · {item.evidence.textbook.lesson_title}</p> : null}
                    {item.evidence?.source_feature === "auto_tutor" && <p>参考自主辅导知识点：{assistantSession?.context?.knowledge_point || "当前知识点"}</p>}
                    {item.evidence?.history_messages ? <p>结合了最近 {item.evidence.history_messages} 条对话</p> : null}
                    {item.evidence?.used_memory_count ? <p>结合了 {item.evidence.used_memory_count} 条近期学习记忆</p> : null}
                    {item.evidence?.generation_mode === "fallback" ? <p>本回答使用了稳定降级模式</p> : null}
                    {item.intent && <p>回答方式：{intentLabels[item.intent] || item.intent}</p>}
                    {item.routeMode && <p>路由方式：{item.routeMode}</p>}
                    {item.evidence?.plan_summary?.total_steps ? <p>计划完成：{item.evidence.plan_summary.completed_steps || 0}/{item.evidence.plan_summary.total_steps}</p> : null}
                    {(item.evidence?.tool_names?.length || item.tools?.length) ? <p>学习能力：{(item.evidence?.tool_names || item.tools?.map((tool) => tool.tool_name) || []).map(toolLabel).join("、")}</p> : null}
                  </div>
                </details>
              ) : null}
            </article>
          ))}
          {pendingConfirmation && (
            <div className="learning-confirmation-card">
              <span>需要你的确认</span>
              <strong>是否允许使用“{toolLabel(pendingConfirmation.toolName)}”？</strong>
              <p>{pendingConfirmation.message}</p>
              <div className="learning-confirmation-actions">
                <button type="button" onClick={() => void confirmToolExecution()} disabled={loading}>确认执行</button>
                <button type="button" onClick={() => void cancelToolExecution()} disabled={loading}>取消</button>
              </div>
            </div>
          )}
        </div>

        <div className="learning-composer-wrap">
          {(assistantSession?.source_feature === "auto_tutor" || textbookContext) && (
            <div className="learning-context-chips" aria-label="当前学习上下文">
              {assistantSession?.source_feature === "auto_tutor" ? (
                <span className="learning-context-chip locked">自主辅导 · {assistantSession.context?.knowledge_point || "当前知识点"}</span>
              ) : textbookContext ? (
                <span className="learning-context-chip">
                  <BookOpen size={14} aria-hidden="true" />
                  {textbookContext.grade} · {textbookContext.bookLabel} · {textbookContext.lessonLabel}
                  <button type="button" onClick={() => void removeTextbookContext()} aria-label="移除教材上下文"><X size={14} /></button>
                </span>
              ) : null}
            </div>
          )}

          {contextPickerOpen && (
            <div className="learning-context-picker" role="dialog" aria-label="添加教材上下文">
              <div className="learning-context-picker-head">
                <div><strong>添加教材上下文</strong><span>可选，用于限定回答范围</span></div>
                <button type="button" onClick={() => setContextPickerOpen(false)} aria-label="关闭教材选择"><X size={17} /></button>
              </div>
              <label>
                教材
                <Select value={bookId} onChange={(value) => void chooseBook(value)} options={books.map((book) => ({ value: book.id, label: `${book.grade} · ${book.book}` } as SelectOption))} />
              </label>
              <label>
                课文
                <Select value={lessonId} onChange={setLessonId} disabled={!units.length} options={units.flatMap((unit) => unit.lessons.map((lesson) => ({ value: lesson.id, label: lesson.title, group: unit.title || unit.unit } as SelectOption)))} />
              </label>
              {contextLoading && <p className="learning-context-hint">正在加载教材…</p>}
              {contextError && <p className="learning-context-error">{contextError}</p>}
              <div className="learning-context-picker-actions">
                <button type="button" onClick={() => setContextPickerOpen(false)}>暂不使用</button>
                <button type="button" onClick={() => void applyTextbookContext()} disabled={!selectedBook || !selectedLesson || contextLoading}>添加本课</button>
              </div>
            </div>
          )}

          <form className="learning-input-bar" onSubmit={handleSubmit}>
            <button type="button" className="learning-context-trigger" onClick={() => void openContextPicker()} disabled={loading || assistantSession?.source_feature === "auto_tutor"} aria-label="添加教材上下文" title={assistantSession?.source_feature === "auto_tutor" ? "当前已使用自主辅导上下文" : "添加教材上下文"}>
              <Plus size={20} aria-hidden="true" />
            </button>
            <textarea ref={textareaRef} value={message} maxLength={500} rows={1} onChange={(event) => setMessage(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder="问任何学习问题……" aria-label="学习问题" />
            {loading ? (
              <button type="button" className="learning-send-button learning-stop-button" onClick={stopGeneration} aria-label="停止生成"><Square size={15} aria-hidden="true" /></button>
            ) : (
              <button type="submit" className="learning-send-button" disabled={!assistantReady || !sessionReady} aria-label="发送问题"><ArrowUp size={20} aria-hidden="true" /></button>
            )}
          </form>
          <div className="learning-composer-meta">
            <span>{loading ? status : textbookContext ? "已限定为当前课文" : "可直接提问，也可以添加教材"}</span>
            <span>Enter 发送 · Shift+Enter 换行</span>
          </div>
          {errorMessage && (
            <div className="learning-error" role="alert">
              <span>{errorMessage}</span>
              {lastRequestText && <button type="button" onClick={retryInterruptedAnswer} disabled={loading}>重新生成</button>}
            </div>
          )}
        </div>
      </section>

      {debugMode && (
        <details className="learning-debug-inspector">
          <summary>开发者调试信息 <ChevronDown size={15} aria-hidden="true" /></summary>
          <div className="learning-debug-content">
            <AgentPipeline steps={orderedRuntimeSteps} />
            {traceId && <p className="learning-trace-id">Trace: {traceId}</p>}
            <TraceTimeline traceId={traceId} token={user?.token} />
            <div className="learning-runtime-list">
              {orderedRuntimeSteps.map((step) => (
                <div className={`learning-runtime-step ${step.status}`} key={`${step.trace_id || "local"}-${step.step_id}`}>
                  <div className="learning-runtime-step-head"><span>{step.step_name}</span><strong>{step.status}</strong></div>
                  {runtimeStepSummary(step) && <p>{runtimeStepSummary(step)}</p>}
                </div>
              ))}
            </div>
            {ragChunks.length > 0 && <p>RAG：{ragSummary?.sourceCount || ragChunks.length} 个片段 · 查询“{ragQuery || ragSummary?.query}”</p>}
            <p>Tools：{toolRegistry.length} · Memory：{profileContext?.used_memory?.length || 0}</p>
            <Link href="/memory">打开 Memory Center</Link>
          </div>
        </details>
      )}
    </main>
  );
}

export default function LearningAssistantPage() {
  return (
    <Suspense fallback={<main className="learning-assistant-shell learning-conversation-shell"><div className="learning-page-skeleton" /></main>}>
      <LearningAssistantContent />
    </Suspense>
  );
}
