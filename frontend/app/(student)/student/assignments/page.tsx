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
};
type SubmitResult = {
  score: number | null;
  status: string;
  objective_correct: number;
  objective_total: number;
  has_subjective: boolean;
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

  useEffect(() => {
    if (user?.role === "student" && user.actorId) load(user.actorId, user.token);
    else if (user) { setError("请以学生身份登录"); setLoading(false); }
  }, [user?.role, user?.actorId, user?.token]);

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
    setActive(a); setAnswers({}); setResult(null);
  }

  async function submit() {
    if (!active || !user?.actorId) return;
    setSubmitting(true); setError("");
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
            <button className="asg-back" onClick={() => setActive(null)}>← 返回列表</button>
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
                        onChange={() => setAnswers({ ...answers, [i]: label })} />
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
                        onChange={() => setAnswers({ ...answers, [i]: opt })} />
                      <span className="asg-opt-badge">{["✓","✗"][oi]}</span>
                      <span className="asg-opt-text">{opt}</span>
                      <span className="asg-opt-dot" />
                    </label>
                  );
                })}
                {!OBJECTIVE.has(q.type) && (
                  <textarea className="asg-textarea" placeholder="在此作答…"
                    value={(answers[i] as string) || ""}
                    onChange={(e) => setAnswers({ ...answers, [i]: e.target.value })} />
                )}
              </div>
            ))}
            {error && <p className="asg-error">{error}</p>}
            <button className="asg-submit" onClick={submit} disabled={submitting}>
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
            <button className="asg-submit" onClick={() => { setActive(null); setResult(null); }}>返回作业本</button>
          </section>
        )}
      </div>
    </div>
  );
}

const CSS = `
.asg { min-height:100vh; color:var(--ink,#1a1612); }
.asg-inner { max-width:680px; margin:0 auto; padding:36px 22px 100px; }
.asg-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 6px; }
.asg-title { font-size:26px; font-weight:700; margin:0 0 4px; }
.asg-sub { font-size:13px; color:var(--muted,#7a7068); margin:0 0 28px; }
.asg-section { margin-bottom:28px; }
.asg-sec-title { font-size:15px; font-weight:700; margin:0 0 12px; display:flex; align-items:center; gap:8px; }
.asg-count { font-size:12px; background:var(--cinnabar,#b7422b); color:#fff; border-radius:10px; padding:1px 8px; }
.asg-empty { font-size:13px; color:var(--muted,#7a7068); padding:16px 0; }
.asg-error { font-size:13px; color:#c0392b; margin:10px 0; }
.asg-card { width:100%; display:flex; justify-content:space-between; align-items:center; gap:12px;
  background:#fff; border:1px solid #e5e0d5; border-radius:10px; padding:14px 16px; margin-bottom:10px;
  text-align:left; cursor:pointer; transition:border-color .15s, transform .1s; }
.asg-card-pending:hover { border-color:var(--cinnabar,#b7422b); transform:translateX(2px); }
.asg-card-done { cursor:default; opacity:.85; }
.asg-card-main { display:flex; flex-direction:column; gap:4px; }
.asg-card-title { font-size:15px; font-weight:600; }
.asg-card-meta { font-size:12px; color:var(--muted,#7a7068); display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.asg-tag { background:#f0ebe0; border-radius:4px; padding:1px 6px; font-size:11px; }
.asg-due { color:#c0392b; }
.asg-card-arrow { font-size:13px; font-weight:600; color:var(--cinnabar,#b7422b); white-space:nowrap; }
.asg-score { font-size:18px; font-weight:700; color:var(--jade,#2d6a4f); white-space:nowrap; }
.asg-back { background:none; border:none; color:var(--muted,#7a7068); font-size:13px; cursor:pointer; padding:0 0 16px; }
.asg-quiz-title { font-size:20px; font-weight:700; margin:0 0 20px; }

/* 题目卡片 */
.asg-q { background:#fff; border:1px solid #e5e0d5; border-radius:12px; padding:20px 20px 14px; margin-bottom:16px; }
.asg-q-prompt { font-size:15px; font-weight:600; margin:0 0 14px; display:flex; gap:10px; line-height:1.55; }
.asg-q-num { background:var(--ink,#1a1612); color:#fff; border-radius:50%; width:24px; height:24px; min-width:24px;
  display:inline-flex; align-items:center; justify-content:center; font-size:12px; flex-shrink:0; margin-top:1px; }

/* 选项行 — 隐藏原生radio，整行可点 */
.asg-opt { display:flex; align-items:center; gap:12px; padding:11px 14px; border:1.5px solid #e5e0d5;
  border-radius:9px; margin-bottom:8px; cursor:pointer; font-size:14px; transition:all .15s;
  background:#faf8f5; user-select:none; }
.asg-opt input[type=radio] { display:none; }
.asg-opt:hover { border-color:#c8b89a; background:#f5f0e8; }
.asg-opt.sel { background:#fdf1ee; border-color:var(--cinnabar,#b7422b); }

/* 字母徽章 */
.asg-opt-badge { width:26px; height:26px; min-width:26px; border-radius:6px; display:flex; align-items:center;
  justify-content:center; font-size:12px; font-weight:700; background:#ede8e0;
  color:var(--muted,#7a7068); transition:all .15s; flex-shrink:0; }
.asg-opt.sel .asg-opt-badge { background:var(--cinnabar,#b7422b); color:#fff; }

/* 选项文字 */
.asg-opt-text { flex:1; line-height:1.45; color:var(--ink,#1a1612); }

/* 右侧选中指示圆 */
.asg-opt-dot { width:16px; height:16px; min-width:16px; border-radius:50%; border:2px solid #d0c8be;
  margin-left:auto; transition:all .15s; flex-shrink:0; }
.asg-opt.sel .asg-opt-dot { border-color:var(--cinnabar,#b7422b); background:var(--cinnabar,#b7422b);
  box-shadow:0 0 0 3px rgba(183,66,43,.15); }

.asg-textarea { width:100%; min-height:80px; border:1.5px solid #e5e0d5; border-radius:9px; padding:10px 12px;
  font-family:inherit; font-size:14px; resize:vertical; background:#faf8f5; }
.asg-textarea:focus { outline:none; border-color:var(--cinnabar,#b7422b); }

.asg-submit { width:100%; background:var(--cinnabar,#b7422b); color:#fff; border:none; border-radius:10px;
  padding:14px; font-size:15px; font-weight:600; cursor:pointer; margin-top:12px;
  transition:opacity .15s, transform .1s; letter-spacing:.02em; }
.asg-submit:hover:not(:disabled) { opacity:.9; transform:translateY(-1px); }
.asg-submit:disabled { opacity:.55; cursor:not-allowed; }

/* 结果面板 */
.asg-result { text-align:center; padding:48px 20px; }
.asg-result-seal { width:72px; height:72px; margin:0 auto 20px; background:var(--jade,#2d6a4f); color:#fff;
  border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:30px;
  box-shadow:0 4px 16px rgba(45,106,79,.25); }
.asg-result-title { font-size:20px; font-weight:700; margin:0 0 8px; }
.asg-result-score { font-size:40px; font-weight:700; color:var(--jade,#2d6a4f); margin:0 0 8px; letter-spacing:-.02em; }
.asg-result-note { font-size:13px; color:var(--muted,#7a7068); margin:0 0 28px; }
`;
