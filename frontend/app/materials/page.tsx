"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchApiJson, normalizeError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

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

export default function MaterialsPage() {
  const { user } = useAuth();
  const [materials, setMaterials] = useState<MaterialRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = user?.token;
    if (!token) {
      setLoading(false);
      return;
    }
    const authToken = token;
    let cancelled = false;
    async function loadMaterials() {
      setLoading(true);
      setError("");
      try {
        const data = await fetchApiJson<{ materials?: MaterialRecord[] }>("/api/materials", {
          token: authToken,
          includeClientSession: true,
          fallbackMessage: "资料库加载失败，请稍后重试",
        });
        if (!cancelled) setMaterials(data.materials || []);
      } catch (err) {
        if (!cancelled) setError(normalizeError(err, "资料库加载失败，请稍后重试"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadMaterials();
    return () => {
      cancelled = true;
    };
  }, [user]);

  return (
    <main className="academy-shell material-library-shell">
      <section className="academy-hero material-upload-hero">
        <div className="hero-copy">
          <span className="eyebrow">Material Library</span>
          <h1>我的资料库</h1>
          <p>查看已保存的 PDF、截图和课堂材料，按页回看内容，并继续基于个人资料进行问答。</p>
          <div className="hero-flow">
            <span>资料保存</span>
            <span>分页回看</span>
            <span>资料问答</span>
            <span>来源引用</span>
          </div>
        </div>
        <aside className="teaching-card material-ink-card">
          <span className="seal-mark">库</span>
          <strong>个人隔离</strong>
          <p>资料仅进入个人资料库和独立 materials 向量索引，不会污染全局历史知识库。</p>
        </aside>
      </section>

      <section className="panel material-library-panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">SAVED MATERIALS</p>
            <h2>已保存资料</h2>
          </div>
          <Link className="secondary-link" href="/material-upload">上传新资料</Link>
        </div>

        {loading && <p className="empty-hint">正在加载资料库...</p>}
        {error && <div className="error-card"><p>{error}</p></div>}
        {!loading && !error && materials.length === 0 && (
          <div className="material-empty-state">
            <strong>还没有保存资料</strong>
            <p>先上传 PDF 或课堂截图，校对文本后保存到个人资料库。</p>
            <Link className="primary-link" href="/material-upload">去上传资料</Link>
          </div>
        )}

        {materials.length > 0 && (
          <div className="material-library-grid">
            {materials.map((material) => (
              <Link key={material.material_id} className="material-library-card" href={`/materials/${material.material_id}`}>
                <div>
                  <span>{material.source_type === "pdf" ? "PDF 文稿" : "图片资料"}</span>
                  <h3>{material.title}</h3>
                  <p>{material.filename}</p>
                </div>
                <dl>
                  <div><dt>年级</dt><dd>{material.grade || "未指定"}</dd></div>
                  <div><dt>学科</dt><dd>{material.subject || "历史"}</dd></div>
                  <div><dt>页数</dt><dd>{material.page_count}</dd></div>
                  <div><dt>片段</dt><dd>{material.chunk_count}</dd></div>
                </dl>
                <em>{material.text_chars} 字 · {formatDate(material.created_at)}</em>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
