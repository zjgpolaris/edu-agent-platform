"use client";
import Link from "next/link";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApiJson, normalizeError } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Weakpoint = {
  knowledge_tag: string;
  wrong_count: number;
  last_wrong_at: string;
  source: string;
  correct_streak?: number;
};
type MasteryHeatmapItem = {
  tag: string; strength: number;
  wrong_count: number; correct_streak: number; last_reviewed: string;
};
type MasteryOverview = {
  total_tags: number; mastered: number; learning: number; weak: number;
  streak_days: number; heatmap: MasteryHeatmapItem[];
};

const SOURCE_LABEL: Record<string, string> = {
  homework_grading: "作业批改", game: "游戏答题", timeline_game: "时间轴游戏",
  card_game: "卡牌游戏", multiplayer_game: "多人游戏",
  textbook_guide: "教材问答", quiz: "测验练习",
};
const SOURCE_ICON: Record<string, string> = {
  homework_grading: "📝", game: "🎮", timeline_game: "⏱",
  card_game: "🃏", multiplayer_game: "🏆", textbook_guide: "📖", quiz: "✏️",
};

const CSS = `
.wp-stage {
  position: relative;
  isolation: isolate;
  min-height: calc(100vh - 62px);
  padding: 34px 24px 82px;
  overflow: hidden;
}
.wp-stage::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -2;
  background:
    radial-gradient(circle at 14% 12%, rgba(183, 66, 43, .14), transparent 250px),
    radial-gradient(circle at 86% 10%, rgba(15, 107, 95, .13), transparent 300px),
    linear-gradient(135deg, rgba(244, 234, 213, .86), rgba(251, 246, 234, .72));
}
.wp-stage::after {
  content: "错 因 归 档 · 温 故 知 新";
  position: absolute;
  right: -34px;
  top: 28px;
  z-index: -1;
  writing-mode: vertical-rl;
  font-family: var(--font-display-family);
  font-size: clamp(44px, 8vw, 92px);
  letter-spacing: .28em;
  color: rgba(96, 72, 44, .055);
  pointer-events: none;
}
.wp-wrap { max-width: 1100px; margin: 0 auto; }
.wp-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 18px;
  align-items: stretch;
  margin-bottom: 18px;
}
.wp-title-card,
.wp-command-card,
.wp-panel,
.wp-empty,
.wp-error {
  border: 1px solid rgba(96, 72, 44, .16);
  background: linear-gradient(145deg, rgba(255, 252, 244, .82), rgba(246, 238, 219, .66));
  box-shadow: 0 18px 52px rgba(59, 39, 19, .11), inset 0 1px 0 rgba(255, 255, 255, .58);
  backdrop-filter: blur(10px);
}
.wp-title-card { position: relative; overflow: hidden; border-radius: 30px; padding: 28px 30px; }
.wp-title-card::after {
  content: "";
  position: absolute;
  width: 190px;
  height: 190px;
  right: -70px;
  bottom: -86px;
  border: 1px solid rgba(183, 66, 43, .2);
  border-radius: 999px;
  box-shadow: inset 0 0 0 22px rgba(183, 66, 43, .04), inset 0 0 0 46px rgba(184, 139, 62, .035);
}
.wp-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 8px;
  color: var(--cinnabar);
  font-family: var(--font-accent-family);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .22em;
  text-transform: uppercase;
}
.wp-eyebrow::before { content: ""; width: 26px; height: 1px; background: currentColor; }
.wp-title-card h1 { margin: 0; font-size: clamp(28px, 4vw, 46px); letter-spacing: .08em; color: var(--ink); }
.wp-title-card p { max-width: 640px; margin: 12px 0 0; color: var(--ink-soft); line-height: 1.9; font-size: 15px; }
.wp-hero-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.wp-action-primary,
.wp-action-secondary,
.wp-action-danger,
.wp-link-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 36px;
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 850;
  text-decoration: none;
  border: 1px solid transparent;
  transition: transform var(--ease), box-shadow var(--ease), background var(--ease), border-color var(--ease), color var(--ease);
}
.wp-action-primary { color: #fffaf0; background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-dark)); box-shadow: 0 12px 26px rgba(183, 66, 43, .22); }
.wp-action-secondary { color: var(--jade-dark); background: rgba(15, 107, 95, .08); border-color: rgba(15, 107, 95, .18); }
.wp-action-primary:hover,
.wp-action-secondary:hover,
.wp-link-button:hover { transform: translateY(-2px); box-shadow: 0 14px 28px rgba(59, 39, 19, .12); }
.wp-command-card { border-radius: 30px; padding: 20px; display: flex; flex-direction: column; justify-content: space-between; }
.wp-seal {
  align-self: flex-start;
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(183, 66, 43, .28);
  border-radius: 18px;
  color: var(--cinnabar);
  background: rgba(183, 66, 43, .055);
  font-family: var(--font-display-family);
  font-size: 28px;
  box-shadow: inset 0 0 0 5px rgba(255, 255, 255, .38);
}
.wp-command-card strong { display: block; margin: 14px 0 8px; font-size: 17px; color: var(--ink); }
.wp-command-card p { margin: 0; color: var(--muted); line-height: 1.75; font-size: 13px; }
.wp-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.wp-stat {
  border: 1px solid rgba(96, 72, 44, .13);
  border-radius: 22px;
  padding: 16px;
  background: rgba(255, 252, 244, .66);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.55);
}
.wp-stat span { display: block; color: var(--muted); font-size: 12px; letter-spacing: .1em; font-weight: 800; }
.wp-stat strong { display: block; margin-top: 5px; color: var(--ink); font-size: 28px; line-height: 1; font-family: var(--font-accent-family); }
.wp-grid { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 18px; align-items: start; }
.wp-panel { border-radius: 26px; padding: 22px; }
.wp-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.wp-kicker { margin: 0 0 4px; color: var(--cinnabar); font-size: 11px; font-weight: 900; letter-spacing: .18em; }
.wp-panel h2 { margin: 0; font-size: 20px; letter-spacing: .05em; }
.wp-badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 5px 10px; color: var(--cinnabar); background: rgba(183, 66, 43, .08); border: 1px solid rgba(183, 66, 43, .16); font-size: 12px; font-weight: 900; }
.wp-action-danger { color: var(--cinnabar-dark); background: rgba(183, 66, 43, .06); border-color: rgba(183, 66, 43, .18); cursor: pointer; }
.wp-action-danger:disabled { opacity: .54; cursor: wait; }
.wp-heat-grid { display: flex; flex-wrap: wrap; gap: 9px; }
.wp-heat-tile {
  position: relative;
  min-width: 86px;
  display: inline-flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 16px;
  text-decoration: none;
  border: 1px solid color-mix(in srgb, var(--tile-fg) 18%, transparent);
  color: var(--tile-fg);
  background:
    linear-gradient(160deg, rgba(255,255,255,.44), rgba(255,255,255,0)),
    var(--tile-bg);
  transition: transform var(--ease-spring), box-shadow var(--ease), filter var(--ease);
}
.wp-heat-tile:hover { transform: translateY(-3px) rotate(-1deg); box-shadow: 0 14px 28px rgba(59, 39, 19, .12); filter: saturate(1.04); }
.wp-heat-tile strong { font-size: 13px; line-height: 1.35; }
.wp-heat-tile span { font-size: 11px; opacity: .78; font-weight: 800; }
.wp-legend { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 14px; color: var(--muted); font-size: 12px; font-weight: 800; }
.wp-list-section + .wp-list-section { margin-top: 18px; }
.wp-list-title { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; color: var(--ink-soft); font-size: 13px; font-weight: 900; letter-spacing: .12em; }
.wp-cards { display: flex; flex-direction: column; gap: 10px; }
.wp-card {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 14px;
  border-radius: 20px;
  border: 1px solid rgba(96, 72, 44, .13);
  background: rgba(255, 252, 244, .62);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.55);
  transition: transform var(--ease), box-shadow var(--ease), border-color var(--ease);
}
.wp-card:hover { transform: translateX(4px); border-color: rgba(183, 66, 43, .22); box-shadow: 0 12px 30px rgba(59, 39, 19, .09); }
.wp-card-icon { width: 44px; height: 44px; display: grid; place-items: center; border-radius: 15px; background: rgba(96, 72, 44, .07); font-size: 22px; }
.wp-card-main { min-width: 0; }
.wp-card-main strong { display: block; color: var(--ink); font-size: 15px; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wp-meta { display: flex; flex-wrap: wrap; gap: 7px; color: var(--muted); font-size: 12px; }
.wp-pill { color: var(--pill-fg); background: var(--pill-bg); border: 1px solid color-mix(in srgb, var(--pill-fg) 16%, transparent); border-radius: 999px; padding: 3px 9px; font-size: 11px; font-weight: 900; white-space: nowrap; }
.wp-card-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.wp-link-button { color: var(--jade-dark); background: rgba(15, 107, 95, .08); border-color: rgba(15, 107, 95, .18); }
.wp-delete { border: 1px solid rgba(96, 72, 44, .16); background: rgba(255,255,255,.38); color: var(--muted); border-radius: 999px; padding: 7px 10px; font-size: 12px; font-weight: 800; cursor: pointer; }
.wp-delete:hover:not(:disabled) { color: var(--cinnabar); border-color: rgba(183, 66, 43, .22); }
.wp-delete:disabled { opacity: .56; cursor: wait; }
.wp-empty,
.wp-error { border-radius: 24px; padding: 34px 24px; text-align: center; color: var(--muted); }
.wp-empty strong { display: block; margin-bottom: 8px; color: var(--ink); font-size: 18px; }
.wp-side-list { display: grid; gap: 10px; }
.wp-side-row { display: flex; justify-content: space-between; gap: 10px; padding: 11px 0; border-bottom: 1px dashed rgba(96, 72, 44, .16); color: var(--ink-soft); font-size: 13px; }
.wp-side-row:last-child { border-bottom: 0; }
.wp-side-row strong { color: var(--ink); }
@media (max-width: 980px) {
  .wp-hero, .wp-grid { grid-template-columns: 1fr; }
  .wp-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .wp-stage { padding: 22px 14px 92px; }
  .wp-title-card, .wp-command-card, .wp-panel { border-radius: 22px; padding: 18px; }
  .wp-stats { grid-template-columns: 1fr 1fr; }
  .wp-card { grid-template-columns: auto minmax(0, 1fr); }
  .wp-card-actions { grid-column: 1 / -1; justify-content: flex-start; }
}
`;

function urgency(count: number): { label: string; color: string; level: "urgent" | "normal" } {
  if (count >= 5) return { label: "重点攻克", color: "#dc2626", level: "urgent" };
  if (count >= 3) return { label: "需要复习", color: "#d97706", level: "urgent" };
  return { label: "待巩固", color: "#4b9560", level: "normal" };
}
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86400000);
  if (!Number.isFinite(days)) return "时间未知";
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 30) return `${days} 天前`;
  return `${Math.floor(days / 30)} 个月前`;
}
function strengthColor(s: number): { bg: string; fg: string; label: string } {
  if (s >= 0.7) return { bg: "#d1fae5", fg: "#065f46", label: "掌握" };
  if (s >= 0.4) return { bg: "#fef3c7", fg: "#92400e", label: "学习中" };
  return { bg: "#fee2e2", fg: "#991b1b", label: "薄弱" };
}

function StatCard({ label, value, suffix }: { label: string; value: number | string; suffix?: string }) {
  return (
    <div className="wp-stat">
      <span>{label}</span>
      <strong>{value}{suffix ? <small style={{ fontSize: 13, marginLeft: 4 }}>{suffix}</small> : null}</strong>
    </div>
  );
}

function MasteryHeatmap({ mastery }: { mastery: MasteryOverview }) {
  const sorted = [...mastery.heatmap].sort((a, b) => a.strength - b.strength);
  return (
    <section className="wp-panel" aria-label="掌握度热力图">
      <div className="wp-panel-head">
        <div>
          <p className="wp-kicker">MASTERY MAP</p>
          <h2>掌握度热力图</h2>
        </div>
        <span className="wp-badge">{mastery.total_tags} 个知识点</span>
      </div>
      <div className="wp-heat-grid">
        {sorted.map((item) => {
          const { bg, fg, label } = strengthColor(item.strength);
          return (
            <Link
              key={item.tag}
              className="wp-heat-tile"
              href={`/student/auto-tutor?focus=${encodeURIComponent(item.tag)}`}
              title={`${item.tag}｜${label}｜出错 ${item.wrong_count} 次｜连对 ${item.correct_streak} 次`}
              style={{ "--tile-bg": bg, "--tile-fg": fg } as CSSProperties}
            >
              <strong>{item.tag}</strong>
              <span>{label} · ×{item.wrong_count}</span>
            </Link>
          );
        })}
      </div>
      <div className="wp-legend">
        <span style={{ color: "#065f46" }}>● 掌握 {mastery.mastered}</span>
        <span style={{ color: "#92400e" }}>● 学习中 {mastery.learning}</span>
        <span style={{ color: "#991b1b" }}>● 薄弱 {mastery.weak}</span>
      </div>
    </section>
  );
}

function WeakCard({ wp, onDelete, deleting }: {
  wp: Weakpoint; onDelete: (tag: string) => void; deleting: string | null;
}) {
  const u = urgency(wp.wrong_count);
  const icon = SOURCE_ICON[wp.source] ?? "📌";
  const sourceLabel = SOURCE_LABEL[wp.source] ?? wp.source;
  const isDeleting = deleting === wp.knowledge_tag;
  return (
    <article className="wp-card">
      <div className="wp-card-icon" aria-hidden="true">{icon}</div>
      <div className="wp-card-main">
        <strong>{wp.knowledge_tag}</strong>
        <div className="wp-meta">
          <span>{sourceLabel}</span>
          <span>出错 {wp.wrong_count} 次</span>
          <span>{timeAgo(wp.last_wrong_at)}</span>
          {typeof wp.correct_streak === "number" && wp.correct_streak > 0 && <span>连对 {wp.correct_streak}</span>}
        </div>
      </div>
      <div className="wp-card-actions">
        <span
          className="wp-pill"
          style={{ "--pill-fg": u.color, "--pill-bg": `${u.color}16` } as CSSProperties}
        >
          {u.label}
        </span>
        <Link
          href={`/student/auto-tutor?focus=${encodeURIComponent(wp.knowledge_tag)}`}
          className="wp-link-button"
          title="让 AutoTutor 针对这个薄弱点自主规划一节课"
        >
          AutoTutor 精讲
        </Link>
        <button className="wp-delete" onClick={() => onDelete(wp.knowledge_tag)} disabled={isDeleting}>
          {isDeleting ? "删除中" : "删除"}
        </button>
      </div>
    </article>
  );
}

function WeakGroup({ title, items, onDelete, deleting }: {
  title: string; items: Weakpoint[];
  onDelete: (tag: string) => void; deleting: string | null;
}) {
  if (items.length === 0) return null;
  return (
    <section className="wp-list-section">
      <h3 className="wp-list-title">{title}</h3>
      <div className="wp-cards">
        {items.map((wp) => <WeakCard key={wp.knowledge_tag} wp={wp} onDelete={onDelete} deleting={deleting} />)}
      </div>
    </section>
  );
}

export default function WeakpointsTab() {
  const { user } = useAuth();
  const id    = user?.actorId;
  const token = user?.token;

  const [weakpoints, setWeakpoints] = useState<Weakpoint[]>([]);
  const [mastery,    setMastery]    = useState<MasteryOverview | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState("");
  const [clearing,   setClearing]   = useState(false);
  const [deleting,   setDeleting]   = useState<string | null>(null);

  useEffect(() => {
    if (!id || !token) { setLoading(false); return; }
    let cancelled = false;
    async function load() {
      setLoading(true); setError("");
      try {
        const [wpData, masteryData] = await Promise.all([
          fetchApiJson<{ weakpoints: Weakpoint[] }>(`/api/student/${id}/weakpoints`, {
            token: token!, fallbackMessage: "错题库加载失败",
          }),
          fetch(`${API}/api/students/${id}/mastery-overview`, { headers: authHeaders(token!) })
            .then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        if (!cancelled) {
          setWeakpoints(wpData.weakpoints || []);
          setMastery(masteryData ?? null);
        }
      } catch (err) {
        if (!cancelled) setError(normalizeError(err, "错题库加载失败"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [id, token]);

  async function clearAll() {
    if (!id || !token || !window.confirm("确认清空所有错题记录？")) return;
    setClearing(true);
    try {
      await fetch(`${API}/api/student/${id}/weakpoints`, {
        method: "DELETE", headers: authHeaders(token),
      });
      setWeakpoints([]);
    } catch { /* silent */ } finally { setClearing(false); }
  }

  async function deleteWeakpoint(tag: string) {
    if (!id || !token) return;
    setDeleting(tag);
    try {
      await fetch(`${API}/api/student/${id}/weakpoints/${encodeURIComponent(tag)}`, {
        method: "DELETE", headers: authHeaders(token),
      });
      setWeakpoints((prev) => prev.filter((wp) => wp.knowledge_tag !== tag));
    } catch { /* silent */ } finally { setDeleting(null); }
  }

  const { urgent, normal, mostRepeated } = useMemo(() => {
    const sorted = [...weakpoints].sort((a, b) => b.wrong_count - a.wrong_count);
    return {
      urgent: sorted.filter((w) => w.wrong_count >= 3),
      normal: sorted.filter((w) => w.wrong_count < 3),
      mostRepeated: sorted[0],
    };
  }, [weakpoints]);

  const weakCount = mastery?.weak ?? urgent.length;
  const learningCount = mastery?.learning ?? normal.length;
  const masteredCount = mastery?.mastered ?? 0;
  const firstFocus = mostRepeated?.knowledge_tag || mastery?.heatmap?.[0]?.tag || "";

  return (
    <main className="wp-stage">
      <style>{CSS}</style>
      <div className="wp-wrap">
        <section className="wp-hero">
          <div className="wp-title-card">
            <p className="wp-eyebrow">Weakpoint Archive</p>
            <h1>错因档案馆</h1>
            <p>
              把每一次失误整理成可追踪的知识坐标：先看薄弱热区，再进入 AutoTutor 精讲，最后回到今日任务完成巩固。
            </p>
            <div className="wp-hero-actions">
              <Link className="wp-action-primary" href={firstFocus ? `/student/auto-tutor?focus=${encodeURIComponent(firstFocus)}` : "/student/auto-tutor"}>
                {firstFocus ? `精讲「${firstFocus}」` : "打开 AutoTutor"}
              </Link>
              <Link className="wp-action-secondary" href="/student/review">
                回到今日任务
              </Link>
            </div>
          </div>
          <aside className="wp-command-card" aria-label="复习建议">
            <div>
              <span className="wp-seal">错</span>
              <strong>{mostRepeated ? `优先攻克：${mostRepeated.knowledge_tag}` : "暂无重点错因"}</strong>
              <p>
                {mostRepeated
                  ? `该知识点累计出错 ${mostRepeated.wrong_count} 次，建议先听一次针对性讲解，再做变式题。`
                  : "完成练习或作业批改后，系统会自动沉淀错因档案。"}
              </p>
            </div>
          </aside>
        </section>

        <section className="wp-stats" aria-label="错题统计">
          <StatCard label="错题档案" value={weakpoints.length} />
          <StatCard label="薄弱知识" value={weakCount} />
          <StatCard label="学习中" value={learningCount} />
          <StatCard label="已掌握" value={masteredCount} />
        </section>

        {loading && <div className="wp-empty">正在加载错因档案…</div>}
        {error && <div className="wp-error"><p>{error}</p></div>}

        {!loading && !error && weakpoints.length === 0 && (
          <div className="wp-empty">
            <strong>暂无错题记录</strong>
            <p>完成练习、作业批改或历史游戏后，答错的知识点会自动归档到这里。</p>
            <div className="wp-hero-actions" style={{ justifyContent: "center" }}>
              <Link className="wp-action-primary" href="/student/quiz">去做智能练习</Link>
              <Link className="wp-action-secondary" href="/student/assignments">查看我的作业</Link>
            </div>
          </div>
        )}

        {!loading && !error && weakpoints.length > 0 && (
          <div className="wp-grid">
            <section className="wp-panel">
              <div className="wp-panel-head">
                <div>
                  <p className="wp-kicker">ERROR RECORDS</p>
                  <h2>知识点错误记录</h2>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <span className="wp-badge">{weakpoints.length} 个</span>
                  <button className="wp-action-danger" onClick={clearAll} disabled={clearing}>
                    {clearing ? "清空中…" : "清空全部"}
                  </button>
                </div>
              </div>
              <WeakGroup title="⚠️ 重点攻克" items={urgent} onDelete={deleteWeakpoint} deleting={deleting} />
              <WeakGroup title="📌 待巩固" items={normal} onDelete={deleteWeakpoint} deleting={deleting} />
            </section>

            <aside className="wp-side-list">
              {mastery && mastery.heatmap.length > 0 && <MasteryHeatmap mastery={mastery} />}
              <section className="wp-panel">
                <div className="wp-panel-head" style={{ marginBottom: 6 }}>
                  <div>
                    <p className="wp-kicker">ROUTE CHECK</p>
                    <h2>跳转核查</h2>
                  </div>
                </div>
                <div className="wp-side-row"><span>今日任务</span><Link href="/student/review"><strong>可达</strong></Link></div>
                <div className="wp-side-row"><span>错题库入口</span><Link href="/student/review?tab=weakpoints"><strong>当前页</strong></Link></div>
                <div className="wp-side-row"><span>AutoTutor</span><Link href={firstFocus ? `/student/auto-tutor?focus=${encodeURIComponent(firstFocus)}` : "/student/auto-tutor"}><strong>可达</strong></Link></div>
                {mastery?.streak_days ? (
                  <div className="wp-side-row"><span>连续复习</span><strong>{mastery.streak_days} 天</strong></div>
                ) : null}
              </section>
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}
