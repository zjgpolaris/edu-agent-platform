"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import Link from "next/link";
import { authHeaders, clientSessionHeaders } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type OcrMode = "auto" | "textbook" | "page" | "multimodal";
type OcrQualityLevel = "high" | "medium" | "low";

type MaterialSummary = {
  title: string;
  key_points: string[];
  study_notes: string[];
  classroom_questions: string[];
};

type MaterialQuestion = {
  id: string;
  type: string;
  question: string;
  options?: string[] | null;
  answer: string;
  explanation: string;
};

type OcrQuality = {
  level: OcrQualityLevel;
  chinese_ratio: number;
  noise_count: number;
  symbol_density: number;
  char_count: number;
  needs_review: boolean;
};

type OcrRegion = {
  name: string;
  label: string;
  text: string;
  quality_level: OcrQualityLevel;
  warnings: string[];
};

type OcrCorrection = {
  original: string;
  replacement: string;
  reason: string;
  count: number;
  region?: string | null;
};

type MaterialParseResponse = {
  filename: string;
  content_type: string;
  source_type: "pdf" | "image";
  text: string;
  pages: { page_number: number; text: string; source_type: "pdf" | "image" }[];
  warnings: string[];
  quality?: OcrQuality | null;
  regions?: OcrRegion[];
  corrections?: OcrCorrection[];
  ocr_mode?: OcrMode | null;
};

type MaterialAnalyzeResponse = {
  summary?: MaterialSummary | null;
  explanation?: string | null;
  questions: MaterialQuestion[];
  raw_text?: string | null;
  warnings: string[];
};

type SavedMaterial = {
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

const modeOptions: { value: OcrMode; label: string; description: string; recommended?: boolean }[] = [
  { value: "multimodal", label: "多模态转写", description: "推荐：适合教材截图、图文混排和材料框", recommended: true },
  { value: "textbook", label: "教材页 OCR", description: "分区识别正文、图注和材料框" },
  { value: "page", label: "普通整页", description: "适合单张讲义或无复杂版面图片" },
  { value: "auto", label: "自动", description: "由系统选择适合的识别模式" },
];

const ocrModeLabels: Record<OcrMode, string> = {
  multimodal: "多模态转写 · qwen3.5-omni",
  textbook: "教材页 OCR",
  page: "普通整页 OCR",
  auto: "自动识别",
};

const qualityMeta: Record<OcrQualityLevel, { label: string; description: string; percent: number }> = {
  high: { label: "较高", description: "识别质量较高，建议快速浏览确认。", percent: 88 },
  medium: { label: "中等", description: "识别结果基本可用，请检查关键名词。", percent: 62 },
  low: { label: "较低", description: "识别质量较低，请重点校对后再生成。", percent: 34 },
};

const correctionReasonLabels: Record<string, string> = {
  noise_removed: "过滤噪声",
  year_punctuation_normalized: "年份修正",
  parentheses_normalized: "括号修正",
  space_normalized: "空格修正",
  history_entity_corrected: "历史名词修正",
};

function fileLabel(file: File | null) {
  if (!file) return "尚未选择资料";
  const size = file.size / 1024 / 1024;
  return `${file.name} · ${size.toFixed(size >= 1 ? 1 : 2)} MB`;
}

function normalizeError(err: unknown, fallback: string) {
  return err instanceof Error && err.message ? err.message : fallback;
}

function getQualityMeta(level: string | undefined) {
  return qualityMeta[(level as OcrQualityLevel) || "medium"] || qualityMeta.medium;
}

function pagesFromMarkedText(text: string, sourceType: "pdf" | "image") {
  const matches = Array.from(text.matchAll(/【第\s*(\d+)\s*页】/g));
  if (!matches.length) return [];
  return matches.map((match, index) => {
    const start = (match.index || 0) + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index || text.length : text.length;
    return {
      page_number: Number(match[1]),
      text: text.slice(start, end).trim(),
      source_type: sourceType,
    };
  }).filter((page) => page.page_number > 0 && page.text.length > 0);
}

function buildMaterialPages(text: string, originalText: string, parsedMeta: Pick<MaterialParseResponse, "filename" | "source_type" | "pages" | "ocr_mode">) {
  const markedPages = pagesFromMarkedText(text, parsedMeta.source_type);
  if (markedPages.length > 0) return markedPages;
  if (text.trim() === originalText.trim() && parsedMeta.pages.length > 0) return parsedMeta.pages;
  return [{ page_number: 1, text, source_type: parsedMeta.source_type }];
}

export default function MaterialUploadPage() {
  const { user } = useAuth();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [grade, setGrade] = useState("七年级");
  const [subject, setSubject] = useState("历史");
  const [ocrMode, setOcrMode] = useState<OcrMode>("multimodal");
  const [preprocess, setPreprocess] = useState(true);
  const [parseLoading, setParseLoading] = useState(false);
  const [generateLoading, setGenerateLoading] = useState(false);
  const [parseError, setParseError] = useState("");
  const [generateError, setGenerateError] = useState("");
  const [parsedText, setParsedText] = useState("");
  const [originalParsedText, setOriginalParsedText] = useState("");
  const [parseWarnings, setParseWarnings] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<MaterialAnalyzeResponse | null>(null);
  const [copyMessage, setCopyMessage] = useState("");
  const [parsedMeta, setParsedMeta] = useState<Pick<MaterialParseResponse, "filename" | "source_type" | "pages" | "ocr_mode"> | null>(null);
  const [ocrQuality, setOcrQuality] = useState<OcrQuality | null>(null);
  const [ocrRegions, setOcrRegions] = useState<OcrRegion[]>([]);
  const [ocrCorrections, setOcrCorrections] = useState<OcrCorrection[]>([]);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [savedMaterial, setSavedMaterial] = useState<SavedMaterial | null>(null);
  const [question, setQuestion] = useState("");
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState("");
  const [materialAnswer, setMaterialAnswer] = useState<MaterialAnswerResponse | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const reviewRequired = ocrQuality?.needs_review ?? false;
  const canParse = Boolean(selectedFile && user?.token && !parseLoading);
  const canGenerate = parsedText.trim().length >= 20 && Boolean(user?.token) && !parseLoading && !generateLoading && (!reviewRequired || reviewAcknowledged);
  const canSaveMaterial = parsedText.trim().length >= 20 && Boolean(parsedMeta) && Boolean(user?.token) && !parseLoading && !saveLoading && (!reviewRequired || reviewAcknowledged);
  const canAskMaterial = Boolean(savedMaterial && question.trim() && user?.token && !askLoading);
  const textStats = useMemo(() => {
    const chars = parsedText.trim().length;
    const pages = parsedMeta?.pages.length || 0;
    return { chars, pages };
  }, [parsedMeta, parsedText]);

  function resetParseState() {
    setParseError("");
    setGenerateError("");
    setCopyMessage("");
    setAnalysis(null);
    setParsedMeta(null);
    setParseWarnings([]);
    setParsedText("");
    setOriginalParsedText("");
    setOcrQuality(null);
    setOcrRegions([]);
    setOcrCorrections([]);
    setReviewAcknowledged(false);
    setSaveError("");
    setSavedMaterial(null);
    setQuestion("");
    setAskError("");
    setMaterialAnswer(null);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] || null;
    setSelectedFile(file);
    resetParseState();
  }

  async function parseMaterial(event: FormEvent) {
    event.preventDefault();
    if (!selectedFile) {
      setParseError("请先选择 PDF、PNG 或 JPG 资料");
      return;
    }
    if (!user?.token) {
      setParseError("请先登录后再上传资料");
      return;
    }

    setParseLoading(true);
    resetParseState();

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("grade", grade);
      formData.append("subject", subject);
      formData.append("ocr_mode", ocrMode);
      formData.append("preprocess", String(preprocess));

      const response = await fetch(`${apiBaseUrl}/api/materials/parse`, {
        method: "POST",
        headers: user.token ? authHeaders(user.token) : undefined,
        body: formData,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "资料识别失败，请稍后重试");

      const result = data as MaterialParseResponse;
      setParsedText(result.text || "");
      setOriginalParsedText(result.text || "");
      setParseWarnings(result.warnings || []);
      setParsedMeta({ filename: result.filename, source_type: result.source_type, pages: result.pages || [], ocr_mode: result.ocr_mode });
      setOcrQuality(result.quality || null);
      setOcrRegions(result.regions || []);
      setOcrCorrections(result.corrections || []);
      setReviewAcknowledged(!result.quality?.needs_review);
    } catch (err) {
      setParseError(normalizeError(err, "资料识别失败，请稍后重试"));
    } finally {
      setParseLoading(false);
    }
  }

  async function generateLearningContent() {
    if (!parsedText.trim()) {
      setGenerateError("请先确认或补充识别文本");
      return;
    }
    if (!user?.token) {
      setGenerateError("请先登录后再生成学习内容");
      return;
    }
    if (reviewRequired && !reviewAcknowledged) {
      setGenerateError("请先确认已校对识别文本中的人名、年份、书名、引文和不确定标记");
      return;
    }
    if (analysis && !window.confirm("重新生成将清除当前学习内容，确认继续？")) return;
    if (ocrQuality?.level === "low" && !window.confirm("OCR 质量较低，确认已校对后继续生成？")) {
      return;
    }

    setGenerateLoading(true);
    setGenerateError("");
    setCopyMessage("");
    setAnalysis(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/materials/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
        },
        body: JSON.stringify({ text: parsedText, grade, subject, task: "all" }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "学习内容生成失败，请稍后重试");
      setAnalysis(data as MaterialAnalyzeResponse);
    } catch (err) {
      setGenerateError(normalizeError(err, "学习内容生成失败，请稍后重试"));
    } finally {
      setGenerateLoading(false);
    }
  }

  async function copyParsedText() {
    if (!parsedText.trim()) return;
    await navigator.clipboard.writeText(parsedText);
    setCopyMessage("识别文本已复制");
  }

  async function saveMaterial() {
    if (!parsedMeta || !parsedText.trim()) {
      setSaveError("请先完成资料识别并确认文本");
      return;
    }
    if (!user?.token) {
      setSaveError("请先登录后再保存资料");
      return;
    }
    if (reviewRequired && !reviewAcknowledged) {
      setSaveError("请先确认已校对识别文本，再保存到个人资料库");
      return;
    }

    setSaveLoading(true);
    setSaveError("");
    setAskError("");
    setMaterialAnswer(null);

    try {
      const title = parsedText.split("\n").find((line) => line.trim() && !line.trim().startsWith("【"))?.trim().slice(0, 80) || parsedMeta.filename;
      const pages = buildMaterialPages(parsedText, originalParsedText, parsedMeta);
      const response = await fetch(`${apiBaseUrl}/api/materials/save`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
          ...clientSessionHeaders(),
        },
        body: JSON.stringify({
          title,
          filename: parsedMeta.filename,
          content_type: selectedFile?.type || "",
          source_type: parsedMeta.source_type,
          grade,
          subject,
          tags: [],
          text: parsedText,
          pages,
          ocr_mode: parsedMeta.ocr_mode,
          quality: ocrQuality,
          warnings: parseWarnings,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "资料保存失败，请稍后重试");
      setSavedMaterial(data as SavedMaterial);
    } catch (err) {
      setSaveError(normalizeError(err, "资料保存失败，请稍后重试"));
    } finally {
      setSaveLoading(false);
    }
  }

  async function askMaterial() {
    if (!savedMaterial || !question.trim()) return;
    if (!user?.token) {
      setAskError("请先登录后再围绕资料提问");
      return;
    }

    setAskLoading(true);
    setAskError("");
    setMaterialAnswer(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/materials/${savedMaterial.material_id}/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
          ...clientSessionHeaders(),
        },
        body: JSON.stringify({ question, k: 4 }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "资料问答失败，请稍后重试");
      setMaterialAnswer(data as MaterialAnswerResponse);
    } catch (err) {
      setAskError(normalizeError(err, "资料问答失败，请稍后重试"));
    } finally {
      setAskLoading(false);
    }
  }

  async function deleteMaterial() {
    if (!savedMaterial || !user?.token) return;
    setDeleteLoading(true);
    setSaveError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/materials/${savedMaterial.material_id}`, {
        method: "DELETE",
        headers: {
          ...authHeaders(user.token),
          ...clientSessionHeaders(),
        },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "资料删除失败，请稍后重试");
      setSavedMaterial(null);
      setQuestion("");
      setMaterialAnswer(null);
      setAskError("");
    } catch (err) {
      setSaveError(normalizeError(err, "资料删除失败，请稍后重试"));
    } finally {
      setDeleteLoading(false);
    }
  }

  function generateButtonText() {
    if (generateLoading) return "正在生成学习内容...";
    if (reviewRequired) return reviewAcknowledged ? "我已校对，继续生成" : "请先完成 OCR 校对确认";
    return "生成摘要、讲解和练习";
  }

  return (
    <main className="academy-shell material-upload-shell">
      <section className="academy-hero material-upload-hero">
        <div className="hero-copy">
          <span className="eyebrow">Level 1 · Material Studio</span>
          <h1>资料上传学习</h1>
          <p>
            把 PDF、截图和课堂图片转成可确认的学习文本，再由 AI 生成知识点摘要、学生讲解和随堂练习。确认前不入库，保存后仅进入个人资料库用于问答。
          </p>
          <div className="hero-flow">
            <span>上传资料</span>
            <span>识别文本</span>
            <span>编辑确认</span>
            <span>生成学习内容</span>
          </div>
        </div>
        <aside className="teaching-card material-ink-card">
          <span className="seal-mark">材</span>
          <strong>先校对，再生成</strong>
          <p>OCR 结果不会直接进入模型，学生或教师可以像批注拓片一样先修正文稿。</p>
        </aside>
      </section>

      <section className="material-upload-grid">
        <form className="panel material-upload-panel" onSubmit={parseMaterial}>
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">STEP 01</p>
              <h2>上传与识别</h2>
            </div>
            <span className="soft-badge">PDF / PNG / JPG</span>
          </div>

          <label className="material-dropzone">
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={handleFileChange} />
            <span>选择资料</span>
            <strong>{fileLabel(selectedFile)}</strong>
            <em>支持文本型 PDF、课堂截图、教材照片；建议文件不超过 15MB。</em>
          </label>

          <div className="material-field-grid">
            <label>
              <span>年级</span>
              <input value={grade} onChange={(event) => setGrade(event.target.value)} placeholder="例如：七年级" />
            </label>
            <label>
              <span>学科</span>
              <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="例如：历史" />
            </label>
          </div>

          <div className="material-ocr-options">
            <div className="material-option-head">
              <strong>图片识别模式</strong>
              <span>PDF 文本抽取会自动忽略这些选项</span>
            </div>
            <div className="material-mode-grid">
              {modeOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={ocrMode === option.value ? "active" : ""}
                  onClick={() => setOcrMode(option.value)}
                >
                  <strong>{option.label}{option.recommended && <em className="material-recommend-badge">推荐</em>}</strong>
                  <span>{option.description}</span>
                </button>
              ))}
            </div>
            <label className="material-toggle-row">
              <input type="checkbox" checked={preprocess} onChange={(event) => setPreprocess(event.target.checked)} />
              <span>{ocrMode === "multimodal" ? "启用图片预处理/压缩：多模态会保留原图版面，仅在图片过大时压缩发送" : "启用图片预处理（推荐）：放大、增强对比度、锐化并减少背景干扰"}</span>
            </label>
          </div>

          {parseError && <div className="error-card"><p>{parseError}</p></div>}
          {parseWarnings.length > 0 && (
            <div className="material-warning-card">
              <strong>识别提示</strong>
              <ul>{parseWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          )}

          <button className="primary" type="submit" disabled={!canParse}>
            {parseLoading ? "正在识别资料..." : "识别资料文本"}
          </button>
        </form>

        <section className="panel material-editor-panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">STEP 02</p>
              <h2>确认识别文本</h2>
            </div>
            <span className="soft-badge">{textStats.chars} 字 · {textStats.pages || 0} 页</span>
          </div>

          {parsedMeta && (
            <div className="material-meta-strip">
              <span>{parsedMeta.source_type === "pdf" ? "PDF 文稿" : ocrModeLabels[(parsedMeta.ocr_mode || "auto") as OcrMode]}</span>
              <strong>{parsedMeta.filename}</strong>
            </div>
          )}

          {ocrQuality && (
            <div className={`material-quality-card ${ocrQuality.level}`}>
              <div>
                <span>识别质量</span>
                <strong>{getQualityMeta(ocrQuality.level).label}</strong>
                <p>{getQualityMeta(ocrQuality.level).description}</p>
              </div>
              <div className="material-quality-stats">
                <span>中文占比 {(ocrQuality.chinese_ratio * 100).toFixed(0)}%</span>
                <span>噪声 {ocrQuality.noise_count}</span>
                <span>{ocrQuality.needs_review ? "需人工校对" : "快速确认即可"}</span>
              </div>
              <div className="material-quality-meter"><i style={{ width: `${getQualityMeta(ocrQuality.level).percent}%` }} /></div>
            </div>
          )}

          {ocrRegions.length > 0 && (
            <div className="material-region-list">
              <strong>分区识别结果</strong>
              {ocrRegions.map((region) => (
                <details key={`${region.name}-${region.label}`} className={`material-region-card ${region.quality_level}`}>
                  <summary>
                    <span>{region.label}</span>
                    <em>{getQualityMeta(region.quality_level).label}</em>
                  </summary>
                  <p>{region.text}</p>
                  {region.warnings.length > 0 && <ul>{region.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                </details>
              ))}
            </div>
          )}

          {ocrCorrections.length > 0 && (
            <div className="material-correction-log">
              <strong>自动修正记录</strong>
              <ul>
                {ocrCorrections.slice(0, 20).map((correction, index) => (
                  <li key={`${correction.original}-${correction.replacement}-${index}`}>
                    <span>{correctionReasonLabels[correction.reason] || correction.reason}</span>
                    <code>{correction.original || "已删除"}</code>
                    <b>→</b>
                    <code>{correction.replacement || "已过滤"}</code>
                    <em>{correction.count} 次{correction.region ? ` · ${correction.region}` : ""}</em>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <textarea
            className="material-textarea"
            value={parsedText}
            onChange={(event) => {
              setParsedText(event.target.value);
              setAnalysis(null);
              setGenerateError("");
              setSavedMaterial(null);
              setMaterialAnswer(null);
              setQuestion("");
              setAskError("");
            }}
            placeholder="识别出的资料文本会显示在这里。你也可以直接粘贴或修正 OCR 文本后生成学习内容。"
          />

          <div className="material-editor-actions">
            <button className="secondary" type="button" onClick={() => { setParsedText(""); setAnalysis(null); setSavedMaterial(null); }} disabled={!parsedText || parseLoading || generateLoading}>清空文本</button>
            <button className="secondary" type="button" onClick={copyParsedText} disabled={!parsedText}>复制文本</button>
            {copyMessage && <span>{copyMessage}</span>}
          </div>

          {reviewRequired && (
            <label className={`material-review-card ${reviewAcknowledged ? "checked" : ""}`}>
              <input type="checkbox" checked={reviewAcknowledged} onChange={(event) => setReviewAcknowledged(event.target.checked)} />
              <span>我已校对人名、年份、书名、引文和不确定标记，再用这份文本生成学习内容。</span>
            </label>
          )}

          {generateError && <div className="error-card"><p>{generateError}</p></div>}

          <div className="material-save-card">
            <div>
              <strong>保存到个人资料库</strong>
              <p>保存后会写入个人资料库和独立向量索引，可围绕这份资料提问；不会进入全局历史知识库。</p>
            </div>
            <button className="secondary" type="button" disabled={!canSaveMaterial} onClick={saveMaterial}>
              {saveLoading ? "正在保存..." : savedMaterial ? "重新保存为新资料" : "保存资料并建立索引"}
            </button>
          </div>
          {saveError && <div className="error-card"><p>{saveError}</p></div>}
          {savedMaterial && (
            <div className="material-rag-panel">
              <div className="material-rag-head">
                <div>
                  <span>个人资料库</span>
                  <strong>{savedMaterial.title}</strong>
                  <p>{savedMaterial.page_count} 页 · {savedMaterial.chunk_count} 个检索片段 · {savedMaterial.text_chars} 字</p>
                  <Link href={`/materials/${savedMaterial.material_id}`}>打开资料详情</Link>
                </div>
                <button className="secondary" type="button" disabled={deleteLoading || askLoading} onClick={deleteMaterial}>{deleteLoading ? "删除中..." : "删除资料"}</button>
              </div>
              <label className="material-question-box">
                <span>围绕这份资料提问</span>
                <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：为什么孙中山能成为革命党公认的领袖？" />
              </label>
              {askError && <div className="error-card"><p>{askError}</p></div>}
              <button className="primary" type="button" disabled={!canAskMaterial} onClick={askMaterial}>{askLoading ? "正在检索资料..." : "基于资料回答"}</button>
              {materialAnswer && (
                <div className="material-answer-card">
                  <strong>资料回答</strong>
                  <p>{materialAnswer.answer}</p>
                  {materialAnswer.sources.length > 0 && (
                    <div className="material-source-list">
                      <span>引用来源</span>
                      {materialAnswer.sources.map((source) => (
                        <article key={source.chunk_id} className="material-source-card">
                          <strong>{source.title} · 第 {source.page || 1} 页</strong>
                          <em>{source.source_mode} · score {source.score.toFixed(2)}</em>
                          <p>{source.snippet}</p>
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <button className="primary" type="button" disabled={!canGenerate} onClick={generateLearningContent}>
            {generateButtonText()}
          </button>
        </section>
      </section>

      <section className="panel material-results-panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">STEP 03</p>
            <h2>学习产出</h2>
          </div>
          <span className="soft-badge">不入库 · 本次生成</span>
        </div>

        {!analysis && !generateLoading && (
          <p className="empty-hint">完成识别并确认文本后，这里会出现知识点摘要、讲解和练习题。</p>
        )}
        {generateLoading && <p className="empty-hint">正在把资料整理成可学习的结构，请稍候...</p>}

        {analysis?.warnings && analysis.warnings.length > 0 && (
          <div className="material-warning-card">
            <strong>生成提示</strong>
            <ul>{analysis.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </div>
        )}

        {analysis?.summary && (
          <div className="material-result-grid">
            <article className="material-result-card material-summary-card">
              <span>知识点摘要</span>
              <h3>{analysis.summary.title}</h3>
              <ul>{analysis.summary.key_points.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
            <article className="material-result-card">
              <span>复习笔记</span>
              <ul>{analysis.summary.study_notes.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
            <article className="material-result-card">
              <span>课堂追问</span>
              <ul>{analysis.summary.classroom_questions.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
          </div>
        )}

        {analysis?.explanation && (
          <article className="material-explanation-card">
            <span>学生讲解</span>
            <p>{analysis.explanation}</p>
          </article>
        )}

        {analysis?.questions && analysis.questions.length > 0 && (
          <div className="material-question-list">
            {analysis.questions.map((question, index) => (
              <details key={question.id || question.question} className="material-question-card">
                <summary>
                  <span>练习 {index + 1}</span>
                  <strong>{question.question}</strong>
                </summary>
                {question.options && question.options.length > 0 && (
                  <ol>{question.options.map((option) => <li key={option}>{option}</li>)}</ol>
                )}
                <div className="material-answer-card">
                  <strong>参考答案：{question.answer}</strong>
                  {question.explanation && <p>{question.explanation}</p>}
                </div>
              </details>
            ))}
          </div>
        )}

        {analysis?.raw_text && (
          <details className="material-raw-card">
            <summary>查看模型原始输出</summary>
            <pre>{analysis.raw_text}</pre>
          </details>
        )}
      </section>
    </main>
  );
}
