"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Textbook = {
  id: string; grade: string; book: string; source: string;
  status: "ready" | "empty" | "invalid";
  unit_count: number; lesson_count: number; item_count: number;
  message?: string | null;
};

function statusLabel(s: Textbook["status"]) {
  if (s === "ready") return "可学习";
  if (s === "empty") return "待补全";
  return "需检查";
}
function statusColor(s: Textbook["status"]) {
  if (s === "ready") return "#2d6a4f";
  if (s === "empty") return "#d97706";
  return "#dc2626";
}

const SKELETON_CSS = `
.tb-skeleton-panel { overflow:hidden; }
.tb-skel-head { display:flex; justify-content:space-between; gap:12px; margin-bottom:14px; }
.tb-skel-head span, .tb-skel-head i, .tb-skel-line, .tb-skel-grid b { display:block; border-radius:12px; background:linear-gradient(90deg,#f2eadc 0%,#fffaf0 48%,#f2eadc 100%); background-size:220% 100%; animation:tbShimmer 1.2s ease-in-out infinite; }
.tb-skel-head span { width:210px; height:30px; }
.tb-skel-head i { width:64px; height:24px; }
.tb-skel-line { width:72%; height:12px; margin-bottom:20px; }
.tb-skel-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:16px; }
.tb-skel-grid b { height:132px; }
@keyframes tbShimmer { 0%{background-position:120% 0} 100%{background-position:-120% 0} }
`;

export default function TextbookTab() {
  const { user, ready } = useAuth();
  const [textbooks, setTextbooks] = useState<Textbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    if (!user?.token) {
      setLoading(false);
      setError(true);
      return () => { cancelled = true; };
    }
    setLoading(true);
    setError(false);
    fetch(`${API}/api/textbooks`, { cache: "no-store", headers: authHeaders(user.token) })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { if (!cancelled) { setTextbooks(d.textbooks || []); } })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ready, user?.token]);

  if (loading) return (
    <section className="panel tb-skeleton-panel" style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px" }} aria-busy="true" aria-label="教材列表加载中">
      <style>{SKELETON_CSS}</style>
      <div className="tb-skel-head"><span /><i /></div>
      <div className="tb-skel-line" />
      <div className="tb-skel-grid">
        <b /><b /><b />
      </div>
    </section>
  );

  if (error) return (
    <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--muted)" }}>
      <p style={{ fontWeight: 700, color: "var(--ink)", marginBottom: 6 }}>教材目录加载失败</p>
      <p>请确认已登录，或稍后重试。</p>
    </div>
  );

  if (textbooks.length === 0) return (
    <div className="material-empty-state" style={{ margin: "40px auto", maxWidth: 480 }}>
      <strong>暂无教材</strong>
      <p>管理员尚未导入课程教材，请稍后再试。</p>
    </div>
  );

  return (
    <section className="panel" style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px" }}>
      <div className="panel-heading-row">
        <div>
          <p className="section-kicker">TEXTBOOK</p>
          <h2>教材同步学习</h2>
        </div>
        <span className="soft-badge">{textbooks.length} 册</span>
      </div>
      <p style={{ fontSize: "0.88rem", color: "var(--muted)", marginBottom: "20px" }}>
        按教材目录进入每一课，围绕结构化知识点进行解释、摘要、笔记和自测。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "16px" }}>
        {textbooks.map((book) => (
          <Link
            key={book.id}
            href={`/textbook-learning/${book.id}`}
            style={{
              display: "block", padding: "18px 20px", borderRadius: "10px",
              background: "var(--paper-soft, #fdfbf7)",
              border: "1px solid var(--border)",
              textDecoration: "none", color: "inherit",
              transition: "box-shadow .18s, border-color .18s",
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 16px rgba(0,0,0,.08)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.boxShadow = ""; (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, letterSpacing: ".1em", color: "var(--muted)" }}>
                {book.grade}
              </span>
              <span style={{ fontSize: "0.7rem", fontWeight: 600, color: statusColor(book.status) }}>
                {statusLabel(book.status)}
              </span>
            </div>
            <p style={{ fontWeight: 700, fontSize: "1rem", marginBottom: "10px", color: "var(--ink)" }}>
              {book.book}
            </p>
            <div style={{ display: "flex", gap: "12px", fontSize: "0.75rem", color: "var(--muted)" }}>
              <span>{book.unit_count} 单元</span>
              <span>{book.lesson_count} 课</span>
              <span>{book.item_count} 知识点</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
