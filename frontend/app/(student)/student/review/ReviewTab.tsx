"use client";
import Link from "next/link";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import { normalizeError } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Task = {
  task_index?: number;
  tag: string; question: string; options: string[];
  answer?: string; explanation?: string; selected_feedback?: string;
  done: boolean; correct: boolean | null;
  material?: string | null;
  material_timing?: "before_answer" | "after_answer";
  difficulty?: "easy" | "medium" | "hard";
  cognitive_action?: "recall" | "explain" | "compare" | "apply";
  lesson_label?: string; source_label?: string;
  adaptive_message?: string;
  quality_status?: "verified" | "blocked";
  blocked_message?: string;
  is_variant?: boolean;
  pending_generate?: boolean;
  task_role?: "retrieval" | "verification" | "retention";
  phase?: "answering" | "awaiting_feedback" | "answered";
  feedback_acknowledged?: boolean;
};
type Session = {
  date: string; completed: number; total: number; tasks: Task[];
  blocked_count?: number; blocked_tags?: string[];
  session_revision: number;
  scheduled_reviews?: Array<{ knowledge_tag: string; available_at: string; message: string }>;
};

/** 后端出题失败时会留下无法作答的占位题，前端不能把它当正常题呈现。 */
function isUnusableTask(task: Task): boolean {
  if (task.pending_generate || task.quality_status === "blocked") return true;
  if (!task.options || task.options.length !== 4) return true;
  if (task.options.some(o => !o?.trim())) return true;
  return !task.question?.trim();
}

const CSS = `
.rv { font-family:var(--font-body-family); background:transparent; color:var(--ink); }
.rv-load { display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;gap:20px; }
.rv-load-char { font-family:var(--font-display-family);font-size:56px;color:var(--cinnabar);line-height:1;animation:rvPulse 2s ease-in-out infinite;filter:drop-shadow(0 0 16px rgba(183,66,43,.35)); }
@keyframes rvPulse { 0%,100%{opacity:.25;transform:scale(.88)} 50%{opacity:1;transform:scale(1.04)} }
.rv-load-dots { display:flex;gap:5px; }
.rv-load-dot { width:4px;height:4px;border-radius:50%;background:var(--cinnabar);animation:rvBounce 1.4s ease-in-out infinite; }
.rv-load-dot:nth-child(2){animation-delay:.18s} .rv-load-dot:nth-child(3){animation-delay:.36s}
@keyframes rvBounce { 0%,60%,100%{transform:translateY(0);opacity:.25} 30%{transform:translateY(-7px);opacity:1} }
.rv-load-txt { font-size:11px;color:var(--muted);letter-spacing:.22em; }
.rv-inner { max-width:640px;margin:0 auto;padding:32px 24px 80px; }
.rv-head { display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px; }
.rv-eyebrow { font-size:10px;letter-spacing:.28em;color:var(--cinnabar);display:flex;align-items:center;gap:8px;margin-bottom:6px; }
.rv-eyebrow::before { content:'';width:18px;height:1px;background:var(--cinnabar);flex-shrink:0; }
.rv-h1 { font-size:22px;font-weight:700;letter-spacing:.08em;color:var(--ink);margin:0 0 5px; }
.rv-date { font-size:11px;color:var(--muted);letter-spacing:.14em; }
.rv-counter { text-align:right;padding:10px 16px;border:1px solid rgba(183,66,43,.2);border-radius:3px;background:rgba(183,66,43,.05); }
.rv-cn { font-size:30px;font-weight:700;color:var(--cinnabar);line-height:1;font-feature-settings:'tnum'; }
.rv-cs,.rv-ct { font-size:14px;color:var(--ink-soft); }
.rv-cl { font-size:10px;color:var(--muted);letter-spacing:.12em;margin-top:3px; }
.rv-rail { display:flex;gap:4px;margin-bottom:28px; }
.rv-seg { height:3px;flex:1;border-radius:2px;background:var(--border);transition:background .4s,box-shadow .4s; }
.rv-seg.cur { background:var(--cinnabar);box-shadow:0 0 10px rgba(183,66,43,.45); }
.rv-seg.ok  { background:var(--gold); }
.rv-seg.bad { background:rgba(183,66,43,.28); }
.rv-card { background:var(--paper-soft);border:1px solid var(--border);border-radius:4px;padding:28px 28px 24px;position:relative;overflow:hidden;box-shadow:var(--shadow-md),inset 0 1px 0 rgba(255,255,255,.6);animation:rvCardIn .4s cubic-bezier(.2,.8,.4,1); }
@keyframes rvCardIn { from{opacity:0;transform:translateY(14px) scale(.985)} to{opacity:1;transform:none} }
.rv-corner { position:absolute;width:16px;height:16px;border-color:rgba(183,66,43,.2);border-style:solid; }
.rv-corner.tl { top:10px;left:10px;border-width:1px 0 0 1px; }
.rv-corner.br { bottom:10px;right:10px;border-width:0 1px 1px 0; }
.rv-wm { position:absolute;right:-8px;bottom:-24px;font-family:var(--font-display-family);font-size:128px;line-height:1;color:rgba(96,72,44,.06);pointer-events:none;user-select:none; }
.rv-tagrow { display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;gap:8px; }
.rv-tag-group { display:flex;align-items:center;gap:6px;flex-wrap:wrap; }
.rv-tag { display:inline-flex;align-items:center;gap:5px;padding:3px 12px;border:1px solid rgba(183,66,43,.25);border-radius:2px;background:rgba(183,66,43,.06);color:var(--cinnabar);font-size:11px;letter-spacing:.14em; }
.rv-tag::before { content:'◆';font-size:7px; }
.rv-variant-badge { display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border:1px solid rgba(88,128,72,.35);border-radius:2px;background:rgba(88,128,72,.07);color:#4a7a3c;font-size:10px;letter-spacing:.1em; }
.rv-variant-badge::before { content:'∿';font-size:11px; }
.rv-level-badge { display:inline-flex;align-items:center;padding:2px 8px;border:1px solid rgba(96,72,44,.2);border-radius:2px;background:rgba(96,72,44,.04);color:var(--ink-soft);font-size:10px;letter-spacing:.08em; }
.rv-qmeta { font-size:11px;color:var(--muted);letter-spacing:.1em;flex-shrink:0; }
.rv-adaptive { margin:-8px 0 16px;padding:8px 11px;border-left:2px solid rgba(88,128,72,.48);background:rgba(88,128,72,.055);color:#47673e;font-size:11px;line-height:1.65;letter-spacing:.03em; }
.rv-material { margin:0 0 16px;padding:13px 15px;border:1px solid rgba(96,72,44,.16);border-radius:3px;background:rgba(96,72,44,.035);color:var(--ink-soft);font-size:13px;line-height:1.8;letter-spacing:.025em;position:relative;z-index:1; }
.rv-material::before { content:'对照材料';display:block;color:var(--cinnabar);font-size:10px;font-weight:700;letter-spacing:.18em;margin-bottom:5px; }
.rv-q { font-size:16px;font-weight:600;line-height:1.9;color:var(--ink);margin-bottom:22px;letter-spacing:.03em;position:relative;z-index:1; }
.rv-opts { display:flex;flex-direction:column;gap:9px; }
.rv-opt { display:flex;align-items:center;gap:14px;padding:12px 16px;border:1px solid var(--border);border-radius:3px;background:var(--paper);cursor:pointer;text-align:left;width:100%;color:var(--ink-soft);font-size:14px;letter-spacing:.02em;font-family:var(--font-body-family);transition:border-color .18s,background .18s,color .18s; }
.rv-opt:not(:disabled):hover { border-color:var(--border-strong);background:var(--paper-strong);color:var(--ink); }
.rv-circle { width:26px;height:26px;border-radius:50%;border:1px solid currentColor;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;opacity:.55;transition:all .18s; }
.rv-opt.sel   { border-color:var(--cinnabar);background:rgba(183,66,43,.06);color:var(--ink); }
.rv-opt.sel .rv-circle { opacity:1;background:var(--cinnabar);border-color:var(--cinnabar);color:#fff; }
.rv-opt.ok    { border-color:var(--gold);background:rgba(184,139,62,.07);color:var(--gold); }
.rv-opt.ok .rv-circle  { opacity:1;background:var(--gold);border-color:var(--gold);color:#fff; }
.rv-opt.bad   { border-color:rgba(183,66,43,.3);background:rgba(183,66,43,.05);color:var(--cinnabar-dark); }
.rv-opt.bad .rv-circle { opacity:.7;border-color:rgba(183,66,43,.4);color:var(--cinnabar-dark); }
.rv-expl { margin-top:18px;padding:14px 18px;border-radius:3px;background:rgba(184,139,62,.05);border-left:2px solid var(--gold);font-size:13px;color:var(--ink-soft);line-height:1.9;letter-spacing:.02em;animation:rvFade .3s ease; }
.rv-expl-lbl { color:var(--gold);font-weight:600;margin-right:8px;letter-spacing:.12em; }
@keyframes rvFade { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }
.rv-actions { margin-top:22px;display:flex;justify-content:flex-end; }
.rv-btn { padding:9px 30px;border-radius:3px;font-size:13px;font-weight:600;letter-spacing:.1em;cursor:pointer;font-family:var(--font-body-family);transition:all .18s; }
.rv-btn-outline { background:transparent;border:1px solid var(--cinnabar);color:var(--cinnabar); }
.rv-btn-outline:hover:not(:disabled) { background:var(--cinnabar);color:#fff; }
.rv-btn-outline:disabled { border-color:var(--border);color:var(--muted);cursor:default; }
.rv-btn-fill { background:var(--cinnabar);border:1px solid var(--cinnabar);color:#fff; }
.rv-btn-fill:hover { background:var(--cinnabar-dark); }
.rv-sum { text-align:center;padding:40px 28px;animation:rvCardIn .5s cubic-bezier(.2,.8,.4,1); }
.rv-seal { width:88px;height:88px;border:2px solid var(--gold);border-radius:6px;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;background:rgba(184,139,62,.06);font-family:var(--font-display-family);font-size:46px;color:var(--gold);animation:rvStamp .65s cubic-bezier(.36,.07,.19,.97); }
@keyframes rvStamp { 0%{transform:scale(2) rotate(-9deg);opacity:0} 60%{transform:scale(.9) rotate(2deg);opacity:1} 100%{transform:scale(1) rotate(0)} }
.rv-sum-title { font-size:18px;font-weight:700;letter-spacing:.1em;color:var(--ink); }
.rv-sum-score { font-size:54px;font-weight:700;color:var(--gold);line-height:1.1;margin:12px 0 0; }
.rv-sum-denom { font-size:20px;color:var(--ink-soft); }
.rv-sum-stat  { font-size:12px;color:var(--muted);letter-spacing:.12em;margin-top:6px; }
.rv-divider   { height:1px;background:linear-gradient(to right,transparent,var(--border),transparent);margin:20px 0; }
.rv-chips { display:flex;flex-wrap:wrap;gap:8px;justify-content:center; }
.rv-chip { padding:4px 14px;border-radius:2px;font-size:12px;letter-spacing:.08em;border:1px solid;display:inline-flex;align-items:center;gap:5px; }
.rv-chip.ok  { border-color:rgba(184,139,62,.3);color:var(--gold);background:rgba(184,139,62,.05); }
.rv-chip.bad { border-color:rgba(183,66,43,.25);color:var(--cinnabar-dark);background:rgba(183,66,43,.05); }
.rv-empty { text-align:center;padding:60px 24px; }
.rv-empty-c { font-family:var(--font-display-family);font-size:64px;color:var(--muted);opacity:.4;line-height:1;margin-bottom:20px; }
.rv-empty-t { font-size:18px;font-weight:700;color:var(--ink);letter-spacing:.08em;margin-bottom:10px; }
.rv-empty-s { font-size:13px;color:var(--muted);line-height:1.9;letter-spacing:.04em; }
.rv-empty-actions { display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-top:20px; }
.rv-empty-link { border:1px solid rgba(183,66,43,.2);border-radius:999px;padding:8px 14px;color:var(--cinnabar);background:rgba(255,252,244,.72);font-size:12px;font-weight:700;text-decoration:none;letter-spacing:.08em; }
.rv-empty-link:hover { border-color:var(--cinnabar);background:rgba(183,66,43,.06); }
.rv-empty-link.btn { cursor:pointer;font-family:var(--font-body-family); }
.rv-error-text { margin:18px 0 -4px;padding:9px 12px;border-radius:3px;background:rgba(183,66,43,.06);border:1px solid rgba(183,66,43,.18);color:var(--cinnabar-dark);font-size:12px;line-height:1.7;letter-spacing:.04em; }
.rv-regen { position:relative;z-index:1;padding:14px 0 4px; }
.rv-regen-title { font-size:16px;font-weight:600;color:var(--ink);letter-spacing:.04em;margin:0 0 10px; }
.rv-regen-desc { font-size:13px;color:var(--ink-soft);line-height:1.9;letter-spacing:.02em;margin:0; }
.rv-regen-actions { display:flex;flex-wrap:wrap;gap:10px;margin-top:20px; }
`;

const WM = ["史", "文", "思", "知", "学", "悟", "道", "义"];

function InjectStyles() {
  useEffect(() => {
    const id = "rv-v4";
    if (document.getElementById(id)) return;
    const el = document.createElement("style");
    el.id = id; el.textContent = CSS;
    document.head.appendChild(el);
    return () => { document.getElementById(id)?.remove(); };
  }, []);
  return null;
}

export default function ReviewTab() {
  const { user } = useAuth();
  const studentId = user?.actorId;
  const token     = user?.token;

  const [session,    setSession]    = useState<Session | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [current,    setCurrent]    = useState(0);
  const [selected,   setSelected]   = useState<string | null>(null);
  const [revealed,   setRevealed]   = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cardKey,    setCardKey]    = useState(0);
  const [error,      setError]      = useState("");
  const [submitError,setSubmitError]= useState("");

  async function loadSession(signal?: AbortSignal) {
    if (!studentId || !token) return;
    setLoading(true);
    setError("");
    setSubmitError("");
    try {
      const res = await fetch(`${API}/api/students/${studentId}/review/today`, { headers: authHeaders(token), signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const nextSession = await res.json() as Session;
      const feedbackIndex = nextSession.tasks.findIndex(t => t.phase === "awaiting_feedback");
      const nextIndex = feedbackIndex >= 0 ? feedbackIndex : nextSession.tasks.findIndex(t => !t.done);
      setCurrent(nextIndex >= 0 ? nextIndex : Math.max(0, nextSession.tasks.length - 1));
      setSelected(null);
      setRevealed(feedbackIndex >= 0);
      setCardKey(k => k + 1);
      setSession(nextSession);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(normalizeError(e, "今日复习加载失败，请稍后重试"));
      setSession(null);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    if (!studentId || !token) return;
    const controller = new AbortController();
    void loadSession(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studentId, token]);

  async function handleSubmit() {
    if (!selected || !session || !studentId || !token || submitting) return;
    const task = session.tasks[current];
    setSubmitting(true);
    setSubmitError("");
    try {
      const res = await fetch(`${API}/api/students/${studentId}/review/submit`, {
        method: "POST",
        headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({
          task_index: task.task_index ?? current,
          selected_answer: selected.charAt(0),
          expected_revision: session.session_revision,
          idempotency_key: `review-client-${Date.now()}-${current}`,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSession(prev => prev ? {
        ...prev, completed: data.completed, total: data.total, session_revision: data.session_revision,
        scheduled_reviews: data.available_at ? [
          ...(prev.scheduled_reviews || []),
          { knowledge_tag: task.tag, available_at: data.available_at, message: data.mastery?.student_message || "明天再确认一次。" },
        ] : prev.scheduled_reviews,
        tasks: prev.tasks.map((t, i) => i === current ? { ...t, ...data.task, done: true, correct: data.is_correct } : t),
      } : prev);
      setRevealed(true);
    } catch (e) {
      setSubmitError(normalizeError(e, "提交失败，请稍后重试"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleNext() {
    if (!session) return;
    const task = session.tasks[current];
    if (task.task_role === "retrieval" && task.done && !task.feedback_acknowledged) {
      if (!studentId || !token || submitting) return;
      setSubmitting(true);
      setSubmitError("");
      try {
        const res = await fetch(`${API}/api/students/${studentId}/review/advance`, {
          method: "POST",
          headers: { ...authHeaders(token), "Content-Type": "application/json" },
          body: JSON.stringify({
            task_index: task.task_index ?? current,
            action: "continue_after_feedback",
            expected_revision: session.session_revision,
            idempotency_key: `review-feedback-${Date.now()}-${current}`,
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.phase === "content_blocked") {
          setSubmitError(data.content_blocked?.message || "当前没有合适的新验证题。");
          return;
        }
        const nextTask = { ...data.task, task_index: data.task_index } as Task;
        setSession(prev => prev ? {
          ...prev,
          total: prev.total + 1,
          session_revision: data.session_revision,
          tasks: [
            ...prev.tasks.map((item, index) => index === current
              ? { ...item, feedback_acknowledged: true, phase: "answered" as const }
              : item),
            nextTask,
          ],
        } : prev);
        setCurrent(data.task_index);
        setSelected(null);
        setRevealed(false);
        setCardKey(k => k + 1);
      } catch (e) {
        setSubmitError(normalizeError(e, "验证题加载失败，请稍后重试"));
      } finally {
        setSubmitting(false);
      }
      return;
    }
    const next = session.tasks.findIndex((t, i) => i > current && !t.done);
    if (next >= 0) { setCurrent(next); setSelected(null); setRevealed(false); setCardKey(k => k + 1); }
  }

  if (!studentId || !token) return null;

  if (loading) return (
    <div className="rv">
      <InjectStyles />
      <div className="rv-load">
        <div className="rv-load-char">习</div>
        <div className="rv-load-dots">
          <div className="rv-load-dot" /><div className="rv-load-dot" /><div className="rv-load-dot" />
        </div>
        <div className="rv-load-txt">正在生成今日复习</div>
      </div>
    </div>
  );

  if (error && !session) return (
    <div className="rv">
      <InjectStyles />
      <div className="rv-inner">
        <div className="rv-empty">
          <div className="rv-empty-c">叹</div>
          <div className="rv-empty-t">今日复习加载失败</div>
          <div className="rv-empty-s">{error}<br />可能是网络波动或登录状态过期，请稍后重试</div>
          <div className="rv-empty-actions">
            <button type="button" className="rv-empty-link btn" onClick={() => void loadSession()}>重新加载</button>
            <Link href="/student/quiz" className="rv-empty-link">做智能练习</Link>
          </div>
        </div>
      </div>
    </div>
  );

  if (!session || session.total === 0) return (
    <div className="rv">
      <InjectStyles />
      <div className="rv-inner">
        <div className="rv-empty">
          <div className="rv-empty-c">卷</div>
          <div className="rv-empty-t">{session?.blocked_count ? "暂无可发布复习题" : "暂无复习任务"}</div>
          <div className="rv-empty-s">
            {session?.blocked_count
              ? `有 ${session.blocked_count} 个薄弱点暂时缺少通过内容校验的题目，系统不会据此判断掌握情况。`
              : session?.scheduled_reviews?.length
                ? session.scheduled_reviews.map(item => `${item.knowledge_tag}：${item.message}`).join("；")
              : <>完成练习或作业批改后<br />这里会出现个性化复习内容</>}
          </div>
          <div className="rv-empty-actions">
            <Link href="/student/assignments" className="rv-empty-link">去完成作业</Link>
            <Link href="/student/quiz" className="rv-empty-link">做智能练习</Link>
          </div>
        </div>
      </div>
    </div>
  );

  const allDone = session.completed >= session.total;
  const task    = session.tasks[current];
  const needsFeedbackAdvance = Boolean(
    revealed && task?.task_role === "retrieval" && task.done && !task.feedback_acknowledged
  );
  const correct = session.tasks.filter(t => t.correct === true).length;
  const pct     = Math.round(correct / session.total * 100);

  return (
    <div className="rv">
      <InjectStyles />
      <div className="rv-inner">
        <div className="rv-head">
          <div>
            <div className="rv-eyebrow">今日复习</div>
            <h1 className="rv-h1">自适应练习</h1>
            <div className="rv-date">{session.date}</div>
          </div>
          <div className="rv-counter">
            <div>
              <span className="rv-cn">{session.completed}</span>
              <span className="rv-cs">/</span>
              <span className="rv-ct">{session.total}</span>
            </div>
            <div className="rv-cl">已完成</div>
          </div>
        </div>

        <div className="rv-rail">
          {session.tasks.map((t, i) => {
            const c = t.done ? (t.correct ? "ok" : "bad") : (i === current && !allDone ? "cur" : "");
            return <div key={i} className={`rv-seg ${c}`} />;
          })}
        </div>

        {allDone && !revealed ? (
          <div className="rv-card rv-sum">
            <div className="rv-corner tl" /><div className="rv-corner br" />
            <div className="rv-seal">{pct >= 80 ? "优" : pct >= 60 ? "良" : "继"}</div>
            <div className="rv-sum-title">今日复习完成</div>
            <div className="rv-sum-score">
              {correct}<span className="rv-sum-denom"> / {session.total}</span>
            </div>
            <div className="rv-sum-stat">正确率 {pct}%</div>
            <div className="rv-divider" />
            <div className="rv-chips">
              {session.tasks.map((t, i) => (
                <span key={i} className={`rv-chip ${t.correct ? "ok" : "bad"}`}>
                  {t.correct ? "✓" : "✗"} {t.tag}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div key={cardKey} className="rv-card">
            <div className="rv-corner tl" /><div className="rv-corner br" />
            <div className="rv-wm">{WM[current % WM.length]}</div>
            <div className="rv-tagrow">
              <div className="rv-tag-group">
                <span className="rv-tag">{task.tag}</span>
                {task.is_variant && <span className="rv-variant-badge">变式题</span>}
                {task.difficulty && (
                  <span className="rv-level-badge">
                    {task.difficulty === "easy"
                      ? "基础辨析"
                      : task.difficulty === "hard"
                        ? "综合挑战"
                        : task.material_timing === "after_answer" ? "先答后证" : "材料迁移"}
                  </span>
                )}
              </div>
              <span className="rv-qmeta">{current + 1} / {session.total}</span>
            </div>
            {isUnusableTask(task) ? (
              <div className="rv-regen">
                <p className="rv-regen-title">这道题暂不作答</p>
                <p className="rv-regen-desc">
                  {task.blocked_message || `「${task.tag}」暂时没有通过内容校验的可靠题目。`}
                  系统不会用这道题判断你的掌握情况。
                </p>
                <div className="rv-regen-actions">
                  <button type="button" className="rv-btn rv-btn-outline" onClick={() => void loadSession()}>
                    重新检查
                  </button>
                  {session.tasks.some((t, i) => i > current && !t.done) && (
                    <button type="button" className="rv-btn rv-btn-fill" onClick={handleNext}>
                      先做下一题 →
                    </button>
                  )}
                </div>
              </div>
            ) : (
            <>
            {task.adaptive_message && <div className="rv-adaptive">{task.adaptive_message}</div>}
            <div className="rv-q">{task.question}</div>
            <div className="rv-opts">
              {task.options.map((opt, i) => {
                const letter = opt.charAt(0);
                const isSel  = selected === opt;
                const isOk   = revealed && letter === task.answer?.charAt(0);
                const isBad  = revealed && isSel && !isOk;
                const cls    = isOk ? "ok" : isBad ? "bad" : isSel ? "sel" : "";
                return (
                  <button
                    key={i}
                    type="button"
                    disabled={revealed}
                    className={`rv-opt ${cls}`}
                    onClick={() => setSelected(opt)}
                    aria-pressed={isSel}
                  >
                    <span className="rv-circle">{letter}</span>
                    <span>{opt.slice(2)}</span>
                  </button>
                );
              })}
            </div>
            {revealed && task.material && <div className="rv-material">{task.material}</div>}
            {revealed && (
              <div className="rv-expl">
                <span className="rv-expl-lbl">解析</span>{task.selected_feedback || task.explanation}
              </div>
            )}
            {submitError && <p className="rv-error-text" role="alert">{submitError}</p>}
            <div className="rv-actions">
              {!revealed ? (
                <button type="button" disabled={!selected || submitting} onClick={handleSubmit} className="rv-btn rv-btn-outline">
                  {submitting ? "提交中…" : selected ? "确认答案" : "先选择一个答案"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={needsFeedbackAdvance ? () => void handleNext() : allDone ? () => setRevealed(false) : () => void handleNext()}
                  className="rv-btn rv-btn-fill"
                >
                  {submitting
                    ? "加载中…"
                    : needsFeedbackAdvance
                      ? "看完了，做一道验证题"
                      : allDone ? "查看结果" : "下一题 →"}
                </button>
              )}
            </div>
            </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
