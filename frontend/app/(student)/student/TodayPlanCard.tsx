"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Task = {
  kind: "assignment" | "review" | "weakpoint";
  priority: "urgent" | "high" | "normal";
  title: string;
  detail: string;
  href: string;
  count?: number;
  ref_id?: string | null;
};
type TodayPlan = {
  date: string;
  tasks: Task[];
  summary: {
    pending_assignments: number;
    overdue_assignments: number;
    review_remaining: number;
    weakpoint_count: number;
    all_clear: boolean;
  };
};

const KIND_MARK: Record<Task["kind"], string> = { assignment: "业", review: "复", weakpoint: "弱" };
const PRIORITY_LABEL: Record<Task["priority"], string> = { urgent: "紧急", high: "优先", normal: "待办" };

/** 学生「今日计划」：把作业到期、今日复习、薄弱点合成一条按优先级排序的待办清单。 */
export default function TodayPlanCard() {
  const { user } = useAuth();
  const [plan, setPlan] = useState<TodayPlan | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!user?.actorId) return;
    setError(false);
    fetch(`${API}/api/students/${user.actorId}/today`, { headers: authHeaders(user.token) })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: TodayPlan) => setPlan(d))
      .catch(() => setError(true));
  }, [user?.actorId, user?.token]);

  if (error) return (
    <section className="tp-card" aria-label="今日计划">
      <style>{CSS}</style>
      <p className="tp-load-err">今日计划加载失败，请刷新重试。</p>
    </section>
  );
  if (!plan) return null;

  const { tasks, summary } = plan;

  return (
    <section className="tp-card" aria-label="今日计划">
      <style>{CSS}</style>
      <div className="tp-head">
        <div>
          <p className="tp-eyebrow">TODAY · 今日计划</p>
          <h2 className="tp-title">今天优先完成这些</h2>
        </div>
        {summary.overdue_assignments > 0 && (
          <span className="tp-alert">{summary.overdue_assignments} 份逾期作业</span>
        )}
      </div>

      {summary.all_clear ? (
        <div className="tp-clear">
          <span className="tp-clear-mark" aria-hidden="true">✓</span>
          <div>
            <strong>今日无待办</strong>
            <p>作业已交、复习已清。可以去读教材或与历史人物对话，拓展新知识。</p>
          </div>
        </div>
      ) : (
        <ol className="tp-list">
          {tasks.map((t, i) => (
            <li key={i}>
              <Link href={t.href} className={`tp-task pri-${t.priority}`}>
                <span className="tp-mark" aria-hidden="true">{KIND_MARK[t.kind]}</span>
                <span className="tp-body">
                  <span className="tp-task-title">{t.title}</span>
                  <span className="tp-task-detail">{t.detail}</span>
                </span>
                <span className={`tp-badge pri-${t.priority}`}>{PRIORITY_LABEL[t.priority]}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

const CSS = `
.tp-card { background:#fff; border:1px solid #e5e0d5; border-radius:14px; padding:20px 22px; margin:0 0 24px; }
.tp-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:14px; }
.tp-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 4px; }
.tp-title { font-size:18px; font-weight:700; margin:0; color:var(--ink,#1a1612); }
.tp-alert { font-size:12px; font-weight:600; color:#fff; background:var(--cinnabar,#b7422b); border-radius:12px; padding:4px 10px; white-space:nowrap; }
.tp-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:8px; }
.tp-task { display:flex; align-items:center; gap:12px; padding:12px 14px; border:1px solid #eee6d8; border-radius:10px;
  background:#fdfbf7; transition:border-color .15s, transform .1s; }
.tp-task:hover { border-color:var(--cinnabar,#b7422b); transform:translateX(2px); }
.tp-task.pri-urgent { border-left:3px solid #c0392b; }
.tp-task.pri-high { border-left:3px solid #e0a52b; }
.tp-task.pri-normal { border-left:3px solid #c8bfb2; }
.tp-mark { width:30px; height:30px; flex:none; border-radius:8px; background:#f0ebe0; color:var(--ink,#4a4038);
  display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:700; }
.tp-body { display:flex; flex-direction:column; gap:2px; min-width:0; flex:1; }
.tp-task-title { font-size:14px; font-weight:600; color:var(--ink,#1a1612); }
.tp-task-detail { font-size:12px; color:var(--muted,#7a7068); }
.tp-badge { font-size:11px; font-weight:700; border-radius:8px; padding:2px 8px; white-space:nowrap; }
.tp-badge.pri-urgent { background:#fdecea; color:#c0392b; }
.tp-badge.pri-high { background:#fdf6e3; color:#b0862b; }
.tp-badge.pri-normal { background:#f0ebe0; color:var(--muted,#7a7068); }
.tp-clear { display:flex; align-items:center; gap:14px; padding:8px 0; }
.tp-clear-mark { width:40px; height:40px; flex:none; border-radius:50%; background:#f0faf5; color:var(--jade,#2d6a4f);
  display:flex; align-items:center; justify-content:center; font-size:20px; font-weight:700; }
.tp-clear strong { font-size:15px; display:block; margin-bottom:2px; }
.tp-clear p { font-size:13px; color:var(--muted,#7a7068); margin:0; }
.tp-load-err { font-size:13px; color:var(--cinnabar,#b7422b); padding:8px 0; margin:0; }
`;
