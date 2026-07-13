"use client";

import { useCallback, useEffect, useMemo, useRef, useState, Suspense } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import { TraceTimeline } from "@/components/TraceTimeline";
import { useSearchParams } from "next/navigation";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type PlanStep = {
  knowledge_point: string;
  source_tag?: string | null;
  difficulty: string;
  strategy: string;
  rationale: string;
  status: "pending" | "active" | "mastered" | "struggling";
  attempts: number;
  replanned: boolean;
};
type CurrentQuestion = {
  knowledge_point: string;
  difficulty: string;
  strategy: string;
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
type SessionState = {
  session_id: string;
  trace_id: string;
  student_id: string;
  grade?: string | null;
  status: "awaiting_answer" | "completed";
  lesson_plan: PlanStep[];
  current_step_index: number;
  current_question: CurrentQuestion | null;
  reflect_log: Reflection[];
  replans: number;
  summary?: string | null;
  runtime_steps: RuntimeStep[];
  reflection?: Reflection;
  last_answer_correct?: boolean;
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
  mastered: "已掌握",
  struggling: "仍薄弱",
};

const runtimeStatusLabel: Record<string, string> = {
  success: "成功",
  failed: "失败",
  degraded: "降级",
  waiting_answer: "等待作答",
};

function eventTone(eventType: string): string {
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
    setStatus("Agent 正在读取你的画像与错题本，规划本节课……");
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
      setStatus(data.current_question ? "请作答当前题目" : "本节课已完成");
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
    setStatus("Agent 正在判分……");
    try {
      const res = await fetch(`${apiBaseUrl}/api/autotutor/answer`, {
        method: "POST",
        headers,
        body: JSON.stringify({ session_id: session.session_id, answer: letter, student_id: studentId }),
      });
      if (!res.ok) throw new Error(`提交失败：${res.status}`);
      const data = (await res.json()) as SessionState;
      setSession(data);
      setSelected(null);
      if (data.status === "completed") setStatus("本节课已完成 🎉");
      else if (data.reflection) setStatus("Agent 反思后调整了计划，请再试一次");
      else setStatus(data.last_answer_correct ? "答对了，进入下一个知识点" : "请作答当前题目");
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
        setStatus(data.status === "completed" ? "已恢复最近一节已完成课程" : "已恢复最近一节未完成课程");
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
            Agent 自己读你的画像和错题本、规划本节课、出题检验；答错时会反思「是讲得不对还是题超纲」并实时调整计划。
            全程的规划与反思都在右侧轨迹里可见。
          </p>
          <div className="hero-flow" aria-label="AutoTutor 闭环">
            <span>读学情</span>
            <span>规划</span>
            <span>出题检验</span>
            <span>反思重规划</span>
            <span>课后复习</span>
          </div>
        </div>
        <div className="teaching-card" aria-label="辅导状态">
          <div className="seal-mark" aria-hidden="true">辅</div>
          <span className="card-label">辅导台状态</span>
          <strong>{status}</strong>
          <p>
            {session
              ? `已规划 ${plan.length} 个知识点 · 触发 ${session.replans} 次重规划`
              : "点击下方按钮，让 agent 现场为你规划一节课。"}
          </p>
          {session && session.status === "awaiting_answer" && (
            <p style={{ fontSize: 12, color: "var(--jade-dark,#2f6f4f)", margin: "4px 0 0" }}>
              已自动恢复最近一节未完成课程，可继续作答当前题目。
            </p>
          )}
          {!session && (
            <>
              {focusTag && (
                <p style={{ fontSize: 12, color: "var(--jade-dark,#2f6f4f)", margin: "4px 0 8px" }}>
                  将优先讲解你的薄弱知识点「{focusTag}」
                </p>
              )}
              {focusTag && rootCause && (
                <p style={{ fontSize: 12, color: "#b87a00", margin: "0 0 8px", lineHeight: 1.5 }}>
                  {rootCause.icon} 错因诊断：{rootCause.label} — {rootCause.description} agent 会据此调整讲法。
                </p>
              )}
              <button type="button" className="learning-tool-action" onClick={() => void start()} disabled={loading || !studentId}>
                {loading ? "规划中…" : "开始本节课"}
              </button>
            </>
          )}
        </div>
      </section>

      <section className="learning-command-grid">
        {/* 左：课程计划 */}
        <aside className="panel learning-control-panel">
          <div className="panel-kicker">Lesson Plan</div>
          <h2>本节课计划</h2>
          {!plan.length && <p style={{ fontSize: 13, color: "var(--muted)" }}>开始后，这里会展示 agent 自主生成的教学计划。</p>}
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
                  <span style={{ fontSize: "0.7rem", color: step.status === "mastered" ? "#2f6f4f" : step.status === "struggling" ? "#b8004d" : "var(--muted)" }}>
                    {stepStatusLabel[step.status]}
                  </span>
                </div>
                <div className="learning-runtime-chips" style={{ marginTop: 4 }}>
                  <small>{difficultyLabel[step.difficulty] || step.difficulty}</small>
                  {step.replanned && <small style={{ color: "#b87a00" }}>已重规划</small>}
                  {step.attempts > 0 && <small>尝试 {step.attempts} 次</small>}
                </div>
                {step.rationale && <p style={{ fontSize: "0.76rem", color: "var(--muted)", margin: "4px 0 0" }}>{step.rationale}</p>}
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
              <div className="learning-suggestion-row" style={{ marginTop: 16 }}>
                <a href="/student/review" className="learning-tool-action">去今日复习</a>
                <a href="/student/memory" className="learning-tool-action">查看记忆中心</a>
                <button type="button" onClick={() => void start()} disabled={loading}>再上一节</button>
              </div>
            </div>
          ) : q ? (
            <div className="autotutor-question" style={{ padding: 8 }}>
              <div className="learning-message-meta">
                <span>第 {q.step_index + 1} 题 · {q.knowledge_point}</span>
                <em>{difficultyLabel[q.difficulty] || q.difficulty}{q.replanned ? " · 调整后" : ""}</em>
              </div>
              {lastReflection && (
                <div
                  className="autotutor-reflection"
                  style={{ border: "1px solid #f0c8d8", background: "rgba(184,0,77,0.05)", borderRadius: 10, padding: "10px 12px", margin: "10px 0" }}
                >
                  <strong style={{ color: "#b8004d" }}>🤔 Agent 反思并调整了计划</strong>
                  <p style={{ margin: "6px 0 2px", fontSize: "0.85rem" }}><b>诊断：</b>{lastReflection.diagnosis}</p>
                  <p style={{ margin: "2px 0", fontSize: "0.85rem" }}><b>调整：</b>{adjustmentLabel[lastReflection.adjustment] || lastReflection.adjustment}</p>
                  <p style={{ margin: "2px 0 0", fontSize: "0.85rem" }}>{lastReflection.explanation}</p>
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
              {q.strategy && <p style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: 8 }}>教学策略：{q.strategy}</p>}
            </div>
          ) : (
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
              <p>{loading ? "Agent 正在规划本节课……" : "点击右上角「开始本节课」，让 agent 为你现场规划。"}</p>
            </div>
          )}
          {error && <p className="learning-error">{error}</p>}
        </section>

        {/* 右：运行时轨迹 */}
        <aside className="panel learning-observation-panel" aria-label="运行时轨迹">
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
        </aside>
      </section>
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
