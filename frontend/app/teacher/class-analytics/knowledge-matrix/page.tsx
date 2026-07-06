"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

// ─── 类型定义 ───────────────────────────────────────────────
type MatrixStudent = { id: string; name: string };

type KnowledgeMatrixData = {
  students: MatrixStudent[];
  tags: string[];
  /** matrix[student_idx][tag_idx] = strength (0.0–1.0；1.0 代表无数据/默认掌握) */
  matrix: number[][];
};

type TooltipState = {
  visible: boolean;
  x: number;
  y: number;
  student: string;
  tag: string;
  strength: number;
};

// ─── 颜色工具 ────────────────────────────────────────────────
function getColor(strength: number): string {
  if (strength >= 1.0) return "#e5e7eb"; // 灰色 = 无数据
  if (strength < 0.3)  return "#ef4444"; // 红色 = 薄弱
  if (strength < 0.7)  return "#f59e0b"; // 黄色 = 学习中
  return "#22c55e";                       // 绿色 = 掌握
}

function getTextColor(strength: number): string {
  if (strength >= 1.0) return "#9ca3af";
  if (strength < 0.3)  return "#fff";
  if (strength < 0.7)  return "#fff";
  return "#fff";
}

function getLabel(strength: number): string {
  if (strength >= 1.0) return "—";
  return (strength * 100).toFixed(0) + "%";
}

function getStatusText(strength: number): string {
  if (strength >= 1.0) return "暂无数据";
  if (strength < 0.3)  return "薄弱";
  if (strength < 0.7)  return "学习中";
  return "掌握";
}

// ─── 主页面 ──────────────────────────────────────────────────
export default function KnowledgeMatrixPage() {
  const { user } = useAuth();
  const [data, setData] = useState<KnowledgeMatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tooltip, setTooltip] = useState<TooltipState>({ visible: false, x: 0, y: 0, student: "", tag: "", strength: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!user?.token) return;
    if (user.role !== "teacher" && user.role !== "admin") {
      setError("仅教师可访问此页面");
      setLoading(false);
      return;
    }
    fetch(`${API}/api/teacher/class-knowledge-matrix`, { headers: authHeaders(user.token) })
      .then(r => r.ok ? r.json() : Promise.reject("获取矩阵数据失败"))
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(typeof e === "string" ? e : "获取矩阵数据失败"); setLoading(false); });
  }, [user]);

  function showTooltip(e: React.MouseEvent, student: string, tag: string, strength: number) {
    const rect = containerRef.current?.getBoundingClientRect();
    setTooltip({
      visible: true,
      x: e.clientX - (rect?.left ?? 0) + 12,
      y: e.clientY - (rect?.top ?? 0) - 8,
      student,
      tag,
      strength,
    });
  }

  function hideTooltip() {
    setTooltip(t => ({ ...t, visible: false }));
  }

  // ─── 汇总统计 ────────────────────────────────────────────
  function computeSummary() {
    if (!data) return null;
    let weak = 0, learning = 0, mastered = 0, noData = 0;
    data.matrix.forEach(row => row.forEach(v => {
      if (v >= 1.0) noData++;
      else if (v < 0.3) weak++;
      else if (v < 0.7) learning++;
      else mastered++;
    }));
    const total = weak + learning + mastered;
    return { weak, learning, mastered, noData, total };
  }

  // ─── 每个知识点最差掌握人数（用于表头排序提示） ──────────
  function computeTagWeakCount(tagIdx: number): number {
    if (!data) return 0;
    return data.matrix.filter(row => row[tagIdx] < 0.3 && row[tagIdx] < 1.0).length;
  }

  if (loading) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row"><div><p className="section-kicker">教师工作台</p><h2>班级知识矩阵</h2></div></div>
          <p className="empty-hint">加载中...</p>
        </section>
      </main>
    );
  }

  if (error) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row"><div><p className="section-kicker">教师工作台</p><h2>班级知识矩阵</h2></div></div>
          <div className="error-card"><p>{error}</p></div>
        </section>
      </main>
    );
  }

  if (!data || data.students.length === 0) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row"><div><p className="section-kicker">教师工作台</p><h2>班级知识矩阵</h2></div></div>
          <p className="empty-hint">暂无学生错题数据，知识矩阵将在学生产生答题记录后自动生成。</p>
        </section>
      </main>
    );
  }

  const summary = computeSummary();
  const CELL_W = 64;
  const CELL_H = 36;
  const NAME_W = 96;

  return (
    <main className="academy-shell">
      <section className="panel">
        {/* 页头 */}
        <div className="panel-heading-row" style={{ marginBottom: "0.5rem" }}>
          <div>
            <p className="section-kicker">教师工作台</p>
            <h2>班级知识矩阵</h2>
            <p style={{ color: "#6b7280", fontSize: "0.85rem", marginTop: "0.25rem" }}>
              {data.students.length} 名学生 · {data.tags.length} 个知识点 · 颜色表示掌握强度
            </p>
          </div>
          <Link href="/teacher/class-analytics" style={{ fontSize: "0.85rem", color: "#6b7280", textDecoration: "underline" }}>
            ← 返回班级学情
          </Link>
        </div>

        {/* 图例 + 汇总 */}
        <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", marginBottom: "1.25rem", alignItems: "center" }}>
          {[
            { color: "#ef4444", label: "薄弱（<30%）" },
            { color: "#f59e0b", label: "学习中（30–70%）" },
            { color: "#22c55e", label: "掌握（>70%）" },
            { color: "#e5e7eb", label: "暂无数据", border: "#d1d5db" },
          ].map(({ color, label, border }) => (
            <span key={label} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.8rem", color: "#374151" }}>
              <span style={{ width: 14, height: 14, borderRadius: 3, background: color, border: border ? `1px solid ${border}` : undefined, display: "inline-block" }} />
              {label}
            </span>
          ))}
          {summary && (
            <span style={{ marginLeft: "auto", fontSize: "0.8rem", color: "#6b7280" }}>
              薄弱格 <strong style={{ color: "#ef4444" }}>{summary.weak}</strong> ·
              学习中 <strong style={{ color: "#f59e0b" }}>{summary.learning}</strong> ·
              已掌握 <strong style={{ color: "#22c55e" }}>{summary.mastered}</strong>
            </span>
          )}
        </div>

        {/* 矩阵容器（横向滚动） */}
        <div ref={containerRef} style={{ position: "relative", overflowX: "auto", overflowY: "visible", borderRadius: 8, border: "1px solid #e5e7eb" }}>
          <table style={{ borderCollapse: "collapse", minWidth: NAME_W + data.tags.length * CELL_W }}>
            {/* 表头：知识点 */}
            <thead>
              <tr>
                <th style={{
                  width: NAME_W, minWidth: NAME_W, padding: "8px 10px",
                  background: "#f9fafb", textAlign: "left", fontSize: "0.78rem",
                  color: "#9ca3af", fontWeight: 600, borderBottom: "1px solid #e5e7eb",
                  position: "sticky", left: 0, zIndex: 2,
                }}>
                  学生 ↓ / 知识点 →
                </th>
                {data.tags.map((tag, ti) => {
                  const weakCount = computeTagWeakCount(ti);
                  return (
                    <th key={tag} style={{
                      width: CELL_W, minWidth: CELL_W, maxWidth: CELL_W,
                      padding: "6px 4px", textAlign: "center",
                      background: "#f9fafb", borderBottom: "1px solid #e5e7eb",
                      borderLeft: "1px solid #f3f4f6",
                    }}>
                      <div style={{ fontSize: "0.7rem", color: "#374151", fontWeight: 600, lineHeight: 1.3,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        maxWidth: CELL_W - 8, margin: "0 auto" }} title={tag}>
                        {tag.length > 5 ? tag.slice(0, 5) + "…" : tag}
                      </div>
                      {weakCount > 0 && (
                        <div style={{ fontSize: "0.65rem", color: "#ef4444", marginTop: 2 }}>
                          {weakCount}人薄弱
                        </div>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>

            {/* 矩阵内容 */}
            <tbody>
              {data.students.map((stu, si) => (
                <tr key={stu.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  {/* 学生姓名（固定左列） */}
                  <td style={{
                    padding: "4px 10px", fontSize: "0.8rem", fontWeight: 500, color: "#374151",
                    background: "#fff", whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis", maxWidth: NAME_W,
                    position: "sticky", left: 0, zIndex: 1,
                    borderRight: "1px solid #e5e7eb",
                  }} title={stu.name}>
                    {stu.name}
                  </td>

                  {/* 每个知识点格子 */}
                  {data.matrix[si]?.map((strength, ti) => (
                    <td
                      key={ti}
                      onMouseEnter={e => showTooltip(e, stu.name, data.tags[ti], strength)}
                      onMouseLeave={hideTooltip}
                      style={{
                        width: CELL_W, height: CELL_H,
                        background: getColor(strength),
                        textAlign: "center", verticalAlign: "middle",
                        fontSize: "0.7rem", fontWeight: 600,
                        color: getTextColor(strength),
                        cursor: "pointer",
                        borderLeft: "1px solid rgba(255,255,255,0.3)",
                        transition: "opacity 0.1s",
                      }}
                    >
                      {getLabel(strength)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>

          {/* Tooltip */}
          {tooltip.visible && (
            <div style={{
              position: "absolute",
              left: tooltip.x,
              top: tooltip.y,
              background: "rgba(17,24,39,0.92)",
              color: "#fff",
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: "0.78rem",
              lineHeight: 1.6,
              pointerEvents: "none",
              zIndex: 10,
              minWidth: 140,
              boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
            }}>
              <div style={{ fontWeight: 700, marginBottom: 2 }}>{tooltip.student}</div>
              <div style={{ color: "#d1d5db" }}>{tooltip.tag}</div>
              <div>
                状态：<strong style={{ color: getColor(tooltip.strength) }}>
                  {getStatusText(tooltip.strength)}
                </strong>
              </div>
              {tooltip.strength < 1.0 && (
                <div>掌握度：<strong>{(tooltip.strength * 100).toFixed(0)}%</strong></div>
              )}
            </div>
          )}
        </div>

        {/* 底部说明 */}
        <p style={{ marginTop: "1rem", fontSize: "0.78rem", color: "#9ca3af" }}>
          数据来源：各学生错题本实时聚合 · 数据每次页面加载时刷新
        </p>
      </section>
    </main>
  );
}
