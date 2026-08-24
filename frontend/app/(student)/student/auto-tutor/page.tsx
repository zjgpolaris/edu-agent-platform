"use client";

import { useCallback, useEffect, useMemo, useRef, useState, Suspense } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import { TraceTimeline } from "@/components/TraceTimeline";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type PlanStep = {
  knowledge_point: string;
  source_tag?: string | null;
  difficulty: string;
  status: "pending" | "active" | "practiced" | "mastered" | "struggling" | "content_blocked";
  attempts: number;
  replanned: boolean;
  objective?: { objective_id: string; entity: string; aspect: string; target_outcome: string } | null;
  content_status?: "verified" | "blocked" | null;
};
type CurrentQuestion = {
  kind?: "practice" | "exit_ticket";
  assessment_id?: string;
  objective?: { objective_id: string; label: string } | null;
  content_status?: "verified" | "blocked";
  evidence_label?: string | null;
  knowledge_point: string;
  difficulty: string;
  teaching?: {
    explanation: string;
    key_points: string[];
    example?: string;
  } | null;
  question: string;
  options: string[];
  step_index: number;
  replanned: boolean;
};
type Reflection = {
  step_index: number;
  knowledge_point: string;
  diagnosis: string;
  adjustment: string;
  explanation: string;
};
type RuntimeStep = {
  trace_id?: string | null;
  agent_name: string;
  step_id: string;
  step_name: string;
  sequence: number;
  event_type: string;
  status: string;
  latency_ms?: number | null;
  metadata?: Record<string, unknown>;
  error?: { message?: string } | null;
};
type ExitTicketResult = {
  knowledge_point: string;
  source_tag?: string | null;
  selected_answer: string;
  correct_answer: string;
  is_correct: boolean;
  explanation?: string;
  mastery_signal: "exit_ticket_passed" | "exit_ticket_failed";
};

type EvidenceSummary = {
  exit_ticket_recorded: boolean;
  learning_event_types: string[];
  weakpoint_action: string;
  review_action: string;
  tutor_effectiveness_ready: boolean;
};

type SessionState = {
  session_id: string;
  trace_id: string;
  student_id: string;
  grade?: string | null;
  status: "awaiting_answer" | "needs_content" | "completed";
  phase?: "lesson" | "exit_ticket" | "content_blocked" | "completed";
  revision: number;
  lesson_plan: PlanStep[];
  current_step_index: number;
  current_question: CurrentQuestion | null;
  reflect_log: Reflection[];
  replans: number;
  summary?: string | null;
  exit_ticket_result?: ExitTicketResult | null;
  evidence?: EvidenceSummary | null;
  runtime_steps: RuntimeStep[];
  reflection?: Reflection;
  last_answer_correct?: boolean;
  stale_answer_ignored?: boolean;
  answer_feedback?: {
    selected_option: string;
    message: string;
    correction: string;
    misconception_code?: string | null;
    is_correct: boolean;
  } | null;
  mastery?: {
    status: "verified" | "not_yet_verified";
    practice_verified: boolean;
    practice_correct: boolean;
    exit_ticket_verified: boolean;
  };
  content_blocked?: {
    objective_label: string;
    message: string;
    suggested_actions: string[];
  } | null;
};

type RootCauseInfo = {
  root_cause: string;
  label: string;
  icon: string;
  description: string;
  tip: string;
  confidence?: number;
} | null;

const difficultyLabel: Record<string, string> = { easy: "基础", medium: "进阶", hard: "挑战" };
const adjustmentLabel: Record<string, string> = {
  reteach: "补讲后重测",
  lower_difficulty: "降低难度",
  change_example: "换个例子",
  advance: "继续推进",
};
const stepStatusLabel: Record<string, string> = {
  pending: "待教",
  active: "进行中",
  practiced: "已完成练习",
  mastered: "已掌握",
  struggling: "仍薄弱",
  content_blocked: "等待补充内容",
};

const runtimeStatusLabel: Record<string, string> = {
  success: "成功",
  failed: "失败",
  degraded: "降级",
  waiting_answer: "等待作答",
};

function eventTone(eventType: string): string {
  if (eventType === "exit_ticket") return "#7a4bb0";
  if (eventType === "teach" || eventType === "reteach") return "#247a73";
  if (eventType === "reflect") return "#b8004d";
  if (eventType === "re_plan") return "#b87a00";
  if (eventType === "plan") return "#2f6f4f";
  if (eventType === "memory") return "#4b6fb0";
  if (eventType === "judge") return "#7a4bb0";
  return "var(--jade-dark, #2f6f4f)";
}

function formatMeta(value: unknown): string {
  if (value == null || value === "") return "-";
  if (Array.isArray(value)) return value.map(formatMeta).join("、");
  if (typeof value === "object") return JSON.stringify(value).slice(0, 160);
  return String(value);
}

function AutoTutorInner() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const studentId = user?.actorId ?? "";
  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("准备就绪");
  const [selected, setSelected] = useState<string | null>(null);
  const [rootCause, setRootCause] = useState<RootCauseInfo>(null);
  const [rootCauseChecked, setRootCauseChecked] = useState(false);
  const [restored, setRestored] = useState(false);
  const traceRef = useRef<HTMLDivElement>(null);
  const autoStartedFocusRef = useRef<string | null>(null);

  // 从 URL ?focus=知识点 读取作业/错题本跳转带来的聚焦知识点
  const focusTag = searchParams?.get("focus") ?? null;
  const showDebugTrace = process.env.NODE_ENV === "development" && searchParams?.get("debug") === "1";

  const headers = useMemo(
    () => ({ "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) }),
    [user?.token]
  );

  // 若带 focus 知识点，拉取该点的根因诊断，用于让 agent 针对真实错因规划
  useEffect(() => {
    setRootCause(null);
    setRootCauseChecked(false);
    if (focusTag && autoStartedFocusRef.current !== focusTag) {
      setSession(null);
      setSelected(null);
      setError("");
      setStatus("正在准备针对性辅导……");
    }
    if (!focusTag || !studentId || !user?.token) {
      setRootCauseChecked(true);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `${apiBaseUrl}/api/students/${studentId}/weakpoints/${encodeURIComponent(focusTag)}/root-cause`,
          { headers }
        );
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && data && data.label) setRootCause(data as RootCauseInfo);
        }
      } catch {
        /* 根因缺失时静默降级为纯 focus 规划 */
      } finally {
        if (!cancelled) setRootCauseChecked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [focusTag, studentId, user?.token, headers]);

  const start = useCallback(async () => {
    if (!studentId || loading) return;
    setLoading(true);
    setError("");
    setSelected(null);
    setStatus("正在读取你的画像与错题本，准备本节课……");
    try {
      const body: Record<string, unknown> = { student_id: studentId };
      if (focusTag) body.focus_tags = [focusTag];
      if (rootCause?.label) body.focus_reason = `${rootCause.label}：${rootCause.description}`;
      const res = await fetch(`${apiBaseUrl}/api/autotutor/start`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`启动失败：${res.status}`);
      const data = (await res.json()) as SessionState;
      setSession(data);
      setStatus(data.status === "needs_content" ? "当前内容需要补充" : data.current_question ? "请作答当前题目" : "本节课已完成");
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
      setStatus("启动失败");
    } finally {
      setLoading(false);
    }
  }, [studentId, loading, headers, focusTag, rootCause]);

  // 从错题库/学习路径带 focus 进入时，自动开始本节针对性辅导，避免用户二次点击。
  useEffect(() => {
    if (!focusTag || !studentId || session || loading || !rootCauseChecked) return;
    if (autoStartedFocusRef.current === focusTag) return;
    autoStartedFocusRef.current = focusTag;
    void start();
  }, [focusTag, studentId, session, loading, rootCauseChecked, start]);

  async function answer(letter: string) {
    if (!session || loading || session.status !== "awaiting_answer") return;
    setSelected(letter);
    setLoading(true);
    setError("");
    setStatus("正在检查答案……");
    try {
      const res = await fetch(`${apiBaseUrl}/api/autotutor/answer`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          session_id: session.session_id,
          answer: letter,
          student_id: studentId,
          expected_revision: session.revision,
        }),
      });
      if (!res.ok) throw new Error(`提交失败：${res.status}`);
      const data = (await res.json()) as SessionState;
      setSession(data);
      setSelected(null);
      if (data.stale_answer_ignored) setStatus("已同步最新辅导进度");
      else if (data.status === "needs_content") setStatus("当前内容需要补充，不会改变掌握记录");
      else if (data.status === "completed") setStatus(data.mastery?.status === "verified" ? "本节课已完成，掌握已验证" : "本节课已完成，掌握尚未验证");
      else if (data.phase === "exit_ticket") setStatus("进入退出票检验，请完成最后一题证明掌握");
      else if (data.reflection) setStatus("已根据你的作答调整讲解，请再试一次");
      else setStatus(data.last_answer_correct ? "练习答对了，继续完成独立检验" : "已根据你的选择调整讲解");
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
      setStatus("提交失败");
      setSelected(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    traceRef.current?.scrollTo({ top: traceRef.current.scrollHeight, behavior: "smooth" });
  }, [session?.runtime_steps.length]);

  useEffect(() => {
    if (!studentId || !user?.token || focusTag || session || loading || restored) return;
    let cancelled = false;
    setRestored(true);
    (async () => {
      try {
        const res = await fetch(`${apiBaseUrl}/api/autotutor/student/${studentId}/latest-session`, { headers });
        if (!res.ok) return;
        const data = (await res.json()) as SessionState;
        if (cancelled) return;
        setSession(data);
        setStatus(data.status === "completed" ? "已恢复最近一节已完成课程" : data.status === "needs_content" ? "已恢复等待补充内容的课程" : "已恢复最近一节未完成课程");
      } catch {
        /* 无可恢复会话时静默跳过 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studentId, user?.token, focusTag, session, loading, restored, headers]);

  const plan = session?.lesson_plan ?? [];
  const q = session?.current_question ?? null;
  const lastReflection = session?.reflection ?? null;
  const orderedSteps = (session?.runtime_steps ?? []).slice().sort((a, b) => a.sequence - b.sequence);

  return (
    <main className="academy-shell">
      <section className="academy-hero">
        <div className="hero-copy">
          <div className="eyebrow">Autonomous Tutor</div>
          <h1>AutoTutor 自主辅导</h1>
          <p>
            根据你的薄弱点安排少量学习目标，先讲清再练习；答错后会结合具体选项换一种讲法。
            只有通过不同于练习题的课末检验，才会更新已验证掌握记录。
          </p>
          {session && (
            <div className="hero-flow" aria-label="AutoTutor 闭环">
              <span>读学情</span>
              <span>规划</span>
              <span>讲解</span>
              <span>出题检验</span>
              <span>错因反馈</span>
              <span>退出票检验</span>
              <span>证据入库</span>
            </div>
          )}
        </div>        <div className="teaching-card" aria-label="辅导状态">
          <div className="seal-mark" aria-hidden="true">辅</div>
          <span className="card-label">辅导台状态</span>
          <strong>{status}</strong>
          <p>
            {session
              ? `本节聚焦 ${plan.length} 个学习目标 · 调整讲解 ${session.replans} 次`
              : "还没有进行中的课程。"}
          </p>
          {session && session.status === "awaiting_answer" && (
            <p style={{ fontSize: 12, color: "var(--jade-dark,#2f6f4f)", margin: "4px 0 0" }}>
              已自动恢复最近一节未完成课程，可继续作答当前题目。
            </p>
          )}
        </div>
      </section>

      {!session ? (
        <section className="autotutor-launch" aria-label="开始辅导">
          <span className="autotutor-launch-seal" aria-hidden="true">辅</span>
          <h2>{loading ? "正在准备本节课…" : "开始一节针对性辅导课"}</h2>
          <p>
            {loading
              ? "正在读取你的画像和错题本，安排知识点顺序与难度。"
              : "开始后，系统会根据你的画像和错题本安排学习目标、出题检验，并结合你的作答调整讲解。"}
          </p>
          {focusTag && !loading && (
            <p className="autotutor-launch-focus">将优先讲解你的薄弱知识点「{focusTag}」</p>
          )}
          {focusTag && rootCause && !loading && (
            <p className="autotutor-launch-cause">
              {rootCause.icon} 错因诊断：{rootCause.label} — {rootCause.description} 后续讲解会据此调整。
            </p>
          )}
          <button
            type="button"
            className="autotutor-launch-btn"
            onClick={() => void start()}
            disabled={loading || !studentId}
          >
            {loading ? "规划中…" : "开始本节课"}
          </button>
          {error && <p className="learning-error">{error}</p>}
          <ol className="autotutor-launch-steps" aria-label="开始后会发生什么">
            <li><strong>读学情</strong><span>翻你的画像与错题本</span></li>
            <li><strong>规划</strong><span>排知识点顺序和难度</span></li>
            <li><strong>先讲解</strong><span>结合史料讲清关键点</span></li>
            <li><strong>出题检验</strong><span>每讲一点就检验一次</span></li>
            <li><strong>错因反馈</strong><span>结合具体选项说明误区、改讲法</span></li>
            <li><strong>退出票</strong><span>课末验收本节掌握度</span></li>
            <li><strong>证据入库</strong><span>写回错题、复习与教师端</span></li>
          </ol>
        </section>
      ) : (
      <section className={`learning-command-grid${showDebugTrace ? "" : " student-focused"}`}>
        {/* 左：课程计划 */}
        <aside className="panel learning-control-panel">
          <div className="panel-kicker">Lesson Plan</div>
          <h2>本节课计划</h2>
          {!plan.length && <p style={{ fontSize: 13, color: "var(--muted)" }}>开始后，这里会展示本节课的学习目标。</p>}
          <ol className="autotutor-plan">
            {plan.map((step, i) => (
              <li
                key={`${step.knowledge_point}-${i}`}
                className={`autotutor-plan-step status-${step.status}${i === session?.current_step_index ? " current" : ""}`}
                style={{
                  border: "1px solid var(--line, #e2ded3)",
                  borderRadius: 10,
                  padding: "8px 10px",
                  marginBottom: 8,
                  background: i === session?.current_step_index ? "rgba(47,111,79,0.06)" : undefined,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <strong style={{ fontSize: "0.92rem" }}>{i + 1}. {step.knowledge_point}</strong>
                  <span style={{ fontSize: "0.7rem", color: step.status === "mastered" ? "#2f6f4f" : step.status === "struggling" || step.status === "content_blocked" ? "#b8004d" : "var(--muted)" }}>
                    {stepStatusLabel[step.status]}
                  </span>
                </div>
                <div className="learning-runtime-chips" style={{ marginTop: 4 }}>
                  <small>{difficultyLabel[step.difficulty] || step.difficulty}</small>
                  {step.replanned && <small style={{ color: "#b87a00" }}>已调整讲解</small>}
                  {step.attempts > 0 && <small>尝试 {step.attempts} 次</small>}
                </div>
              </li>
            ))}
          </ol>
        </aside>

        {/* 中：当前题 / 反思 / 小结 */}
        <section className="panel learning-dialog-panel" aria-label="辅导对话">
          {session?.status === "completed" ? (
            <div className="autotutor-summary" style={{ padding: 8 }}>
              <h2>本节课小结</h2>
              <p style={{ marginTop: 8 }}>{session.summary}</p>
              {session.exit_ticket_result && (
                <div style={{ border: "1px solid #d8c8f0", background: "rgba(122,75,176,0.06)", borderRadius: 12, padding: "12px 14px", marginTop: 12 }}>
                  <strong style={{ color: session.exit_ticket_result.is_correct ? "#2f6f4f" : "#b8004d" }}>
                    退出票{session.exit_ticket_result.is_correct ? "通过" : "未通过"}：{session.exit_ticket_result.knowledge_point}
                  </strong>
                  <p style={{ margin: "6px 0", fontSize: "0.86rem" }}>
                    你的答案 {session.exit_ticket_result.selected_answer || "—"}；正确答案 {session.exit_ticket_result.correct_answer}。
                    {session.exit_ticket_result.explanation ? ` ${session.exit_ticket_result.explanation}` : ""}
                  </p>
                  {session.evidence && (
                    <div className="learning-runtime-chips">
                      <small>{session.evidence.exit_ticket_recorded ? "学习事件已记录" : "学习事件未记录"}</small>
                      <small>{session.evidence.weakpoint_action === "verified_correct_evidence_recorded" ? "已写入验证掌握" : session.evidence.weakpoint_action === "weakpoint_recorded" ? "已回流错题本" : "未改变掌握记录"}</small>
                      <small>{session.evidence.tutor_effectiveness_ready ? "教师端可见" : "等待同步"}</small>
                    </div>
                  )}
                </div>
              )}
              <div className="learning-suggestion-row" style={{ marginTop: 16 }}>
                <Link href="/student/review" className="learning-tool-action">去今日复习</Link>
                <Link href="/student/memory" className="learning-tool-action">查看记忆中心</Link>
                <button type="button" onClick={() => void start()} disabled={loading}>再上一节</button>
              </div>
            </div>
          ) : session?.status === "needs_content" && session.content_blocked ? (
            <div className="autotutor-summary" style={{ padding: 16 }} role="status">
              <div style={{ border: "1px solid #e6b9a9", background: "rgba(184,72,32,0.06)", borderRadius: 12, padding: "14px 16px" }}>
                <strong style={{ color: "#9f3f25" }}>这个学习目标暂时不能安全出题</strong>
                <h2 style={{ margin: "8px 0" }}>{session.content_blocked.objective_label}</h2>
                <p style={{ lineHeight: 1.7 }}>{session.content_blocked.message}</p>
              </div>
              <div className="learning-suggestion-row" style={{ marginTop: 16 }}>
                <Link href={`/student/assistant?prompt=${encodeURIComponent(`我想继续了解${session.content_blocked.objective_label}，请先说明现有教材能支持哪些内容。`)}`}>进入随问继续提问</Link>
                <Link href="/student/review">换一个复习目标</Link>
              </div>
            </div>
          ) : q ? (
            <div className="autotutor-question" style={{ padding: 8 }}>
              <div className="learning-message-meta">
                <span>{q.kind === "exit_ticket" ? "退出票检验" : `第 ${q.step_index + 1} 题`} · {q.knowledge_point}</span>
                <em>{difficultyLabel[q.difficulty] || q.difficulty}{q.replanned ? " · 调整后" : ""}</em>
              </div>
              {q.objective && (
                <div style={{ borderLeft: "3px solid var(--jade-dark,#2f6f4f)", paddingLeft: 10, margin: "10px 0" }}>
                  <strong>本题学习目标</strong>
                  <p style={{ margin: "4px 0 0", fontSize: "0.86rem" }}>{q.objective.label}</p>
                  {q.evidence_label && <small style={{ color: "var(--muted)" }}>{q.evidence_label}</small>}
                </div>
              )}
              {session.answer_feedback && (
                <div style={{ border: `1px solid ${session.answer_feedback.is_correct ? "#b9d8ca" : "#f0c8d8"}`, background: session.answer_feedback.is_correct ? "rgba(47,111,79,0.05)" : "rgba(184,0,77,0.05)", borderRadius: 10, padding: "10px 12px", margin: "10px 0" }} role="status">
                  <strong style={{ color: session.answer_feedback.is_correct ? "#2f6f4f" : "#b8004d" }}>
                    {session.answer_feedback.is_correct ? "练习答对" : "看看这一步为什么容易混淆"}
                  </strong>
                  <p style={{ margin: "5px 0" }}>{session.answer_feedback.message}</p>
                  {!session.answer_feedback.is_correct && <p style={{ margin: 0, fontSize: "0.85rem" }}>更正：{session.answer_feedback.correction}</p>}
                  {session.mastery && <small style={{ color: "var(--muted)" }}>{session.mastery.status === "verified" ? "已验证掌握" : "掌握尚未验证"}</small>}
                </div>
              )}
              {q.kind === "exit_ticket" && (
                <div style={{ border: "1px solid #d8c8f0", background: "rgba(122,75,176,0.06)", borderRadius: 10, padding: "10px 12px", margin: "10px 0" }}>
                  <strong style={{ color: "#7a4bb0" }}>退出票检验</strong>
                  <p style={{ margin: "6px 0 0", fontSize: "0.85rem" }}>这是本节课的最后一题，用于确认辅导是否真正生效；结果会写入复习计划与教师端学习证据。</p>
                </div>
              )}
              {lastReflection && (
                <div
                  className="autotutor-reflection"
                  style={{ border: "1px solid #f0c8d8", background: "rgba(184,0,77,0.05)", borderRadius: 10, padding: "10px 12px", margin: "10px 0" }}
                >
                  <strong style={{ color: "#b8004d" }}>根据本次作答调整讲解</strong>
                  <p style={{ margin: "6px 0 2px", fontSize: "0.85rem" }}><b>容易混淆的地方：</b>{lastReflection.diagnosis}</p>
                  <p style={{ margin: "2px 0", fontSize: "0.85rem" }}><b>调整：</b>{adjustmentLabel[lastReflection.adjustment] || lastReflection.adjustment}</p>
                  <p style={{ margin: "2px 0 0", fontSize: "0.85rem" }}>{lastReflection.explanation}</p>
                </div>
              )}
              {q.kind !== "exit_ticket" && q.teaching && (
                <div style={{ border: "1px solid var(--line, #e2ded3)", background: "rgba(47,111,79,0.05)", borderRadius: 10, padding: "12px 14px", margin: "10px 0 14px" }}>
                  <strong style={{ color: "var(--jade-dark,#2f6f4f)" }}>{q.replanned ? "换一种讲法" : "先理解，再作答"}</strong>
                  <p style={{ margin: "7px 0", lineHeight: 1.7 }}>{q.teaching.explanation}</p>
                  {!!q.teaching.key_points?.length && (
                    <div className="learning-runtime-chips">
                      {q.teaching.key_points.map((point) => <small key={point}>{point}</small>)}
                    </div>
                  )}
                  {q.teaching.example && <p style={{ margin: "8px 0 0", fontSize: "0.84rem", color: "var(--muted)" }}>例子：{q.teaching.example}</p>}
                  <div className="learning-suggestion-row" style={{ marginTop: 10 }}>
                    <Link href={`/student/assistant?autotutor_session_id=${encodeURIComponent(session.session_id)}`}>我有疑问</Link>
                    <Link href={`/student/assistant?autotutor_session_id=${encodeURIComponent(session.session_id)}&prompt=${encodeURIComponent("请结合当前知识点换一个生活化例子解释。")}`}>换个例子</Link>
                    <Link href={`/student/assistant?autotutor_session_id=${encodeURIComponent(session.session_id)}&prompt=${encodeURIComponent("请把当前讲解改成更简单的说法。")}`}>讲简单一点</Link>
                  </div>
                </div>
              )}
              <p className="quiz-question-text" style={{ fontSize: "1rem", margin: "10px 0" }}>{q.question}</p>
              <ul className="quiz-options">
                {q.options.map((opt, i) => {
                  const letter = String.fromCharCode(65 + i);
                  return (
                    <li key={i}>
                      <button
                        type="button"
                        className={`quiz-option-btn ${selected === letter ? "selected" : ""}`}
                        onClick={() => void answer(letter)}
                        disabled={loading}
                      >
                        {opt}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
              <p>{loading ? "正在准备本节课……" : "点击右上角「开始本节课」，生成针对性学习目标。"}</p>
            </div>
          )}
          {error && <p className="learning-error">{error}</p>}
        </section>

        {/* 右：运行时轨迹 */}
        {showDebugTrace && <aside className="panel learning-observation-panel" aria-label="开发调试轨迹">
          <div className="panel-kicker">Agent Trace</div>
          <h2>规划 / 反思轨迹</h2>
          {session?.trace_id && <p className="learning-trace-id">Trace: {session.trace_id}</p>}
          <div className="learning-runtime-list" ref={traceRef} style={{ maxHeight: 420, overflowY: "auto" }}>
            {orderedSteps.map((step) => {
              const meta = step.metadata || {};
              const summary = (meta.result_summary as string) || step.error?.message || "";
              return (
                <div className={`learning-runtime-step ${step.status}`} key={step.step_id}>
                  <div className="learning-runtime-step-head">
                    <span style={{ color: eventTone(step.event_type) }}>
                      {step.sequence}. {step.step_name}
                    </span>
                    <strong>{runtimeStatusLabel[step.status] || step.status.replace("_", " ")}</strong>
                  </div>
                  {step.latency_ms != null && <em>{step.latency_ms}ms</em>}
                  {summary && <p className="learning-runtime-summary">{summary}</p>}
                  {(step.event_type === "reflect" || step.event_type === "re_plan") && (
                    <div className="learning-runtime-chips">
                      {meta.diagnosis != null && <small>诊断: {formatMeta(meta.diagnosis)}</small>}
                      {meta.adjustment != null && <small>调整: {adjustmentLabel[String(meta.adjustment)] || formatMeta(meta.adjustment)}</small>}
                      {meta.plan_changes != null && <small>计划变更: {formatMeta(meta.plan_changes)}</small>}
                    </div>
                  )}
                  {step.event_type === "plan" && meta.targeted_points != null && (
                    <div className="learning-runtime-chips"><small>目标: {formatMeta(meta.targeted_points)}</small></div>
                  )}
                </div>
              );
            })}
            {!orderedSteps.length && (
              <p style={{ fontSize: 12, color: "var(--muted)" }}>开始后，这里会实时展示 plan → act → reflect → re_plan → finalize 每一步。</p>
            )}
          </div>
          {session?.trace_id && <TraceTimeline traceId={session.trace_id} token={user?.token} />}
        </aside>}
      </section>
      )}
    </main>
  );
}

export default function AutoTutorPage() {
  return (
    <Suspense fallback={null}>
      <AutoTutorInner />
    </Suspense>
  );
}
