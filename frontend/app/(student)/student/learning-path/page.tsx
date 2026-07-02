"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Weakpoint = {
  knowledge_tag: string;
  wrong_count?: number;
  correct_streak?: number;
};
type Milestone = { title: string; completed: boolean };
type LearningPath = {
  student_id: string;
  updated_at?: string;
  weak_topics: string[];
  strong_topics: string[];
  weakpoints: Weakpoint[];
  priority_topics: string[];
  recommended_actions: string[];
  progress: Record<string, number>;
  milestones: Milestone[];
};

const MASTERY_THRESHOLD = 2;

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@300;400;600;700&family=Ma+Shan+Zheng&display=swap');

.lp { font-family:'Noto Serif SC',serif; background:transparent; min-height:100vh; color:var(--ink); }

/* ── loading ── */
.lp-load { display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:80vh;gap:20px; }
.lp-load-char {
  font-family:'Ma Shan Zheng',serif; font-size:56px; color:var(--cinnabar); line-height:1;
  animation:lpPulse 2s ease-in-out infinite;
  filter:drop-shadow(0 0 16px rgba(183,66,43,.35));
}
@keyframes lpPulse { 0%,100%{opacity:.25;transform:scale(.88)} 50%{opacity:1;transform:scale(1.04)} }
.lp-load-dots { display:flex;gap:5px; }
.lp-load-dot { width:4px;height:4px;border-radius:50%;background:var(--cinnabar);animation:lpBounce 1.4s ease-in-out infinite; }
.lp-load-dot:nth-child(2){animation-delay:.18s}
.lp-load-dot:nth-child(3){animation-delay:.36s}
@keyframes lpBounce { 0%,60%,100%{transform:translateY(0);opacity:.25} 30%{transform:translateY(-7px);opacity:1} }
.lp-load-txt { font-size:11px;color:var(--muted);letter-spacing:.22em; }

/* ── layout ── */
.lp-inner { max-width:640px;margin:0 auto;padding:40px 24px 100px; }

/* ── header ── */
.lp-head { margin-bottom:26px; }
.lp-eyebrow {
  font-size:10px;letter-spacing:.28em;color:var(--cinnabar);
  display:flex;align-items:center;gap:8px;margin-bottom:6px;
}
.lp-eyebrow::before { content:'';width:18px;height:1px;background:var(--cinnabar);flex-shrink:0; }
.lp-h1 { font-size:22px;font-weight:700;letter-spacing:.08em;color:var(--ink);margin:0 0 5px; }
.lp-updated { font-size:11px;color:var(--muted);letter-spacing:.14em; }

/* ── overview ── */
.lp-overview { display:flex;gap:10px;margin-bottom:30px; }
.lp-stat {
  flex:1;text-align:center;padding:16px 10px;
  border:1px solid var(--border);border-radius:4px;background:var(--paper-soft);
  box-shadow:var(--shadow-md),inset 0 1px 0 rgba(255,255,255,.6);
}
.lp-stat-n { font-size:28px;font-weight:700;line-height:1;font-feature-settings:'tnum'; }
.lp-stat.strong .lp-stat-n { color:var(--gold); }
.lp-stat.weak   .lp-stat-n { color:var(--cinnabar); }
.lp-stat.due    .lp-stat-n { color:var(--ink); }
.lp-stat-l { font-size:10px;color:var(--muted);letter-spacing:.14em;margin-top:7px; }

/* ── section ── */
.lp-sec { margin-bottom:32px; }
.lp-sec-title {
  font-size:13px;font-weight:700;letter-spacing:.16em;color:var(--ink);
  margin-bottom:16px;display:flex;align-items:center;gap:8px;
}
.lp-sec-title::before { content:'◆';font-size:8px;color:var(--cinnabar); }

/* ── timeline ── */
.lp-timeline { position:relative;padding-left:22px; }
.lp-timeline::before {
  content:'';position:absolute;left:5px;top:6px;bottom:6px;width:1px;
  background:linear-gradient(to bottom,var(--cinnabar),rgba(183,66,43,.15));
}
.lp-node { position:relative;margin-bottom:20px; }
.lp-node:last-child { margin-bottom:0; }
.lp-node::before {
  content:'';position:absolute;left:-22px;top:5px;width:11px;height:11px;border-radius:50%;
  background:var(--paper);border:2px solid var(--cinnabar);box-shadow:0 0 8px rgba(183,66,43,.3);
}
.lp-node.mastered::before { border-color:var(--gold);background:var(--gold);box-shadow:0 0 8px rgba(184,139,62,.4); }
.lp-node-top { display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:8px; }
.lp-node-tag { font-size:15px;font-weight:600;color:var(--ink);letter-spacing:.03em; }
.lp-node-meta { font-size:10px;color:var(--muted);letter-spacing:.1em;white-space:nowrap; }
.lp-bar { height:5px;border-radius:3px;background:var(--border);overflow:hidden; }
.lp-bar-fill { height:100%;border-radius:3px;background:linear-gradient(to right,var(--cinnabar),#c96a4f);transition:width .5s; }
.lp-node.mastered .lp-bar-fill { background:linear-gradient(to right,var(--gold),#d0aa5e); }
.lp-streak { font-size:10px;color:var(--muted);letter-spacing:.08em;margin-top:5px; }
.lp-streak.hot { color:var(--gold); }

/* ── actions list ── */
.lp-actions { display:flex;flex-direction:column;gap:10px; }
.lp-action {
  display:flex;align-items:flex-start;gap:11px;padding:12px 16px;
  border:1px solid var(--border);border-radius:3px;background:var(--paper-soft);
  font-size:13px;line-height:1.7;color:var(--ink-soft);letter-spacing:.02em;
}
.lp-action-dot { width:9px;height:9px;border-radius:50%;border:1px solid var(--cinnabar);flex-shrink:0;margin-top:6px; }
.lp-action.done .lp-action-dot { background:var(--gold);border-color:var(--gold); }

/* ── CTA ── */
.lp-cta { display:flex;gap:12px;margin-top:8px; }
.lp-cta-btn {
  flex:1;text-align:center;padding:13px 16px;border-radius:3px;
  font-size:13px;font-weight:600;letter-spacing:.08em;font-family:'Noto Serif SC',serif;
  transition:all .18s;text-decoration:none;
}
.lp-cta-fill { background:var(--cinnabar);border:1px solid var(--cinnabar);color:#fff; }
.lp-cta-fill:hover { background:var(--cinnabar-dark); }
.lp-cta-outline { background:transparent;border:1px solid var(--cinnabar);color:var(--cinnabar); }
.lp-cta-outline:hover { background:var(--cinnabar);color:#fff; }

/* ── empty ── */
.lp-empty { text-align:center;padding:80px 24px; }
.lp-empty-c { font-family:'Ma Shan Zheng',serif;font-size:64px;color:var(--muted);opacity:.4;line-height:1;margin-bottom:20px; }
.lp-empty-t { font-size:18px;font-weight:700;color:var(--ink);letter-spacing:.08em;margin-bottom:10px; }
.lp-empty-s { font-size:13px;color:var(--muted);line-height:1.9;letter-spacing:.04em;margin-bottom:24px; }
`;

function InjectStyles() {
  useEffect(() => {
    const id = "lp-v1";
    if (document.getElementById(id)) return;
    const el = document.createElement("style");
    el.id = id; el.textContent = CSS;
    document.head.appendChild(el);
    return () => { document.getElementById(id)?.remove(); };
  }, []);
  return null;
}

function formatDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export default function LearningPathPage() {
  const { user } = useAuth();
  const studentId = user?.actorId;
  const token = user?.token;

  const [path, setPath] = useState<LearningPath | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!studentId || !token) return;
    let dead = false;
    fetch(`${API}/api/students/${studentId}/learning-path`, { headers: authHeaders(token) })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!dead) { setPath(d); setLoading(false); } })
      .catch(() => { if (!dead) setLoading(false); });
    return () => { dead = true; };
  }, [studentId, token]);

  if (loading) return (
    <div className="lp">
      <InjectStyles />
      <div className="lp-load">
        <div className="lp-load-char">径</div>
        <div className="lp-load-dots">
          <div className="lp-load-dot" /><div className="lp-load-dot" /><div className="lp-load-dot" />
        </div>
        <div className="lp-load-txt">正在规划学习路径</div>
      </div>
    </div>
  );

  const weakpoints = path?.weakpoints ?? [];
  const weakTopics = path?.weak_topics ?? [];
  const strongTopics = path?.strong_topics ?? [];
  const priorityTopics = path?.priority_topics ?? [];
  const actions = path?.recommended_actions ?? [];
  const milestones = path?.milestones ?? [];
  const progress = path?.progress ?? {};

  const isEmpty = weakpoints.length === 0 && weakTopics.length === 0;

  if (isEmpty) return (
    <div className="lp">
      <InjectStyles />
      <div className="lp-inner">
        <div className="lp-empty">
          <div className="lp-empty-c">径</div>
          <div className="lp-empty-t">学习路径尚未生成</div>
          <div className="lp-empty-s">完成一次练习或作业后<br />这里会根据你的错题生成个性化学习路径</div>
          <Link href="/student/assignments" className="lp-cta-btn lp-cta-fill" style={{ display: "inline-block" }}>去做作业</Link>
        </div>
      </div>
    </div>
  );

  // 掌握度节点：优先按 priority_topics 顺序，回落到 weakpoints
  const streakByTag: Record<string, number> = {};
  const wrongByTag: Record<string, number> = {};
  for (const wp of weakpoints) {
    streakByTag[wp.knowledge_tag] = wp.correct_streak ?? 0;
    wrongByTag[wp.knowledge_tag] = wp.wrong_count ?? 0;
  }
  const orderedTags = priorityTopics.length > 0
    ? priorityTopics
    : weakpoints.map(w => w.knowledge_tag);

  const focusTag = priorityTopics[0] ?? "";

  return (
    <div className="lp">
      <InjectStyles />
      <div className="lp-inner">
        <div className="lp-head">
          <div className="lp-eyebrow">个性化学习路径</div>
          <h1 className="lp-h1">我的学习路径</h1>
          {path?.updated_at && <div className="lp-updated">更新于 {formatDate(path.updated_at)}</div>}
        </div>

        <div className="lp-overview">
          <div className="lp-stat strong">
            <div className="lp-stat-n">{strongTopics.length}</div>
            <div className="lp-stat-l">优势知识点</div>
          </div>
          <div className="lp-stat weak">
            <div className="lp-stat-n">{weakTopics.length}</div>
            <div className="lp-stat-l">薄弱知识点</div>
          </div>
          <div className="lp-stat due">
            <div className="lp-stat-n">{weakpoints.length}</div>
            <div className="lp-stat-l">待攻克错题</div>
          </div>
        </div>

        {orderedTags.length > 0 && (
          <div className="lp-sec">
            <div className="lp-sec-title">优先攻克</div>
            <div className="lp-timeline">
              {orderedTags.map((tag) => {
                const pct = Math.round((progress[tag] ?? 0.5) * 100);
                const streak = streakByTag[tag] ?? 0;
                const wrong = wrongByTag[tag] ?? 0;
                const mastered = streak >= MASTERY_THRESHOLD;
                return (
                  <div key={tag} className={`lp-node${mastered ? " mastered" : ""}`}>
                    <div className="lp-node-top">
                      <span className="lp-node-tag">{tag}</span>
                      <span className="lp-node-meta">{wrong > 0 ? `错 ${wrong} 次` : ""}</span>
                    </div>
                    <div className="lp-bar"><div className="lp-bar-fill" style={{ width: `${pct}%` }} /></div>
                    <div className={`lp-streak${streak > 0 ? " hot" : ""}`}>
                      连对 {Math.min(streak, MASTERY_THRESHOLD)}/{MASTERY_THRESHOLD}
                      {mastered ? " · 已掌握" : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {(actions.length > 0 || milestones.length > 0) && (
          <div className="lp-sec">
            <div className="lp-sec-title">推荐行动</div>
            <div className="lp-actions">
              {(milestones.length > 0
                ? milestones
                : actions.map(a => ({ title: a, completed: false }))
              ).map((m, i) => (
                <div key={i} className={`lp-action${m.completed ? " done" : ""}`}>
                  <span className="lp-action-dot" />
                  <span>{m.title}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="lp-cta">
          <Link href="/student/review" className="lp-cta-btn lp-cta-outline">去今日复习</Link>
          <Link
            href={focusTag ? `/student/auto-tutor?focus=${encodeURIComponent(focusTag)}` : "/student/auto-tutor"}
            className="lp-cta-btn lp-cta-fill"
          >
            针对性辅导
          </Link>
        </div>
      </div>
    </div>
  );
}
