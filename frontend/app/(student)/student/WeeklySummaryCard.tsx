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
.ws-card { background:#fff; border:1px solid #e5e0d5; border-radius:14px; padding:20px 22px; margin:0 0 24px; }
.ws-error { border:1px dashed #e5d2bf; border-radius:12px; padding:14px 16px; background:#fffaf0; }
.ws-error strong { display:block; color:var(--ink,#1a1612); font-size:14px; margin-bottom:4px; }
.ws-error p { margin:0; color:var(--muted,#7a7068); font-size:13px; line-height:1.6; }
.ws-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:12px; }
.ws-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--jade,#2d6a4f); margin:0 0 4px; }
.ws-title { font-size:18px; font-weight:700; margin:0; color:var(--ink,#1a1612); }
.ws-range { font-size:12px; font-weight:600; color:var(--muted,#7a7068); background:#f4f1ea; border-radius:12px; padding:4px 10px; white-space:nowrap; }
.ws-summary { font-size:14px; line-height:1.7; color:var(--ink,#3a332c); margin:0 0 14px; }
.ws-chips { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.ws-chip { display:inline-flex; flex-direction:column; gap:1px; background:#fbf9f4; border:1px solid #eee6d8; border-radius:10px; padding:6px 12px; }
.ws-chip-label { font-size:10px; color:var(--muted,#7a7068); letter-spacing:.05em; }
.ws-chip-value { font-size:14px; font-weight:700; color:var(--ink,#1a1612); }
.ws-suggest { border-top:1px solid #f0ebe0; padding-top:12px; }
.ws-suggest-head { font-size:11px; font-weight:700; letter-spacing:.1em; color:var(--cinnabar,#b7422b); margin:0 0 8px; }
.ws-suggest-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
.ws-suggest-list li { position:relative; padding-left:18px; font-size:13px; line-height:1.6; color:var(--ink,#3a332c); }
.ws-suggest-list li::before { content:"→"; position:absolute; left:0; color:var(--jade,#2d6a4f); font-weight:700; }
.ws-skeleton { overflow:hidden; }
.ws-skel-head { display:flex; justify-content:space-between; gap:12px; margin-bottom:14px; }
.ws-skel-head span, .ws-skel-head i, .ws-skel-line, .ws-skel-chips b { display:block; border-radius:12px; background:linear-gradient(90deg,#eef4ec 0%,#fffaf0 48%,#eef4ec 100%); background-size:220% 100%; animation:wsShimmer 1.2s ease-in-out infinite; }
.ws-skel-head span { width:190px; height:28px; }
.ws-skel-head i { width:86px; height:24px; }
.ws-skel-line { height:12px; margin-bottom:10px; }
.ws-skel-line.wide { width:76%; }
.ws-skel-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.ws-skel-chips b { width:86px; height:42px; }
@keyframes wsShimmer { 0%{background-position:120% 0} 100%{background-position:-120% 0} }
`;
