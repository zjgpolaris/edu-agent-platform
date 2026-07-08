"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApiJson, normalizeError } from "@/lib/api";

type QueueItem = {
  key: string;
  tone: "danger" | "warm" | "jade" | "gold";
  label: string;
  title: string;
  detail: string;
  href: string;
  cta: string;
  priority?: number;
};

type TeacherTodayQueueResponse = {
  date: string;
  items: QueueItem[];
  summary?: Record<string, unknown>;
  source_errors?: Array<{ source: string; message: string }>;
};

/** 教师首页「今日教学队列」：复用现有教师接口，聚合今天先处理的教学动作。 */
export default function TeacherTodayQueue() {
  const { user } = useAuth();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.token) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchApiJson<TeacherTodayQueueResponse>("/api/teacher/today-queue", { token: user.token })
      .then((data) => {
        if (cancelled) return;
        setItems(Array.isArray(data.items) ? data.items : []);
      })
      .catch((err) => {
        if (!cancelled) setError(normalizeError(err, "教学队列加载失败"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [user?.token]);

  if (!user?.token) return null;

  return (
    <section className="ttq-card" aria-label="今日教学队列">
      <style>{CSS}</style>
      <div className="ttq-head">
        <div>
          <p className="ttq-eyebrow">TODAY QUEUE · 今日教学队列</p>
          <h2>今天先处理这些</h2>
        </div>
        <Link href="/teacher/class-analytics" className="ttq-head-link">班级学情 →</Link>
      </div>

      {loading ? (
        <div className="ttq-skeleton"><span /><span /><span /></div>
      ) : error ? (
        <p className="ttq-empty">{error}</p>
      ) : items.length === 0 ? (
        <div className="ttq-clear">
          <strong>当前没有紧急教学待办</strong>
          <p>可以查看班级学情，或为下一节课准备资料。</p>
          <div className="ttq-actions">
            <Link href="/teacher/materials">生成资料</Link>
            <Link href="/teacher/class-analytics">查看学情</Link>
          </div>
        </div>
      ) : (
        <div className="ttq-list">
          {items.map((item) => (
            <Link key={item.key} href={item.href} className={`ttq-item ${item.tone}`}>
              <span className="ttq-label">{item.label}</span>
              <span className="ttq-copy">
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </span>
              <span className="ttq-cta">{item.cta} →</span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

const CSS = `
.ttq-card { background:linear-gradient(145deg, rgba(255,252,244,.96), rgba(246,238,219,.82)); border:1px solid rgba(96,72,44,.18); border-radius:18px; padding:20px 22px; margin:0 0 24px; box-shadow:var(--shadow-sm); }
.ttq-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
.ttq-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 4px; }
.ttq-head h2 { margin:0; font-size:20px; letter-spacing:.04em; }
.ttq-head-link { color:var(--cinnabar,#b7422b); font-size:12px; font-weight:800; white-space:nowrap; }
.ttq-list { display:grid; gap:10px; }
.ttq-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:12px; align-items:center; padding:13px 14px; border-radius:14px; border:1px solid rgba(96,72,44,.13); background:rgba(255,252,244,.72); text-decoration:none; color:inherit; transition:transform .18s, border-color .18s, box-shadow .18s; }
.ttq-item:hover { transform:translateX(3px); border-color:rgba(183,66,43,.24); box-shadow:0 12px 28px rgba(59,39,19,.08); }
.ttq-label { border-radius:999px; padding:4px 9px; font-size:11px; font-weight:900; white-space:nowrap; }
.ttq-item.danger .ttq-label { background:#fee2e2; color:#991b1b; }
.ttq-item.warm .ttq-label { background:#ffedd5; color:#9a3412; }
.ttq-item.jade .ttq-label { background:#dff3eb; color:#0b4f48; }
.ttq-item.gold .ttq-label { background:#fef3c7; color:#92400e; }
.ttq-copy { min-width:0; }
.ttq-copy strong { display:block; font-size:15px; color:var(--ink,#1a1612); margin-bottom:3px; }
.ttq-copy small { display:block; color:var(--muted,#887967); line-height:1.5; }
.ttq-cta { color:var(--jade,#0f6b5f); font-size:12px; font-weight:900; white-space:nowrap; }
.ttq-empty,.ttq-clear p { color:var(--muted,#887967); font-size:13px; line-height:1.7; }
.ttq-clear { background:rgba(15,107,95,.06); border:1px solid rgba(15,107,95,.12); border-radius:14px; padding:14px; }
.ttq-clear strong { display:block; color:var(--ink,#1a1612); margin-bottom:4px; }
.ttq-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.ttq-actions a { border:1px solid rgba(15,107,95,.18); border-radius:999px; padding:7px 12px; color:var(--jade-dark,#0b4f48); text-decoration:none; font-size:12px; font-weight:800; }
.ttq-skeleton { display:grid; gap:10px; }
.ttq-skeleton span { height:58px; border-radius:14px; background:linear-gradient(90deg,#f2eadc 0%,#fffaf0 48%,#f2eadc 100%); background-size:220% 100%; animation:ttqShimmer 1.2s ease-in-out infinite; }
@keyframes ttqShimmer { 0%{background-position:120% 0} 100%{background-position:-120% 0} }
@media (max-width:640px) { .ttq-item { grid-template-columns:1fr; } .ttq-cta { justify-self:start; } }
`;
