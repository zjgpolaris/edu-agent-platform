"use client";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Question = {
  type: string;
  prompt: string;
  options?: string[] | null;
  answer?: unknown;
  knowledge_tag?: string | null;
  difficulty?: string | null;
};
type Submission = { score: number | null; status: string; submitted_at: string } | null;
type Assignment = {
  id: string;
  title: string;
  subject: string | null;
  grade: string | null;
  questions: Question[];
  due_date: string | null;
  created_at: string;
  submission: Submission;
  my_difficulty?: string | null;  // 教师设置的难度分层（easy|medium|hard）
};
type SubmitResult = {
  score: number | null;
  status: string;
  objective_correct: number;
  objective_total: number;
  has_subjective: boolean;
  wrong_tags: string[];     // 答错知识点列表，用于引导复习
  correct_tags: string[];
};

const OBJECTIVE = new Set(["single_choice", "multiple_choice", "true_false"]);

export default function StudentAssignmentsPage() {
  const { user } = useAuth();
  const [list, setList] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [active, setActive] = useState<Assignment | null>(null);
  const [answers, setAnswers] = useState<Record<number, unknown>>({});
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitWarning, setSubmitWarning] = useState<number[]>([]);

  useEffect(() => {
    if (user?.role === "student" && user.actorId) load(user.actorId, user.token);
    else if (user) { setError("请以学生身份登录"); setLoading(false); }
  }, [user]);

  async function load(id: string, token: string | undefined) {
    setLoading(true); setError("");
    try {
      const res = await fetch(`${API}/api/student/${id}/assignments`, { headers: token ? authHeaders(token) : {} });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setList(data.assignments || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally { setLoading(false); }
  }

  function openAssignment(a: Assignment) {
    // 若有难度分层，异步拉取过滤后的题目，再展示
    if (a.my_difficulty && user?.actorId && user?.token) {
      fetch(`${API}/api/student/${user.actorId}/assignments/${a.id}/my-questions`, { headers: authHeaders(user.token) })
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (d?.questions?.length) {
            setActive({ ...a, questions: d.questions });
          } else {
            setActive(a);
          }
        })
        .catch(() => setActive(a));
    } else {
      setActive(a);
    }
    setAnswers({}); setResult(null); setSubmitWarning([]);
  }

  function setAnswer(index: number, value: unknown) {
    setAnswers((prev) => ({ ...prev, [index]: value }));
    if (submitWarning.length > 0) setSubmitWarning([]);
  }

  function findUnanswered() {
    if (!active) return [];
    return active.questions
      .map((_, i) => i)
      .filter((i) => {
        const value = answers[i];
        return value == null || (typeof value === "string" && value.trim() === "");
      });
  }

  async function submit(force = false) {
    if (!active || !user?.actorId || submitting) return;
    const missing = findUnanswered();
    if (!force && missing.length > 0) {
      setSubmitWarning(missing);
      return;
    }
    setSubmitting(true); setError(""); setSubmitWarning([]);
    try {
      const ordered = active.questions.map((_, i) => answers[i] ?? null);
      const res = await fetch(`${API}/api/student/${user.actorId}/assignments/${active.id}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(user.token ? authHeaders(user.token) : {}) },
        body: JSON.stringify({ answers: ordered }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setResult(await res.json());
      if (user.actorId) load(user.actorId, user.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    } finally { setSubmitting(false); }
  }

  const pending = list.filter((a) => !a.submission);
  const done = list.filter((a) => a.submission);

  return (
    <div className="asg">
      <style>{CSS}</style>
      <div className="asg-inner">
        <header className="asg-head">
          <p className="asg-eyebrow">ASSIGNMENTS · 我的作业</p>
          <h1 className="asg-title">作业本</h1>
          <p className="asg-sub">老师布置的作业，客观题提交后即时批改</p>
        </header>

        {loading && <p className="asg-empty">加载中…</p>}
        {error && !active && <p className="asg-error">{error}</p>}

        {!loading && !active && (
          <>
            <section className="asg-section">
              <h2 className="asg-sec-title">待完成 <span className="asg-count">{pending.length}</span></h2>
              {pending.length === 0 ? (
                <p className="asg-empty">暂无待完成作业 🎉</p>
              ) : pending.map((a) => (
                <button key={a.id} className="asg-card asg-card-pending" onClick={() => openAssignment(a)}>
                  <div className="asg-card-main">
                    <span className="asg-card-title">{a.title}</span>
                    <span className="asg-card-meta">
                      {a.subject && <span className="asg-tag">{a.subject}</span>}
                      {a.questions.length} 题
                      {a.my_difficulty && (
                        <span className={`asg-diff-tag ${a.my_difficulty}`}>
                          {a.my_difficulty === "easy" ? "基础组" : a.my_difficulty === "hard" ? "提高组" : "中等组"}
                        </span>
                      )}
                      {a.due_date && <span className="asg-due">截止 {a.due_date}</span>}
                    </span>
                  </div>
                  <span className="asg-card-arrow">作答 →</span>
                </button>
              ))}
            </section>

            {done.length > 0 && (
              <section className="asg-section">
                <h2 className="asg-sec-title">已完成 <span className="asg-count">{done.length}</span></h2>
                {done.map((a) => (
                  <div key={a.id} className="asg-card asg-card-done">
                    <div className="asg-card-main">
                      <span className="asg-card-title">{a.title}</span>
                      <span className="asg-card-meta">
                        {a.submission?.status === "graded" ? "已批改" : "待老师评阅"}
                      </span>
                    </div>
                    <span className="asg-score">
                      {a.submission?.score != null ? `${a.submission.score}分` : "—"}
                    </span>
                  </div>
                ))}
              </section>
            )}
          </>
        )}

        {active && !result && (
          <section className="asg-quiz">
            <button className="asg-back" onClick={() => { setActive(null); setSubmitWarning([]); }}>← 返回列表</button>
            <h2 className="asg-quiz-title">{active.title}</h2>
            {active.questions.map((q, i) => (
              <div key={i} className="asg-q">
                <p className="asg-q-prompt"><span className="asg-q-num">{i + 1}</span>{q.prompt}</p>
                {q.type === "single_choice" && (q.options || []).map((opt, oi) => {
                  const label = String.fromCharCode(65 + oi);
                  const selected = answers[i] === label;
                  return (
                    <label key={oi} className={`asg-opt${selected ? " sel" : ""}`}>
                      <input type="radio" name={`q${i}`} checked={selected}
                        onChange={() => setAnswer(i, label)} />
                      <span className="asg-opt-badge">{label}</span>
                      <span className="asg-opt-text">{opt}</span>
                      <span className="asg-opt-dot" />
                    </label>
                  );
                })}
                {q.type === "true_false" && ["正确", "错误"].map((opt, oi) => {
                  const selected = answers[i] === opt;
                  return (
                    <label key={opt} className={`asg-opt${selected ? " sel" : ""}`}>
                      <input type="radio" name={`q${i}`} checked={selected}
                        onChange={() => setAnswer(i, opt)} />
                      <span className="asg-opt-badge">{["✓","✗"][oi]}</span>
                      <span className="asg-opt-text">{opt}</span>
                      <span className="asg-opt-dot" />
                    </label>
                  );
                })}
                {!OBJECTIVE.has(q.type) && (
                  <textarea className="asg-textarea" placeholder="在此作答…"
                    value={(answers[i] as string) || ""}
                    onChange={(e) => setAnswer(i, e.target.value)} />
                )}
              </div>
            ))}
            {error && <p className="asg-error">{error}</p>}
            {submitWarning.length > 0 && (
              <div className="asg-submit-warning" role="alert">
                <strong>还有 {submitWarning.length} 题未作答</strong>
                <p>
                  第 {submitWarning.map((i) => i + 1).join("、")} 题还没有填写。
                  你可以继续检查，也可以仍然提交。
                </p>
                <div className="asg-submit-warning-actions">
                  <button type="button" onClick={() => setSubmitWarning([])}>继续检查</button>
                  <button type="button" onClick={() => submit(true)} disabled={submitting}>
                    {submitting ? "提交中…" : "仍然提交"}
                  </button>
                </div>
              </div>
            )}
            <button className="asg-submit" onClick={() => submit(false)} disabled={submitting}>
              {submitting ? "提交中…" : "提交作业"}
            </button>
          </section>
        )}

        {result && (
          <section className="asg-result">
            <div className="asg-result-seal">{result.status === "graded" ? "✓" : "⏳"}</div>
            <h2 className="asg-result-title">
              {result.objective_total > 0
                ? `客观题 ${result.objective_correct}/${result.objective_total} 正确`
                : "已提交"}
            </h2>
            {result.score != null && <p className="asg-result-score">{result.score} 分</p>}
            {result.has_subjective && <p className="asg-result-note">主观题已提交，等待老师评阅</p>}

            {/* 薄弱知识点反馈 */}
            {result.wrong_tags?.length > 0 && (
              <div className="asg-weakfeed">
                <p className="asg-weakfeed-label">本次答错知识点</p>
                <div className="asg-weakfeed-tags">
                  {result.wrong_tags.map((tag) => (
                    <span key={tag} className="asg-weak-chip">{tag}</span>
                  ))}
                </div>
                <p className="asg-weakfeed-hint">
                  这些知识点已加入今日复习，建议课后巩固。
                </p>
                <div className="asg-result-ctas">
                  <a href="/student/review" className="asg-cta-btn asg-cta-review">
                    今日复习 →
                  </a>
                  <a
                    href={`/student/auto-tutor?focus=${encodeURIComponent(result.wrong_tags[0])}`}
                    className="asg-cta-btn asg-cta-tutor"
                  >
                    AutoTutor 辅导
                  </a>
                </div>
              </div>
            )}

            <button className="asg-submit" onClick={() => { setActive(null); setResult(null); }}>返回作业本</button>
          </section>
        )}
      </div>
    </div>
  );
}

const CSS = `
.asg { min-height:100vh; color:var(--ink,#1a1612); }
.asg-inner { max-width:680px; margin:0 auto; padding:36px 22px 100px; animation:asgIn 300ms ease both; }
@keyframes asgIn { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }
.asg-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 6px; }
.asg-title { font-family:var(--font-display-family); font-size:28px; font-weight:700; margin:0 0 4px; letter-spacing:-.03em; }
.asg-sub { font-size:13px; color:var(--muted,#7a7068); margin:0 0 28px; }
.asg-section { margin-bottom:28px; }
.asg-sec-title { font-size:14px; font-weight:900; margin:0 0 12px; display:flex; align-items:center; gap:8px; letter-spacing:.04em; color:var(--ink-soft,#66584b); }
.asg-count { font-size:11px; background:var(--cinnabar,#b7422b); color:#fff; border-radius:10px; padding:2px 8px; }
.asg-empty { font-size:13px; color:var(--muted,#7a7068); padding:16px 0; }
.asg-error { font-size:13px; color:#c0392b; margin:10px 0; padding:10px 14px; background:rgba(183,66,43,.06); border:1px solid rgba(183,66,43,.2); border-radius:10px; }

/* 作业卡片 */
.asg-card {
  width:100%; display:flex; justify-content:space-between; align-items:center; gap:12px;
  background:rgba(255,252,244,0.9); border:1px solid rgba(96,72,44,0.15);
  border-radius:14px; padding:16px 18px; margin-bottom:10px;
  text-align:left; cursor:pointer;
  transition:border-color 180ms ease, transform 160ms ease, box-shadow 180ms ease;
  -webkit-tap-highlight-color:transparent;
}
.asg-card-pending:hover { border-color:rgba(183,66,43,.35); transform:translateX(3px); box-shadow:0 8px 20px rgba(183,66,43,.08); }
.asg-card-pending:active { transform:translateX(1px) scale(.99); }
.asg-card-done { cursor:default; opacity:.82; }
.asg-card-main { display:flex; flex-direction:column; gap:5px; min-width:0; }
.asg-card-title { font-size:15px; font-weight:700; }
.asg-card-meta { font-size:12px; color:var(--muted,#7a7068); display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.asg-tag { background:rgba(184,139,62,.14); color:#7a5524; border-radius:999px; padding:2px 8px; font-size:11px; font-weight:700; }
.asg-due { color:#c0392b; font-weight:700; }
.asg-card-arrow { font-size:12px; font-weight:900; color:var(--cinnabar,#b7422b); white-space:nowrap; padding:6px 12px; border:1px solid rgba(183,66,43,.2); border-radius:999px; background:rgba(183,66,43,.07); flex-shrink:0; }
.asg-score { font-size:20px; font-weight:900; color:var(--jade,#0f6b5f); white-space:nowrap; letter-spacing:-.04em; }

/* 返回 + 标题 */
.asg-back { display:inline-flex; align-items:center; gap:6px; background:none; border:none; color:var(--muted,#7a7068); font-size:13px; font-weight:700; cursor:pointer; padding:0 0 16px; transition:color .15s; }
.asg-back:hover { color:var(--ink,#1a1612); }
.asg-quiz-title { font-family:var(--font-display-family); font-size:22px; font-weight:700; margin:0 0 20px; letter-spacing:-.03em; }

/* 题目卡片 */
.asg-q {
  background:rgba(255,252,244,0.9); border:1px solid rgba(96,72,44,0.14);
  border-radius:16px; padding:22px 20px 16px; margin-bottom:14px;
  box-shadow:0 4px 12px rgba(59,39,19,.05);
  animation:asgQIn 250ms ease both;
}
@keyframes asgQIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }
.asg-q-prompt { font-size:15px; font-weight:700; margin:0 0 16px; display:flex; gap:10px; line-height:1.65; }
.asg-q-num {
  background:linear-gradient(135deg, var(--cinnabar,#b7422b), #8d2d1c);
  color:#fff; border-radius:9px; width:26px; height:26px; min-width:26px;
  display:inline-flex; align-items:center; justify-content:center;
  font-size:12px; font-weight:900; flex-shrink:0; margin-top:1px;
}

/* 选项行 */
.asg-opt {
  display:flex; align-items:center; gap:12px; padding:12px 14px;
  border:1.5px solid rgba(96,72,44,0.16); border-radius:12px; margin-bottom:8px;
  cursor:pointer; font-size:14px;
  background:rgba(255,252,244,0.7); user-select:none;
  transition:border-color 150ms ease, background 150ms ease, transform 120ms ease;
  -webkit-tap-highlight-color:transparent;
}
.asg-opt input[type=radio] { display:none; }
.asg-opt:hover { border-color:rgba(96,72,44,0.3); background:rgba(255,252,244,0.95); }
.asg-opt:active { transform:scale(.99); }
.asg-opt.sel { background:rgba(183,66,43,.07); border-color:rgba(183,66,43,.45); }

/* 字母徽章 */
.asg-opt-badge {
  width:28px; height:28px; min-width:28px; border-radius:8px;
  display:flex; align-items:center; justify-content:center;
  font-size:12px; font-weight:900;
  background:rgba(96,72,44,.1); color:var(--muted,#7a7068);
  transition:all 150ms ease; flex-shrink:0;
}
.asg-opt.sel .asg-opt-badge { background:var(--cinnabar,#b7422b); color:#fff; box-shadow:0 4px 10px rgba(183,66,43,.2); }

/* 选项文字 */
.asg-opt-text { flex:1; line-height:1.5; color:var(--ink,#1a1612); }

/* 右侧选中指示圆 */
.asg-opt-dot {
  width:18px; height:18px; min-width:18px; border-radius:50%;
  border:2px solid rgba(96,72,44,0.2); margin-left:auto;
  transition:all 150ms ease; flex-shrink:0;
}
.asg-opt.sel .asg-opt-dot {
  border-color:var(--cinnabar,#b7422b); background:var(--cinnabar,#b7422b);
  box-shadow:0 0 0 4px rgba(183,66,43,.12);
}

.asg-textarea {
  width:100%; min-height:90px;
  border:1.5px solid rgba(96,72,44,0.18); border-radius:12px;
  padding:11px 13px; font-family:inherit; font-size:14px; resize:vertical;
  background:rgba(255,252,244,0.85); color:var(--ink,#1a1612);
  transition:border-color .15s, box-shadow .15s;
}
.asg-textarea:focus { outline:none; border-color:rgba(183,66,43,.5); box-shadow:0 0 0 4px rgba(183,66,43,.1); }

/* 提交按钮 */
.asg-submit {
  width:100%;
  background:linear-gradient(135deg, var(--cinnabar,#b7422b), #8d2d1c);
  color:#fff; border:none; border-radius:14px;
  padding:15px; font-size:15px; font-weight:900; cursor:pointer; margin-top:14px;
  transition:transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
  letter-spacing:.03em; box-shadow:0 8px 22px rgba(183,66,43,.2);
  -webkit-tap-highlight-color:transparent;
}
.asg-submit:hover:not(:disabled) { transform:translateY(-2px); box-shadow:0 14px 30px rgba(183,66,43,.28); filter:saturate(1.1); }
.asg-submit:active:not(:disabled) { transform:translateY(0); }
.asg-submit:disabled { opacity:.55; cursor:not-allowed; }

/* 未作答提示 */
.asg-submit-warning {
  margin:18px 0; padding:16px 18px; border-radius:14px;
  border:1px solid rgba(217,119,6,.28); background:rgba(253,246,224,.88);
  color:var(--ink,#1a1612);
}
.asg-submit-warning strong { display:block; margin-bottom:4px; color:#92400e; font-size:14px; font-weight:900; }
.asg-submit-warning p { margin:0; color:var(--muted,#7a7068); font-size:13px; line-height:1.7; }
.asg-submit-warning-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.asg-submit-warning-actions button {
  border:1px solid rgba(146,64,14,.24); border-radius:999px;
  background:#fffaf0; color:#92400e; padding:8px 14px;
  font-size:12px; font-weight:900; cursor:pointer;
  transition:border-color .15s, background .15s, transform .1s;
}
.asg-submit-warning-actions button:hover:not(:disabled) { border-color:#92400e; background:rgba(146,64,14,.06); transform:translateY(-1px); }
.asg-submit-warning-actions button:disabled { opacity:.55; cursor:not-allowed; }

/* 结果面板 */
.asg-result { text-align:center; padding:52px 20px; animation:asgIn 350ms ease both; }
.asg-result-seal {
  width:80px; height:80px; margin:0 auto 22px;
  background:linear-gradient(135deg, var(--jade,#0f6b5f), #0b4f48);
  color:#fff; border-radius:24px;
  display:flex; align-items:center; justify-content:center; font-size:34px;
  box-shadow:0 8px 24px rgba(15,107,95,.25);
  animation:sealIn 500ms cubic-bezier(.34,1.56,.64,1) both;
}
@keyframes sealIn { from{transform:scale(0) rotate(-12deg);opacity:0} to{transform:scale(1) rotate(0);opacity:1} }
.asg-result-title { font-size:20px; font-weight:900; margin:0 0 8px; }
.asg-result-score { font-size:48px; font-weight:900; color:var(--jade,#0f6b5f); margin:0 0 8px; letter-spacing:-.05em; }
.asg-result-note { font-size:13px; color:var(--muted,#7a7068); margin:0 0 20px; }
.asg-weakfeed {
  background:rgba(255,252,244,0.9); border:1px solid rgba(183,66,43,.18);
  border-radius:16px; padding:18px 20px; margin:0 0 24px; text-align:left;
  box-shadow:0 4px 14px rgba(183,66,43,.06);
}
.asg-weakfeed-label { font-size:10px; font-weight:900; letter-spacing:.2em; color:var(--cinnabar,#b7422b); margin:0 0 12px; }
.asg-weakfeed-tags { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
.asg-weak-chip {
  font-size:12px; background:rgba(183,66,43,.08); color:var(--cinnabar,#b7422b);
  border:1px solid rgba(183,66,43,.22); border-radius:999px; padding:4px 11px; font-weight:700;
}
.asg-weakfeed-hint { font-size:12px; color:var(--muted,#7a7068); margin:0 0 16px; line-height:1.6; }
.asg-result-ctas { display:flex; gap:10px; }
.asg-cta-btn {
  flex:1; display:flex; align-items:center; justify-content:center; gap:6px;
  padding:12px 14px; border-radius:12px; font-size:13px; font-weight:900;
  text-decoration:none; transition:transform 160ms ease, box-shadow 160ms ease;
}
.asg-cta-btn:hover { transform:translateY(-2px); box-shadow:0 8px 18px rgba(0,0,0,.12); }
.asg-cta-review { background:linear-gradient(135deg,var(--jade,#0f6b5f),#0b4f48); color:#fff; }
.asg-cta-tutor { background:linear-gradient(135deg,var(--gold,#b88b3e),#8a6620); color:#fff; }

/* 难度标签 */
.asg-diff-tag { font-size:11px; font-weight:900; border-radius:999px; padding:2px 8px; }
.asg-diff-tag.easy { background:rgba(22,101,52,.1); color:#166534; }
.asg-diff-tag.medium { background:rgba(133,77,14,.1); color:#854d0e; }
.asg-diff-tag.hard { background:rgba(153,27,27,.1); color:#991b1b; }
`;
