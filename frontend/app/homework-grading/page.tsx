"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { authHeaders } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type HomeworkTaskType = "history_short_answer" | "history_material_analysis" | "history_single_choice";
type OcrMode = "auto" | "textbook" | "page" | "multimodal";
type Confidence = "high" | "medium" | "low";

type OcrQuality = {
  level: "high" | "medium" | "low";
  chinese_ratio: number;
  noise_count: number;
  symbol_density: number;
  char_count: number;
  needs_review: boolean;
};

type ExtractedHomeworkItem = {
  item_id: string;
  question: string;
  student_answer: string;
  reference_context: string;
  question_type: string;
  options: string[];
  correct_answer?: string | null;
  knowledge_tags: string[];
  confidence: Confidence;
  warnings: string[];
};

type HomeworkExtractResponse = {
  filename: string;
  task_type: HomeworkTaskType;
  grade?: string | null;
  subject?: string | null;
  raw_text: string;
  items: ExtractedHomeworkItem[];
  warnings: string[];
  quality?: OcrQuality | null;
  ocr_mode?: OcrMode | null;
  needs_review: boolean;
};

type HomeworkGradedItem = {
  item_id: string;
  question: string;
  student_answer: string;
  score: number;
  max_score: number;
  grade_level: string;
  is_correct: boolean;
  strengths: string[];
  issues: string[];
  missing_points: string[];
  knowledge_tags: string[];
  correct_answer?: string | null;
  explanation?: string;
  revision_suggestion: string;
};

type HomeworkGradeResponse = {
  total_score: number;
  max_score: number;
  normalized_score: number;
  grade_level: string;
  items: HomeworkGradedItem[];
  overall_feedback: string;
  weak_points: string[];
  follow_up_quiz: { question: string; answer: string }[];
  needs_human_review: boolean;
  review_reason?: string | null;
  event_id?: string | null;
  warnings: string[];
};

const taskTypeOptions: { value: HomeworkTaskType; label: string; description: string }[] = [
  { value: "history_short_answer", label: "历史简答题", description: "适合问答题、原因影响题、人物事件题" },
  { value: "history_material_analysis", label: "材料分析题", description: "适合带史料、引文和设问的作业" },
  { value: "history_single_choice", label: "历史选择题", description: "适合单选题、A/B/C/D 客观题" },
];

const ocrModeOptions: { value: OcrMode; label: string }[] = [
  { value: "multimodal", label: "多模态识别" },
  { value: "textbook", label: "教材页 OCR" },
  { value: "page", label: "普通整页 OCR" },
  { value: "auto", label: "自动" },
];

function fileLabel(file: File | null) {
  if (!file) return "尚未选择作业照片";
  const size = file.size / 1024 / 1024;
  return `${file.name} · ${size.toFixed(size >= 1 ? 1 : 2)} MB`;
}

function normalizeError(err: unknown, fallback: string) {
  return err instanceof Error && err.message ? err.message : fallback;
}

function tagsText(tags: string[]) {
  return tags.join("、");
}

function parseTags(text: string) {
  return text.split(/[、,，\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 8);
}

function parseOptions(text: string) {
  return text.split("\n").map((item) => item.trim()).filter(Boolean).slice(0, 8);
}

export default function HomeworkGradingPage() {
  const { user } = useAuth();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [grade, setGrade] = useState("八年级");
  const [subject, setSubject] = useState("历史");
  const [taskType, setTaskType] = useState<HomeworkTaskType>("history_short_answer");
  const [ocrMode, setOcrMode] = useState<OcrMode>("multimodal");
  const [preprocess, setPreprocess] = useState(true);
  const [studentId, setStudentId] = useState(user?.actorId || "");
  const [parseLoading, setParseLoading] = useState(false);
  const [parseError, setParseError] = useState("");
  const [extractResult, setExtractResult] = useState<HomeworkExtractResponse | null>(null);
  const [rawText, setRawText] = useState("");
  const [items, setItems] = useState<ExtractedHomeworkItem[]>([]);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  const [gradeLoading, setGradeLoading] = useState(false);
  const [gradeError, setGradeError] = useState("");
  const [gradeResult, setGradeResult] = useState<HomeworkGradeResponse | null>(null);

  const reviewRequired = Boolean(
    extractResult?.needs_review
    || extractResult?.quality?.needs_review
    || items.some((item) => item.confidence === "low" || !item.student_answer.trim() || (item.question_type === "history_single_choice" && (!item.options || item.options.length === 0)))
  );
  const canParse = Boolean(selectedFile && user?.token && !parseLoading);
  const canGrade = items.length > 0 && Boolean(user?.token) && !parseLoading && !gradeLoading && (!reviewRequired || reviewAcknowledged);
  const scorePercent = useMemo(() => Math.round((gradeResult?.normalized_score || 0) * 100), [gradeResult]);

  useEffect(() => {
    if (!studentId && user?.actorId) setStudentId(user.actorId);
  }, [studentId, user?.actorId]);

  function resetResultState() {
    setParseError("");
    setGradeError("");
    setExtractResult(null);
    setRawText("");
    setItems([]);
    setReviewAcknowledged(false);
    setGradeResult(null);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] || null);
    resetResultState();
  }

  function updateItem(index: number, patch: Partial<ExtractedHomeworkItem>) {
    setItems((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
    setGradeResult(null);
    setGradeError("");
  }

  async function parseHomework(event: FormEvent) {
    event.preventDefault();
    if (!selectedFile) {
      setParseError("请先选择作业照片或 PDF");
      return;
    }
    if (!user?.token) {
      setParseError("请先登录后再使用拍照批改");
      return;
    }

    setParseLoading(true);
    resetResultState();

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("grade", grade);
      formData.append("subject", subject);
      formData.append("task_type", taskType);
      formData.append("ocr_mode", ocrMode);
      formData.append("preprocess", String(preprocess));

      const response = await fetch(`${apiBaseUrl}/api/homework/parse`, {
        method: "POST",
        headers: user.token ? authHeaders(user.token) : undefined,
        body: formData,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "作业识别失败，请稍后重试");
      const result = data as HomeworkExtractResponse;
      setExtractResult(result);
      setRawText(result.raw_text || "");
      setItems((result.items || []).map((item) => ({ ...item, question_type: taskType === "history_single_choice" ? "history_single_choice" : item.question_type || taskType, options: item.options || [] })));
      setReviewAcknowledged(!result.needs_review);
    } catch (err) {
      setParseError(normalizeError(err, "作业识别失败，请稍后重试"));
    } finally {
      setParseLoading(false);
    }
  }

  async function gradeHomework() {
    if (!items.length) {
      setGradeError("请先确认至少一道题目和学生答案");
      return;
    }
    if (!user?.token) {
      setGradeError("请先登录后再批改");
      return;
    }
    if (reviewRequired && !reviewAcknowledged) {
      setGradeError("请先确认已校对题目和学生答案，再开始批改");
      return;
    }

    setGradeLoading(true);
    setGradeError("");
    setGradeResult(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/homework/grade`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
        },
        body: JSON.stringify({
          task_type: taskType,
          grade,
          subject,
          student_id: studentId.trim() || undefined,
          items,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "作业批改失败，请稍后重试");
      const result = data as HomeworkGradeResponse;
      setGradeResult(result);
      // auto-save for teacher review (fire-and-forget)
      fetch(`${apiBaseUrl}/api/homework/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user.token) },
        body: JSON.stringify({
          grade_request: { task_type: taskType, grade, subject, student_id: studentId.trim() || undefined, items },
          grade_result: result,
        }),
      }).catch(() => null);
    } catch (err) {
      setGradeError(normalizeError(err, "作业批改失败，请稍后重试"));
    } finally {
      setGradeLoading(false);
    }
  }

  return (
    <main className="academy-shell homework-grading-shell">
      <section className="homework-upload-grid">
        <form className="panel homework-upload-panel" onSubmit={parseHomework}>
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">STEP 01</p>
              <h2>上传与识别</h2>
            </div>
            <span className="soft-badge">PDF / PNG / JPG</span>
          </div>

          <label className="material-dropzone">
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={handleFileChange} />
            <span>选择作业</span>
            <strong>{fileLabel(selectedFile)}</strong>
            <em>适合历史简答题、材料分析题、课堂练习照片；建议文字清晰、光线充足。</em>
          </label>

          <div className="material-field-grid">
            <label><span>年级</span><input value={grade} onChange={(event) => setGrade(event.target.value)} /></label>
            <label><span>学科</span><input value={subject} onChange={(event) => setSubject(event.target.value)} /></label>
            <label><span>学生 ID</span><input value={studentId} onChange={(event) => setStudentId(event.target.value)} placeholder="用于写入学情，可留空" /></label>
            <label><span>识别模式</span><select value={ocrMode} onChange={(event) => setOcrMode(event.target.value as OcrMode)}>{ocrModeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          </div>

          <div className="homework-task-grid">
            {taskTypeOptions.map((option) => (
              <button key={option.value} type="button" className={taskType === option.value ? "active" : ""} onClick={() => setTaskType(option.value)}>
                <strong>{option.label}</strong>
                <span>{option.description}</span>
              </button>
            ))}
          </div>

          <label className="material-toggle-row">
            <input type="checkbox" checked={preprocess} onChange={(event) => setPreprocess(event.target.checked)} />
            <span>启用图片预处理/压缩，提升 OCR 或多模态识别稳定性。</span>
          </label>

          {parseError && <div className="error-card"><p>{parseError}</p></div>}
          <button className="primary" type="submit" disabled={!canParse}>{parseLoading ? "正在识别作业..." : "识别题目和答案"}</button>
        </form>

        <section className="panel homework-review-panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">STEP 02</p>
              <h2>确认题目与答案</h2>
            </div>
            <span className="soft-badge">{items.length} 题</span>
          </div>

          {!extractResult && <p className="empty-hint">上传作业后，这里会展示识别出的题目、学生答案和不确定提示。</p>}

          {extractResult && (
            <>
              {extractResult.warnings.length > 0 && <div className="material-warning-card"><strong>识别提示</strong><ul>{extractResult.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
              {extractResult.quality && <div className={`material-quality-card ${extractResult.quality.level}`}><div><span>识别质量</span><strong>{extractResult.quality.level}</strong><p>{extractResult.quality.needs_review ? "建议重点校对题干、答案和年份名词。" : "识别质量可用，仍建议确认。"}</p></div><div className="material-quality-stats"><span>{extractResult.ocr_mode || "auto"}</span><span>{extractResult.quality.char_count} 字</span></div></div>}
              <details className="homework-raw-card">
                <summary>查看原始识别文本</summary>
                <textarea value={rawText} onChange={(event) => setRawText(event.target.value)} />
              </details>
              <div className="homework-item-list">
                {items.map((item, index) => (
                  <article key={item.item_id} className={`homework-item-card ${item.confidence}`}>
                    <div className="homework-item-head"><strong>题目 {index + 1}</strong><em>{item.confidence}</em></div>
                    <label><span>题目</span><textarea value={item.question} onChange={(event) => updateItem(index, { question: event.target.value })} /></label>
                    <label><span>材料 / 引文</span><textarea value={item.reference_context} onChange={(event) => updateItem(index, { reference_context: event.target.value })} /></label>
                    {item.question_type === "history_single_choice" && (
                      <label><span>选项（一行一个）</span><textarea value={(item.options || []).join("\n")} onChange={(event) => updateItem(index, { options: parseOptions(event.target.value) })} /></label>
                    )}
                    <label><span>{item.question_type === "history_single_choice" ? "学生选择" : "学生答案"}</span><textarea value={item.student_answer} onChange={(event) => updateItem(index, { student_answer: event.target.value })} /></label>
                    {item.question_type === "history_single_choice" && (
                      <label><span>可见参考答案（可空）</span><input value={item.correct_answer || ""} onChange={(event) => updateItem(index, { correct_answer: event.target.value || null })} placeholder="如 A 或 A. 洋务运动" /></label>
                    )}
                    <label><span>知识点标签</span><input value={tagsText(item.knowledge_tags)} onChange={(event) => updateItem(index, { knowledge_tags: parseTags(event.target.value) })} /></label>
                    {item.warnings.length > 0 && <ul>{item.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                  </article>
                ))}
              </div>
              {reviewRequired && <label className={`material-review-card ${reviewAcknowledged ? "checked" : ""}`}><input type="checkbox" checked={reviewAcknowledged} onChange={(event) => setReviewAcknowledged(event.target.checked)} /><span>我已校对题目、学生答案、年份、人名和知识点标签，再开始自动批改。</span></label>}
              {gradeError && <div className="error-card"><p>{gradeError}</p></div>}
              <button className="primary" type="button" disabled={!canGrade} onClick={gradeHomework}>{gradeLoading ? "正在批改..." : "确认无误，开始批改"}</button>
            </>
          )}
        </section>
      </section>

      <section className="panel homework-result-panel">
        <div className="panel-heading-row">
          <div><p className="section-kicker">STEP 03</p><h2>批改结果与复习建议</h2></div>
          <span className="soft-badge">{gradeResult ? `${scorePercent}%` : "待批改"}</span>
        </div>
        {!gradeResult && !gradeLoading && <p className="empty-hint">确认识别内容并提交后，这里会展示分数、错因、薄弱点和追问题。</p>}
        {gradeLoading && <p className="empty-hint">正在根据题目和答案生成批改结果...</p>}
        {gradeResult && (
          <>
            <div className="homework-score-card">
              <span>总分</span>
              <strong>{gradeResult.total_score} / {gradeResult.max_score}</strong>
              <p>{gradeResult.grade_level} · {gradeResult.overall_feedback}</p>
              {gradeResult.needs_human_review && <em>{gradeResult.review_reason || "建议教师复核"}</em>}
              {gradeResult.event_id && <small>已写入学习记录 · {gradeResult.event_id}</small>}
              {studentId.trim() && !gradeResult.event_id && <small>未确认写入学情，请稍后在学情页检查。</small>}
            </div>
            {gradeResult.needs_human_review && <div className="material-warning-card"><strong>需要人工复核</strong><p>{gradeResult.review_reason || "题目、答案或 OCR 置信度不足，建议教师复核后采用最终评分。"}</p></div>}
            {gradeResult.warnings.length > 0 && <div className="material-warning-card"><strong>批改提示</strong><ul>{gradeResult.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
            <div className="homework-graded-list">
              {gradeResult.items.map((item, index) => (
                <article key={item.item_id} className="homework-graded-card">
                  <div className="homework-item-head"><strong>题目 {index + 1} · {item.score}/{item.max_score}</strong><em>{item.grade_level}</em></div>
                  <p>{item.question}</p>
                  {(item.correct_answer || item.explanation) && (
                    <div className="homework-choice-result">
                      {item.correct_answer && <span>参考答案：{item.correct_answer}</span>}
                      {item.explanation && <p>{item.explanation}</p>}
                    </div>
                  )}
                  <div className="homework-rubric-list">
                    {item.strengths.length > 0 && <section><span>优点</span><ul>{item.strengths.map((entry) => <li key={entry}>{entry}</li>)}</ul></section>}
                    {item.issues.length > 0 && <section><span>问题</span><ul>{item.issues.map((entry) => <li key={entry}>{entry}</li>)}</ul></section>}
                    {item.missing_points.length > 0 && <section><span>缺失要点</span><ul>{item.missing_points.map((entry) => <li key={entry}>{entry}</li>)}</ul></section>}
                  </div>
                  {item.knowledge_tags.length > 0 && (
                    <div className="homework-knowledge-tags">
                      {item.knowledge_tags.map((tag) => <span key={tag}>{tag}</span>)}
                    </div>
                  )}
                  <strong>修改建议</strong>
                  <p>{item.revision_suggestion}</p>
                </article>
              ))}
            </div>
            {gradeResult.weak_points.length > 0 && (
              <div className="homework-followup-card">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <strong>本次新增/命中的薄弱点</strong>
                  <a href="/student/weakpoints" style={{ fontSize: "0.82rem", color: "var(--accent, #4b9560)", textDecoration: "none" }}>去错题本复习 →</a>
                </div>
                <div>{gradeResult.weak_points.map((point) => <span key={point}>{point}</span>)}</div>
              </div>
            )}
            {gradeResult.follow_up_quiz.length > 0 && <div className="homework-followup-card"><strong>追问练习</strong>{gradeResult.follow_up_quiz.map((quiz) => <details key={quiz.question}><summary>{quiz.question}</summary><p>{quiz.answer}</p></details>)}</div>}
          </>
        )}
      </section>
    </main>
  );
}
