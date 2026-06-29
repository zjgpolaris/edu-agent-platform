"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApiJson, normalizeError } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Weakpoint = {
  knowledge_tag: string;
  wrong_count: number;
  last_wrong_at: string;
  source: string;
};

const SOURCE_LABEL: Record<string, string> = {
  homework_grading: "作业批改",
  game: "游戏答题",
  timeline_game: "时间轴游戏",
  card_game: "卡牌游戏",
  multiplayer_game: "多人游戏",
  textbook_guide: "教材问答",
  quiz: "测验练习",
};

const SOURCE_ICON: Record<string, string> = {
  homework_grading: "📝",
  game: "🎮",
  timeline_game: "⏱",
  card_game: "🃏",
  multiplayer_game: "🏆",
  textbook_guide: "📖",
  quiz: "✏️",
};

function urgency(count: number): { label: string; color: string } {
  if (count >= 5) return { label: "重点攻克", color: "#dc2626" };
  if (count >= 3) return { label: "需要复习", color: "#d97706" };
  return { label: "待巩固", color: "#4b9560" };
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 30) return `${days} 天前`;
  return `${Math.floor(days / 30)} 个月前`;
}

export default function WeakpointsPage() {
  const { user } = useAuth();
  const [weakpoints, setWeakpoints] = useState<Weakpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clearing, setClearing] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const id = user?.actorId;
  const token = user?.token;

  useEffect(() => {
    if (!id || !token) { setLoading(false); return; }
    let cancelled = false;
    async function load() {
      setLoading(true); setError("");
      try {
        const data = await fetchApiJson<{ weakpoints: Weakpoint[] }>(`/api/student/${id}/weakpoints`, {
          token: token!,
          fallbackMessage: "错题本加载失败",
        });
        if (!cancelled) setWeakpoints(data.weakpoints || []);
      } catch (err) {
        if (!cancelled) setError(normalizeError(err, "错题本加载失败"));
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

  const urgent = weakpoints.filter((w) => w.wrong_count >= 3);
  const normal = weakpoints.filter((w) => w.wrong_count < 3);

  return (
    <main className="academy-shell">
      <section className="academy-hero">
        <div className="hero-copy">
          <span className="eyebrow">Error Tracker</span>
          <h1>错题本</h1>
          <p>答对练习题后自动从错题本移除，通过复习确认掌握。</p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">WEAK POINTS</p>
            <h2>知识点错误记录</h2>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <Link className="primary-link" href="/student/learning-path" style={{ fontSize: "0.85rem", fontWeight: 600 }}>
              查看复习路径 →
            </Link>
            <span className="soft-badge">{weakpoints.length} 个</span>
            {weakpoints.length > 0 && (
              <button className="secondary" onClick={clearAll} disabled={clearing}
                style={{ fontSize: "0.8rem", padding: "4px 10px" }}>
                {clearing ? "清空中..." : "清空全部"}
              </button>
            )}
          </div>
        </div>

        {loading && <p className="empty-hint">正在加载错题记录...</p>}
        {error && <div className="error-card"><p>{error}</p></div>}
        {!loading && !error && weakpoints.length === 0 && (
          <div className="material-empty-state">
            <strong>暂无错题记录</strong>
            <p>完成练习答错后自动记入，再次答对后自动移除。</p>
          </div>
        )}

        {urgent.length > 0 && (
          <WeakGroup title="⚠️ 重点攻克" items={urgent} onDelete={deleteWeakpoint} deleting={deleting} />
        )}
        {normal.length > 0 && (
          <WeakGroup title="📌 待巩固" items={normal} onDelete={deleteWeakpoint} deleting={deleting} />
        )}
      </section>
    </main>
  );
}

function WeakGroup({ title, items, onDelete, deleting }: { title: string; items: Weakpoint[]; onDelete: (tag: string) => void; deleting: string | null }) {
  return (
    <div style={{ marginBottom: "24px" }}>
      <p style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted, #6b7280)", marginBottom: "8px", letterSpacing: "0.05em" }}>
        {title}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {items.map((wp) => <WeakCard key={wp.knowledge_tag} wp={wp} onDelete={onDelete} deleting={deleting} />)}
      </div>
    </div>
  );
}

function WeakCard({ wp, onDelete, deleting }: { wp: Weakpoint; onDelete: (tag: string) => void; deleting: string | null }) {
  const u = urgency(wp.wrong_count);
  const icon = SOURCE_ICON[wp.source] ?? "📌";
  const sourceLabel = SOURCE_LABEL[wp.source] ?? wp.source;
  const isDeleting = deleting === wp.knowledge_tag;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "12px",
      padding: "12px 16px", borderRadius: "8px",
      background: "var(--surface-alt, #f9f9f8)",
      border: "1px solid var(--border-subtle, #e5e7eb)",
    }}>
      <span style={{ fontSize: "1.4rem", flexShrink: 0 }}>{icon}</span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontWeight: 600, marginBottom: "2px", fontSize: "0.95rem" }}>{wp.knowledge_tag}</p>
        <p style={{ fontSize: "0.78rem", color: "var(--text-muted, #6b7280)" }}>
          {sourceLabel} · 出错 {wp.wrong_count} 次 · {timeAgo(wp.last_wrong_at)}
        </p>
      </div>

      <span style={{
        fontSize: "0.72rem", fontWeight: 600, padding: "2px 8px",
        borderRadius: "999px", background: u.color + "18", color: u.color,
        flexShrink: 0,
      }}>
        {u.label}
      </span>

      <Link
        href={`/learning-assistant?q=${encodeURIComponent(`帮我复习知识点「${wp.knowledge_tag}」，先简要解释，再出一道练习题考考我`)}`}
        className="primary-link"
        style={{ fontSize: "0.82rem", flexShrink: 0, fontWeight: 500 }}
      >
        复习 →
      </Link>

      <button
        onClick={() => onDelete(wp.knowledge_tag)}
        disabled={isDeleting}
        style={{
          fontSize: "0.82rem",
          padding: "4px 8px",
          border: "1px solid var(--border, #e5e7eb)",
          background: "var(--bg, #ffffff)",
          borderRadius: "4px",
          cursor: isDeleting ? "not-allowed" : "pointer",
          color: "var(--text-muted, #6b7280)",
          flexShrink: 0,
        }}
      >
        {isDeleting ? "删除中..." : "删除"}
      </button>
    </div>
  );
}
