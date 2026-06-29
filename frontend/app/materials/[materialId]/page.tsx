"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
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

type MaterialPage = {
  page_number: number;
  text: string;
  source_type: "pdf" | "image";
};

type MaterialDetailResponse = {
  material: MaterialRecord;
  pages: MaterialPage[];
  warnings: string[];
};

type MaterialSource = {
  material_id: string;
  title: string;
  page?: number | null;
  chunk_id: string;
  score: number;
  source_mode: string;
  snippet: string;
};

type MaterialAnswerResponse = {
  material_id: string;
  answer: string;
  sources: MaterialSource[];
};

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export default function MaterialDetailPage() {
  const { user } = useAuth();
  const params = useParams<{ materialId: string }>();
  const router = useRouter();
  const materialId = params.materialId;
  const [detail, setDetail] = useState<MaterialDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<MaterialAnswerResponse | null>(null);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState("");
  const [deleteLoading, setDeleteLoading] = useState(false);

  useEffect(() => {
    const token = user?.token;
    if (!token || !materialId) {
      setLoading(false);
      return;
    }
    const authToken = token;
    let cancelled = false;
    async function loadDetail() {
      setLoading(true);
      setError("");
      try {
        const data = await fetchApiJson<MaterialDetailResponse>(`/api/materials/${materialId}`, {
          token: authToken,
          includeClientSession: true,
          fallbackMessage: "资料详情加载失败，请稍后重试",
        });
        if (!cancelled) setDetail(data);
      } catch (err) {
        if (!cancelled) setError(normalizeError(err, "资料详情加载失败，请稍后重试"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [materialId, user]);

  async function askMaterial() {
    if (!user?.token || !question.trim()) return;
    setAskLoading(true);
    setAskError("");
    setAnswer(null);
    try {
      const data = await fetchApiJson<MaterialAnswerResponse>(`/api/materials/${materialId}/ask`, {
        method: "POST",
        token: user.token,
        includeClientSession: true,
        body: { question, k: 4 },
        fallbackMessage: "资料问答失败，请稍后重试",
      });
      setAnswer(data);
    } catch (err) {
      setAskError(normalizeError(err, "资料问答失败，请稍后重试"));
    } finally {
      setAskLoading(false);
    }
  }

  async function deleteMaterial() {
    if (!user?.token || !detail) return;
    if (!window.confirm("确认删除这份资料？删除后会同步移除检索索引，无法继续围绕它提问。")) return;
    setDeleteLoading(true);
    setError("");
    try {
      await fetchApiJson(`/api/materials/${materialId}`, {
        method: "DELETE",
        token: user.token,
        includeClientSession: true,
        fallbackMessage: "资料删除失败，请稍后重试",
      });
      router.push("/materials");
    } catch (err) {
      setError(normalizeError(err, "资料删除失败，请稍后重试"));
    } finally {
      setDeleteLoading(false);
    }
  }

  const material = detail?.material;

  return (
    <main className="academy-shell material-detail-shell">
      <section className="academy-hero material-upload-hero">
        <div className="hero-copy">
          <span className="eyebrow">Material Detail</span>
          <h1>{material?.title || "资料详情"}</h1>
          <p>{material ? `${material.filename} · ${material.page_count} 页 · ${material.chunk_count} 个检索片段` : "按页回看资料内容，并围绕这份资料继续提问。"}</p>
          <div className="hero-flow">
            <span>分页文本</span>
            <span>资料问答</span>
            <span>来源片段</span>
            <span>个人隔离</span>
          </div>
        </div>
        <aside className="teaching-card material-ink-card">
          <span className="seal-mark">引</span>
          <strong>只展示真实来源</strong>
          <p>引用卡片仅来自后端检索 sources；没有图像坐标时，不伪造视觉高亮。</p>
        </aside>
      </section>

      {loading && <section className="panel"><p className="empty-hint">正在加载资料详情...</p></section>}
      {error && <section className="panel"><div className="error-card"><p>{error}</p></div></section>}

      {detail && material && (
        <section className="material-detail-layout">
          <article className="panel material-detail-main">
            <div className="panel-heading-row">
              <div>
                <p className="section-kicker">PAGES</p>
                <h2>分页文本</h2>
              </div>
              <Link className="secondary-link" href="/materials">返回资料库</Link>
            </div>
            {detail.warnings.length > 0 && <div className="material-warning-card"><strong>处理提示</strong><ul>{detail.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
            <div className="material-page-list">
              {detail.pages.map((page) => (
                <details key={page.page_number} className="material-page-card" open={detail.pages.length === 1}>
                  <summary>第 {page.page_number} 页 · {page.source_type === "pdf" ? "PDF" : "图片"}</summary>
                  <p>{page.text}</p>
                </details>
              ))}
            </div>
          </article>

          <aside className="panel material-detail-side">
            <div className="panel-heading-row">
              <div>
                <p className="section-kicker">MATERIAL QA</p>
                <h2>围绕资料提问</h2>
              </div>
              <button className="secondary" type="button" disabled={deleteLoading || askLoading} onClick={deleteMaterial}>{deleteLoading ? "删除中..." : "删除资料"}</button>
            </div>
            <dl className="material-detail-meta">
              <div><dt>学科</dt><dd>{material.subject || "历史"}</dd></div>
              <div><dt>年级</dt><dd>{material.grade || "未指定"}</dd></div>
              <div><dt>来源</dt><dd>{material.source_type === "pdf" ? "PDF 文稿" : "图片资料"}</dd></div>
              <div><dt>创建</dt><dd>{formatDate(material.created_at)}</dd></div>
            </dl>
            <label className="material-question-box">
              <span>学生问题</span>
              <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：这份材料如何说明洋务运动的局限？" />
            </label>
            {askError && <div className="error-card"><p>{askError}</p></div>}
            <button className="primary" type="button" disabled={!question.trim() || askLoading} onClick={askMaterial}>{askLoading ? "正在检索资料..." : "基于资料回答"}</button>
            {answer && (
              <div className="material-answer-card">
                <strong>资料回答</strong>
                <p>{answer.answer}</p>
                {answer.sources.length > 0 && <div className="material-source-list"><span>引用来源</span>{answer.sources.map((source) => <article key={source.chunk_id} className="material-source-card"><strong>{source.title} · 第 {source.page || 1} 页</strong><em>{source.source_mode} · score {source.score.toFixed(2)}</em><p>{source.snippet}</p></article>)}</div>}
              </div>
            )}
          </aside>
        </section>
      )}
    </main>
  );
}
