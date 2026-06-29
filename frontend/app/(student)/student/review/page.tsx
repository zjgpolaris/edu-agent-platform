"use client";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Task = {
  tag: string; question: string; options: string[];
  answer: string; explanation: string; done: boolean; correct: boolean | null;
};
type Session = { date: string; completed: number; total: number; tasks: Task[] };

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@300;400;600;700&family=Ma+Shan+Zheng&display=swap');

.rv { font-family:'Noto Serif SC',serif; background:transparent; min-height:100vh; color:var(--ink); }

/* ── loading ── */
.rv-load { display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:80vh;gap:20px; }
.rv-load-char {
  font-family:'Ma Shan Zheng',serif; font-size:56px; color:var(--cinnabar); line-height:1;
  animation:rvPulse 2s ease-in-out infinite;
  filter:drop-shadow(0 0 16px rgba(183,66,43,.35));
}
@keyframes rvPulse {
  0%,100%{opacity:.25;transform:scale(.88)}
  50%{opacity:1;transform:scale(1.04)}
}
.rv-load-dots { display:flex;gap:5px; }
.rv-load-dot {
  width:4px;height:4px;border-radius:50%;background:var(--cinnabar);
  animation:rvBounce 1.4s ease-in-out infinite;
}
.rv-load-dot:nth-child(2){animation-delay:.18s}
.rv-load-dot:nth-child(3){animation-delay:.36s}
@keyframes rvBounce {
  0%,60%,100%{transform:translateY(0);opacity:.25}
  30%{transform:translateY(-7px);opacity:1}
}
.rv-load-txt { font-size:11px;color:var(--muted);letter-spacing:.22em; }

/* ── layout ── */
.rv-inner { max-width:640px;margin:0 auto;padding:40px 24px 100px; }

/* ── header ── */
.rv-head { display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px; }
.rv-eyebrow {
  font-size:10px;letter-spacing:.28em;color:var(--cinnabar);
  display:flex;align-items:center;gap:8px;margin-bottom:6px;
}
.rv-eyebrow::before { content:'';width:18px;height:1px;background:var(--cinnabar);flex-shrink:0; }
.rv-h1 { font-size:22px;font-weight:700;letter-spacing:.08em;color:var(--ink);margin:0 0 5px; }
.rv-date { font-size:11px;color:var(--muted);letter-spacing:.14em; }
.rv-counter {
  text-align:right;padding:10px 16px;
  border:1px solid rgba(183,66,43,.2);border-radius:3px;
  background:rgba(183,66,43,.05);
}
.rv-cn { font-size:30px;font-weight:700;color:var(--cinnabar);line-height:1;font-feature-settings:'tnum'; }
.rv-cs { font-size:14px;color:var(--ink-soft);margin:0 2px; }
.rv-ct { font-size:14px;color:var(--ink-soft); }
.rv-cl { font-size:10px;color:var(--muted);letter-spacing:.12em;margin-top:3px; }

/* ── rail ── */
.rv-rail { display:flex;gap:4px;margin-bottom:28px; }
.rv-seg { height:3px;flex:1;border-radius:2px;background:var(--border);transition:background .4s,box-shadow .4s; }
.rv-seg.cur { background:var(--cinnabar);box-shadow:0 0 10px rgba(183,66,43,.45); }
.rv-seg.ok  { background:var(--gold); }
.rv-seg.bad { background:rgba(183,66,43,.28); }

/* ── card ── */
.rv-card {
  background:var(--paper-soft);border:1px solid var(--border);border-radius:4px;
  padding:28px 28px 24px;position:relative;overflow:hidden;
  box-shadow:var(--shadow-md),inset 0 1px 0 rgba(255,255,255,.6);
  animation:rvCardIn .4s cubic-bezier(.2,.8,.4,1);
}
@keyframes rvCardIn {
  from{opacity:0;transform:translateY(14px) scale(.985)}
  to{opacity:1;transform:none}
}
.rv-corner {
  position:absolute;width:16px;height:16px;
  border-color:rgba(183,66,43,.2);border-style:solid;
}
.rv-corner.tl { top:10px;left:10px;border-width:1px 0 0 1px; }
.rv-corner.br { bottom:10px;right:10px;border-width:0 1px 1px 0; }
.rv-wm {
  position:absolute;right:-8px;bottom:-24px;
  font-family:'Ma Shan Zheng',serif;font-size:128px;line-height:1;
  color:rgba(96,72,44,.06);pointer-events:none;user-select:none;
}

/* ── tag row ── */
.rv-tagrow { display:flex;align-items:center;justify-content:space-between;margin-bottom:20px; }
.rv-tag {
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 12px;border:1px solid rgba(183,66,43,.25);border-radius:2px;
  background:rgba(183,66,43,.06);color:var(--cinnabar);font-size:11px;letter-spacing:.14em;
}
.rv-tag::before { content:'◆';font-size:7px; }
.rv-qmeta { font-size:11px;color:var(--muted);letter-spacing:.1em; }

/* ── question ── */
.rv-q {
  font-size:16px;font-weight:600;line-height:1.9;color:var(--ink);
  margin-bottom:22px;letter-spacing:.03em;position:relative;z-index:1;
}

/* ── options ── */
.rv-opts { display:flex;flex-direction:column;gap:9px; }
.rv-opt {
  display:flex;align-items:center;gap:14px;
  padding:12px 16px;border:1px solid var(--border);border-radius:3px;
  background:var(--paper);cursor:pointer;text-align:left;width:100%;
  color:var(--ink-soft);font-size:14px;letter-spacing:.02em;
  font-family:'Noto Serif SC',serif;transition:border-color .18s,background .18s,color .18s;
}
.rv-opt:not(:disabled):hover { border-color:var(--border-strong);background:var(--paper-strong);color:var(--ink); }
.rv-circle {
  width:26px;height:26px;border-radius:50%;border:1px solid currentColor;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;flex-shrink:0;opacity:.55;transition:all .18s;
}
.rv-opt.sel   { border-color:var(--cinnabar);background:rgba(183,66,43,.06);color:var(--ink); }
.rv-opt.sel .rv-circle { opacity:1;background:var(--cinnabar);border-color:var(--cinnabar);color:#fff; }
.rv-opt.ok    { border-color:var(--gold);background:rgba(184,139,62,.07);color:var(--gold); }
.rv-opt.ok .rv-circle  { opacity:1;background:var(--gold);border-color:var(--gold);color:#fff; }
.rv-opt.bad   { border-color:rgba(183,66,43,.3);background:rgba(183,66,43,.05);color:var(--cinnabar-dark); }
.rv-opt.bad .rv-circle { opacity:.7;border-color:rgba(183,66,43,.4);color:var(--cinnabar-dark); }

/* ── explanation ── */
.rv-expl {
  margin-top:18px;padding:14px 18px;border-radius:3px;
  background:rgba(184,139,62,.05);border-left:2px solid var(--gold);
  font-size:13px;color:var(--ink-soft);line-height:1.9;letter-spacing:.02em;
  animation:rvFade .3s ease;
}
.rv-expl-lbl { color:var(--gold);font-weight:600;margin-right:8px;letter-spacing:.12em; }
@keyframes rvFade { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }

/* ── actions ── */
.rv-actions { margin-top:22px;display:flex;justify-content:flex-end; }
.rv-btn {
  padding:9px 30px;border-radius:3px;font-size:13px;font-weight:600;
  letter-spacing:.1em;cursor:pointer;font-family:'Noto Serif SC',serif;transition:all .18s;
}
.rv-btn-outline { background:transparent;border:1px solid var(--cinnabar);color:var(--cinnabar); }
.rv-btn-outline:hover:not(:disabled) { background:var(--cinnabar);color:#fff; }
.rv-btn-outline:disabled { border-color:var(--border);color:var(--muted);cursor:default; }
.rv-btn-fill { background:var(--cinnabar);border:1px solid var(--cinnabar);color:#fff; }
.rv-btn-fill:hover { background:var(--cinnabar-dark); }

/* ── summary ── */
.rv-sum { text-align:center;padding:40px 28px;animation:rvCardIn .5s cubic-bezier(.2,.8,.4,1); }
.rv-seal {
  width:88px;height:88px;border:2px solid var(--gold);border-radius:6px;
  display:flex;align-items:center;justify-content:center;margin:0 auto 24px;
  background:rgba(184,139,62,.06);
  font-family:'Ma Shan Zheng',serif;font-size:46px;color:var(--gold);
  animation:rvStamp .65s cubic-bezier(.36,.07,.19,.97);
}
@keyframes rvStamp {
  0%{transform:scale(2) rotate(-9deg);opacity:0}
  60%{transform:scale(.9) rotate(2deg);opacity:1}
  100%{transform:scale(1) rotate(0)}
}
.rv-sum-title { font-size:18px;font-weight:700;letter-spacing:.1em;color:var(--ink); }
.rv-sum-score { font-size:54px;font-weight:700;color:var(--gold);line-height:1.1;margin:12px 0 0; }
.rv-sum-denom { font-size:20px;color:var(--ink-soft); }
.rv-sum-stat  { font-size:12px;color:var(--muted);letter-spacing:.12em;margin-top:6px; }
.rv-divider   { height:1px;background:linear-gradient(to right,transparent,var(--border),transparent);margin:20px 0; }
.rv-chips { display:flex;flex-wrap:wrap;gap:8px;justify-content:center; }
.rv-chip {
  padding:4px 14px;border-radius:2px;font-size:12px;letter-spacing:.08em;
  border:1px solid;display:inline-flex;align-items:center;gap:5px;
}
.rv-chip.ok  { border-color:rgba(184,139,62,.3);color:var(--gold);background:rgba(184,139,62,.05); }
.rv-chip.bad { border-color:rgba(183,66,43,.25);color:var(--cinnabar-dark);background:rgba(183,66,43,.05); }

/* ── empty ── */
.rv-empty { text-align:center;padding:80px 24px; }
.rv-empty-c { font-family:'Ma Shan Zheng',serif;font-size:64px;color:var(--muted);opacity:.4;line-height:1;margin-bottom:20px; }
.rv-empty-t { font-size:18px;font-weight:700;color:var(--ink);letter-spacing:.08em;margin-bottom:10px; }
.rv-empty-s { font-size:13px;color:var(--muted);line-height:1.9;letter-spacing:.04em; }
`;

const WM = ["史", "文", "思", "知", "学", "悟", "道", "义"];

function InjectStyles() {
  useEffect(() => {
    const id = "rv-v3";
    if (document.getElementById(id)) return;
    const el = document.createElement("style");
    el.id = id; el.textContent = CSS;
    document.head.appendChild(el);
    return () => { document.getElementById(id)?.remove(); };
  }, []);
  return null;
}

export default function ReviewPage() {
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

  useEffect(() => {
    if (!studentId || !token) return;
    let dead = false;
    fetch(`${API}/api/students/${studentId}/review/today`, { headers: authHeaders(token) })
      .then(r => r.json())
      .then(d => { if (!dead) { setSession(d); setLoading(false); } })
      .catch(() => { if (!dead) setLoading(false); });
    return () => { dead = true; };
  }, [studentId, token]);

  useEffect(() => {
    if (!session) return;
    const idx = session.tasks.findIndex(t => !t.done);
    setCurrent(idx >= 0 ? idx : session.tasks.length - 1);
    setSelected(null); setRevealed(false); setCardKey(k => k + 1);
  }, [session?.completed]); // eslint-disable-line

  async function handleSubmit() {
    if (!selected || !session || !studentId || !token || submitting) return;
    setSubmitting(true);
    const task = session.tasks[current];
    const is_correct = selected.charAt(0) === task.answer.charAt(0);
    const res = await fetch(`${API}/api/students/${studentId}/review/submit`, {
      method: "POST",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify({ task_index: current, is_correct }),
    });
    const data = await res.json();
    setSession(prev => prev ? {
      ...prev, completed: data.completed,
      tasks: prev.tasks.map((t, i) => i === current ? { ...t, done: true, correct: is_correct } : t),
    } : prev);
    setRevealed(true); setSubmitting(false);
  }

  function handleNext() {
    if (!session) return;
    const next = session.tasks.findIndex((t, i) => i > current && !t.done);
    if (next >= 0) { setCurrent(next); setSelected(null); setRevealed(false); setCardKey(k => k + 1); }
  }

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

  if (!session || session.total === 0) return (
    <div className="rv">
      <InjectStyles />
      <div className="rv-inner">
        <div className="rv-empty">
          <div className="rv-empty-c">卷</div>
          <div className="rv-empty-t">暂无复习任务</div>
          <div className="rv-empty-s">完成练习或作业批改后<br />这里会出现个性化复习内容</div>
        </div>
      </div>
    </div>
  );

  const allDone = session.completed >= session.total;
  const task    = session.tasks[current];
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

        {allDone ? (
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
              <span className="rv-tag">{task.tag}</span>
              <span className="rv-qmeta">{current + 1} / {session.total}</span>
            </div>

            <div className="rv-q">{task.question}</div>

            <div className="rv-opts">
              {task.options.map((opt, i) => {
                const letter = opt.charAt(0);
                const isSel  = selected === opt;
                const isOk   = revealed && letter === task.answer.charAt(0);
                const isBad  = revealed && isSel && !isOk;
                const cls    = isOk ? "ok" : isBad ? "bad" : isSel ? "sel" : "";
                return (
                  <button key={i} disabled={revealed} className={`rv-opt ${cls}`} onClick={() => setSelected(opt)}>
                    <span className="rv-circle">{letter}</span>
                    <span>{opt.slice(2)}</span>
                  </button>
                );
              })}
            </div>

            {revealed && (
              <div className="rv-expl">
                <span className="rv-expl-lbl">解析</span>{task.explanation}
              </div>
            )}

            <div className="rv-actions">
              {!revealed ? (
                <button disabled={!selected || submitting} onClick={handleSubmit} className="rv-btn rv-btn-outline">
                  {submitting ? "提交中…" : "确认答案"}
                </button>
              ) : (
                <button onClick={handleNext} className="rv-btn rv-btn-fill">下一题 →</button>
              )}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
