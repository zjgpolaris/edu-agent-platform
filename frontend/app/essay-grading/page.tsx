"use client";

import { FormEvent, useMemo, useState } from "react";
import { authHeaders } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const MAX_BATCH_ESSAYS = 20;

type TabKey = "single" | "batch";
type BatchFilter = "all" | "review" | "failed";

type SingleFormState = {
  title: string;
  gradeLevel: string;
  prompt: string;
  content: string;
  enableFactCheck: boolean;
};

type EssayGradeResponse = {
  student_id: string;
  comments: string;
  needs_human_review: boolean;
  review_reason?: string;
  session_id?: string;
};

type ReviewState = {
  approved: boolean | null;
  teacherComments: string;
  decision: "approved" | "edited" | "rejected";
  scoreOverride: string;
  submitted: boolean;
};

type BatchEssayRow = {
  studentName: string;
  studentId: string;
  className: string;
  title: string;
  prompt: string;
  content: string;
};

type BatchApiResult = {
  student_name: string;
  final_comments: string;
  needs_human_review: boolean;
  review_reason?: string;
  failed?: boolean;
  error?: string;
};

type BatchDisplayResult = BatchEssayRow & {
  finalComments: string;
  needsHumanReview: boolean;
  reviewReason?: string;
  failed: boolean;
  error?: string;
};

type BatchSummary = {
  avg_score?: number;
  score_distribution?: Record<string, number>;
  needs_review_count: number;
  failed_count?: number;
};

const SCORE_MAX: Record<string, number> = { 立意: 20, 结构: 20, 语言: 30, 书写风格: 15, 材料运用: 15 };

type ParsedGrade = { scores: Array<{ label: string; score: number; max: number }>; comment: string };

function parseGradeResult(text: string): ParsedGrade | null {
  const jsonStr = text.trim().replace(/^```json\s*|\s*```$/g, "").trim();
  try {
    const obj = JSON.parse(jsonStr);
    const scores = Object.entries(SCORE_MAX).map(([label, max]) => {
      const key = Object.keys(obj).find((k) => k.startsWith(label));
      const score = key !== undefined ? Number(obj[key]) : NaN;
      return { label, score, max };
    }).filter(({ score }) => !isNaN(score));
    if (!scores.length) return null;
    return { scores, comment: String(obj["总体评语"] || "") };
  } catch {
    return null;
  }
}

function EssayComments({ text }: { text: string }) {
  const parsed = parseGradeResult(text);
  if (!parsed) {
    return (
      <div className="essay-comments">
        {text.split("\n").map((line, i) => <p key={i}>{line || " "}</p>)}
      </div>
    );
  }
  const total = parsed.scores.reduce((sum, s) => sum + s.score, 0);
  return (
    <div className="essay-comments">
      <div className="essay-score-header"><span className="essay-score-total">{total} 分</span></div>
      <div className="essay-score-grid">
        {parsed.scores.map(({ label, score, max }) => (
          <div key={label} className="essay-score-item">
            <div className="essay-score-meta"><span>{label}</span><span>{score}/{max}</span></div>
            <div className="essay-score-bar-bg"><div className="essay-score-bar-fill" style={{ width: `${(score / max) * 100}%` }} /></div>
          </div>
        ))}
      </div>
      {parsed.comment && (
        <div className="essay-overall-comment">
          <p className="essay-overall-label">总体评语</p>
          {parsed.comment.split("\n").map((line, i) => <p key={i}>{line || " "}</p>)}
        </div>
      )}
    </div>
  );
}

const emptySingleForm: SingleFormState = {
  title: "",
  gradeLevel: "",
  prompt: "",
  content: "",
  enableFactCheck: false,
};

function composeEssayText(row: Pick<BatchEssayRow, "title" | "className" | "prompt" | "content"> & { gradeLevel?: string }) {
  return [
    row.title ? `【标题】${row.title}` : "",
    row.gradeLevel ? `【年级】${row.gradeLevel}` : "",
    row.className ? `【班级】${row.className}` : "",
    row.prompt ? `【写作要求】${row.prompt}` : "",
    `【正文】\n${row.content}`,
  ].filter(Boolean).join("\n");
}

function parseCsvLine(line: string) {
  const cells: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];
    if (char === '"' && inQuotes && next === '"') {
      current += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

function parseCsv(text: string): BatchEssayRow[] {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2) return [];

  const headers = parseCsvLine(lines[0]).map((header) => header.toLowerCase());
  return lines.slice(1).map((line) => {
    const cells = parseCsvLine(line);
    const get = (...names: string[]) => {
      const index = headers.findIndex((header) => names.includes(header));
      return index >= 0 ? cells[index] || "" : "";
    };
    return {
      studentName: get("student_name", "student", "name", "姓名", "学生姓名"),
      studentId: get("student_id", "id", "学号", "座号"),
      className: get("class_name", "class", "班级"),
      title: get("title", "作文标题", "标题"),
      prompt: get("prompt", "requirement", "题目", "写作要求"),
      content: get("essay", "content", "作文", "作文正文", "正文"),
    };
  }).filter((row) => row.studentName || row.content);
}

function parsePastedEssays(text: string): BatchEssayRow[] {
  return text
    .trim()
    .split("---")
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const [name, ...contentLines] = block.split("\n");
      return {
        studentName: name.trim(),
        studentId: "",
        className: "",
        title: "",
        prompt: "",
        content: contentLines.join("\n").trim(),
      };
    })
    .filter((row) => row.studentName || row.content);
}

function escapeCsvCell(value: string | number | boolean | undefined) {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

export default function EssayGradingPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("single");
  const [singleForm, setSingleForm] = useState<SingleFormState>(emptySingleForm);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState("");
  const [singleResult, setSingleResult] = useState<EssayGradeResponse | null>(null);
  const [review, setReview] = useState<ReviewState>({ approved: null, teacherComments: "", decision: "approved", scoreOverride: "", submitted: false });
  const [copyMessage, setCopyMessage] = useState("");

  const [batchText, setBatchText] = useState("");
  const [batchRows, setBatchRows] = useState<BatchEssayRow[]>([]);
  const [batchResults, setBatchResults] = useState<BatchDisplayResult[]>([]);
  const [batchSummary, setBatchSummary] = useState<BatchSummary | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchError, setBatchError] = useState("");
  const [batchFilter, setBatchFilter] = useState<BatchFilter>("all");
  const [expandedResult, setExpandedResult] = useState<number | null>(null);

  const canCallApi = Boolean(user?.token);
  const charCount = singleForm.content.length;

  const filteredBatchResults = useMemo(() => {
    if (batchFilter === "review") return batchResults.filter((result) => result.needsHumanReview);
    if (batchFilter === "failed") return batchResults.filter((result) => result.failed);
    return batchResults;
  }, [batchFilter, batchResults]);

  const batchStats = useMemo(() => {
    const failed = batchResults.filter((result) => result.failed).length;
    const needsReview = batchResults.filter((result) => result.needsHumanReview).length;
    return {
      total: batchResults.length,
      needsReview: batchSummary?.needs_review_count ?? needsReview,
      failed: batchSummary?.failed_count ?? failed,
      passed: Math.max(0, batchResults.length - needsReview),
      avgScore: batchSummary?.avg_score ?? null,
    };
  }, [batchResults, batchSummary]);

  function getRequestHeaders() {
    return {
      "Content-Type": "application/json",
      ...(user?.token ? authHeaders(user.token) : {}),
    };
  }

  async function handleSingleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!singleForm.content.trim()) {
      setSingleError("请输入作文正文");
      return;
    }
    if (!user?.actorId || !canCallApi) {
      setSingleError("请先登录后再使用作文批改");
      return;
    }

    setSingleLoading(true);
    setSingleError("");
    setSingleResult(null);
    setCopyMessage("");
    setReview({ approved: null, teacherComments: "", decision: "approved", scoreOverride: "", submitted: false });

    try {
      const essay = composeEssayText({
        title: singleForm.title,
        gradeLevel: singleForm.gradeLevel,
        className: "",
        prompt: singleForm.prompt,
        content: singleForm.content,
      });
      const response = await fetch(`${apiBaseUrl}/api/chinese/essay/grade`, {
        method: "POST",
        headers: getRequestHeaders(),
        body: JSON.stringify({ essay, student_id: user.actorId }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "批改失败，请稍后重试");
      setSingleResult(data as EssayGradeResponse);
    } catch (err) {
      setSingleError(err instanceof Error ? err.message : "批改失败，请稍后重试");
    } finally {
      setSingleLoading(false);
    }
  }

  async function submitReview(decision: "approved" | "edited" | "rejected") {
    if (!singleResult?.session_id) {
      setSingleError("缺少会话 ID，无法提交复核");
      return;
    }
    const approved = decision === "approved";
    const scoreOverride = review.scoreOverride ? parseFloat(review.scoreOverride) : null;
    try {
      const response = await fetch(`${apiBaseUrl}/api/chinese/essay/review-result`, {
        method: "POST",
        headers: getRequestHeaders(),
        body: JSON.stringify({
          session_id: singleResult.session_id,
          approved,
          decision,
          teacher_comments: review.teacherComments,
          score_override: scoreOverride,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "提交复核失败");
      setReview({ ...review, approved, decision, submitted: true });
    } catch (err) {
      setSingleError(err instanceof Error ? err.message : "提交复核失败");
    }
  }

  async function copyComments() {
    if (!singleResult?.comments) return;
    await navigator.clipboard.writeText(singleResult.comments);
    setCopyMessage("评语已复制");
  }

  function setParsedRows(rows: BatchEssayRow[]) {
    if (rows.length === 0) {
      setBatchError("未解析到有效作文，请检查格式");
      return;
    }
    if (rows.length > MAX_BATCH_ESSAYS) {
      setBatchError(`单次最多批改 ${MAX_BATCH_ESSAYS} 篇作文，请拆分后再导入`);
      return;
    }
    const invalidIndex = rows.findIndex((row) => !row.studentName.trim() || !row.content.trim());
    if (invalidIndex >= 0) {
      setBatchError(`第 ${invalidIndex + 1} 行缺少学生姓名或作文正文`);
      return;
    }
    setBatchRows(rows);
    setBatchResults([]);
    setBatchSummary(null);
    setExpandedResult(null);
    setBatchError("");
  }

  function handleParseText() {
    setParsedRows(parsePastedEssays(batchText));
  }

  function handleCsvUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (readerEvent) => {
      const text = String(readerEvent.target?.result || "");
      setParsedRows(parseCsv(text));
    };
    reader.readAsText(file);
    event.target.value = "";
  }

  async function handleBatchGrade() {
    if (!batchRows.length) {
      setBatchError("请先导入作文");
      return;
    }
    if (!canCallApi) {
      setBatchError("请先登录后再使用批量批改");
      return;
    }

    setBatchLoading(true);
    setBatchError("");
    setBatchResults([]);
    setBatchSummary(null);
    setExpandedResult(null);

    try {
      const essays = batchRows.map((row) => ({
        student_name: row.studentName,
        essay: composeEssayText(row),
      }));
      const response = await fetch(`${apiBaseUrl}/api/chinese/essay/grade/batch`, {
        method: "POST",
        headers: getRequestHeaders(),
        body: JSON.stringify({ essays }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "批量批改失败");
      const apiResults = (data.results || []) as BatchApiResult[];
      setBatchResults(apiResults.map((result, index) => {
        const source = batchRows[index] || {
          studentName: result.student_name,
          studentId: "",
          className: "",
          title: "",
          prompt: "",
          content: "",
        };
        return {
          ...source,
          studentName: source.studentName || result.student_name,
          finalComments: result.final_comments || "",
          needsHumanReview: Boolean(result.needs_human_review),
          reviewReason: result.review_reason,
          failed: Boolean(result.failed),
          error: result.error,
        };
      }));
      setBatchSummary(data.summary || null);
    } catch (err) {
      setBatchError(err instanceof Error ? err.message : "批量批改失败");
    } finally {
      setBatchLoading(false);
    }
  }

  function exportBatchCsv() {
    if (!batchResults.length) return;
    const headers = ["student_name", "student_id", "class_name", "title", "needs_human_review", "failed", "review_reason", "comments", "error"];
    const rows = batchResults.map((result) => [
      result.studentName,
      result.studentId,
      result.className,
      result.title,
      result.needsHumanReview,
      result.failed,
      result.reviewReason || "",
      result.finalComments,
      result.error || "",
    ]);
    const csv = [headers, ...rows].map((row) => row.map(escapeCsvCell).join(",")).join("\n");
    const byteOrderMark = String.fromCharCode(0xfeff);
    const blob = new Blob([byteOrderMark + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "essay-grading-results.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="academy-shell essay-grading-shell">
      <section className="essay-grading-tabs" aria-label="作文批改模式">
        <button className={activeTab === "single" ? "active" : ""} type="button" onClick={() => setActiveTab("single")}>单篇批改</button>
        <button className={activeTab === "batch" ? "active" : ""} type="button" onClick={() => setActiveTab("batch")}>批量批改</button>
      </section>

      {activeTab === "single" && (
        <section className="essay-grading-layout single-mode">
          <form className="panel essay-single-panel" onSubmit={handleSingleSubmit}>
            <div className="panel-heading-row">
              <div>
                <p className="section-kicker">Single Essay</p>
                <h2>单篇作文批改</h2>
              </div>
              <span className="soft-badge">AI 建议，教师确认</span>
            </div>
            <div className="essay-single-grid">
              <label>
                作文标题
                <input value={singleForm.title} onChange={(event) => setSingleForm({ ...singleForm, title: event.target.value })} placeholder="例如：秦统一的意义" />
              </label>
              <label>
                年级/学段
                <input value={singleForm.gradeLevel} onChange={(event) => setSingleForm({ ...singleForm, gradeLevel: event.target.value })} placeholder="例如：七年级" />
              </label>
            </div>
            <label>
              写作要求
              <textarea value={singleForm.prompt} onChange={(event) => setSingleForm({ ...singleForm, prompt: event.target.value })} placeholder="请输入作文题目或评分要求，可选" rows={3} />
            </label>
            <label>
              作文正文
              <textarea value={singleForm.content} onChange={(event) => setSingleForm({ ...singleForm, content: event.target.value })} placeholder="请在此处输入作文正文..." rows={12} />
            </label>
            <div className="essay-form-footer">
              <span>{charCount}/2000 字</span>
              <label className="essay-inline-check">
                <input type="checkbox" checked={singleForm.enableFactCheck} onChange={(event) => setSingleForm({ ...singleForm, enableFactCheck: event.target.checked })} />
                史实一致性检查提示
              </label>
            </div>
            {singleForm.enableFactCheck && <div className="verify-note">当前版本会把史实核查要求写入作文上下文，由批改 Agent 给出复核提示。</div>}
            {singleError && <div className="error-card">{singleError}</div>}
            <button className="primary" type="submit" disabled={singleLoading}>{singleLoading ? "批改中..." : "开始批改"}</button>
          </form>

          <section className="panel essay-single-result-panel">
            <div className="panel-heading-row">
              <div>
                <p className="section-kicker">Result</p>
                <h2>批改结果</h2>
              </div>
              {singleResult?.needs_human_review && <span className="review-chip">需教师复核</span>}
            </div>
            {!singleResult && <p className="empty-hint">提交作文后，这里会展示 AI 评语、修改建议和复核提醒。</p>}
            {singleResult && (
              <div className="essay-result-card">
                {singleResult.needs_human_review && singleResult.review_reason && (
                  <div className="review-reason-card"><strong>复核原因</strong><span>{singleResult.review_reason}</span></div>
                )}
                <EssayComments text={singleResult.comments} />
                <div className="essay-result-actions">
                  <button className="secondary" type="button" onClick={copyComments}>复制评语</button>
                  {copyMessage && <span>{copyMessage}</span>}
                </div>
                {singleResult.needs_human_review && !review.submitted && (
                  <div className="teacher-review-form">
                    <p className="teacher-review-title">教师复核</p>
                    <div className="teacher-score-row">
                      <label className="teacher-score-row">
                        <span>分数修正（可选）</span>
                        <input
                          type="number" min="0" max="100"
                          className="teacher-score-input"
                          placeholder="原分"
                          value={review.scoreOverride}
                          onChange={(event) => setReview({ ...review, scoreOverride: event.target.value })}
                        />
                      </label>
                    </div>
                    <textarea
                      className="teacher-comment-textarea"
                      placeholder="补充评语（可选）"
                      value={review.teacherComments}
                      onChange={(event) => setReview({ ...review, teacherComments: event.target.value })}
                      rows={3}
                    />
                    <div className="teacher-review-actions">
                      <button className="teacher-review-btn approve" type="button" onClick={() => void submitReview("approved")}>确认通过</button>
                      <button className="teacher-review-btn edit" type="button" onClick={() => void submitReview("edited")}>修改后通过</button>
                      <button className="teacher-review-btn reject" type="button" onClick={() => void submitReview("rejected")}>退回重做</button>
                    </div>
                  </div>
                )}
                {review.submitted && (
                  <div className="teacher-review-submitted">
                    复核结果已提交：{review.decision === "approved" ? "确认通过" : review.decision === "edited" ? "修改后通过" : "退回重做"}
                  </div>
                )}
              </div>
            )}
          </section>
        </section>
      )}

      {activeTab === "batch" && (
        <section className="essay-grading-layout batch-mode">
          <section className="panel essay-upload-panel">
            <div className="panel-heading-row">
              <div>
                <p className="section-kicker">Batch Import</p>
                <h2>批量导入作文</h2>
              </div>
              <span className="soft-badge">最多 {MAX_BATCH_ESSAYS} 篇/次</span>
            </div>
            <div className="essay-upload-grid">
              <label className="essay-paste-box">
                <span>粘贴文本</span>
                <textarea value={batchText} onChange={(event) => setBatchText(event.target.value)} placeholder={"张三\n作文内容...\n---\n李四\n作文内容..."} rows={10} />
                <button className="secondary" type="button" onClick={handleParseText}>解析文本</button>
              </label>
              <div className="essay-csv-box">
                <span>上传 CSV</span>
                <p>支持表头：student_name,student_id,class_name,title,prompt,essay 或 content</p>
                <input type="file" accept=".csv" onChange={handleCsvUpload} />
              </div>
            </div>
            {batchError && <div className="error-card">{batchError}</div>}
            {batchRows.length > 0 && (
              <div className="essay-import-preview">
                <div className="essay-import-summary">
                  <div><strong>{batchRows.length}</strong><span>篇作文已就绪</span></div>
                  <button className="primary" type="button" onClick={handleBatchGrade} disabled={batchLoading}>{batchLoading ? "批改中..." : "开始批量批改"}</button>
                </div>
                <div className="essay-preview-table-wrap">
                  <table className="essay-preview-table">
                    <thead><tr><th>学生</th><th>班级</th><th>标题</th><th>正文预览</th></tr></thead>
                    <tbody>
                      {batchRows.slice(0, 8).map((row, index) => (
                        <tr key={`${row.studentName}-${index}`}><td>{row.studentName}</td><td>{row.className || "-"}</td><td>{row.title || "-"}</td><td>{row.content.slice(0, 48)}{row.content.length > 48 ? "..." : ""}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>

          {batchResults.length > 0 && (
            <>
              <section className="panel essay-stats-panel essay-grading-stats">
                <h2>班级批改概览</h2>
                <div className="essay-stat-grid">
                  <article><span>总批改数</span><strong>{batchStats.total}</strong></article>
                  <article><span>需人工复核</span><strong>{batchStats.needsReview}</strong></article>
                  <article><span>批改失败</span><strong>{batchStats.failed}</strong></article>
                  <article><span>自动通过</span><strong>{batchStats.passed}</strong></article>
                  {batchStats.avgScore != null && <article><span>班级均分</span><strong>{batchStats.avgScore} / 100</strong></article>}
                </div>
              </section>

              <section className="panel essay-results-panel">
                <div className="panel-heading-row">
                  <div>
                    <p className="section-kicker">Review Queue</p>
                    <h2>逐篇批改详情</h2>
                  </div>
                  <div className="essay-result-toolbar">
                    <div className="essay-filter-group">
                      <button type="button" className={batchFilter === "all" ? "active" : ""} onClick={() => setBatchFilter("all")}>全部</button>
                      <button type="button" className={batchFilter === "review" ? "active" : ""} onClick={() => setBatchFilter("review")}>需复核</button>
                      <button type="button" className={batchFilter === "failed" ? "active" : ""} onClick={() => setBatchFilter("failed")}>失败</button>
                    </div>
                    <button className="secondary" type="button" onClick={exportBatchCsv}>导出 CSV</button>
                  </div>
                </div>
                <div className="essay-result-list">
                  {filteredBatchResults.map((result, index) => (
                    <article key={`${result.studentName}-${index}`} className={`${result.needsHumanReview ? "needs-review" : ""} ${result.failed ? "failed" : ""}`}>
                      <button className="essay-result-head result-toggle" type="button" onClick={() => setExpandedResult(expandedResult === index ? null : index)}>
                        <strong>{result.studentName}</strong>
                        <span>{result.failed ? "批改失败" : result.needsHumanReview ? "需复核" : "自动通过"}</span>
                      </button>
                      <p>{result.failed ? result.error : result.finalComments.slice(0, 120)}{!result.failed && result.finalComments.length > 120 ? "..." : ""}</p>
                      {result.reviewReason && <em>{result.reviewReason}</em>}
                      {expandedResult === index && (
                        <div className="essay-result-detail">
                          <dl><dt>班级</dt><dd>{result.className || "-"}</dd><dt>标题</dt><dd>{result.title || "-"}</dd><dt>学号</dt><dd>{result.studentId || "-"}</dd></dl>
                          <EssayComments text={result.failed ? result.error || "批改失败" : result.finalComments} />
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </section>
      )}
    </main>
  );
}
