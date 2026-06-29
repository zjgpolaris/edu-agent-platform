"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type MaterialRecord = {
  material_id: string;
  title: string;
  filename: string;
  subject?: string | null;
  grade?: string | null;
  source_type: "pdf" | "image";
  text_chars: number;
  page_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export default function TeacherMaterialsPage() {
  const { user } = useAuth();
  const [materials, setMaterials] = useState<MaterialRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "pdf" | "image">("all");

  useEffect(() => {
    if (user?.role !== "teacher" && user?.role !== "admin") {
      setError("仅教师可访问此页面");
      setLoading(false);
      return;
    }
    fetchMaterials();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function fetchMaterials() {
    if (!user?.token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/teacher/materials`, {
        headers: authHeaders(user.token),
      });
      if (!response.ok) throw new Error("获取学生资料失败");
      const data = await response.json();
      setMaterials(data.materials || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取学生资料失败");
    } finally {
      setLoading(false);
    }
  }

  const filteredMaterials = filter === "all"
    ? materials
    : materials.filter(m => m.source_type === filter);

  if (loading) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">教师工作台</p>
              <h2>学生资料库</h2>
            </div>
          </div>
          <p className="empty-hint">加载中...</p>
        </section>
      </main>
    );
  }

  if (error) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">教师工作台</p>
              <h2>学生资料库</h2>
            </div>
          </div>
          <div className="error-card"><p>{error}</p></div>
        </section>
      </main>
    );
  }

  return (
    <main className="academy-shell">
      <section className="panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">教师工作台</p>
            <h2>学生资料库</h2>
          </div>
          <Link className="secondary-link" href="/teacher">返回班级总览</Link>
        </div>

        <div className="filter-bar">
          <span className="filter-label">筛选：</span>
          <button
            className={`filter-btn${filter === "all" ? " active" : ""}`}
            onClick={() => setFilter("all")}
          >
            全部 ({materials.length})
          </button>
          <button
            className={`filter-btn${filter === "pdf" ? " active" : ""}`}
            onClick={() => setFilter("pdf")}
          >
            PDF ({materials.filter(m => m.source_type === "pdf").length})
          </button>
          <button
            className={`filter-btn${filter === "image" ? " active" : ""}`}
            onClick={() => setFilter("image")}
          >
            图片 ({materials.filter(m => m.source_type === "image").length})
          </button>
        </div>

        {filteredMaterials.length === 0 ? (
          <p className="empty-hint">
            {filter === "all" ? "暂无学生上传的资料" : "暂无该类型的资料"}
          </p>
        ) : (
          <div className="material-grid">
            {filteredMaterials.map((material) => (
              <div key={material.material_id} className="material-card">
                <div className="material-type-badge">
                  {material.source_type === "pdf" ? "PDF" : "图片"}
                </div>
                <h3 className="material-title">{material.title}</h3>
                <p className="material-filename">{material.filename}</p>
                <div className="material-meta">
                  <span>年级: {material.grade || "未指定"}</span>
                  <span>学科: {material.subject || "历史"}</span>
                  <span>页数: {material.page_count}</span>
                </div>
                <p className="material-date">{formatDate(material.created_at)}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <style jsx>{`
        .filter-bar {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .filter-label {
          font-size: 0.9rem;
          color: var(--text-muted, #6b7280);
        }

        .filter-btn {
          padding: 6px 12px;
          border: 1px solid var(--border, #e5e7eb);
          background: var(--bg, #ffffff);
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.85rem;
          color: var(--text, #1f2937);
          transition: all 0.2s;
        }

        .filter-btn:hover {
          border-color: var(--accent, #4b9560);
        }

        .filter-btn.active {
          background: var(--accent, #4b9560);
          color: white;
          border-color: var(--accent, #4b9560);
        }

        .material-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 16px;
        }

        .material-card {
          padding: 16px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
          background: var(--bg, #ffffff);
          position: relative;
        }

        .material-type-badge {
          position: absolute;
          top: 12px;
          right: 12px;
          padding: 4px 8px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 500;
          color: var(--text-muted, #6b7280);
        }

        .material-title {
          margin: 0 0 8px 0;
          font-size: 1rem;
          font-weight: 600;
          padding-right: 60px;
        }

        .material-filename {
          margin: 0 0 12px 0;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .material-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          margin-bottom: 12px;
          font-size: 0.8rem;
          color: var(--text-muted, #6b7280);
        }

        .material-date {
          margin: 0;
          font-size: 0.75rem;
          color: var(--text-muted, #6b7280);
        }
      `}</style>
    </main>
  );
}
