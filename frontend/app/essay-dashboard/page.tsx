"use client";

import { useState } from "react";

type EssayItem = { student_name: string; essay: string };
type BatchResult = { student_name: string; final_comments: string; needs_human_review: boolean; review_reason?: string };
type BatchSummary = { avg_score: number; score_distribution: Record<string, number>; needs_review_count: number };

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function EssayDashboardPage() {
  const [inputText, setInputText] = useState("");
  const [essays, setEssays] = useState<EssayItem[]>([]);
  const [results, setResults] = useState<BatchResult[]>([]);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function parseInput(text: string): EssayItem[] {
    return text
      .trim()
      .split("---")
      .map((block) => block.trim())
      .filter(Boolean)
      .map((block) => {
        const [name, ...essayLines] = block.split("\n");
        return { student_name: name.trim(), essay: essayLines.join("\n").trim() };
      })
      .filter((item) => item.student_name && item.essay);
  }

  function handleParse() {
    const parsed = parseInput(inputText);
    if (parsed.length === 0) {
      setError("请按格式输入：学生姓名 + 换行 + 作文内容，多篇之间用 --- 分隔");
      return;
    }
    if (parsed.length > 50) {
      setError("单次最多批改 50 篇作文");
      return;
    }
    setEssays(parsed);
    setError("");
  }

  function handleCsvUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (readerEvent) => {
      const text = String(readerEvent.target?.result || "");
      const parsed = text
        .split("\n")
        .slice(1)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const [name, ...essayParts] = line.split(",");
          return { student_name: name.trim(), essay: essayParts.join(",").trim() };
        })
        .filter((item) => item.student_name && item.essay);
      if (parsed.length > 50) {
        setError("单次最多批改 50 篇作文");
        return;
      }
      setEssays(parsed);
      setError("");
    };
    reader.readAsText(file);
  }

  async function handleBatchGrade() {
    if (!essays.length) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/chinese/essay/grade/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ essays }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "批改失败");
      setResults(data.results || []);
      setSummary(data.summary || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "批改失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="academy-shell essay-dashboard-shell">
      <section className="essay-dashboard-layout">
        <section className="panel essay-upload-panel">
          <h2>导入作文</h2>
          <div className="essay-upload-grid">
            <label className="essay-paste-box">
              <span>粘贴文本</span>
              <textarea value={inputText} onChange={(event) => setInputText(event.target.value)} placeholder={"张三\n作文内容...\n---\n李四\n作文内容..."} rows={10} />
              <button className="secondary" type="button" onClick={handleParse}>解析文本</button>
            </label>
            <div className="essay-csv-box">
              <span>上传 CSV</span>
              <p>首行为表头：student_name,essay</p>
              <input type="file" accept=".csv" onChange={handleCsvUpload} />
            </div>
          </div>
          {error && <div className="error-card">{error}</div>}
          {essays.length > 0 && (
            <div className="essay-import-summary">
              <div><strong>{essays.length}</strong><span>篇作文已就绪</span></div>
              <button className="primary" onClick={handleBatchGrade} disabled={loading}>{loading ? "批改中..." : "开始批改"}</button>
            </div>
          )}
        </section>

        {summary && (
          <section className="panel essay-stats-panel">
            <h2>班级批改概览</h2>
            <div className="essay-stat-grid">
              <article><span>需人工复核</span><strong>{summary.needs_review_count}</strong></article>
              <article><span>自动通过</span><strong>{summary.score_distribution["自动通过"] || 0}</strong></article>
              <article><span>总批改数</span><strong>{results.length}</strong></article>
            </div>
          </section>
        )}

        {results.length > 0 && (
          <section className="panel essay-results-panel">
            <h2>逐篇批改详情</h2>
            <div className="essay-result-list">
              {results.map((result, index) => (
                <article key={`${result.student_name}-${index}`} className={result.needs_human_review ? "needs-review" : ""}>
                  <div className="essay-result-head">
                    <strong>{result.student_name}</strong>
                    <span>{result.needs_human_review ? "需复核" : "自动通过"}</span>
                  </div>
                  <p>{result.final_comments}</p>
                  {result.review_reason && <em>{result.review_reason}</em>}
                </article>
              ))}
            </div>
          </section>
        )}
      </section>
    </main>
  );
}
