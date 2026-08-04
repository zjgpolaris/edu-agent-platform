"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type WeeklyMetrics = {
  active_days: number;
  streak_days: number;
  reviews_done: number;
  reviews_total: number;
  review_completion_rate: number | null;
  homework_count: number;
  homework_avg_score: number | null;
  autotutor_sessions: number;
  weakpoint_count: number;
  top_weakpoints: { tag: string; count: number }[];
};
type WeeklySummary = {
  student_id: string;
  week_start: string;
  week_end: string;
  metrics: WeeklyMetrics;
  summary: string;
  suggestions: string[];
  generated_by: "llm" | "rule";
};

function fmtRange(start: string, end: string): string {
  const s = start.slice(5).replace("-", "/");
  const e = end.slice(5).replace("-", "/");
  return `${s} – ${e}`;
}

/** 学生「本周小结」：聚合本周学习数据，展示 AI 生成的小结与下周建议。 */
export default function WeeklySummaryCard() {
  const { user } = useAuth();
  const [data, setData] = useState<WeeklySummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!user?.actorId) return;
    setFailed(false);
    fetch(`${API}/api/students/${user.actorId}/weekly-summary`, { headers: authHeaders(user.token) })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => setData(d as WeeklySummary))
      .catch(() => setFailed(true));
  }, [user?.actorId, user?.token]);

  if (!user?.actorId) return null;
  if (failed) return (
    <section className="ws-card ws-error-card" aria-label="本周小结加载失败">
      <style>{CSS}</style>
      <div className="ws-error">
        <strong>本周小结暂时加载失败</strong>
        <p>学习数据仍会正常记录，可以稍后刷新重试。</p>
      </div>
    </section>
  );
  if (!data) return (
    <section className="ws-card ws-skeleton" aria-label="本周小结加载中" aria-busy="true">
      <style>{CSS}</style>
      <div className="ws-skel-head">
        <span />
        <i />
      </div>
      <div className="ws-skel-line wide" />
      <div className="ws-skel-line" />
      <div className="ws-skel-chips">
        <b /><b /><b /><b />
      </div>
    </section>
  );

  const m = data.metrics;
  const chips: { label: string; value: string }[] = [
    { label: "活跃", value: `${m.active_days}/7 天` },
    { label: "连续打卡", value: `${m.streak_days} 天` },
  ];
  if (m.review_completion_rate !== null) chips.push({ label: "复习完成", value: `${m.review_completion_rate}%` });
  if (m.homework_avg_score !== null) chips.push({ label: "作业均分", value: `${m.homework_avg_score}` });
  if (m.autotutor_sessions > 0) chips.push({ label: "AutoTutor", value: `${m.autotutor_sessions} 次` });
  chips.push({ label: "错题", value: `${m.weakpoint_count} 个` });

  return (
    <section className="ws-card" aria-label="本周小结">
      <style>{CSS}</style>
      <div className="ws-head">
        <div>
          <p className="ws-eyebrow">WEEKLY · 本周小结</p>
          <h2 className="ws-title">这一周你做到了这些</h2>
        </div>
        <span className="ws-range">{fmtRange(data.week_start, data.week_end)}</span>
      </div>

      <p className="ws-summary">{data.summary}</p>

      <div className="ws-chips">
        {chips.map((c) => (
          <span key={c.label} className="ws-chip">
            <span className="ws-chip-label">{c.label}</span>
            <span className="ws-chip-value">{c.value}</span>
          </span>
        ))}
      </div>

      {data.suggestions.length > 0 && (
        <div className="ws-suggest">
          <p className="ws-suggest-head">下周建议</p>
          <ul className="ws-suggest-list">
            {data.suggestions.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
}

const CSS = `
.ws-card {
  background:rgba(255,252,244,0.95);
  border:1px solid rgba(96,72,44,0.15);
  border-radius:18px;
  padding:22px 24px;
  margin:0 0 20px;
  box-shadow:0 4px 16px rgba(59,39,19,.06);
  animation:wsCardIn 280ms ease both;
}
@keyframes wsCardIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }
.ws-error { border:1px dashed rgba(96,72,44,.18); border-radius:12px; padding:14px 16px; background:rgba(255,252,244,0.7); }
.ws-error strong { display:block; color:var(--ink,#1a1612); font-size:14px; margin-bottom:4px; }
.ws-error p { margin:0; color:var(--muted,#7a7068); font-size:13px; line-height:1.6; }
.ws-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:14px; }
.ws-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--jade,#0f6b5f); margin:0 0 4px; font-weight:900; }
.ws-title { font-size:18px; font-weight:900; margin:0; color:var(--ink,#1a1612); letter-spacing:-.02em; }
.ws-range { font-size:11px; font-weight:900; color:var(--muted,#7a7068); background:rgba(96,72,44,.07); border-radius:999px; padding:5px 12px; white-space:nowrap; }
.ws-summary { font-size:14px; line-height:1.75; color:var(--ink-soft,#3a332c); margin:0 0 16px; }
.ws-chips { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.ws-chip {
  display:inline-flex; flex-direction:column; gap:2px;
  background:rgba(255,252,244,0.9); border:1px solid rgba(96,72,44,.14);
  border-radius:12px; padding:8px 14px;
  transition:border-color 160ms ease, transform 160ms ease;
  cursor:default;
}
.ws-chip:hover { border-color:rgba(15,107,95,.28); transform:translateY(-1px); }
.ws-chip-label { font-size:10px; color:var(--muted,#7a7068); letter-spacing:.06em; font-weight:800; }
.ws-chip-value { font-size:15px; font-weight:900; color:var(--ink,#1a1612); letter-spacing:-.02em; }
.ws-suggest { border-top:1px solid rgba(96,72,44,.1); padding-top:14px; }
.ws-suggest-head { font-size:10px; font-weight:900; letter-spacing:.18em; color:var(--cinnabar,#b7422b); margin:0 0 10px; }
.ws-suggest-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:7px; }
.ws-suggest-list li {
  position:relative; padding:8px 12px 8px 28px;
  font-size:13px; line-height:1.6; color:var(--ink,#3a332c);
  border:1px solid transparent; border-radius:10px;
  transition:border-color 160ms ease, background 160ms ease;
}
.ws-suggest-list li::before { content:"→"; position:absolute; left:10px; color:var(--jade,#0f6b5f); font-weight:900; }
.ws-suggest-list li:hover { border-color:rgba(15,107,95,.16); background:rgba(15,107,95,.04); }
.ws-skeleton { overflow:hidden; }
.ws-skel-head { display:flex; justify-content:space-between; gap:12px; margin-bottom:14px; }
.ws-skel-head span, .ws-skel-head i, .ws-skel-line, .ws-skel-chips b { display:block; border-radius:12px; background:linear-gradient(90deg,#eef4ec 0%,#fffaf0 48%,#eef4ec 100%); background-size:220% 100%; animation:wsShimmer 1.2s ease-in-out infinite; }
.ws-skel-head span { width:190px; height:28px; }
.ws-skel-head i { width:86px; height:24px; }
.ws-skel-line { height:12px; margin-bottom:10px; }
.ws-skel-line.wide { width:76%; }
.ws-skel-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.ws-skel-chips b { width:86px; height:46px; }
@keyframes wsShimmer { 0%{background-position:120% 0} 100%{background-position:-120% 0} }
`;
