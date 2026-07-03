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

type CheckInStatus = {
  checked_in_today: boolean;
  current_streak: number;
  total_days: number;
  today_summary: string | null;
};
type Achievement = {
  key: string;
  name: string;
  icon: string;
  description: string;
};

/** 学生「今日计划」：把作业到期、今日复习、薄弱点合成一条按优先级排序的待办清单。 */
export default function TodayPlanCard() {
  const { user } = useAuth();
  const [plan, setPlan] = useState<TodayPlan | null>(null);
  const [error, setError] = useState(false);
  const [notices, setNotices] = useState<Array<{ id: string; message: string; teacher_id: string }>>([]);
  const [checkInStatus, setCheckInStatus] = useState<CheckInStatus | null>(null);
  const [checkingIn, setCheckingIn] = useState(false);
  const [newAchievements, setNewAchievements] = useState<Achievement[]>([]);

  useEffect(() => {
    if (!user?.actorId) return;
    setError(false);
    // 并发获取今日计划 + 未读通知 + 打卡状态
    Promise.all([
      fetch(`${API}/api/students/${user.actorId}/today`, { headers: authHeaders(user.token) })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
      fetch(`${API}/api/students/${user.actorId}/notifications?unread_only=true&limit=3`, { headers: authHeaders(user.token) })
        .then(r => r.ok ? r.json() : { notifications: [] }).catch(() => ({ notifications: [] })),
      fetch(`${API}/api/students/${user.actorId}/check-in/status`, { headers: authHeaders(user.token) })
        .then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([planData, nData, checkInData]) => {
      setPlan(planData as TodayPlan);
      setNotices((nData.notifications || []).slice(0, 3));
      setCheckInStatus(checkInData as CheckInStatus | null);
    }).catch(() => setError(true));
  }, [user?.actorId, user?.token]);

  function dismissNotice(id: string) {
    if (!user?.token || !user?.actorId) return;
    setNotices(prev => prev.filter(n => n.id !== id));
    // 后台静默标记已读（不阻塞 UI）
    fetch(`${API}/api/students/${user.actorId}/notifications/read-all`, {
      method: "POST", headers: authHeaders(user.token),
    }).catch(() => {});
  }

  async function doCheckIn() {
    if (!user?.actorId || !user?.token || checkingIn) return;
    setCheckingIn(true);
    try {
      const res = await fetch(`${API}/api/students/${user.actorId}/check-in`, {
        method: "POST", headers: authHeaders(user.token),
      });
      const data = await res.json();
      if (data.success) {
        setCheckInStatus({
          checked_in_today: true,
          current_streak: data.current_streak,
          total_days: data.total_days,
          today_summary: data.summary,
        });
        if (data.new_achievements?.length > 0) {
          setNewAchievements(data.new_achievements);
        }
      }
    } catch {
      // ignore
    } finally {
      setCheckingIn(false);
    }
  }

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

      {/* 新成就弹窗 */}
      {newAchievements.length > 0 && (
        <div className="tp-achievement-popup">
          {newAchievements.map(a => (
            <div key={a.key} className="tp-achievement-item">
              <span className="tp-ach-icon">{a.icon}</span>
              <div className="tp-ach-body">
                <strong>解锁成就：{a.name}</strong>
                <span>{a.description}</span>
              </div>
            </div>
          ))}
          <button className="tp-ach-close" onClick={() => setNewAchievements([])}>×</button>
        </div>
      )}

      {/* 催办通知横幅 */}
      {notices.length > 0 && (
        <div className="tp-notices">
          {notices.map((n) => (
            <div key={n.id} className="tp-notice">
              <span className="tp-notice-icon">📢</span>
              <span className="tp-notice-msg">{n.message}</span>
              <button className="tp-notice-dismiss" onClick={() => dismissNotice(n.id)} aria-label="关闭">×</button>
            </div>
          ))}
        </div>
      )}
      <div className="tp-head">
        <div>
          <p className="tp-eyebrow">TODAY · 今日计划</p>
          <h2 className="tp-title">今天优先完成这些</h2>
        </div>
        <div className="tp-head-right">
          {checkInStatus && (
            <div className="tp-checkin-widget">
              {checkInStatus.checked_in_today ? (
                <div className="tp-checkin-done">
                  <span className="tp-checkin-icon">✓</span>
                  <div className="tp-checkin-info">
                    <span className="tp-streak">已打卡 · 连续 {checkInStatus.current_streak} 天</span>
                    <Link href="/student/achievements" className="tp-ach-link">查看成就 →</Link>
                  </div>
                </div>
              ) : (
                <button className="tp-checkin-btn" onClick={doCheckIn} disabled={checkingIn}>
                  {checkingIn ? "打卡中..." : "今日打卡"}
                </button>
              )}
            </div>
          )}
          {summary.overdue_assignments > 0 && (
            <span className="tp-alert">{summary.overdue_assignments} 份逾期作业</span>
          )}
        </div>
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
.tp-head-right { display:flex; flex-direction:column; align-items:flex-end; gap:6px; }
.tp-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 4px; }
.tp-title { font-size:18px; font-weight:700; margin:0; color:var(--ink,#1a1612); }
.tp-alert { font-size:12px; font-weight:600; color:#fff; background:var(--cinnabar,#b7422b); border-radius:12px; padding:4px 10px; white-space:nowrap; }
/* 打卡组件 */
.tp-checkin-widget { display:flex; align-items:center; gap:8px; }
.tp-checkin-btn { font-size:12px; font-weight:700; color:#fff; background:var(--jade,#2d6a4f); border:none; border-radius:20px; padding:6px 14px; cursor:pointer; transition:background .15s; }
.tp-checkin-btn:hover:not(:disabled) { background:#235a3f; }
.tp-checkin-btn:disabled { opacity:.6; cursor:not-allowed; }
.tp-checkin-done { display:flex; align-items:center; gap:6px; }
.tp-checkin-icon { width:22px; height:22px; border-radius:50%; background:#f0faf5; color:var(--jade,#2d6a4f); display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; flex-shrink:0; }
.tp-checkin-info { display:flex; flex-direction:column; gap:1px; }
.tp-streak { font-size:11px; font-weight:600; color:var(--jade,#2d6a4f); }
.tp-ach-link { font-size:10px; color:var(--muted,#7a7068); text-decoration:underline; }
/* 成就解锁弹窗 */
.tp-achievement-popup { position:relative; background:linear-gradient(135deg,#fff8e1,#fffde7); border:1px solid #ffd54f; border-radius:12px; padding:12px 36px 12px 14px; margin-bottom:12px; display:flex; flex-direction:column; gap:8px; }
.tp-achievement-item { display:flex; align-items:center; gap:10px; }
.tp-ach-icon { font-size:24px; flex-shrink:0; }
.tp-ach-body { display:flex; flex-direction:column; gap:2px; }
.tp-ach-body strong { font-size:14px; color:#5d4037; }
.tp-ach-body span { font-size:12px; color:#8d6e63; }
.tp-ach-close { position:absolute; top:8px; right:10px; background:none; border:none; cursor:pointer; color:#a1887f; font-size:18px; line-height:1; }
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
/* 催办通知横幅 */
.tp-notices { display:flex; flex-direction:column; gap:6px; margin-bottom:12px; }
.tp-notice { display:flex; align-items:flex-start; gap:8px; background:#fff8e1; border:1px solid #ffe082; border-radius:8px; padding:8px 10px; }
.tp-notice-icon { font-size:14px; flex-shrink:0; margin-top:1px; }
.tp-notice-msg { flex:1; font-size:12px; color:#795548; line-height:1.5; }
.tp-notice-dismiss { background:none; border:none; cursor:pointer; color:#a1887f; font-size:16px; line-height:1; padding:0 2px; flex-shrink:0; }
.tp-notice-dismiss:hover { color:#6d4c41; }
`;
