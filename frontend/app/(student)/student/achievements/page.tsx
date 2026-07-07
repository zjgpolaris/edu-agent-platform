"use client";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Achievement = {
  key: string;
  name: string;
  icon: string;
  description: string;
  unlocked_at?: string;
  progress?: number;
};

type AchievementsData = {
  unlocked: Achievement[];
  locked: Achievement[];
};

type CheckInStatus = {
  checked_in_today: boolean;
  current_streak: number;
  total_days: number;
  today_summary: string | null;
};

export default function AchievementsPage() {
  const { user } = useAuth();
  const [data, setData] = useState<AchievementsData | null>(null);
  const [status, setStatus] = useState<CheckInStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [checkingIn, setCheckingIn] = useState(false);
  const [newAchievements, setNewAchievements] = useState<Achievement[]>([]);

  const loadAchievements = useCallback(async () => {
    if (!user?.actorId || !user?.token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const [achData, statusData] = await Promise.all([
        fetch(`${API}/api/students/${user.actorId}/achievements`, { headers: authHeaders(user.token) })
          .then(r => r.ok ? r.json() : null)
          .catch(() => null),
        fetch(`${API}/api/students/${user.actorId}/check-in/status`, { headers: authHeaders(user.token) })
          .then(r => r.ok ? r.json() : null)
          .catch(() => null),
      ]);
      setData(achData);
      setStatus(statusData);
      setError(!achData && !statusData);
    } finally {
      setLoading(false);
    }
  }, [user?.actorId, user?.token]);

  useEffect(() => {
    loadAchievements();
  }, [loadAchievements]);

  async function doCheckIn() {
    if (!user?.actorId || !user?.token || checkingIn) return;
    setCheckingIn(true);
    try {
      const res = await fetch(`${API}/api/students/${user.actorId}/check-in`, {
        method: "POST", headers: authHeaders(user.token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result = await res.json();
      if (result.success) {
        setStatus({
          checked_in_today: true,
          current_streak: result.current_streak,
          total_days: result.total_days,
          today_summary: result.summary,
        });
        if (result.new_achievements?.length > 0) {
          setNewAchievements(result.new_achievements);
        }
        // 刷新成就列表；失败时保留当前 UI，不弹出运行时错误遮罩。
        fetch(`${API}/api/students/${user.actorId}/achievements`, {
          headers: authHeaders(user.token),
        })
          .then(r => r.ok ? r.json() : null)
          .then(achData => { if (achData) setData(achData); })
          .catch(() => {});
      }
    } catch {
      setError(true);
    } finally {
      setCheckingIn(false);
    }
  }

  if (loading) return <div className="ach-loading">加载中…</div>;

  return (
    <div className="ach-page">
      <style>{CSS}</style>

      <h1 className="ach-title">我的成就</h1>

      {error && (
        <div className="ach-error" role="alert">
          成就数据暂时加载失败，请确认后端服务已启动后重试。
          <button type="button" onClick={loadAchievements}>重新加载</button>
        </div>
      )}

      {/* 新成就弹窗 */}
      {newAchievements.length > 0 && (
        <div className="ach-popup">
          <div className="ach-popup-inner">
            <span className="ach-popup-title">🎉 解锁新成就！</span>
            {newAchievements.map(a => (
              <div key={a.key} className="ach-popup-item">
                <span className="ach-icon-lg">{a.icon}</span>
                <div>
                  <strong>{a.name}</strong>
                  <p>{a.description}</p>
                </div>
              </div>
            ))}
            <button className="ach-popup-close" onClick={() => setNewAchievements([])}>知道了</button>
          </div>
        </div>
      )}

      {/* 打卡面板 */}
      {status && (
        <div className="ach-checkin-panel">
          <div className="ach-streak-display">
            <span className="ach-streak-num">{status.current_streak}</span>
            <span className="ach-streak-label">连续打卡天数</span>
          </div>
          <div className="ach-streak-display">
            <span className="ach-streak-num">{status.total_days}</span>
            <span className="ach-streak-label">累计打卡天数</span>
          </div>
          <div className="ach-checkin-action">
            {status.checked_in_today ? (
              <div className="ach-checked-today">
                <span>✓</span>
                <div>
                  <strong>今日已打卡</strong>
                  {status.today_summary && <p>{status.today_summary}</p>}
                </div>
              </div>
            ) : (
              <button className="ach-checkin-btn" onClick={doCheckIn} disabled={checkingIn}>
                {checkingIn ? "打卡中…" : "今日打卡 ✎"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* 已解锁成就 */}
      {data && data.unlocked.length > 0 && (
        <section className="ach-section">
          <h2 className="ach-section-title">已解锁 ({data.unlocked.length})</h2>
          <div className="ach-grid">
            {data.unlocked.map(a => (
              <div key={a.key} className="ach-card ach-card--unlocked">
                <span className="ach-card-icon">{a.icon}</span>
                <strong className="ach-card-name">{a.name}</strong>
                <span className="ach-card-desc">{a.description}</span>
                {a.unlocked_at && (
                  <span className="ach-card-date">
                    {new Date(a.unlocked_at).toLocaleDateString("zh-CN")}
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 未解锁成就 */}
      {data && data.locked.length > 0 && (
        <section className="ach-section">
          <h2 className="ach-section-title">努力解锁 ({data.locked.length})</h2>
          <div className="ach-grid">
            {data.locked.map(a => (
              <div key={a.key} className="ach-card ach-card--locked">
                <span className="ach-card-icon ach-card-icon--gray">{a.icon}</span>
                <strong className="ach-card-name">{a.name}</strong>
                <span className="ach-card-desc">{a.description}</span>
                {a.progress !== undefined && a.progress > 0 && (
                  <div className="ach-progress-bar">
                    <div className="ach-progress-fill" style={{ width: `${Math.round(a.progress * 100)}%` }} />
                    <span className="ach-progress-label">{Math.round(a.progress * 100)}%</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {data && data.unlocked.length === 0 && data.locked.length === 0 && (
        <p className="ach-empty">开始每日打卡，解锁你的第一个成就吧！</p>
      )}
    </div>
  );
}

const CSS = `
.ach-loading { padding:40px; text-align:center; color:var(--muted,#7a7068); }
.ach-page { max-width:700px; margin:0 auto; padding:24px 20px 48px; }
.ach-title { font-size:22px; font-weight:700; color:var(--ink,#1a1612); margin:0 0 20px; }
.ach-error { display:flex; align-items:center; justify-content:space-between; gap:12px; background:#fff7ed; border:1px solid #fed7aa; color:#9a3412; border-radius:12px; padding:12px 14px; margin-bottom:18px; font-size:13px; }
.ach-error button { border:none; border-radius:16px; background:#ea580c; color:#fff; font-size:12px; font-weight:700; padding:6px 12px; cursor:pointer; white-space:nowrap; }
/* 打卡面板 */
.ach-checkin-panel { display:flex; align-items:center; gap:20px; background:linear-gradient(135deg,#f0faf5,#e8f5e9); border:1px solid #a5d6a7; border-radius:14px; padding:18px 22px; margin-bottom:28px; flex-wrap:wrap; }
.ach-streak-display { display:flex; flex-direction:column; align-items:center; gap:2px; min-width:70px; }
.ach-streak-num { font-size:32px; font-weight:800; color:var(--jade,#2d6a4f); line-height:1; }
.ach-streak-label { font-size:11px; color:#558b2f; }
.ach-checkin-action { flex:1; display:flex; align-items:center; justify-content:flex-end; }
.ach-checkin-btn { font-size:15px; font-weight:700; color:#fff; background:var(--jade,#2d6a4f); border:none; border-radius:24px; padding:10px 24px; cursor:pointer; transition:background .15s; }
.ach-checkin-btn:hover:not(:disabled) { background:#235a3f; }
.ach-checkin-btn:disabled { opacity:.6; cursor:not-allowed; }
.ach-checked-today { display:flex; align-items:center; gap:10px; }
.ach-checked-today > span { width:32px; height:32px; border-radius:50%; background:#2d6a4f; color:#fff; display:flex; align-items:center; justify-content:center; font-size:16px; font-weight:700; flex-shrink:0; }
.ach-checked-today strong { font-size:14px; color:#2d6a4f; display:block; }
.ach-checked-today p { font-size:12px; color:#558b2f; margin:2px 0 0; }
/* 成就弹窗 */
.ach-popup { position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:1000; display:flex; align-items:center; justify-content:center; padding:20px; }
.ach-popup-inner { background:#fff; border-radius:16px; padding:24px; max-width:380px; width:100%; display:flex; flex-direction:column; gap:14px; }
.ach-popup-title { font-size:18px; font-weight:700; color:var(--ink,#1a1612); text-align:center; }
.ach-popup-item { display:flex; align-items:center; gap:12px; }
.ach-icon-lg { font-size:36px; flex-shrink:0; }
.ach-popup-item strong { font-size:15px; display:block; }
.ach-popup-item p { font-size:13px; color:var(--muted,#7a7068); margin:2px 0 0; }
.ach-popup-close { align-self:center; font-size:14px; font-weight:600; color:#fff; background:var(--jade,#2d6a4f); border:none; border-radius:20px; padding:8px 24px; cursor:pointer; }
/* 成就列表 */
.ach-section { margin-bottom:24px; }
.ach-section-title { font-size:15px; font-weight:700; color:var(--ink,#1a1612); margin:0 0 12px; }
.ach-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; }
.ach-card { border-radius:12px; padding:16px 12px; display:flex; flex-direction:column; align-items:center; gap:6px; text-align:center; border:1px solid; }
.ach-card--unlocked { background:#fffde7; border-color:#ffd54f; }
.ach-card--locked { background:#f5f5f5; border-color:#e0e0e0; }
.ach-card-icon { font-size:28px; }
.ach-card-icon--gray { filter:grayscale(1) opacity(.5); }
.ach-card-name { font-size:13px; font-weight:700; color:var(--ink,#1a1612); }
.ach-card-desc { font-size:11px; color:var(--muted,#7a7068); }
.ach-card-date { font-size:10px; color:#aaa; margin-top:2px; }
.ach-progress-bar { width:100%; height:6px; background:#e0e0e0; border-radius:3px; margin-top:4px; position:relative; }
.ach-progress-fill { height:100%; background:var(--jade,#2d6a4f); border-radius:3px; transition:width .3s; }
.ach-progress-label { position:absolute; right:0; top:-14px; font-size:10px; color:var(--muted,#7a7068); }
.ach-empty { font-size:14px; color:var(--muted,#7a7068); text-align:center; padding:32px 0; }
`;
